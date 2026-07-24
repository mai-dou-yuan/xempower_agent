from __future__ import annotations

import argparse
import json

import uvicorn

from .agent import BoxingJudgeAgent
from .rag.ingest import rebuild_index


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="拳击评判员 Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="分析 CSV 并生成非官方条件报告")
    analyze.add_argument("--csv", required=True)
    analyze.add_argument("--question", default="根据现有数据和规则给出红蓝双方分析。")
    analyze.add_argument("--assume-videos-as-rounds", action="store_true")
    analyze.add_argument("--json", action="store_true", dest="as_json")
    sub.add_parser("rebuild-index", help="重建本地规则索引")
    serve = sub.add_parser("serve", help="启动 HTTP 服务")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    agent = BoxingJudgeAgent()
    if args.command == "rebuild-index":
        result = rebuild_index(agent.settings.knowledge_base, agent.store.indexes / "rules.json", settings=agent.settings)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "serve":
        uvicorn.run("boxing_judge_agent.api:app", host=args.host, port=args.port)
        return 0
    session = agent.create_session(args.csv, args.question)
    skipped = agent.confirm(session.session_id, "skip_supplement")
    result = agent.confirm(
        session.session_id,
        "confirm_assumptions" if args.assume_videos_as_rounds else "reject_assumptions",
    )
    report = result["session"]["report"]
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.as_json else report["report_markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
