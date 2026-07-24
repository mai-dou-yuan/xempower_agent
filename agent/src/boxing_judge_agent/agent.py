from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .config import Settings, get_settings
from .csv_analyzer import analyze_event_batch, get_event_details
from .errors import AgentError
from .guard import validate_output
from .llm import DeepSeekJudge
from .missing_context import analyze_missing_context
from .rag.retrieve import retrieve_rule_evidence
from .report import build_report
from .schemas import AgentSession, ProgressEvent, SessionStatus, SupplementRecord
from .scoring import calculate_scorecard, plausible_score_range
from .supplements import find_conflicts, is_skip_message, minimal_mapping_assumption, parse_user_supplement


class Judge(Protocol):
    def assess(
        self,
        round_contexts: list[dict[str, Any]],
        supplements: list[SupplementRecord],
        evidence: list[Any],
        analysis_question: str | None = None,
    ) -> list[Any]: ...


class SessionStore:
    def __init__(self, root: Path):
        self.root = root
        self.sessions = root / "sessions"
        self.uploads = root / "uploads"
        self.indexes = root / "indexes"
        for path in (self.sessions, self.uploads, self.indexes):
            path.mkdir(parents=True, exist_ok=True)

    def save(self, session: AgentSession) -> None:
        session.updated_at = datetime.now(timezone.utc).isoformat()
        target = self.sessions / f"{session.session_id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, target)

    def load(self, session_id: str) -> AgentSession:
        if not session_id or any(x not in "0123456789abcdef-" for x in session_id.lower()):
            raise AgentError("session_not_found", "会话不存在", status_code=404)
        path = self.sessions / f"{session_id}.json"
        if not path.exists():
            raise AgentError("session_not_found", "会话不存在", status_code=404)
        return AgentSession.model_validate_json(path.read_text(encoding="utf-8"))


class BoxingJudgeAgent:
    def __init__(self, settings: Settings | None = None, judge: Judge | None = None):
        self.settings = settings or get_settings()
        self.store = SessionStore(self.settings.artifact_dir)
        self.judge = judge or DeepSeekJudge(self.settings)

    def _record_progress(
        self,
        session: AgentSession,
        *,
        phase: str,
        status: str,
        tool: str,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        session.progress_events.append(ProgressEvent(
            sequence=len(session.progress_events) + 1,
            phase=phase,
            status=status,
            tool=tool,
            title=title,
            message=message,
            details=details or {},
        ))
        self.store.save(session)

    def create_session(self, csv_path: str | Path, question: str | None = None) -> AgentSession:
        normalized_question = question.strip() if question else None
        if normalized_question and len(normalized_question) > 2000:
            raise AgentError("invalid_question", "分析问题不能超过 2000 个字符")
        session_id = str(uuid.uuid4())
        session = AgentSession(
            session_id=session_id,
            status=SessionStatus.ANALYZING,
            csv_path=str(Path(csv_path).resolve()),
            question=normalized_question,
        )
        self._record_progress(
            session,
            phase="csv_analysis",
            status="running",
            tool="Pandas CSV Analyzer",
            title="读取并校验赛事数据",
            message="正在检查字段、枚举值、帧区间和事件唯一性。",
        )
        batch = analyze_event_batch(csv_path, mode="runtime")
        session.analysis_id = batch["analysis_id"]
        session.csv_hash = batch["source"]["sha256"]
        session.batch_analysis = batch
        session.missing_context = analyze_missing_context(batch)
        session.status = SessionStatus.AWAITING_SUPPLEMENT_CHOICE
        self._record_progress(
            session,
            phase="csv_analysis",
            status="completed",
            tool="Pandas CSV Analyzer",
            title="赛事数据分析完成",
            message=f"已分析 {batch['dataset']['event_count']} 条事件和 {batch['dataset']['video_count']} 个视频。",
            details={
                "event_count": batch["dataset"]["event_count"],
                "video_count": batch["dataset"]["video_count"],
                "anomaly_count": len(batch.get("anomalies", [])),
            },
        )
        return session

    def get_session(self, session_id: str) -> AgentSession:
        return self.store.load(session_id)

    def add_message(self, session_id: str, message: str) -> dict[str, Any]:
        session = self.store.load(session_id)
        if session.status == SessionStatus.AWAITING_SUPPLEMENT_CHOICE and is_skip_message(message):
            return self.confirm(session_id, "skip_supplement")
        if session.status not in {
            SessionStatus.AWAITING_SUPPLEMENT_CHOICE,
            SessionStatus.AWAITING_USER_INPUT,
        }:
            raise AgentError("awaiting_user_confirmation", "当前状态不接受补充文本")
        session.supplement_mode = "add"
        session.supplement_rounds += 1
        if session.supplement_rounds > 8:
            return self._finalize(session, allow_mapping=False)
        pending = parse_user_supplement(message, session.supplement_rounds)
        conflicts = find_conflicts(session.supplements, pending)
        session.pending_supplements = pending
        session.status = SessionStatus.AWAITING_CONFIRMATION
        self.store.save(session)
        return {
            "session": session.model_dump(mode="json", exclude={"batch_analysis"}),
            "parsed_supplements": [x.model_dump(mode="json") for x in pending],
            "conflicts": conflicts,
            "prompt": "请核对结构化理解；确认后才会用于分析。",
        }

    def confirm(self, session_id: str, action: str) -> dict[str, Any]:
        session = self.store.load(session_id)
        if action == "add_supplement":
            if session.status != SessionStatus.AWAITING_SUPPLEMENT_CHOICE:
                raise AgentError("awaiting_user_confirmation", "当前不能选择补充模式")
            session.supplement_mode = "add"
            session.status = SessionStatus.AWAITING_USER_INPUT
            self.store.save(session)
            return self._session_response(session)
        if action == "skip_supplement":
            if session.status not in {SessionStatus.AWAITING_SUPPLEMENT_CHOICE, SessionStatus.AWAITING_USER_INPUT}:
                raise AgentError("awaiting_user_confirmation", "当前不能跳过补充")
            # “skip” 在已补充事实后表示停止继续录入，不能覆盖已经采用的补充模式。
            session.supplement_mode = "add" if session.supplements else "skip"
            session.status = SessionStatus.SUPPLEMENT_SKIPPED
            assumption = minimal_mapping_assumption(session.batch_analysis or {}, len(session.assumptions) + 1)
            session.assumptions = [assumption]
            session.status = SessionStatus.AWAITING_CONFIRMATION
            self.store.save(session)
            return {
                **self._session_response(session),
                "confirmation_scope": "minimal_assumption",
                "prompt": "如需唯一逐回合主估算，请一次性确认视频排序即回合排序的最小假设；也可 reject_assumptions 直接生成多情景/证据不足报告。",
            }
        if action == "confirm_supplements":
            if session.status != SessionStatus.AWAITING_CONFIRMATION or not session.pending_supplements:
                raise AgentError("awaiting_user_confirmation", "没有待确认的补充")
            for item in session.pending_supplements:
                item.confirmed = True
                session.supplements.append(item)
            session.pending_supplements = []
            has_mapping = any(x.metric == "round_mapping" for x in session.supplements)
            if has_mapping:
                return self._finalize(session, allow_mapping=True)
            session.status = SessionStatus.AWAITING_USER_INPUT
            self.store.save(session)
            questions = (session.missing_context or {}).get("questions", [])[:3]
            return {**self._session_response(session), "questions": questions}
        if action == "confirm_assumptions":
            if not session.assumptions:
                raise AgentError("awaiting_user_confirmation", "没有待确认的假设")
            for item in session.assumptions:
                item.confirmed = True
            return self._finalize(session, allow_mapping=True)
        if action == "reject_assumptions":
            return self._finalize(session, allow_mapping=False)
        raise AgentError("invalid_confirmation", f"未知确认动作：{action}")

    def _round_contexts(self, session: AgentSession) -> list[dict[str, Any]]:
        videos = (session.batch_analysis or {}).get("videos", [])
        return [
            {
                "round": index + 1,
                "video_id": video["video_id"],
                "prediction_summary": video["fighter_summaries"],
                "warning": "仅为模型预测统计，不能机械换算得分。",
            }
            for index, video in enumerate(videos)
        ]

    def _finalize(self, session: AgentSession, *, allow_mapping: bool) -> dict[str, Any]:
        session.status = SessionStatus.RETRIEVING_RULES
        index_path = self.store.indexes / "rules.json"
        signatures = (session.batch_analysis or {}).get("unique_rule_query_signatures", [])
        self._record_progress(
            session,
            phase="rule_retrieval",
            status="running",
            tool=f"Qwen · {self.settings.dashscope_embedding_model}",
            title="正在检索评判规则",
            message="正在编码分析问题和 CSV 规则查询，并计算知识库向量相似度。",
            details={"query_count": len(signatures) + int(bool(session.question)), "dimensions": self.settings.dashscope_embedding_dimensions},
        )
        try:
            session.rule_evidence = retrieve_rule_evidence(
                self.settings.knowledge_base,
                signatures,
                index_path if index_path.exists() else None,
                settings=self.settings,
                user_query=session.question,
            )
        except AgentError as exc:
            self._record_progress(
                session,
                phase="rule_retrieval",
                status="failed",
                tool=f"Qwen · {self.settings.dashscope_embedding_model}",
                title="规则检索失败",
                message=exc.message,
                details={"error_code": exc.code},
            )
            raise
        self._record_progress(
            session,
            phase="rule_retrieval",
            status="completed",
            tool="Local Cosine Retriever",
            title="规则证据检索完成",
            message=f"已选出 {len(session.rule_evidence)} 条带来源的规则证据。",
            details={"evidence_count": len(session.rule_evidence)},
        )
        session.status = SessionStatus.SCORING
        session.last_error = None
        assessments = []
        if allow_mapping:
            round_contexts = self._round_contexts(session)
            self._record_progress(
                session,
                phase="llm_assessment",
                status="running",
                tool=f"DeepSeek · {self.settings.deepseek_model}",
                title="正在进行逐回合定性评判",
                message="模型正在依据预测摘要、已确认补充和规则证据生成结构化判断。",
                details={"round_count": len(round_contexts), "confirmed_supplement_count": len([x for x in session.supplements + session.assumptions if x.confirmed])},
            )
            try:
                assessments = self.judge.assess(
                    round_contexts,
                    session.supplements + session.assumptions,
                    session.rule_evidence,
                    analysis_question=session.question,
                )
                self._record_progress(
                    session,
                    phase="llm_assessment",
                    status="completed",
                    tool=f"DeepSeek · {self.settings.deepseek_model}",
                    title="逐回合判断完成",
                    message=f"模型已返回并通过结构校验的 {len(assessments)} 个回合判断。",
                    details={"assessment_count": len(assessments)},
                )
            except AgentError as exc:
                session.last_error = {"code": exc.code, "message": exc.message}
                session.status = SessionStatus.LLM_UNAVAILABLE
                self._record_progress(
                    session,
                    phase="llm_assessment",
                    status="failed",
                    tool=f"DeepSeek · {self.settings.deepseek_model}",
                    title="模型评判暂不可用",
                    message=exc.message,
                    details={"error_code": exc.code},
                )
        else:
            self._record_progress(
                session,
                phase="llm_assessment",
                status="skipped",
                tool=f"DeepSeek · {self.settings.deepseek_model}",
                title="已跳过逐回合模型判断",
                message="用户未确认回合映射，系统不会强行生成唯一逐回合比分。",
            )
        session.round_assessments = assessments
        self._record_progress(
            session,
            phase="deterministic_scoring",
            status="running",
            tool="Deterministic Score Engine",
            title="正在计算记分卡",
            message="根据结构化回合判断计算基础分、正式扣分和合理比分范围。",
        )
        scorecard = calculate_scorecard(assessments)
        swings = [x.round for x in assessments if x.confidence == "low" or x.winner in {"even", "insufficient"}]
        session.report = {
            "scorecard": scorecard,
            "plausible_range": plausible_score_range(scorecard, swings),
        }
        self._record_progress(
            session,
            phase="deterministic_scoring",
            status="completed",
            tool="Deterministic Score Engine",
            title="记分计算完成",
            message="记分卡已完成。" if scorecard["complete"] else "存在未知回合或扣分，总分保持未确定。",
            details={"complete": scorecard["complete"], "scored_rounds": len(scorecard["rounds"])},
        )
        self._record_progress(
            session,
            phase="guard_validation",
            status="running",
            tool="Evidence Guard",
            title="正在执行证据与算术审计",
            message="检查标签泄漏、规则引用、正式裁定来源和计分一致性。",
        )
        guard_errors = validate_output(
            session.batch_analysis or {}, assessments, scorecard, session.rule_evidence,
            [x for x in session.supplements + session.assumptions if x.confirmed],
        )
        self._record_progress(
            session,
            phase="guard_validation",
            status="completed",
            tool="Evidence Guard",
            title="审计检查完成",
            message="未发现审计问题。" if not guard_errors else f"发现 {len(guard_errors)} 项需要在报告中披露的问题。",
            details={"issue_count": len(guard_errors)},
        )
        session.status = SessionStatus.REPORTING
        self._record_progress(
            session,
            phase="report_generation",
            status="running",
            tool="Report Builder",
            title="正在生成分析报告",
            message="正在组合结论、比分、证据索引、替代情景和局限说明。",
        )
        report = build_report(session, guard_errors=guard_errors)
        session.report = report
        if session.last_error:
            session.status = SessionStatus.LLM_UNAVAILABLE
        else:
            session.status = SessionStatus.COMPLETE
        self._record_progress(
            session,
            phase="report_generation",
            status="completed",
            tool="Report Builder",
            title="分析报告已生成",
            message="报告已持久化，可以查看完整结果。",
            details={"report_status": report["status"], "official": report["official"]},
        )
        return self._session_response(session, include_report=True)

    def get_report(self, session_id: str) -> dict[str, Any]:
        session = self.store.load(session_id)
        if not session.report:
            raise AgentError("awaiting_user_confirmation", "报告尚未生成", status_code=409)
        return session.report

    def get_event(self, session_id: str, event_id: str) -> dict[str, Any]:
        session = self.store.load(session_id)
        event = get_event_details(session.batch_analysis or {}, event_id)
        if event is None:
            raise AgentError("event_not_found", "事件不存在", status_code=404)
        return event

    @staticmethod
    def _session_response(session: AgentSession, include_report: bool = False) -> dict[str, Any]:
        excluded = {"batch_analysis"}
        if not include_report:
            excluded.add("report")
        data = session.model_dump(mode="json", exclude=excluded)
        return {"session": data}
