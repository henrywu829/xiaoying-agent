"""检索：自写 bigram 分词 + rank_bm25.BM25Okapi 打分 + 命中词数阈值。

命中阈值只看"命中了几个不同的查询词项"，不看 BM25 分数，
因此不受 rank-bm25 小语料 IDF 下限的影响，资料外问题能得到干净的空结果。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

# 疑问/泛化 bigram，命中它们不算"相关内容"
STOP_BIGRAMS = {"什么", "怎么", "多少", "多久", "如何", "可以", "是否", "请问"}

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """中文段取相邻两字 bigram；连续 ASCII 字母数字整体保留并转大写。"""
    terms: list[str] = []
    for seg in _TOKEN_RE.findall(text):
        if seg.isascii():
            terms.append(seg.upper())
        elif len(seg) == 1:
            terms.append(seg)
        else:
            terms.extend(seg[i : i + 2] for i in range(len(seg) - 1))
    return [t for t in terms if t not in STOP_BIGRAMS]


@dataclass
class Hit:
    doc_id: str
    para_id: str
    title: str
    version_date: str
    score: float
    matched_terms: list[str]
    preview: str = ""
    index: int = -1  # 段落在语料中的下标，内部使用


@dataclass
class BM25Index:
    """索引单位=段落；每段词项前拼上文档标题的词项。"""

    paragraphs: list = field(default_factory=list)  # list[(para_ref, doc)]，见 kb.py
    _corpus: list[list[str]] = field(default_factory=list)
    _para_term_sets: list[set] = field(default_factory=list)
    _bm25: BM25Okapi | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._corpus = []
        self._para_term_sets = []
        for para, doc in self.paragraphs:
            terms = tokenize(doc.title) + tokenize(para.text)
            self._corpus.append(terms)
            self._para_term_sets.append(set(terms))
        self._bm25 = BM25Okapi(self._corpus) if self._corpus else None

    def search(self, query: str, top_k: int = 4) -> list[Hit]:
        if self._bm25 is None:
            return []
        q_terms = tokenize(query)
        if not q_terms:
            return []
        q_set = set(q_terms)
        need = 1 if len(q_set) <= 2 else 2  # 至少命中 2 个不同词项；查询词项少时放宽到 1
        scores = self._bm25.get_scores(q_terms)
        hits: list[Hit] = []
        for i, (para, doc) in enumerate(self.paragraphs):
            matched = q_set & self._para_term_sets[i]
            if len(matched) < need:
                continue
            hits.append(
                Hit(
                    doc_id=doc.doc_id,
                    para_id=para.para_id,
                    title=doc.title,
                    version_date=doc.version_date,
                    score=round(float(scores[i]), 4),
                    matched_terms=sorted(matched, key=q_terms.index),
                    preview=para.text[:40],
                    index=i,
                )
            )
        hits.sort(key=lambda h: (-h.score, h.para_id))
        return hits[:top_k]
