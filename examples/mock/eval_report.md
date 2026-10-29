# 评测报告

- 用例数：14；通过 8，失败 6
- 模式：Mock（不证明决策能力）

## 用例结果

| 用例 | 状态 | 步数 | 引用文档 | 改写次数 | 结果 |
|---|---|---|---|---|---|
| C01_direct | answered | 3 | D06 | 0 | ✓ |
| C02_paraphrase | no_evidence | 3 | — | 1 | ✗ status=no_evidence，期望 ['answered']；未引用 D06；回答不含 ['OA', '20', '工卡', '补办'] 中任何一项 |
| C03_conflict | answered | 3 | D02 | 0 | ✗ status=answered，期望 ['conflict']；未引用 D01；clarify_options 只有 0 个，期望 ≥2 |
| C04_conflict_removed | answered | 3 | D01 | 0 | ✓ |
| C05_conflict_scoped | answered | 3 | D01 | 0 | ✗ 未引用 D02；回答不含 ['15'] 中任何一项 |
| C06_superseded | answered | 3 | D04 | 0 | ✗ 未引用 D05；回答不含 ['2'] 中任何一项；无 resolution=resolved_by_doc 的冲突 |
| C07_out_of_scope | no_evidence | 3 | — | 1 | ✓ |
| C08_followup | answered | 3 | D03 | 0 | ✓ |
| C09_tool_fail_once | answered | 4 | D06 | 0 | ✓ |
| C10_tool_fail_always | tool_error | 3 | — | 0 | ✓ |
| C11_step_limit | incomplete | 2 | — | 0 | ✓ |
| C12_ambiguous | no_evidence | 3 | — | 1 | ✓ |
| C13_no_supersede | answered | 3 | D04 | 0 | ✗ status=answered，期望 ['conflict']；未引用 D05；clarify_options 只有 0 个，期望 ≥2 |
| C14_pick_option | answered | 3 | D02 | 0 | ✗ 回答不含 ['15'] 中任何一项；无 resolution=resolved_by_user 的冲突 |

## 检索改写效果（只观察，不判定）

| 用例 | 检索次数 | 首次命中 | 最终命中 | 改写次数 | 查询序列 |
|---|---|---|---|---|---|
| C01_direct | 1 | 是 | 是 | 0 | 工卡丢了怎么补办？ |
| C02_paraphrase | 2 | 否 | 否 | 1 | 进公司刷的那张卡找不着了，咋整？ → 刷 那张卡  ， 整 |
| C03_conflict | 1 | 是 | 是 | 0 | 报销期限是多久？ |
| C04_conflict_removed | 1 | 是 | 是 | 0 | 报销期限是多久？ |
| C05_conflict_scoped | 1 | 是 | 是 | 0 | 报销期限是多久？ |
| C07_out_of_scope | 2 | 否 | 否 | 1 | 公司明年的股价目标是多少？ → 公司明年 股价目标是 |
| C08_followup | 1 | 是 | 是 | 0 | 年假有几天？ 那试用期的呢？ |
| C09_tool_fail_once | 1 | 是 | 是 | 0 | 工卡丢了怎么补办？ |
| C11_step_limit | 1 | 否 | 否 | 0 | 报销期限是多久？ |
| C12_ambiguous | 2 | 否 | 否 | 1 | 这个要多久？ → 这个要 |
| C13_no_supersede | 1 | 是 | 是 | 0 | 每周可以远程办公几天？ |

改写挽回的用例（首次未命中、最终命中）：无
