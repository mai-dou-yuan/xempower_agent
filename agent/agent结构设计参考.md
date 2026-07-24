# AI 拳击评判员 Agent 结构设计（批量分析优先）

本文依据以下项目文件设计：

- `agent/event_data/README.txt`；
- `agent/rag/rag结构设计参考.md`；
- `agent/rag/knowledge_base/README.md`。

当前系统的合理定位是：

> 对一批已有的出拳模型预测先做确定性整体分析，再由 Agent 结合 WBC Judge 规则生成视频级/事件组级证据报告；只有出现异常、低置信度或需要举证时，才按 `event_id` 下钻。

`event_id` 是追溯和定位主键，不是 Agent 默认逐条推理的工作单位。当前数据仍不足以完成正式逐回合 10-Point Must 判分。

## 1. 当前项目事实与边界

### 1.1 实际输入

当前输入为 `agent/event_data/predictions.csv`，共有 318 条已标注出拳事件，涉及 4 个 `video_id`。每行通过 `event_id` 对齐同一次出拳的两类模型预测：

```text
pred_punch_type
pred_punch_type_confidence
pred_contact_outcome
pred_contact_outcome_confidence
```

其中 `pred_contact_outcome` 只有：

```text
landed
blocked
missed
```

事件定位依赖：

```text
event_id
video_id / video_name
fighter
start_frame / peak_frame / contact_frame / end_frame
```

当前 CSV 包含 4 个视频，但没有 bout/match manifest，不能自动断言这 4 个视频属于同一场比赛。系统应先做“全文件分析”，再按 `video_id` 分组；未来得到比赛映射后，才能进一步按 `bout_id → round` 聚合。

### 1.2 GT 与线上预测隔离

CSV 同时包含人工标注和模型预测。至少 `punch_type`、`contact_outcome` 是 GT；`target`、`score_result`、`no_score_reason`、`foul_action`、`notes` 也属于标注侧信息。

必须产生两个物理或逻辑隔离的数据视图：

```text
offline_eval_view
  事件定位 + GT/标注 + prediction
  仅用于模型评估和误差分析

runtime_view
  事件定位 + prediction + 线上真实可用字段
  仅用于 Agent 推理
```

Agent 不得接收完整 CSV 行，也不得读取：

```text
punch_type
contact_outcome
target
score_result
no_score_reason
foul_action
notes
```

如果未来上线独立目标区域模型，应新增 `pred_target` 和 `pred_target_confidence`，不能复用人工标注 `target`。

### 1.3 知识库

知识库目录为 `agent/rag/knowledge_base/`：

| 文件 | 角色 | 使用方式 |
|---|---|---|
| `Ring-Official-Guidelines-Boxing-Judge-RAG.md` | 整理后的知识库 | 默认建立 RAG 索引并返回规则证据 |
| `Ring-Official-Guidelines-Ingles_no_images.md` | 英文源文件 | 核验整理版，不作为第一版默认召回库 |
| `README.md` | 说明文件 | 记录两份规则文件的角色和维护原则 |

整理版存在明确的规则歧义、OCR 问题和未定义术语。Agent 不能利用模型常识补写规则，必须返回 `ambiguous` 或 `insufficient`。

### 1.4 当前不能完成的判断

现有数据没有：

- 回合边界、比赛时钟和 FPS；
- 线上目标区域预测；
- 干净程度、拳力、实际效果或伤害特征；
- Referee 正式击倒、犯规、扣分、伤因和终止裁定；
- 即时回放最终裁定；
- KO、TKO、DQ、Technical Decision 等正式结果。

所以批量分析可以描述“预测命中、预测格挡、预测未命中、拳型分布、置信度和异常”，但不能把这些统计直接命名为“有效拳”“得分拳”或正式回合比分。

## 2. 核心设计：先批量分析，再进行 Agent 推理

旧思路容易让系统按 `event_id` 重复执行完整 Agent Loop。修订后采用两层架构：

```text
predictions.csv
       |
       v
Mandatory Batch Preprocessor
固定调用 analyze_event_batch()，只执行一次
       |
       +-- 建立 runtime/offline 隔离
       +-- 校验整批数据
       +-- 按 video_id 分组并按帧排序
       +-- 生成双方预测统计和置信度分布
       +-- 识别缺失值、异常和复核候选
       +-- 生成唯一规则查询签名
       |
       v
batch_analysis.json
       |
       v
Boxing Judge Evidence Agent
       |
       +-- 批量检索唯一规则签名
       +-- 对视频/事件组进行证据评估
       +-- 仅对异常 event_id 按需下钻
       +-- 执行权限与证据充分性检查
       |
       v
整体报告 + 事件组结论 + 复核队列 + 规则证据索引
```

核心变化：

- Agent 默认接收 `batch_analysis.json`，不接收 318 条原始事件全文；
- 整体统计和异常发现由确定性代码完成，不让 LLM 自己计数；
- 同一规则问题只检索一次，再映射到多个事件组；
- 默认输出视频级和事件组级结果，不默认输出 318 份事件判断；
- `event_id` 只用于下钻、引用和人工复核。

## 3. 为什么批量优先更适合当前项目

### 3.1 减少重复推理

大量事件共享相同规则问题。例如所有 `pred_contact_outcome=landed` 且目标未知的事件，都需要查询“预测接触是否足以支持合法有效击打”这一类规则。无需为每个事件分别检索。

### 3.2 保留整体上下文

拳击 Judge 评价的是整个回合表现，不是将每一拳机械换算成一分。虽然当前没有回合边界，但视频级/帧区间级整体分布仍比孤立事件更接近未来的回合分析方式。

### 3.3 控制上下文体积

Agent 只接收统计摘要、事件组、异常列表和少量代表事件。完整运行时事件保存在外部事件索引中，需要时通过工具读取。

### 3.4 保留可追溯性

批量处理不等于丢弃事件。每个统计组必须保留 `event_count`、`event_ids` 或外部事件集合引用；最终可以追溯到具体视频和帧。

### 3.5 防止过度聚合

只看总数可能隐藏低置信度和异常事件。因此批量工件必须同时提供：

- 总体统计；
- 置信度分布，而不是只给平均值；
- 缺失字段统计；
- 异常/低置信度事件列表；
- 每个事件组的覆盖数量和代表事件；
- 可供下钻的事件索引。

## 4. 系统总体架构

第一版采用单 Agent，不拆成 Vision Agent、Rule Agent、Judge Agent 和 Supervisor Agent。

```text
                              predictions.csv
                                     |
                    +----------------+----------------+
                    |                                 |
                    v                                 v
              runtime_view                      offline_eval_view
              Agent 可用                         评估专用
                    |
                    v
          analyze_event_batch()  [固定前置步骤]
                    |
                    v
             Batch Analysis Store
                    |
                    v
          Boxing Judge Evidence Agent
                    |
          +---------+----------+----------------+
          |                    |                |
          v                    v                v
 Batch Rule Retrieval   Event Drill-down   Evidence Guard
 规则签名批量检索         异常按需查看       权限/粒度/引用
          |                    |                |
          +---------+----------+----------------+
                    |
                    v
       Video/Group Report + Review Queue + Audit
```

推荐 Agent 名称：

```text
Boxing Judge Evidence Agent
拳击评判员规则证据 Agent
```

不使用 `Boxing Referee Agent`，因为当前系统无权认定正式击倒、犯规、扣分、伤因或停止比赛。

## 5. 固定前置工具：`analyze_event_batch`

### 5.1 调用位置

该工具由 Controller 在进入 LLM Agent Loop 前无条件调用，不交给 LLM 决定是否调用：

```python
batch_analysis = analyze_event_batch(
    csv_path="agent/event_data/predictions.csv",
    mode="runtime",
    group_by="video_id",
)

agent_result = judge_agent.run(batch_analysis)
```

一次任务原则上只调用一次。若 CSV 内容发生变化，应以文件哈希识别新批次并重新分析。

### 5.2 工具职责

`analyze_event_batch` 必须确定性完成：

1. 读取 CSV 并校验字段；
2. 检查 `event_id` 唯一性；
3. 在进入 Agent 前移除 GT/标注字段；
4. 保留 `contact_frame=null`，不静默替换；
5. 校验帧号和置信度范围；
6. 按 `video_id` 分组；
7. 在每个视频内按帧排序；
8. 按 fighter、预测拳型和预测接触结果聚合；
9. 生成置信度区间分布和缺失值统计；
10. 标记低置信度、重叠、时序异常和缺失字段事件；
11. 建立外部 `event_index`；
12. 生成去重后的规则查询签名；
13. 输出数据完整性和覆盖信息。

置信度的低/中/高阈值必须从验证集校准，不能在工具中任意写死。

### 5.3 输出工件

推荐输出：

```json
{
  "analysis_id": "batch_001",
  "source": {
    "file": "agent/event_data/predictions.csv",
    "sha256": "...",
    "mode": "runtime"
  },
  "dataset": {
    "event_count": 318,
    "video_count": 4,
    "gt_fields_removed": true,
    "round_manifest_available": false,
    "fps_available": false
  },
  "videos": [
    {
      "video_id": "...",
      "frame_range": [8, 8036],
      "event_count": 80,
      "fighter_summaries": {
        "red": {
          "predicted_contact_distribution": {
            "landed": 0,
            "blocked": 0,
            "missed": 0
          },
          "predicted_punch_type_distribution": {},
          "confidence_distribution": {}
        },
        "blue": {}
      },
      "event_groups": [
        {
          "group_id": "video_x_red_landed_target_unknown",
          "criteria": {
            "fighter": "red",
            "pred_contact_outcome": "landed",
            "pred_target": null
          },
          "event_count": 0,
          "event_ids_ref": "event-set://...",
          "representative_event_ids": [],
          "rule_query_signature": "..."
        }
      ],
      "review_candidates": [],
      "rounds": null
    }
  ],
  "unique_rule_query_signatures": [],
  "event_index_ref": "event-index://batch_001"
}
```

示例中的统计值为结构占位符，实际值必须由工具从 CSV 计算，不能让 LLM填写。

### 5.4 运行模式

```text
mode=runtime
  删除 GT，生成供 Agent 使用的批量工件

mode=offline_eval
  可读取 GT，计算模型指标；结果与 runtime 工件分开保存
```

Agent 只能接收 `mode=runtime` 的工件。离线评估结果不能混入事件规则判断提示词。

## 6. Agent 可调用工具

### 6.1 `search_boxing_judge_rules_batch`

一次接收全部唯一规则签名：

```python
search_boxing_judge_rules_batch(
    query_signatures,
    match_config,
    knowledge_base_hash,
)
```

返回 `signature → evidence package` 映射：

```json
{
  "signature_x": {
    "status": "sufficient | ambiguous | insufficient",
    "evidence": [
      {
        "chunk_id": "...",
        "parent_id": "...",
        "heading_path": ["..."],
        "content": "...",
        "decision_authority": ["judge"],
        "source_file": "knowledge_base/Ring-Official-Guidelines-Boxing-Judge-RAG.md",
        "retrieval_score": 0.0
      }
    ],
    "missing_evidence_roles": [],
    "review_required": false
  }
}
```

检索结果应覆盖 definition、condition、exception、authority 和 ambiguity。`retrieval_score` 只表示文档相关性，不能与预测置信度合并。

### 6.2 `get_event_drilldown`

仅在需要复核时读取具体事件：

```python
get_event_drilldown(
    event_ids,
    before_events=2,
    after_events=2,
)
```

适用情况：

- 低置信度或字段缺失；
- 同一时间段事件重叠；
- 双方密集交换；
- 批量统计出现异常；
- 需要为报告提供具体例证；
- 用户明确询问某个 `event_id`。

默认使用前后事件数量或帧区间，不能在没有 FPS 时声称查询“前后 5 秒”。工具仍只能返回运行时字段，不能泄漏 GT。

### 6.3 `check_batch_evidence_and_authority`

在最终输出前检查：

```python
check_batch_evidence_and_authority(
    batch_analysis,
    group_assessments,
    rule_evidence_map,
    official_rulings,
)
```

必须检查：

- 工件是否为 `runtime` 模式；
- 是否存在 GT 字段；
- 统计名称是否明确带“预测”；
- 是否把 landed 直接当成合法有效击打；
- 是否从视频总量直接推导回合比分；
- 是否越过 Judge 权限认定击倒、犯规或扣分；
- 是否缺少规则定义、条件、例外、权限或歧义证据；
- 每个组结论是否可追溯到事件集合和规则块；
- 是否应加入人工复核队列。

### 6.4 `build_batch_report`

确定性地将 Agent 的结构化结论渲染成 JSON 或 Markdown 报告，不负责改变判断：

```python
build_batch_report(
    batch_analysis,
    group_assessments,
    rule_evidence_map,
    review_queue,
)
```

### 6.5 第一版不提供 `calculate_round_score`

当前没有回合边界、完整整回合特征和官方裁定，不能开放通用回合计分工具。未来只有在补齐 round manifest、目标/效果特征和正式裁定后，才能新增受限的 `calculate_round_base_score`。

## 7. 批量优先的 Agent Loop

`analyze_event_batch()` 是 Loop 之前的固定前置步骤。Agent Loop 每个批次或视频执行，不是每个 `event_id` 执行。

```text
0. Mandatory Preprocess（Controller）
   对整个 CSV 固定调用一次 analyze_event_batch()

1. Observe
   接收 batch_analysis，而不是逐条原始事件

2. Validate Scope
   确认文件范围、video 分组、runtime 模式、缺失字段和任务粒度

3. Plan by Group
   根据 event_groups 和 unique_rule_query_signatures 制定批量规则任务

4. Retrieve Once
   对全部唯一签名批量检索或复用缓存

5. Assess Groups
   将预测统计、规则要求和缺失信息映射到视频/事件组

6. Drill Down Selectively
   只对异常、低置信度、争议或被用户点名的 event_id 查看上下文

7. Verify
   执行标签泄漏、权限、粒度、覆盖率和引用检查

8. Finalize
   输出整体报告、事件组结论、复核队列和证据索引
```

循环控制：

- 一次批次分析只生成一份 `batch_analysis`；
- 每个唯一规则签名最多一次主检索和一次补检；
- 补检只用于缺失关键证据角色；
- event drill-down 有数量上限，超过时输出复核队列而不是塞入全部上下文；
- 两次规则检索后仍不完整，返回 `ambiguous/insufficient`；
- Agent 不能通过反复调用工具把缺失数据变成确定结论。

## 8. 规则查询签名与事件分组

简单枚举由代码归一化：

```text
lead_straight / rear_straight
left_hook / right_hook
left_uppercut / right_uppercut

landed / blocked / missed
```

拳型描述动作形态。当前 Judge 规则没有为直拳、勾拳和上勾拳设置不同分值，因此评分规则签名通常不包含拳型。

推荐签名：

```python
query_signature = (
    knowledge_base_hash,
    "WBC",
    "edition_unknown",
    judgment_task,
    pred_contact_outcome,
    predicted_target_or_unknown,
)
```

推荐事件组：

```text
video_id
  └── fighter
      └── pred_contact_outcome
          └── predicted_target_or_unknown
```

拳型分布作为组的描述性统计保留，不直接决定规则结论。

查询必须中立：

```text
错误：红方预测命中 30 拳，因此赢得该视频对应的回合。

正确：对于一组预测为 landed、但目标和效果未知的事件，
      WBC Judge 判断其能否作为合法有效击打证据还需要哪些条件？
```

## 9. Agent 状态设计

```python
agent_state = {
    "run_id": "...",
    "match_config": {
        "organization": "WBC",
        "rulebook_edition": None,
        "fps": None,
        "round_manifest_available": False,
        "official_rulings_available": False,
    },
    "batch_analysis_ref": "...",
    "video_analysis_summaries": {},
    "rule_evidence_map": {},
    "group_assessments": {},
    "drilldown_contexts": {},
    "review_queue": [],
    "audit_log": [],
}
```

完整事件保存在 Batch Analysis Store，不复制进 Agent 状态或提示词。`drilldown_contexts` 只保存本次实际查看的少量事件。

缓存键必须包含 CSV 哈希、知识库哈希和查询签名，避免数据或规则变化后使用旧结果。

## 10. 输出契约

### 10.1 默认批量报告

```json
{
  "analysis_id": "batch_001",
  "assessment_scope": "dataset_and_video",
  "status": "insufficient",
  "dataset_summary": {
    "event_count": 318,
    "video_count": 4,
    "round_manifest_available": false
  },
  "video_assessments": [
    {
      "video_id": "...",
      "prediction_summary": {},
      "group_assessments": [
        {
          "group_id": "...",
          "event_count": 0,
          "provisional_classification": "possible_scoring_evidence",
          "status": "insufficient",
          "rule_signature": "...",
          "missing_information": [
            "target prediction",
            "clean contact evidence",
            "power/effect evidence"
          ],
          "review_required": true
        }
      ],
      "round_score": null
    }
  ],
  "review_queue": [],
  "rule_evidence_index": {},
  "limitations": [
    "当前 CSV 没有回合边界和 Referee 正式裁定。"
  ]
}
```

### 10.2 事件下钻输出

只有被下钻的事件才生成事件级结果：

```json
{
  "event_id": "...",
  "assessment_scope": "event_drilldown",
  "trigger": "low_confidence",
  "prediction": {
    "punch_type": "left_hook",
    "punch_type_confidence": 0.91,
    "contact_outcome": "landed",
    "contact_outcome_confidence": 0.51
  },
  "status": "insufficient",
  "provisional_classification": "possible_scoring_blow",
  "official_ruling": null,
  "missing_information": [
    "target prediction",
    "clean contact evidence",
    "power/effect evidence"
  ],
  "review_required": true
}
```

### 10.3 当前回合输出

没有 round manifest 时必须返回：

```json
{
  "assessment_scope": "round",
  "round": null,
  "status": "insufficient",
  "base_score": null,
  "reason": "当前事件文件没有回合边界和正式裁定。",
  "review_required": true
}
```

## 11. Self-Verification

输出前检查：

```text
[ ] analyze_event_batch 是否恰好针对当前 CSV 版本执行？
[ ] batch_analysis 是否为 runtime 模式？
[ ] Agent 是否接触了 GT 或标注字段？
[ ] CSV 中的不同 video_id 是否被错误合并成一场比赛？
[ ] 所有计数是否由确定性工具产生？
[ ] 是否把“预测 landed”误写为“正式有效拳”？
[ ] 是否根据全视频总数直接生成回合比分？
[ ] 是否擅自认定 knockdown、foul、deduction、injury 或 stoppage？
[ ] 是否按唯一规则签名复用了证据？
[ ] 事件组是否保留 event 集合引用和覆盖数量？
[ ] drill-down 是否仅用于异常或明确请求？
[ ] 是否引用 chunk_id、heading_path 和 source_file？
[ ] 证据不足时是否进入 review_queue？
```

任何关键检查失败都必须降级为 `ambiguous` 或 `insufficient`。

## 12. 错误与降级策略

统一状态：

```text
sufficient    规则、数据和权限来源足够支持当前粒度的结论
ambiguous     找到相关规则，但规则或事件条件无法唯一解释
insufficient  缺少必要数据、正式裁定或关键规则证据
```

| 情况 | 处理方式 |
|---|---|
| CSV 中包含多个视频 | 全文件校验后按 `video_id` 分组，不假设同一比赛 |
| `contact_frame` 为空 | 保留 `null`，不改变预测类别 |
| 接触结果低置信度 | 保留原预测，加入复核队列 |
| predicted landed 但目标/效果未知 | 事件组标记 `possible_scoring_evidence + insufficient` |
| 批量统计与事件索引数量不一致 | 阻止 Agent 推理，返回批处理完整性错误 |
| 没有 FPS 却请求秒级窗口 | 改用帧或事件数，或返回缺失 FPS |
| 没有回合边界却请求比分 | `base_score=null + insufficient` |
| 没有官方裁定却请求犯规/击倒 | `official_ruling=null + review_required` |
| 规则库未定义相关结果 | 不类推，返回 `ambiguous/insufficient` |
| RAG 不可用 | 不使用模型常识补规则，返回工具错误 |
| drill-down 事件过多 | 截止下钻并输出人工复核清单 |

## 13. 建议项目结构

```text
agent/
├── agent结构设计参考.md
├── event_data/
│   ├── README.txt
│   └── predictions.csv
├── rag/
│   ├── rag结构设计参考.md
│   └── knowledge_base/
│       ├── README.md
│       ├── Ring-Official-Guidelines-Boxing-Judge-RAG.md
│       └── Ring-Official-Guidelines-Ingles_no_images.md
└── boxing_agent/
    ├── controller.py
    ├── state.py
    ├── batch/
    │   ├── analyzer.py
    │   ├── schemas.py
    │   ├── event_index.py
    │   └── anomaly_detector.py
    ├── events/
    │   ├── csv_loader.py
    │   ├── views.py
    │   ├── validator.py
    │   └── drilldown.py
    ├── tools/
    │   ├── batch_rule_retrieval.py
    │   ├── evidence_guard.py
    │   └── report_builder.py
    ├── output/
    │   └── schemas.py
    └── evaluation/
        ├── batch_integrity_tests.py
        ├── leakage_tests.py
        ├── authority_tests.py
        └── end_to_end_cases.jsonl
```

## 14. 当前 MVP 实施顺序

1. 实现 `analyze_event_batch`，一次读取 CSV 并生成 `runtime` 批量工件；
2. 建立 GT/预测隔离测试，确保 Agent 永远看不到标注结论；
3. 按 `video_id` 分组、帧排序并建立外部事件索引；
4. 生成预测分布、置信度分布、缺失值和异常列表；
5. 生成事件组与唯一规则查询签名；
6. 实现 `search_boxing_judge_rules_batch` 和规则证据缓存；
7. 实现事件组级评估和选择性 `get_event_drilldown`；
8. 实现 Evidence Guard、复核队列和批量报告；
9. 验证正常批次不会产生“一事件一次 RAG/LLM 调用”；
10. 在缺少 round manifest 和官方裁定时固定拒绝正式回合比分。

未来要支持真正的逐回合 Judge 判分，至少还需：

- `bout_id`、回合边界、比赛时钟和 FPS；
- 线上目标区域预测及置信度；
- 干净程度、拳力/效果等可验证特征；
- Referee/即时回放正式击倒、犯规、扣分、伤因和终止裁定；
- 组织、明确规则版本、回合数及当地委员会配置。

## 15. 最终方案

推荐架构是：

> **一次确定性批量分析 + 一个 Boxing Judge Evidence Agent + 一次批量规则检索 + 事件组级评估 + 异常事件按需下钻 + Evidence Guard。**

默认处理单位从单个 `event_id` 改为“数据批次 → video_id → event_group”。`event_id` 只承担定位、举证和复核职责。这样既能减少重复计算，又不会因为过度汇总而失去可追溯性，并且与当前项目只有拳型和接触结果预测的事实一致。
