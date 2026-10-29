"""真实模型评测：跑 data/eval_cases.json，产出 examples/。

用法：
  python scripts/run_eval.py --out examples            # 真实模型（读 .env 的 LLM_API_KEY）
  python scripts/run_eval.py --mock --out examples/mock
  python scripts/run_eval.py --out examples --perturb  # 追加"改文档复测"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from kbqa.api import app  # noqa: E402
from kbqa.config import load_settings  # noqa: E402
from kbqa.guard import extract_numbers  # noqa: E402
from kbqa.kb import load_kb  # noqa: E402
from kbqa.llm import make_provider  # noqa: E402
from kbqa.schemas import AskRequest  # noqa: E402
from kbqa.agent import run_to_result  # noqa: E402


def check(case: dict, result: dict) -> list[str]:
    """返回失败信息列表（空=通过）。全部为硬性断言。"""
    exp = case.get("expect") or {}
    fails: list[str] = []
    if exp.get("status") and result.get("status") not in exp["status"]:
        fails.append(f"status={result.get('status')}，期望 {exp['status']}")
    cited_docs = {c.get("doc_id") for c in result.get("citations") or []}
    for d in exp.get("must_cite_docs") or []:
        if d not in cited_docs:
            fails.append(f"未引用 {d}")
    for d in exp.get("must_not_cite_docs") or []:
        if d in cited_docs:
            fails.append(f"不应引用 {d}")
    answer = result.get("answer") or ""
    if exp.get("answer_contains_any") and not any(s in answer for s in exp["answer_contains_any"]):
        fails.append(f"回答不含 {exp['answer_contains_any']} 中任何一项")
    for s in exp.get("answer_not_contains") or []:
        if s in answer:
            fails.append(f"回答不应包含 {s!r}")
    if exp.get("max_citations") is not None and len(result.get("citations") or []) > exp["max_citations"]:
        fails.append(f"引用数 {len(result['citations'])} 超过上限 {exp['max_citations']}")
    if exp.get("conflict_resolution"):
        if not any(c.get("resolution") == exp["conflict_resolution"] for c in result.get("conflicts") or []):
            fails.append(f"无 resolution={exp['conflict_resolution']} 的冲突")
    if exp.get("min_clarify_options"):
        n = len(result.get("clarify_options") or [])
        if n < exp["min_clarify_options"]:
            fails.append(f"clarify_options 只有 {n} 个，期望 ≥{exp['min_clarify_options']}")
    return fails


def _search_metrics(result: dict, expect: dict) -> dict:
    """改写效果量化（只观察记录，不参与判定）。"""
    want = set(expect.get("must_cite_docs") or [])
    searches = []
    for ev in result.get("trace") or []:
        if ev.get("action") != "search_docs" or not ev.get("ok"):
            continue
        try:
            obs = json.loads(ev.get("observation") or "{}")
        except json.JSONDecodeError:
            continue
        searches.append(obs)
    def hit_docs(obs):
        return {h.get("doc_id") for h in obs.get("hits") or []} & want
    queries = [o.get("query") for o in searches]
    return {
        "n_searches": len(searches),
        "first_hit": bool(searches and hit_docs(searches[0])),
        "final_hit": bool(want) and any(hit_docs(o) for o in searches),
        "rewrites": max(0, len(set(queries)) - 1),
        "queries": queries,
    }


def _num_token(n: str) -> str:
    """把 guard 归一化后的数字还原为正则可用的文本形式。"""
    return n


def run_perturb(case: dict, first: dict, out_dir: Path, mock: bool) -> dict | None:
    """自动改文档复测：把引用段落中出现在答案里的数字 n 改成 n+7 后重跑。"""
    if first.get("status") != "answered":
        return None
    question = first.get("question") or ""
    target = None
    for c in first.get("citations") or []:
        c_nums = extract_numbers(c.get("quote", ""))
        for n in sorted(extract_numbers(first.get("answer", "")) & c_nums):
            if n not in extract_numbers(question):
                target = (c["para_id"], n)
                break
        if target:
            break
    if not target:
        return {"skipped": "答案无可用数字"}

    para_id, n = target
    req = AskRequest(**{**case["request"], "max_steps": case["request"].get("max_steps")})
    kb = load_kb(req.kb)
    para = kb.get_para(para_id)
    m = n
    while True:
        m = str(int(float(m)) + 7)
        if m not in para.text:
            break
    new_text, cnt = re.subn(rf"(?<![\d.]){re.escape(n)}(?![\d.])", m, para.text, count=1)
    if cnt == 0:
        return {"skipped": f"段落中无法定位数字 {n}"}
    kb2 = kb.with_text(para_id, new_text)

    provider = make_provider(load_settings(), force_mock=mock)
    result2 = run_to_result(req, provider, kb2)

    new_nums = extract_numbers(result2.get("answer", ""))
    still_in = n in extract_numbers(question)
    ok = (
        result2.get("status") == "answered"
        and m in new_nums
        and (still_in or n not in new_nums)
        and any(c.get("para_id") == para_id for c in result2.get("citations") or [])
    )
    rec = {
        "case_id": case["id"], "para_id": para_id, "old": n, "new": m,
        "old_text": para.text, "new_text": new_text,
        "answer_before": (first.get("answer") or "")[:120],
        "answer_after": (result2.get("answer") or "")[:120],
        "passed": ok,
    }
    d = out_dir / case["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "diff.json").write_text(json.dumps(
        {"para_id": para_id, "old": n, "new": m, "old_text": para.text, "new_text": new_text},
        ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "output.json").write_text(json.dumps(result2, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "trace.jsonl").write_text(
        "".join(json.dumps(ev, ensure_ascii=False) + "\n" for ev in result2.get("trace") or []),
        encoding="utf-8")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="examples")
    ap.add_argument("--perturb", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    cases_dir, perturb_dir = out / "cases", out / "perturb"
    cases = json.loads((ROOT / "data" / "eval_cases.json").read_text(encoding="utf-8"))
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    if only:
        cases = [c for c in cases if c["id"] in only or c["id"].split("_")[0] in only]

    client = TestClient(app)
    results: list[tuple[dict, dict, list[str], dict]] = []
    for case in cases:
        body = dict(case["request"])
        body.setdefault("kb", "default")
        if args.mock:
            body["mock"] = True
        resp = client.post("/api/ask", json=body)
        if resp.status_code != 200:
            result = {"status": "failed", "answer": f"HTTP {resp.status_code}: {resp.text[:200]}",
                      "trace": [], "citations": []}
        else:
            result = resp.json()
        fails = check(case, result)
        metrics = _search_metrics(result, case.get("expect") or {})
        results.append((case, result, fails, metrics))

        d = cases_dir / case["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "input.json").write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "output.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "trace.jsonl").write_text(
            "".join(json.dumps(ev, ensure_ascii=False) + "\n" for ev in result.get("trace") or []),
            encoding="utf-8")
        mark = "✓" if not fails else "✗ " + "；".join(fails)
        print(f"{case['id']:<24} {result.get('status'):<18} steps={result.get('steps_used', '-')} {mark}")

    perturb_rows: list[dict] = []
    if args.perturb:
        print("\n--perturb 改文档复测 --")
        for case, result, _fails, _m in results:
            rec = run_perturb(case, result, perturb_dir, args.mock)
            if rec:
                perturb_rows.append(rec)
                if rec.get("skipped"):
                    print(f"{case['id']:<24} 跳过：{rec['skipped']}")
                else:
                    print(f"{case['id']:<24} {rec['para_id']} {rec['old']}→{rec['new']} "
                          f"{'✓ 答案跟随' if rec['passed'] else '✗ 未跟随'}")

    # eval_report.md
    n_fail = sum(1 for _c, _r, f, _m in results if f)
    lines = ["# 评测报告", "",
             f"- 用例数：{len(results)}；通过 {len(results) - n_fail}，失败 {n_fail}",
             f"- 模式：{'Mock（不证明决策能力）' if args.mock else '真实模型'}", "",
             "## 用例结果", "",
             "| 用例 | 状态 | 步数 | 引用文档 | 改写次数 | 结果 |",
             "|---|---|---|---|---|---|"]
    for case, result, fails, m in results:
        docs = "、".join(sorted({c.get('doc_id') for c in result.get('citations') or []})) or "—"
        mark = "✓" if not fails else "✗ " + "；".join(fails)
        lines.append(f"| {case['id']} | {result.get('status')} | {result.get('steps_used')} | "
                     f"{docs} | {m['rewrites']} | {mark} |")
    lines += ["", "## 检索改写效果（只观察，不判定）", "",
              "| 用例 | 检索次数 | 首次命中 | 最终命中 | 改写次数 | 查询序列 |",
              "|---|---|---|---|---|---|"]
    rescued = []
    for case, _r, _f, m in results:
        if m["n_searches"] == 0:
            continue
        if m["rewrites"] > 0 and m["final_hit"] and not m["first_hit"]:
            rescued.append(case["id"])
        lines.append(f"| {case['id']} | {m['n_searches']} | {'是' if m['first_hit'] else '否'} | "
                     f"{'是' if m['final_hit'] else '否'} | {m['rewrites']} | {' → '.join(m['queries'])} |")
    lines.append(f"\n改写挽回的用例（首次未命中、最终命中）：{('、'.join(rescued)) or '无'}")
    if perturb_rows:
        lines += ["", "## 改文档复测（--perturb）", "",
                  "| 用例 | 段落 | 数字改动 | 新答案摘要 | 结果 |", "|---|---|---|---|---|"]
        for rec in perturb_rows:
            if rec.get("skipped"):
                lines.append(f"| {rec.get('case_id', '—')} | — | — | — | 跳过：{rec['skipped']} |")
            else:
                lines.append(f"| {rec['case_id']} | {rec['para_id']} | {rec['old']} → {rec['new']} | "
                             f"{rec['answer_after'][:40]} | {'✓ 通过' if rec['passed'] else '✗ 未通过'} |")
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告写入 {out / 'eval_report.md'}；失败用例 {n_fail}")
    return n_fail + sum(1 for r in perturb_rows if not r.get("skipped") and not r.get("passed"))


if __name__ == "__main__":
    sys.exit(min(main(), 99))
