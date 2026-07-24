from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


def _domains(path: list[str], text: str) -> list[str]:
    corpus = " ".join(path) + " " + text[:300]
    mapping = {
        "round_scoring": ["比分", "评分", "10-Point", "10-"],
        "knockdown": ["击倒", "Knockdown"],
        "foul_deduction": ["犯规", "扣分", "警告"],
        "scoring_blow": ["有效击打", "计分拳", "Scoring Blow", "进攻性"],
        "authority": ["权限", "职责", "Judge", "Referee", "裁定权"],
        "ambiguity": ["歧义", "待确认", "未定义", "OCR"],
    }
    return [domain for domain, words in mapping.items() if any(w in corpus for w in words)]


def _authority(path: list[str], text: str) -> list[str]:
    corpus = " ".join(path) + " " + text[:500]
    result = []
    for value, words in {
        "judge": ["Judge", "评判员"],
        "referee": ["Referee", "台上裁判"],
        "supervisor_commissioner": ["Supervisor", "Commissioner", "监督", "委员会"],
        "instant_replay_panel": ["回放小组", "Instant Replay"],
    }.items():
        if any(w in corpus for w in words):
            result.append(value)
    return result


def parse_knowledge_base(source_path: str | Path) -> dict[str, Any]:
    path = Path(source_path).resolve()
    raw = path.read_bytes()
    kb_hash = hashlib.sha256(raw).hexdigest()
    lines = raw.decode("utf-8").splitlines()
    title = path.stem
    parent_title: str | None = None
    child_title: str | None = None
    parent_index = child_index = 0
    buffer: list[str] = []
    chunks: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal buffer
        text = "\n".join(buffer).strip()
        if not text or not parent_title:
            buffer = []
            return
        path_parts = [title, parent_title] + ([child_title] if child_title else [])
        chunk_id = f"judge_rag_{parent_index:02d}_{child_index:02d}"
        chunks.append({
            "chunk_id": chunk_id,
            "parent_id": f"judge_rag_{parent_index:02d}",
            "heading_path": path_parts,
            "text": text,
            "rule_domains": _domains(path_parts, text),
            "decision_authority": _authority(path_parts, text),
            "source_file": str(path),
            "knowledge_base_hash": kb_hash,
        })
        buffer = []

    for line in lines:
        match = HEADING.match(line)
        if not match:
            buffer.append(line)
            continue
        level, heading = len(match.group(1)), match.group(2)
        if level == 1:
            title = heading
        elif level == 2:
            flush()
            parent_index += 1
            child_index = 0
            parent_title, child_title = heading, None
        elif level == 3:
            flush()
            child_index += 1
            child_title = heading
    flush()
    return {"knowledge_base_hash": kb_hash, "source_file": str(path), "chunks": chunks}


def rebuild_index(source_path: str | Path, output_path: str | Path, *, settings: Any | None = None) -> dict[str, Any]:
    index = parse_knowledge_base(source_path)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    # Import lazily to keep Markdown parsing usable without network credentials.
    from .retrieve import RuleRetriever

    retriever = RuleRetriever(source_path, destination, settings=settings)
    return {
        "knowledge_base_hash": index["knowledge_base_hash"],
        "chunk_count": len(index["chunks"]),
        "embedding": retriever.index["embedding"],
        "path": str(destination),
    }
