"""知识库：Markdown + 简单 front matter 加载、变体组合、mtime 热加载、扰动接口。"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .config import KB_ROOT
from .retrieval import BM25Index

META_KEYS = {"doc_id", "title", "version_date", "scope", "supersedes", "category"}


@dataclass
class Paragraph:
    para_id: str
    text: str


@dataclass
class Document:
    doc_id: str
    title: str
    version_date: str
    scope: str
    supersedes: str
    category: str
    paragraphs: list[Paragraph]


@dataclass
class KnowledgeBase:
    docs: dict[str, Document]
    index: BM25Index

    def get_doc(self, doc_id: str) -> Document | None:
        return self.docs.get(doc_id)

    def get_para(self, para_id: str) -> Paragraph | None:
        doc_id = para_id.split("#", 1)[0]
        doc = self.docs.get(doc_id)
        if doc is None:
            return None
        for p in doc.paragraphs:
            if p.para_id == para_id:
                return p
        return None

    def with_text(self, para_id: str, new_text: str) -> "KnowledgeBase":
        """返回替换了指定段落并重建索引的新实例（供 --perturb 使用），原实例不变。"""
        target = self.get_para(para_id)
        if target is None:
            raise KeyError(para_id)
        doc_id = para_id.split("#", 1)[0]
        new_docs: dict[str, Document] = {}
        for did, doc in self.docs.items():
            if did != doc_id:
                new_docs[did] = doc
                continue
            new_paras = [
                Paragraph(p.para_id, new_text if p.para_id == para_id else p.text)
                for p in doc.paragraphs
            ]
            new_docs[did] = Document(
                doc_id=doc.doc_id, title=doc.title, version_date=doc.version_date,
                scope=doc.scope, supersedes=doc.supersedes, category=doc.category,
                paragraphs=new_paras,
            )
        return _build_kb(new_docs.values())


def parse_doc(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    meta: dict[str, str] = {}
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
            if ":" in lines[i]:
                k, _, v = lines[i].partition(":")
                k = k.strip()
                if k in META_KEYS:
                    meta[k] = v.strip()
    body = "\n".join(lines[body_start:])
    doc_id = meta.get("doc_id", path.stem)
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    return Document(
        doc_id=doc_id,
        title=meta.get("title", doc_id),
        version_date=meta.get("version_date", ""),
        scope=meta.get("scope", ""),
        supersedes=meta.get("supersedes", ""),
        category=meta.get("category", ""),
        paragraphs=[Paragraph(f"{doc_id}#p{i}", text) for i, text in enumerate(paras, 1)],
    )


def _build_kb(docs) -> KnowledgeBase:
    doc_map = {d.doc_id: d for d in docs}
    pairs = [(p, d) for d in doc_map.values() for p in d.paragraphs]
    return KnowledgeBase(docs=doc_map, index=BM25Index(pairs))


def list_variants(kb_root: Path = KB_ROOT) -> dict:
    path = kb_root / "variants.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _kb_files(kb_root: Path, variant: str) -> list[Path]:
    spec = list_variants(kb_root)[variant]  # KeyError 自然防路径穿越
    files = sorted((kb_root / "docs").glob("*.md"))
    files += [kb_root / "extra" / f for f in spec.get("extra", [])]
    return files


def _load_docs(kb_root: Path, variant: str) -> dict[str, Document]:
    spec = list_variants(kb_root)[variant]
    exclude = set(spec.get("exclude", []))
    docs: dict[str, Document] = {}
    for f in sorted((kb_root / "docs").glob("*.md")):
        d = parse_doc(f)
        if d.doc_id not in exclude:
            docs[d.doc_id] = d
    for fname in spec.get("extra", []):
        d = parse_doc(kb_root / "extra" / fname)  # 同 doc_id 覆盖基础文档
        docs[d.doc_id] = d
    return docs


_cache: dict[str, tuple[float, KnowledgeBase]] = {}
_lock = threading.Lock()


def load_kb(variant: str = "default", kb_root: Path = KB_ROOT) -> KnowledgeBase:
    """按变体缓存；缓存键为相关文件的最大 mtime，评审者改 md 后不用重启。"""
    files = _kb_files(kb_root, variant)
    mtime = max((os.path.getmtime(f) for f in files), default=0.0)
    with _lock:
        hit = _cache.get(variant)
        if hit and hit[0] == mtime:
            return hit[1]
        kb = _build_kb(_load_docs(kb_root, variant).values())
        _cache[variant] = (mtime, kb)
        return kb


def reset_cache() -> None:
    with _lock:
        _cache.clear()
