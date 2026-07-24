# 知识库文件说明

本目录存放拳击评判员 RAG 使用的 WBC 规则资料。

| 文件 | 角色 | 使用说明 |
|---|---|---|
| `Ring-Official-Guidelines-Boxing-Judge-RAG.md` | 整理后的知识库 | 面向 Judge 型 AI 的结构化规则版本；包含术语、判分边界、规则来源、歧义与待确认项，供 RAG 建索引和检索使用。 |
| `Ring-Official-Guidelines-Ingles_no_images.md` | 源文件 | 英文、无图片的原始 WBC Ring Officials Guidelines 文本，作为整理版的核验依据；不应被整理版覆盖或改写。 |

维护原则：先以源文件核验规则内容，再更新整理后的知识库；如源文件存在 OCR、断句或规则歧义，应在整理版中明确标注，不得自行补全规则。
