# 拳击评判员 Agent

这是一个基于赛事 CSV、拳击评判规则知识库、Qwen Embedding 和 DeepSeek 的非官方比分评估 Agent。

它会先对完整 CSV 做确定性批量分析，再根据用户确认的回合映射和补充信息检索规则、调用大模型进行定性判断，并由程序生成可追溯的条件性报告。所有输出均标记为 `score_kind=estimated_opinion`、`official=false`，不代表官方赛果或正式记分卡。

## 快速运行

以下命令均在工作区根目录 `D:\xempower_agent` 中执行。

### 1. 激活环境并安装项目

首次运行或依赖发生变化时执行：

```powershell
conda activate boxing-judge-agent
python -m pip install -e .\agent --no-build-isolation
```

项目安装完成后，后续只需激活环境：

```powershell
conda activate boxing-judge-agent
```

### 2. 重建 RAG 规则索引

首次运行、知识库发生变化或更换 Embedding 模型后执行：

```powershell
python -m boxing_judge_agent.cli rebuild-index
```

索引会写入 `agent/artifacts/indexes/rules.json`。该步骤调用 `qwen3.7-text-embedding`，因此需要在 `agent/.env` 中配置有效的 `DASHSCOPE_API_KEY`。

### 3. 启动 HTTP 服务

```powershell
python -m boxing_judge_agent.cli serve
```

默认监听地址：

- 网页工作台：http://127.0.0.1:8000/
- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

自定义监听地址和端口：

```powershell
python -m boxing_judge_agent.cli serve --host 0.0.0.0 --port 8080
```

也可以使用安装后生成的命令：

```powershell
boxing-judge-agent serve
```

网页工作台支持拖拽上传 CSV、补充或跳过比赛信息、确认最小回合映射假设、查看逐回合判断和完整分析报告。浏览器会保存最近一次会话 ID，可在刷新页面后恢复分析。前端资源由 FastAPI 本地提供，不依赖外部 CDN。

“分析问题”会作为独立查询交给 `qwen3.7-text-embedding` 检索相关规则，并作为受约束的分析目标传给 DeepSeek。CSV 自动生成的基础规则查询仍会始终执行；用户问题只能调整分析重点，不能覆盖证据标准、跳过确认流程或改变非官方报告边界。分析问题最长 2000 个字符。

生成报告时，网页会实时展示结构化执行轨迹，包括 Qwen 向量检索、本地余弦排序、DeepSeek 逐回合判断、确定性计分、证据审计和报告生成。轨迹只包含工具、状态与结果摘要，不展示模型隐藏推理。后端进度可通过 `GET /sessions/{session_id}/progress` 查询，并持久化在会话的 `progress_events` 字段中。

### 4. 使用 CLI 分析 CSV

安全的默认模式不会猜测多个视频与回合的对应关系，也不会强行生成唯一比分：

```powershell
python -m boxing_judge_agent.cli analyze --csv .\agent\event_data\predictions.csv
```

将报告输出为 JSON：

```powershell
python -m boxing_judge_agent.cli analyze `
  --csv .\agent\event_data\predictions.csv `
  --json
```

仅当确认“按视频顺序将每个视频视为一个回合”时使用：

```powershell
python -m boxing_judge_agent.cli analyze `
  --csv .\agent\event_data\predictions.csv `
  --assume-videos-as-rounds
```

该模式会执行规则检索并调用 DeepSeek。若模型调用失败，系统会保留 `LLM_UNAVAILABLE` 可恢复状态，同时保留已完成的确定性数据分析。

查看全部 CLI 参数：

```powershell
python -m boxing_judge_agent.cli --help
python -m boxing_judge_agent.cli analyze --help
python -m boxing_judge_agent.cli serve --help
```

## 在 agent 目录中运行

如果当前目录已经是 `D:\xempower_agent\agent`，CSV 路径不需要再带 `agent` 前缀：

```powershell
conda activate boxing-judge-agent
python -m boxing_judge_agent.cli analyze --csv .\event_data\predictions.csv
python -m boxing_judge_agent.cli serve
```

## 配置

运行时配置位于 `agent/.env`。该文件已被 `.gitignore` 排除，不应提交到版本库，也不要把真实 API Key 写入 README、源码或 `.env.example`。

配置模板如下：

```env
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro

DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_EMBEDDING_MODEL=qwen3.7-text-embedding
DASHSCOPE_EMBEDDING_DIMENSIONS=1024

DASHSCOPE_TIMEOUT_SECONDS=60
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=1
BOXING_ARTIFACT_DIR=artifacts
BOXING_KNOWLEDGE_BASE=rag/knowledge_base/Ring-Official-Guidelines-Boxing-Judge-RAG.md
```

如果尚未创建 `.env`，可先复制模板再填写 Key：

```powershell
Copy-Item .\agent\.env.example .\agent\.env
```

当前项目的 `.env` 已配置时，不要再次执行上面的复制命令，以免覆盖已有配置。

修改 `.env` 后，需要重启正在运行的 HTTP 服务，新进程才会加载新配置。

## HTTP API 流程

服务启动后可以在网页工作台 `http://127.0.0.1:8000/` 中完成整个流程，也可以在 Swagger 页面 `http://127.0.0.1:8000/docs` 中直接调试接口。主要接口如下：

1. `POST /sessions`：以 multipart/form-data 上传 `csv`，可附带 `question`。
2. `POST /sessions/{session_id}/confirm`：选择 `add_supplement` 或 `skip_supplement`。
3. `POST /sessions/{session_id}/messages`：补充回合映射、击打质量、击倒和扣分信息。
4. `POST /sessions/{session_id}/confirm`：发送 `confirm_supplements`，确认补充信息。
5. 跳过补充时，确认或拒绝系统提出的最小映射假设。
6. `GET /sessions/{session_id}/report?format=json`：获取 JSON 报告。
7. `GET /sessions/{session_id}/report?format=markdown`：获取 Markdown 报告。

其他接口包括：

- `GET /health`：健康检查。
- `GET /sessions/{session_id}`：恢复会话。
- `GET /sessions/{session_id}/progress`：查询工具调用与执行进度。
- `GET /sessions/{session_id}/events/{event_id}`：按事件下钻。
- `POST /rag/rebuild`：通过 HTTP 重建规则索引。

错误响应使用稳定结构：

```json
{
  "error": {
    "code": "duplicate_event_id",
    "message": "..."
  }
}
```

## 测试

在工作区根目录运行全部测试：

```powershell
conda activate boxing-judge-agent
python -m pytest .\agent\tests -q
```

默认测试不会消耗 DeepSeek API 配额。显式运行 DeepSeek smoke test：

```powershell
$env:RUN_DEEPSEEK_SMOKE="1"
python -m pytest .\agent\tests\test_llm_smoke.py -q
Remove-Item Env:RUN_DEEPSEEK_SMOKE
```

## 代理下载（可选）

仅在安装依赖或访问模型服务较慢时，可在当前 PowerShell 临时设置代理：

```powershell
$env:http_proxy="http://127.0.0.1:10808"
$env:https_proxy="http://127.0.0.1:10808"
$env:all_proxy="socks5://127.0.0.1:10808"
```

这些变量只对当前 PowerShell 会话生效。

## 设计边界

- Agent 运行时不会读取 `punch_type`、`target`、`contact_outcome`、`score_result`、`no_score_reason`、`foul_action`、`notes` 等标注列。
- `pred_contact_outcome=landed` 只表示“预测命中”，不等同于有效拳或得分拳。
- 出拳数量不会被机械累加为比分；DeepSeek 只输出逐回合定性比较，基础分、扣分和总分由代码计算。
- 未确认的补充信息和假设不能进入判分；未知击倒或扣分保持 `null`，不会默认成零。
- 没有回合映射时，不会从多个 `video_id` 猜测回合；没有 FPS 时，不会伪造比赛时间。
- RAG 没有证据或规则存在歧义时会降级处理，不会用模型常识补写规则。
