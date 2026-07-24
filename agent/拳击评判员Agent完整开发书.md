# 拳击评判员 Agent 开发任务书（Codex 精简版）

> 目标：让 Codex 按本文直接完成一个可运行、可测试的 MVP。  
> 产品定位：基于比赛事件 CSV、WBC Judge 规则知识库以及可选的用户补充信息，生成**非官方估算比分**、判分理由与完整红蓝对战报告。

## 1. 必须实现的用户场景

用户上传一场比赛的事件 CSV，并提问：

> 根据现有的比赛数据以及裁判规则知识库，给出你认为合理的红蓝双方比分，并说明分数合理的原因，同时整理一份完整的红蓝双方对战报告。

系统必须：

1. 一次性读取并分析完整 CSV，不逐事件调用大模型。
2. 识别回合映射、击倒、扣分、击打质量等缺失信息。
3. 告知用户当前缺失信息并询问是否补充；既接受精确事实，也接受大致比例、区间和总体趋势，同时必须提供“跳过补充，按现有数据继续”的选项。
4. 用户可以补充信息，也可以不提供任何额外信息。已提供的补充信息及需要采纳的系统假设应先让用户确认；选择跳过后不得反复追问。
5. 按回合输出 10-Point Must 估算比分、双方总分、判分理由、置信度、摇摆回合和比分敏感性。
6. 输出完整中文对战报告，并引用实际检索到的知识库条款。
7. 始终声明结果是分析意见，不是官方赛果或正式记分卡。

用户选择不补充时，系统仍应继续分析：根据现有 CSV 和知识库输出当前证据下的最佳估计；对无法确定的内容使用条件比分、合理区间或替代情景，并降低置信度、说明缺失信息会怎样影响结果，不得编造唯一确定比分。

## 2. 项目输入与规则优先级

开发前先阅读：

- `agent/event_data/README.txt`
- `agent/event_data/predictions.csv`
- `agent/rag/knowledge_base/Ring-Official-Guidelines-Boxing-Judge-RAG.md`
- `agent/rag/knowledge_base/README.md`
- `agent/rag/rag结构设计参考.md`
- `agent/agent结构设计参考.md`

规则含义发生冲突时，优先级如下：

1. 知识库中可核验的 WBC 规则及其权限边界；
2. 英文源文件 `Ring-Official-Guidelines-Ingles_no_images.md`；
3. 本开发书的工程约定。

不得用模型常识补写知识库没有定义或明确标为歧义的规则。

## 3. 技术方案

使用 Python 3.11+，建议依赖：

- FastAPI + Uvicorn：HTTP 服务；
- Pydantic：输入、状态和输出模型；
- pandas：CSV 校验与批量统计；
- OpenAI Python SDK：调用 DeepSeek 的 OpenAI 兼容接口；
- rank-bm25 + sentence-transformers + FAISS（或等价本地方案）：混合检索；
- pytest：测试。

DeepSeek 配置只能从环境变量读取：

```env
DEEPSEEK_API_KEY=""
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
```

禁止把真实 API Key 写入源码、文档、测试、日志或提交记录。提供 `.env.example`，真实 `.env` 必须加入 `.gitignore`。模型名必须可配置，不能散落硬编码。

## 4. 交付目录

在 `agent/` 下实现：

```text
agent/
├─ src/boxing_judge_agent/
│  ├─ config.py              # 环境变量与运行配置
│  ├─ schemas.py             # Pydantic 数据契约
│  ├─ csv_analyzer.py        # CSV 校验、隔离、统计、事件索引
│  ├─ missing_context.py     # 缺失信息检测与提问规划
│  ├─ supplements.py         # 用户补充解析、校验、确认和版本化
│  ├─ rag/
│  │  ├─ ingest.py           # 知识库切分和建索引
│  │  └─ retrieve.py         # 混合检索与证据包
│  ├─ scoring.py             # 确定性 10 分制计算
│  ├─ agent.py               # DeepSeek 编排与工具循环
│  ├─ guard.py               # 证据、权限、泄漏和输出检查
│  ├─ report.py              # Markdown/JSON 报告生成
│  ├─ api.py                 # FastAPI 路由
│  └─ cli.py                 # 本地命令行入口
├─ tests/
├─ artifacts/                # 运行工件，加入 .gitignore
├─ pyproject.toml
├─ .env.example
└─ README.md
```

如项目已有同等结构，应复用，不为目录一致性做无意义迁移。

## 5. 数据处理要求

### 5.1 两种数据视图

必须在代码层隔离：

- `runtime_view`：只含事件定位字段和 `pred_*` 预测字段，供 Agent 判分分析。
- `offline_eval_view`：可含 GT/人工标注，仅供模型离线评估。

运行时禁止把以下人工标注字段传给 Agent：

```text
punch_type, target, contact_outcome, score_result,
no_score_reason, foul_action, notes
```

只有用户明确选择“历史标注复盘模式”时，才可把标注包装为独立的 `dataset_annotation` 证据；它仍不是官方裁定。

### 5.2 批量分析

`analyze_event_batch(csv_path, mode)` 必须只执行一次，并确定性完成：

- 必填列、类型、枚举、置信度范围和 `event_id` 唯一性校验；
- 按 `video_id`、fighter、预测拳型、预测接触结果聚合；
- 统计数量、比例、置信度分布、缺失值和异常事件；
- 建立可按 `event_id` 查询的事件索引；
- 输出文件哈希和分析 ID；
- 生成后续规则检索所需的去重查询，而非每条事件检索一次。

硬性边界：

- `pred_contact_outcome=landed` 只能写作“预测命中”，不能直接称为有效拳或得分拳；
- 每次出拳不是一分，禁止按命中数量机械累加比分；
- `contact_frame=null` 保持为空，不能自动视为未命中，也不能静默替换；
- 没有 manifest 时，不能自动断言多个 `video_id` 对应哪些回合；
- 帧号仅能在同一视频内排序，缺少 FPS 时不能伪造比赛时间。

## 6. 用户交互补全

### 6.1 优先补充的信息

系统先给用户两个明确选择：

- `add_supplement`：继续补充缺失信息；
- `skip_supplement`：不添加额外信息，按现有 CSV 和知识库继续。

只有用户选择 `add_supplement` 时，才按信息增益依次确认：

1. 比赛回合数、已完成回合数，以及 `video_id/帧区间 → round` 的映射；
2. 每回合双方实际有效进攻的相对质量、干净程度、力量、准确性和效果；
3. 击倒、警告、犯规和扣分，以及是否属于正式裁定；
4. CSV/视频覆盖是否完整，是否存在未记录的重要片段；
5. 其他可能改变回合胜负的信息。

每轮最多问 3 个最关键问题，避免一次抛出长问卷。最多进行 8 轮；到达上限后给出当前信息下的条件结果。用户在任意一轮选择 `skip_supplement` 后，立即停止补充提问并进入现有数据分析流程。

### 6.2 接受的回答形式

系统必须能解析以下形式：

- 精确事实：“第 3 回合蓝方有一次击倒，双方无扣分。”
- 比较判断：“第 2 回合红方干净重拳明显更多，但蓝方出拳量略多。”
- 大致比例：“四个回合约 60% 的高质量命中来自红方。”
- 区间：“蓝方每回合大约有 6—8 次清晰命中。”
- 总体分布：“前两回合接近，后两回合红方优势较明显。”
- 未知：“击倒情况不清楚。”
- 跳过补充：“我不补充额外信息，请直接根据现有数据分析。”

每条补充都保存为版本化记录，至少包含：

```text
revision, scope, round, fighter, metric, value/range,
source_type, confidence, raw_user_text, confirmed
```

`source_type` 仅允许：

- `user_asserted_fact`
- `user_estimate`
- `verified_official_ruling`
- `agent_assumption`
- `dataset_annotation`

解析后先向用户回显结构化理解。用户提供了补充信息时，确认前不得将其用于最终判分。用户选择跳过时，保存 `supplement_mode=skip` 和确认记录，缺失项继续保持 `unknown`，不得把“未提供”解释为“没有发生”。

选择跳过补充不等于同意任意系统假设。若形成主比分必须依赖回合映射等关键假设，系统应列出最少量假设供用户一次性确认；用户不接受时，改为输出多情景条件比分和区间，不再要求用户提供事实细节。

## 7. RAG 要求

### 7.1 建库

以 `Ring-Official-Guidelines-Boxing-Judge-RAG.md` 为默认召回库：

- `##` 章节作为 Parent；
- `###` 及其自然段/列表作为 Child；
- Child 用于召回，最终向 Agent 同时提供命中的 Child 和必要 Parent 上下文；
- 表格切分时保留表头和标题路径；
- 不跨标题边界制造重叠文本。

每个 chunk 至少保存：

```text
chunk_id, parent_id, heading_path, text, rule_domains,
decision_authority, source_file, knowledge_base_hash
```

### 7.2 检索

流程：规则域路由 → BM25 与向量召回 → 合并去重 → 重排 → Parent/歧义条款扩展 → 证据包。

评分、击倒、犯规/扣分、权限边界等不同主题分别检索，一次请求内复用结果。每条规则性结论都必须带：

```text
chunk_id + heading_path + source_file + knowledge_base_hash
```

检索不到足够证据时返回 `insufficient_rule_evidence`；知识库存在冲突或歧义时返回 `ambiguous_rule`。两种情况都禁止模型凭常识补规则。

## 8. 判分设计

### 8.1 职责分离

- 确定性代码负责：数量、比例、排序、缺失检测、基础分与扣分相减、总分汇总。
- DeepSeek 负责：根据事件摘要、用户补充和规则证据，对每回合做定性比较并给出理由。
- Guard 负责：检查证据来源、权限边界、比分计算和措辞。

模型不得直接自由生成最终算术结果。

### 8.2 每回合评估

DeepSeek 对每回合输出结构化 `RoundAssessment`：

```json
{
  "round": 1,
  "winner": "red|blue|even|insufficient",
  "dominance": "close|clear|overwhelming",
  "knockdowns": {"red": 0, "blue": 0, "source": "..."},
  "deductions": {"red": 0, "blue": 0, "source": "..."},
  "reason": "...",
  "evidence_refs": ["chunk_id"],
  "data_sources": ["model_prediction", "user_estimate"],
  "confidence": "high|medium|low"
}
```

`scoring.py` 再依据检索到的规则情景把评估映射为基础回合分，并单独扣除正式/已确认的扣分：

```text
adjusted_score = base_round_score - deductions
```

实现时不得假定“有一次击倒必然是 10-8”，也不得把大致比例转成固定权重公式。必须保留基础分、扣分和调整后得分三列。

### 8.3 判分充分性与跳过补充分支

形成较高置信度的单一主比分最好具备：

- 已完成回合数；
- 事件到回合的映射，或用户明确授权的映射假设；
- 每回合双方有效进攻表现的相对信息；
- 击倒和扣分已知，或明确记录为未知/假设；
- 用户已确认其提供的补充信息和需要实际采纳的关键假设。

用户选择 `skip_supplement` 是合法且完整的交互路径，不得将其视为错误或阻塞。此时：

- 仅使用运行时 CSV、知识库和已确认的最小假设；
- 未提供的击倒、扣分、回合映射或击打质量保持 `unknown`，不能默认成 0、无或双方相同；
- 能在现有证据下形成主估计时，标记 `score_status=conditional` 和低置信度；
- 无法支持唯一主估计时，给出多个明确条件下的情景比分，不强迫用户继续补充；
- 报告必须说明如果补充哪些信息，比分可能发生什么变化。

信息不满足时输出 `score_status=conditional` 或 `insufficient`，并给出：

- 主情景比分；
- 合理比分范围；
- 最多 3 个替代情景；
- 会改变结果的关键未知项。

所有比分统一标记：

```text
score_kind=estimated_opinion
official=false
```

## 9. Agent 工作流

```text
接收 CSV 与问题
  → 批量校验和统计
  → 检测缺失上下文
  → 询问“补充信息”或“跳过补充”
  → [补充] 生成最多 3 个问题 → 解析、回显并确认
  → [跳过] 记录选择 → 必要时一次性确认最小假设
  → 批量检索规则证据
  → 生成逐回合定性评估
  → 确定性计算比分与敏感性
  → Guard 校验
  → 输出 JSON + Markdown 完整报告
```

Agent 状态至少包括：

```text
ANALYZING → AWAITING_SUPPLEMENT_CHOICE
→ AWAITING_USER_INPUT | SUPPLEMENT_SKIPPED
→ AWAITING_CONFIRMATION
→ RETRIEVING_RULES → SCORING → REPORTING → COMPLETE
```

状态必须持久化，服务重启后可以凭 `session_id` 继续。

Agent 可调用的内部工具保持精简：

```text
analyze_event_batch
analyze_missing_context
parse_user_supplement
retrieve_rule_evidence
get_event_details
calculate_scorecard
validate_output
build_report
```

## 10. API 与 CLI

最低 HTTP 接口：

```text
POST /sessions                         创建会话并上传 CSV
GET  /sessions/{id}                    查询状态
POST /sessions/{id}/messages           提交问题或补充信息
POST /sessions/{id}/confirm            选择补充/跳过并确认补充信息或假设
GET  /sessions/{id}/report             获取 JSON 或 Markdown 报告
GET  /sessions/{id}/events/{event_id}  事件下钻
POST /rag/rebuild                       重建知识库索引
GET  /health                            健康检查
```

CLI 至少支持：

```powershell
python -m boxing_judge_agent.cli analyze --csv agent/event_data/predictions.csv
python -m boxing_judge_agent.cli rebuild-index
python -m boxing_judge_agent.cli serve
```

API 错误需返回稳定错误码，例如：

```text
invalid_csv, missing_required_columns, duplicate_event_id,
awaiting_user_confirmation, insufficient_context,
insufficient_rule_evidence, llm_unavailable
```

## 11. 最终报告格式

Markdown 报告固定包含：

1. 结论摘要与非官方声明；
2. 数据范围和比赛结构；
3. 数据质量、缺失项和模型预测局限；
4. 用户补充信息（或跳过补充记录）与系统假设；
5. 红方整体表现；
6. 蓝方整体表现；
7. 逐回合分析；
8. 估算记分卡（基础分、扣分、调整后分、总分）；
9. 比分合理性说明；
10. 关键事件、摇摆回合与比赛转折；
11. 合理比分范围和替代情景；
12. 规则证据索引；
13. 待复核事项与结论局限。

同时返回结构化 JSON，至少包含：

```text
session_id, analysis_id, status, score_kind, official,
data_quality, supplement_mode, assumptions, round_assessments, scorecard,
plausible_range, swing_rounds, alternative_scenarios,
rule_evidence, report_markdown
```

## 12. Guard 硬性检查

最终输出前必须拒绝或降级以下情况：

- GT/标注字段泄漏到运行时 Agent；
- 将预测命中称为官方有效拳或得分拳；
- 将用户估计称为官方裁定；
- 将尚未确认的用户补充或关键系统假设用于最终比分；
- 用户选择跳过补充后继续反复追问或拒绝生成条件分析；
- 将一次出拳机械换算成一分；
- 将击倒机械固定为 10-8；
- Judge Agent 自行认定击倒、犯规、扣分、伤因或正式赛果；
- 无知识库引用却陈述具体规则；
- 分项与总分算术不一致；
- 把估算结果描述成正式记分卡。

Guard 失败时返回明确原因，可修复则自动回到相应步骤重试一次；仍失败则输出降级报告，不输出伪造比分。

## 13. 测试与验收

### 13.1 必测内容

- CSV schema、重复 ID、空值、异常帧和置信度范围；
- runtime/offline 字段隔离和提示词标签泄漏测试；
- 批量统计结果可重复，且一次任务只分析一次 CSV；
- RAG chunk、混合召回、Parent 扩展、引用和知识库哈希；
- 用户精确事实、比例、区间、总体趋势、未知和冲突回答的解析；
- 用户补充内容和关键系统假设的确认控制；
- `skip_supplement` 分支能够停止追问并生成低置信度条件结果；
- 基础回合分、扣分和总分计算；
- 条件比分、替代情景和摇摆回合；
- DeepSeek 超时、返回非法 JSON、RAG 不可用时的降级；
- 完整报告的 13 个固定章节。

外部 LLM 测试使用 mock，默认测试不能消耗真实 API 配额。另提供一个显式启用的 smoke test。

### 13.2 端到端验收场景

至少覆盖：

1. 数据完整：直接确认后生成逐回合比分和完整报告。
2. 缺回合映射：系统先提问，补充并确认后继续。
3. 用户只给大致分布：生成低置信度条件比分和合理范围。
4. 用户不知道击倒/扣分：保留未知，展示对应替代情景。
5. 用户选择不添加任何信息：停止追问，仅根据现有数据输出低置信度条件比分、区间和完整报告。
6. 用户跳过补充且不接受关键假设：输出多情景比分，不虚构唯一结果。
7. 用户补充前后冲突：要求澄清，不静默覆盖。
8. RAG 无证据：不给具体规则结论，输出 `insufficient_rule_evidence`。
9. LLM 不可用：仍返回确定性数据分析和可恢复状态。
10. 当前 `predictions.csv`：不写死 318 条等统计值，运行时重新计算。

### 13.3 完成定义

满足以下条件才算交付完成：

- `pytest` 全部通过；
- README 包含安装、配置、建索引、启动、示例交互和测试命令；
- `.env.example` 不含真实密钥；
- CLI 与 API 均能跑通目标问题；
- 会话可多轮补充、确认和恢复，也可跳过全部补充直接继续；
- 输出包含估算总分、逐回合理由、合理区间和完整报告；
- 每条规则性结论可追溯到知识库；
- 不满足可判分条件时能正确降级；
- 所有估算比分都明确标注为非官方意见。

## 14. Codex 实施顺序

Codex 按以下顺序工作，每步完成后运行相关测试：

1. 建工程骨架、配置和 Pydantic schema。
2. 实现 CSV 视图隔离、批量分析和事件索引。
3. 实现知识库切分、索引、检索和引用。
4. 实现缺失检测、补充解析、确认和会话状态。
5. 接入 DeepSeek，要求结构化输出并处理重试/非法 JSON。
6. 实现确定性判分、敏感性分析和 Guard。
7. 实现 Markdown/JSON 报告。
8. 实现 FastAPI、CLI、持久化和错误码。
9. 补齐单元、集成、端到端和 smoke tests。
10. 用 `agent/event_data/predictions.csv` 完成一次演示并记录命令，不把演示结果写死进业务代码。

除非遇到会改变产品边界的阻塞问题，Codex 应直接实现、测试和修复，不需要再次输出一份更细的设计文档。
