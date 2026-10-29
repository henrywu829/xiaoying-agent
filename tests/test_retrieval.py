from kbqa.retrieval import tokenize


def test_tokenize_bigram_and_stopwords():
    terms = tokenize("工卡丢了怎么补办？")
    assert "工卡" in terms
    assert "补办" in terms
    assert "怎么" not in terms  # 停用 bigram
    assert "？" not in terms    # 无标点


def test_tokenize_ascii_preserved():
    terms = tokenize("导出4K视频")
    assert "4K" in terms


def test_conflict_docs_both_recalled(kb_default):
    hits = kb_default.index.search("报销期限是多久？", top_k=4)
    ids = {h.para_id for h in hits}
    assert "D01#p2" in ids and "D02#p1" in ids


def test_matched_terms_reported(kb_default):
    hits = kb_default.index.search("报销期限是多久？", top_k=4)
    d01 = next(h for h in hits if h.para_id == "D01#p2")
    q_terms = set(tokenize("报销期限是多久？"))
    assert {"报销", "期限"} <= set(d01.matched_terms)
    assert set(d01.matched_terms) <= q_terms


def test_no_supersede_recall(kb_no_supersede):
    hits = kb_no_supersede.index.search("每周可以远程办公几天？", top_k=4)
    ids = {h.para_id for h in hits}
    assert "D04#p1" in ids and "D05#p1" in ids


def test_out_of_scope_empty(kb_default):
    assert kb_default.index.search("公司明年的股价目标是多少", top_k=4) == []


def test_colloquial_query_weak(kb_default):
    hits = kb_default.index.search("进公司刷的那张卡找不着了，咋整？", top_k=4)
    d06_hits = [h for h in hits if h.doc_id == "D06"]
    # 词法检索的局限：口语表达要么没有命中，要么 D06 不是第一
    assert not d06_hits or hits[0].doc_id != "D06"
