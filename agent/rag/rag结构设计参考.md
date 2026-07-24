# AI 拳击评判员 RAG 结构设计（按当前项目数据修订）

本文只以以下两个项目内文件为事实依据：

- `agent/event_data/predictions.csv`（字段说明见同目录 `README.txt`）；
- `agent/rag/知识库/Ring-Official-Guidelines-Boxing-Judge-RAG.md`。

当前项目适合采用“结构化事件处理 + 层次化规则检索 + 回合级聚合”的方案。RAG 的作用是提供可追溯的 WBC Judge 规则证据，不能把模型预测自动提升为 Referee 的正式裁定，也不能用单个出拳事件直接生成正式回合比分。

## 1. 当前项目事实

### 1.1 事件数据的实际形态

输入不是示例性的事件 JSON，而是 `predictions.csv`。当前文件共有 318 条出拳事件，来自 4 个视频；每行用 `event_id` 对齐同一次出拳的人工标注与两类模型预测。

CSV 共 25 个字段，可按用途分成四组：

1. 事件定位字段：
   `event_id`、`video_id`、`video_name`、`fighter`、`start_frame`、`peak_frame`、`contact_frame`、`end_frame`。
2. 人工标注/评估标签：
   `punch_type`、`target`、`contact_outcome`、`score_result`、`no_score_reason`、`foul_action`、`notes`。
3. 模型预测：
   `pred_punch_type`、`pred_punch_type_confidence`、`pred_contact_outcome`、`pred_contact_outcome_confidence`。
4. 标注审计字段：
   `annotator_id`、`created_at`、`updated_at`、`revision_count`、`original_event_json`、`edit_history_json`。

当前数据的主要取值如下：

| 字段 | 当前取值/分布 |
|---|---|
| `fighter` | red 180，blue 138 |
| `punch_type`（GT） | lead_straight 130，left_hook 88，right_hook 62，rear_straight 24，left_uppercut 10，right_uppercut 3，unknown 1 |
| `contact_outcome`（GT） | blocked 108，missed 103，landed 94，uncertain 13 |
| `pred_contact_outcome` | landed 121，missed 116，blocked 81；模型没有输出 `uncertain` |
| `target`（标注） | head 217，body 100，unknown 1 |
| `score_result`（标注） | no_score 216，scored 88，uncertain 14 |
| `no_score_reason`（标注） | none 224，blocked_by_arm 37，blocked_by_glove 29，missed_target 14，unclear 10，too_light 4 |
| `foul_action` | 318 条全部为空 |

当前文件中 `contact_frame` 有 109 条为空；空值不能被解释成“未命中”，因为 landed、blocked、missed 等类别中都存在空 `contact_frame`。

### 1.2 当前预测能力的边界

项目当前只有两类模型输出：拳型预测和接触结果预测。没有以下模型输出或正式事件字段：

- 回合号、比赛时钟、视频 FPS；
- 目标区域预测置信度；
- 拳力、干净程度、有效效果或伤害程度；
- Referee 正式认定的 knockdown/no-knockdown；
- foul、warning、point deduction；
- injury cause、stoppage、instant replay final ruling；
- KO、TKO、DQ、Technical Decision 等正式比赛结果。

因此，现阶段可以做“出拳事件识别、规则证据匹配、按视频片段统计模型预测”，但不能仅凭现有 CSV 完成 WBC 意义上的正式逐回合 10-Point Must 判分。

### 1.3 规则库的实际范围

规则库是 `agent/rag/知识库/Ring-Official-Guidelines-Boxing-Judge-RAG.md`，标题为“AI 拳击评判员 RAG 知识库”。它是由同目录英文源文件整理而成的 WBC Judge 规则知识库，覆盖职责边界、计分、击倒、犯规、伤情、即时回放和记分卡流程。

它不是一个标注为“2026 edition”的多组织规则库，也不是按 `Elbow Strike > Penalty` 组织的犯规词典。文件内还明确记录了原始材料的歧义、OCR 问题和未定义术语。因此不得在 metadata 或过滤条件中凭空写入 `edition=2026`、独立的肘击处罚章节、RTD 或 No Contest 规则。

## 2. 总体架构

```text
predictions.csv
    |
    +-- 离线评估视图：GT + prediction（仅用于评估）
    |
    +-- 线上推理视图：事件定位 + prediction（禁止读取 GT）
                         |
                  字段校验 / 置信度门控
                         |
                  事件归一化 / 查询路由
                         |
        +----------------+----------------+
        |                                 |
  确定性规则映射                    规则 RAG 检索
  （状态、缓存签名）       标题/关键词 + Dense + 重排序
        |                                 |
        +----------------+----------------+
                         |
              父章节与歧义条款扩展
                         |
                  结构化证据包
                         |
               视频/回合级事件聚合
                         |
          可判定性检查 + Judge Agent
                         |
        判分建议/证据/缺失信息/人工复核标记
```

关键原则：

- 小块负责定位，父章节负责理解；
- 规则检索和事件统计分离；
- GT 与线上推理分离；
- Judge 权限与 Referee 权限分离；
- 事件级结论与回合级比分分离；
- 有歧义时显式返回 `ambiguous` 或 `insufficient`。

## 3. 数据视图与防标签泄漏

### 3.1 离线评估视图

离线评估可以读取整行，用于比较：

- `punch_type` 与 `pred_punch_type`；
- `contact_outcome` 与 `pred_contact_outcome`；
- 预测事件与 `score_result`、`no_score_reason` 的关系。

按当前文件直接计算，拳型预测准确率为 258/318（81.13%）；接触结果预测若把 GT 的 `uncertain` 也计入总体，为 213/318（66.98%），排除 13 条 `uncertain` GT 后为 213/305（69.84%）。这些数字是当前数据集上的描述性结果，不是正式 Judge 判分准确率。

### 3.2 线上推理视图

线上 Agent 不得读取以下标签列：

```text
punch_type
contact_outcome
score_result
no_score_reason
foul_action
notes
```

`target` 当前只有人工标注值，没有对应的 `pred_target` 和置信度。除非上游明确保证线上能够独立产生 target，否则也应从线上视图排除。推荐生成单独的运行时 DTO，而不是把 CSV 整行直接传入 Agent：

```json
{
  "event_id": "a002c0001_20250416044916_0001_000001",
  "video_id": "a002c0001_20250416044916_0001",
  "fighter": "red",
  "start_frame": 8,
  "peak_frame": 18,
  "contact_frame": 18,
  "end_frame": 23,
  "pred_punch_type": "lead_straight",
  "pred_punch_type_confidence": 0.958613,
  "pred_contact_outcome": "missed",
  "pred_contact_outcome_confidence": 0.401006,
  "pred_target": null,
  "pred_target_confidence": null
}
```

### 3.3 缺失值与置信度规则

- `contact_frame` 为空时保留为 `null`，不能用 `peak_frame` 静默替代，也不能直接改判 missed。
- 两个置信度分别绑定各自预测，不能合并成虚构的 `event_confidence`。
- 置信度阈值应通过验证集校准，不在设计文档中臆定固定数值。
- `pred_contact_outcome` 没有 `uncertain` 类；系统应通过低置信度门控额外产生 `review_required=true`，而不是强迫三分类结果成为确定事实。
- 帧号只能用于同一视频内排序。没有 FPS 和回合边界时，不能可靠换算时间戳或回合号。

## 4. 规则知识库预处理

### 4.1 按真实标题结构切分

当前规则库实际使用 `#`、`##`、`###` 三层标题。推荐：

- 文档根节点：`# AI 拳击评判员 RAG 知识库`；
- Parent：每个 `##` 章节；
- Child：每个 `###` 子章节；
- 对较长 Child 再按自然段、列表或表格行细分。

不要跨 `###` 边界做 overlap。表格应保留表头，并为每一行补上所在标题路径，避免检索到孤立的“10-8”或“TDEC”而失去条件。

### 4.2 Parent–Child 存储

Child 用于精确召回：

```json
{
  "chunk_id": "judge_rag_06_03_p01",
  "parent_id": "judge_rag_06",
  "heading_path": [
    "AI 拳击评判员 RAG 知识库",
    "6. 10-Point Must System",
    "6.3 10-8：压倒性优势或一次击倒后的规定情形"
  ],
  "text": "……",
  "rule_domains": ["round_scoring", "knockdown"],
  "authority_scope": "judge",
  "source_file": "知识库/Ring-Official-Guidelines-Boxing-Judge-RAG.md"
}
```

Parent 保存完整 `##` 章节，用于把定义、适用条件、例外和权限边界一起交给 Agent。若 Parent 过长，可保存 `##` 章节摘要索引，但最终证据必须回到原文 Child，不以自动摘要代替规则原文。

### 4.3 项目适用的 metadata

```json
{
  "chunk_id": "judge_rag_05_01_p01",
  "parent_id": "judge_rag_05",
  "document_title": "AI 拳击评判员 RAG 知识库",
  "organization": "WBC",
  "document_scope": "ring_official_guidelines_judge",
  "edition": null,
  "language": "zh-CN_with_en_terms",
  "heading_path": ["5. 回合胜负的评分标准", "5.1 第一评价层：有效进攻性"],
  "rule_domains": ["effective_aggressiveness", "round_scoring"],
  "decision_authority": ["judge"],
  "source_section_refs": ["BASIC FUNDAMENTALS FOR SCORING"],
  "ambiguity_links": ["16.5", "16.6"],
  "source_file": "知识库/Ring-Official-Guidelines-Boxing-Judge-RAG.md"
}
```

必须注意：

- `edition` 设为 `null/unknown`，不能填 2026；
- 当前只有一个组织和一份知识文件，组织/版本过滤不是第一版的核心召回手段；
- `decision_authority` 很重要，用于区分 Judge、Referee、Supervisor/Commissioner、Instant Replay Panel；
- 与规则库第 16 节相关的条款要建立 `ambiguity_links`；
- 保留原文已有的“来源章节”信息，但不要伪造新的原始页码或行号。

### 4.4 规则域路由

建议建立以下确定性路由：

| 任务 | 优先章节 | 必须联查 |
|---|---|---|
| 合法计分拳/计分区 | 4、5.1 | 3、13.5、16.5、16.8 |
| 回合胜负与 10 分制 | 5、6、7 | 8、13.5、14、15 |
| 击倒如何影响比分 | 6、8 | 3.2、14、16.4 |
| 犯规与扣分 | 3、9 | 10、11、15.3、16.2 |
| 伤情与终止结果 | 10 | 3、11、12.2、16.1—16.3 |
| Judge 权限边界 | 3 | 8.1、9、10、11.3、12 |
| 数据或规则无法支持的术语 | 2.14、16 | 对应主题章节 |

## 5. 从当前事件构造检索查询

### 5.1 先做确定性归一化

不需要用 LLM 改写简单枚举。建议保留：

```python
PUNCH_TYPE_TERMS = {
    "lead_straight": ["lead straight", "前手直拳"],
    "rear_straight": ["rear straight", "后手直拳"],
    "left_hook": ["left hook", "左勾拳"],
    "right_hook": ["right hook", "右勾拳"],
    "left_uppercut": ["left uppercut", "左上勾拳"],
    "right_uppercut": ["right uppercut", "右上勾拳"]
}

CONTACT_TERMS = {
    "landed": ["landed", "接触/命中"],
    "blocked": ["blocked", "被手臂或手套格挡"],
    "missed": ["missed", "未接触目标"]
}
```

拳型只描述动作形态。规则库的 Judge 评分重点是合法落点、力量、数量、准确性、干净程度和效果；不能给某种拳型预设更高分值。

### 5.2 查询必须中立

不推荐：

```text
红方左勾拳已形成有效得分，应如何计分？
```

推荐：

```text
Judge 判断一次预测为 landed 的出拳能否作为合法有效击打时，
需要哪些关于合法落点、干净程度、力量和权限边界的证据？
```

`pred_contact_outcome=landed` 只是一项模型预测，不等价于规则上的 `legal and scoring blow`；`blocked` 或 `missed` 也应保留置信度和人工复核出口。

### 5.3 当前数据可用的查询签名

规则不会随每一个 `event_id` 改变，建议缓存：

```python
query_signature = (
    "WBC",
    "edition_unknown",
    judgment_task,               # scoring_evidence / authority / round_scoring
    pred_contact_outcome,
    predicted_target_or_unknown
)
```

通常不把 `pred_punch_type` 放入评分规则缓存键，因为现有规则没有为直拳、勾拳、上勾拳设置不同分值。只有在解释动作或检索术语时才加入拳型。

### 5.4 事件与回合查询分层

事件级查询回答：

- 该预测是否具有成为有效击打证据的可能；
- 还缺少哪些信息；
- 应引用哪些规则；
- 是否需要人工复核。

回合级查询才回答：

- 双方整个回合的有效进攻性比较；
- 必要时的 Ring Generalship、Pure Aggressiveness；
- Referee 已正式认定的击倒和扣分如何记录；
- 基础比分是否可判定。

当前 CSV 没有回合边界，第一版必须将回合评分状态设为 `insufficient`，除非另有可靠的 bout/round manifest 输入。

## 6. 检索器设计

### 6.1 第一版优先级

当前只有约 16 个 Parent 章节，知识库规模很小。第一版推荐：

1. 规则域/标题路径确定性路由；
2. BM25 或全文关键词检索；
3. Dense 语义检索，解决中英文和自然语言改写；
4. 合并去重后重排序；
5. 按 `parent_id` 扩展，并追加 `ambiguity_links`。

不需要第一版直接做 GraphRAG。也不应为了形式固定使用 Dense Top-20 + BM25 Top-20：当 Child 总量较少时，Top-K 应按实际索引规模和验证集调优。

### 6.2 融合与重排序

Dense 与 BM25 分数尺度不同，可使用 RRF 按排名融合。重排序输入应包含：

```text
query + 完整标题路径 + child 正文 + authority_scope
```

重排后不是简单返回最高分的 3—6 个孤立块，而是先按规则域检查证据角色：

- definition：定义；
- condition：适用条件；
- exception：例外；
- authority：谁有权决定；
- procedure：记录或执行流程；
- ambiguity：来源歧义/待确认项。

缺少关键角色时，应继续扩展同 Parent 或返回证据不足。

### 6.3 上下文扩展规则

示例：检索到“6.3 10-8”时，应同时提供：

- 第 6 节的 10-Point Must 基础规则；
- 第 8 节击倒对比分的影响；
- 第 3.2 节关于 Referee 正式裁定的边界；
- 第 16.4 节“一次击倒不是无条件 10-8”。

检索到“有效进攻性 80%”时，应同时提供第 16.5、16.6 节，防止 Agent 把规则误写成固定的数值加权公式。

## 7. RAG 工具接口

建议将检索工具限定为规则证据服务：

```python
search_boxing_judge_rules(
    judgment_task,
    event_view=None,
    round_context=None,
    match_config=None
)
```

当前 `match_config` 建议形态：

```json
{
  "organization": "WBC",
  "rulebook_edition": null,
  "round_manifest_available": false,
  "fps": null,
  "official_rulings_available": false
}
```

返回结构：

```json
{
  "query_id": "query_001",
  "status": "ambiguous",
  "task": "scoring_evidence",
  "evidence": [
    {
      "chunk_id": "judge_rag_04_01_p01",
      "parent_id": "judge_rag_04",
      "heading_path": ["4. 有效击打与出拳质量", "4.1 有效击打的必要特征"],
      "content": "……",
      "decision_authority": ["judge"],
      "source_section_refs": ["Quality of Punches", "Scoring Zone"],
      "retrieval_score": 0.91
    }
  ],
  "event_assessment": {
    "predicted_contact_outcome": "landed",
    "prediction_confidence": 0.72,
    "is_official_scoring_blow": null
  },
  "missing_information": [
    "predicted or verified target zone",
    "clean contact evidence",
    "power/effect evidence"
  ],
  "review_required": true
}
```

`retrieval_score` 只表示检索相关性，不能作为规则结论或事件真实性的置信度。

## 8. Judge Agent 输出契约

### 8.1 事件级输出

```json
{
  "event_id": "...",
  "assessment_scope": "event",
  "prediction": {
    "punch_type": "left_hook",
    "punch_type_confidence": 0.91,
    "contact_outcome": "landed",
    "contact_outcome_confidence": 0.67
  },
  "scoring_evidence_status": "insufficient",
  "provisional_classification": "possible_scoring_blow",
  "official_ruling": null,
  "missing_information": ["target prediction", "clean/power/effect evidence"],
  "rule_citations": ["4.1", "4.3", "4.4", "5.1"],
  "review_required": true
}
```

禁止把 `possible_scoring_blow` 输出成“本回合得 1 分”。WBC 10-Point Must 是回合比较体系，不是每拳累加一分。

### 8.2 回合级输出

```json
{
  "assessment_scope": "round",
  "round": null,
  "status": "insufficient",
  "base_score": null,
  "point_deduction_marks": [],
  "official_rulings_used": [],
  "reason": "当前事件文件没有回合边界和 Referee 正式裁定。",
  "missing_information": ["round boundaries", "official knockdown/foul rulings"],
  "review_required": true
}
```

未来补齐数据后，Judge 仍只提交基础回合比分和 Referee 指示的扣分标记；实际减分由 Supervisor/Commissioner 执行。KO、TKO、DQ、abandonment 等终止结果不能被积分汇总覆盖。

## 9. 证据充分性与权限检查

`status` 统一使用：

```text
sufficient    规则证据、事件信息和权限来源均足够
ambiguous     找到相关规则，但规则自身有歧义或多个条件无法区分
insufficient  缺少必要事件字段、正式裁定或关键规则证据
```

以下情况必须返回 `ambiguous/insufficient`：

- 只有 `pred_contact_outcome=landed`，却没有合法目标、干净程度或效果证据；
- 试图从 `contact_frame=null` 推断是否命中；
- 试图用单个事件决定整个回合；
- 缺少 round manifest、FPS 或比赛时钟，却生成回合级统计；
- 没有 Referee/回放正式裁定，却认定击倒、犯规、扣分或伤因；
- 询问 RTD、No Contest 等本规则库未定义的结果；
- 涉及第 16 节列出的回合门槛、意外头撞、混合伤因、OCR 残缺等问题；
- 检索到处罚/比分结论，却没有同时检索定义、条件和权限边界；
- 模型置信度未校准或低于经验证的阈值。

## 10. 缓存与批处理

318 个事件不应触发 318 次相同规则检索。推荐流程：

```text
加载 CSV
  -> 构建 offline_eval_view / runtime_view
  -> 按 video_id 和 frame 排序
  -> 按 query_signature 去重
  -> 每个签名检索一次规则
  -> 规则证据映射回事件
  -> 有 round manifest 时再按回合聚合
```

缓存键必须包含知识库指纹（例如文件哈希或索引版本），避免规则文件更新后继续使用旧证据：

```python
cache_key = (
    knowledge_base_hash,
    organization,
    rulebook_edition,
    judgment_task,
    pred_contact_outcome,
    predicted_target_or_unknown
)
```

## 11. 建议的项目结构

```text
agent/
├── event_data/
│   ├── predictions.csv
│   └── README.txt
├── rag/
│   ├── 知识库/
│   │   ├── README.md
│   │   ├── Ring-Official-Guidelines-Boxing-Judge-RAG.md
│   │   └── Ring-Official-Guidelines-Ingles_no_images.md
│   └── rag结构设计参考.txt
└── boxing_rag/
    ├── ingestion/
    │   ├── markdown_parser.py
    │   ├── hierarchy_splitter.py
    │   ├── metadata_builder.py
    │   └── index_builder.py
    ├── events/
    │   ├── csv_loader.py
    │   ├── views.py
    │   ├── validator.py
    │   └── normalizer.py
    ├── retrieval/
    │   ├── rule_router.py
    │   ├── hybrid_retriever.py
    │   ├── reranker.py
    │   ├── parent_expander.py
    │   └── evidence_checker.py
    ├── scoring/
    │   ├── event_assessor.py
    │   ├── round_aggregator.py
    │   └── authority_guard.py
    ├── tools/
    │   └── search_boxing_judge_rules.py
    └── evaluation/
        ├── retrieval_cases.jsonl
        ├── leakage_tests.py
        ├── evaluate_predictions.py
        └── evaluate_retrieval.py
```

## 12. 评估方案

### 12.1 数据与模型预测评估

- 拳型：accuracy、macro-F1、每类 precision/recall、混淆矩阵；
- 接触结果：accuracy、macro-F1、landed/blocked/missed 的每类指标；
- `uncertain` GT 单独报告，不把模型不存在的 `uncertain` 类静默并入 missed；
- 置信度：可靠性图、ECE/Brier score，并据此制定复核阈值；
- 按 `video_id` 分组切分训练/验证/测试，避免同一视频相邻帧泄漏；
- 单独检查 `contact_frame` 缺失是否造成系统性偏差。

### 12.2 RAG 检索评估

人工建立小型 query—relevant chunk 数据集，至少覆盖：

- landed 不等于自动有效计分拳；
- blocked/missed 与有效进攻证据；
- 一次击倒不是无条件 10-8；
- Judge 与 Referee 权限边界；
- 基础比分与扣分分离；
- 意外/故意伤情和第 16 节歧义；
- RTD、No Contest 等知识库无答案问题；
- 中文问题与英文术语混用。

指标建议：Recall@K、MRR、Parent 命中率、authority 命中率、ambiguity-link 命中率和无答案拒答准确率。

### 12.3 端到端安全测试

必须包含：

- 标签泄漏测试：线上 DTO 不含任何 GT/标注结论；
- 权限测试：没有 Referee 裁定时不能输出正式 knockdown/foul/deduction；
- 粒度测试：事件级输出不能伪装成回合比分；
- 引用一致性：每个结论可回溯到 `chunk_id + heading_path + source_file`；
- 反事实测试：只改变模型预测时，不应读取 GT 来“纠正”线上结果；
- 缺失字段测试：`contact_frame`、target、round、FPS 缺失时能正确降级。

## 13. 当前 MVP

第一阶段应完成：

1. 将 CSV 明确拆成 `offline_eval_view` 与 `runtime_view`，先消除标签泄漏；
2. 按真实 Markdown 标题构建 Parent–Child 索引，并建立第 16 节歧义链接；
3. 实现标题/规则域路由 + BM25/Dense 混合召回 + 轻量重排序；
4. 实现 `search_boxing_judge_rules` 的结构化证据返回；
5. 实现事件级 `possible_scoring_blow / insufficient / review_required` 输出；
6. 在没有 round manifest 和正式 Referee rulings 时，明确拒绝生成正式回合比分；
7. 用当前 318 条数据评估两类预测，但不把预测准确率当作 Judge 判分准确率。

后续若要真正进行逐回合 Judge 判分，至少还需新增：

- 视频 FPS、比赛时钟和可靠的 round boundaries；
- 线上可用的目标区域预测及置信度；
- 干净程度、力量/效果等可验证特征；
- Referee/即时回放正式击倒、犯规、扣分、伤因及终止裁定；
- bout/match config（组织、明确规则版本、回合数及当地委员会适用项）。

在这些字段补齐之前，本系统的正确定位是“出拳预测 + WBC Judge 规则证据助手”，而不是自动正式裁判。
