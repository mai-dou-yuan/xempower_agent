# 拳击评判员 Agent 开发环境 Requirements（Conda）

本文用于搭建 `拳击评判员 Agent` 的本地开发环境。用户自行执行安装命令；本文不保存任何真实 API Key。

## 1. 基础要求

- 操作系统：Windows 10/11、Linux 或 macOS
- Conda：Miniconda、Anaconda 或 Miniforge
- Python：3.11，64 位
- Git：建议 2.40+
- 内存：最低 8 GB，建议 16 GB+
- 磁盘：建议预留 8 GB；首次构建向量索引会下载嵌入模型
- GPU：MVP 不强制，默认使用 CPU

推荐环境名：`boxing-judge-agent`

## 2. 创建 Conda 环境

在项目根目录 `D:\xempower_agent` 执行：

```powershell
conda create -n boxing-judge-agent python=3.11 pip -y
conda activate boxing-judge-agent
python -m pip install --upgrade pip setuptools wheel
```

确认当前解释器来自新环境：

```powershell
python --version
where.exe python
```

Linux/macOS 使用：

```bash
which python
```

## 3. 项目依赖

在已激活的 Conda 环境中安装：

```powershell
python -m pip install `
  "fastapi>=0.115,<1" `
  "uvicorn[standard]>=0.34,<1" `
  "pydantic>=2.10,<3" `
  "pydantic-settings>=2.7,<3" `
  "python-multipart>=0.0.20,<1" `
  "pandas>=2.2,<4" `
  "numpy>=1.26,<3" `
  "openai>=1.70,<3" `
  "python-dotenv>=1.0,<2" `
  "httpx>=0.28,<1" `
  "tenacity>=9,<10" `
  "rank-bm25>=0.2.2,<1" `
  "jieba>=0.42.1,<1" `
  "sentence-transformers>=4,<6" `
  "faiss-cpu>=1.10,<2" `
  "orjson>=3.10,<4" `
  "PyYAML>=6.0,<7" `
  "pytest>=8,<10" `
  "pytest-asyncio>=0.25,<2" `
  "pytest-cov>=6,<8"
```

Linux/macOS 将命令改为：

```bash
python -m pip install \
  "fastapi>=0.115,<1" \
  "uvicorn[standard]>=0.34,<1" \
  "pydantic>=2.10,<3" \
  "pydantic-settings>=2.7,<3" \
  "python-multipart>=0.0.20,<1" \
  "pandas>=2.2,<4" \
  "numpy>=1.26,<3" \
  "openai>=1.70,<3" \
  "python-dotenv>=1.0,<2" \
  "httpx>=0.28,<1" \
  "tenacity>=9,<10" \
  "rank-bm25>=0.2.2,<1" \
  "jieba>=0.42.1,<1" \
  "sentence-transformers>=4,<6" \
  "faiss-cpu>=1.10,<2" \
  "orjson>=3.10,<4" \
  "PyYAML>=6.0,<7" \
  "pytest>=8,<10" \
  "pytest-asyncio>=0.25,<2" \
  "pytest-cov>=6,<8"
```

依赖用途：

| 分类 | 依赖 | 用途 |
|---|---|---|
| API | FastAPI、Uvicorn、python-multipart | HTTP 服务与 CSV 上传 |
| 配置与模型 | Pydantic、pydantic-settings、python-dotenv | 数据契约和环境变量 |
| 数据处理 | pandas、NumPy | CSV 校验、统计和确定性计算 |
| DeepSeek | openai、httpx、tenacity | OpenAI 兼容调用、超时和重试 |
| RAG | rank-bm25、jieba、sentence-transformers、FAISS | 中文关键词与向量混合检索 |
| 输出 | orjson、PyYAML | JSON 序列化和配置文件 |
| 测试 | pytest、pytest-asyncio、pytest-cov | 单元、异步和覆盖率测试 |

## 4. DeepSeek 配置

在 `agent/.env` 中配置，禁止提交该文件：

```env
DEEPSEEK_API_KEY=""
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

同时确保 `.gitignore` 至少包含：

```gitignore
.env
agent/.env
agent/artifacts/
__pycache__/
.pytest_cache/
.coverage
htmlcov/
```

不要在源码、Markdown、测试、终端截图或日志中写入真实密钥。

## 5. 嵌入模型

建议默认使用适合中文检索的小型模型，并通过环境变量配置：

```env
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DEVICE=cpu
```

首次重建 RAG 索引时会从模型仓库下载文件。若运行环境不能联网，应提前下载模型，并将 `EMBEDDING_MODEL` 改为本地目录的绝对路径。

## 6. 安装后验证

只验证依赖，不调用 DeepSeek、不消耗 API 配额：

```powershell
python -c "import fastapi, pydantic, pandas, openai, sentence_transformers, faiss; print('environment ok')"
python -m pip check
```

项目代码完成后执行：

```powershell
python -m pytest agent/tests -q
python -m boxing_judge_agent.cli rebuild-index
python -m boxing_judge_agent.cli analyze --csv agent/event_data/predictions.csv
python -m boxing_judge_agent.cli serve
```

最后一个命令启动服务后，访问：

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/health
```

只有显式运行项目提供的 DeepSeek smoke test 时才应产生 API 请求。

## 7. 常见安装问题

### 7.1 `faiss-cpu` 安装失败

先确认使用 64 位 Python 3.11。若 pip 安装失败，可在 Conda 环境中改用：

```powershell
conda install -c conda-forge faiss-cpu
```

然后重新执行：

```powershell
python -m pip check
```

### 7.2 PyTorch 或嵌入模型安装过慢

`sentence-transformers` 会安装 PyTorch。CPU 开发环境无需安装 CUDA 版本；如需 GPU，请按 PyTorch 官方安装器生成与本机 CUDA 匹配的命令，不要在本项目中写死 CUDA 版本。

### 7.3 Conda 环境未生效

执行：

```powershell
conda init powershell
```

关闭并重新打开 PowerShell，再执行：

```powershell
conda activate boxing-judge-agent
```

### 7.4 依赖版本冲突

先运行 `python -m pip check`。不要在 `base` 环境中修补依赖；删除并重新创建 `boxing-judge-agent` 环境通常更可靠。

## 8. 环境导出

开发环境验证通过后，可导出仅包含手动安装项的环境记录：

```powershell
conda env export --from-history > agent/environment.history.yml
python -m pip freeze > agent/requirements.lock.txt
```

`requirements.lock.txt` 用于复现已验证环境，不应替代本文中的跨平台兼容版本范围。
