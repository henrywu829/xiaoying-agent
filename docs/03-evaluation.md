# 03 评测结果

## 真实模型评测（DeepSeek deepseek-flash，temperature=0.1）

`python scripts/run_eval.py --out examples`：**14/14 通过**。详见 `examples/eval_report.md` 与各用例 `examples/cases/<id>/trace.jsonl`。

| 用例 | 状态 | 步数 | 验证的验收点 |
|---|---|---|---|
| C01_direct | answered | 3 | 明确答案+引用 |
| C02_paraphrase | answered | 4 | 口语改写（查询改写 1 次） |
| C03_conflict | conflict | 5 | 不可消解冲突+澄清选项 |
| C04_conflict_removed | answered | 4 | 同一问题，删掉冲突文档→answered 30 天 |
| C05_conflict_scoped | answered | 5 | 适用范围声明消解冲突 |
| C06_superseded | answered | 5 | 替代声明消解，`resolved_by_doc`+依据引用 |
| C07_out_of_scope | no_evidence | 4 | 资料外，无引用 |
| C08_followup | answered | 5 | 结合历史补全"试用期的"→年假 |
| C09_tool_fail_once | answered | 5 | 检索失败 1 次，模型自行重试 |
| C10_tool_fail_always | tool_error | 4 | 持续失败，如实报告 |
| C11_step_limit | incomplete | 2 | 步数上限强制 |
| C12_ambiguous | need_clarification | 2 | "这个要多久？"→追问 |
| C13_no_supersede | conflict | 4 | 与 C06 对照：去掉替代声明→conflict |
| C14_pick_option | answered | 4 | 点选澄清项→`resolved_by_user` |

## 四组测试的对照

- **C03/C04/C05**（同一问题，只改知识库）：conflict → answered(30天，D01) → answered(差旅 15 天、其他 30 天，双引用)。证明结论来自原文而非固定分支。
- **C06/C13**（同问题，D05 删除了一句"同时废止"）：answered(2天，resolved_by_doc) → conflict。若模型是按日期新旧选，两次结果应相同——它读的是原文声明。
- **C01/C02**（同意图改措辞）：C02 首次检索"门禁卡丢失补办"→未命中→改写"员工工卡挂失补办流程"→命中 D06，最终引用与 C01 一致。
- **perturb**（改被引段落的数字重跑）：`examples/perturb/` 下 7 个已回答用例（C01/C02/C04/C05/C06/C09/C14），把引用中的数字 n 改成 n+7 后重跑，**此时答案应该跟随新文档**（如 D06#p2 20→27 元，新答案答 27 元）。C08 因答案无数字跳过。这直接回答评审点"替换文档内容，答案和动作是否改变"。

## 检索改写效果（eval_report.md 观察表）

14 个用例里 C02 是唯一首次未命中后改写挽回的用例——其余用例查询词与原文重合足够，bigram+BM25 一次命中。这正是词法检索的价值：改写发生在它确实需要发生的地方。

## Guard 拒绝统计（真实运行）

14 用例中 **1 次被拒提交**：C05 第一次提交 answered 里写了数字 2（原文 D02_scoped 没有——模型似乎顺手把"两份文档"写进了答案），guard 报"回答中的数字 2 未出现在引用、问题或文档版本信息中"（见 trace 第 4 步）→ 模型修正后通过。**0 次错误引用**、**0 次裁决缺依据**逃逸。数字溯源确实拦住了真实模型会犯的"顺手换算/带无出处数字"错误。

## pytest（离线，60 个用例）

`examples/pytest_output.txt`：**60 passed**。覆盖检索分词/命中阈值/matched_terms、KB 解析与变体/with_text 热加载、工具故障注入与错误类型、guard 全部规则（含数字溯源三来源、裁决依据、clarify_options 格式）、Agent 循环（正常路径、观察驱动分支、拒后修正、resolved_by_user、故障不自动重试、步数上限、no_tool_call 纠偏、多 tool_call 计步、LLMError）、API（mock 强制、422、NDJSON 恰一个 final、health 不泄 key）。

## Mock 评测（不代表决策能力）

`examples/mock/`：6/14 失败是**预期**——MockProvider 是启发式脚本，不会判冲突、不生成 clarify_options。它验证流程能走通（C01/C04/C07/C08/C09/C10/C11/C12 过），供无 Key 时演示。

## 失败例子分析

- 数字溯源只会核实阿拉伯数字；模型若自行换算（"2 天→每月约 8 天"）会被拒（提示词已禁止换算，C05 那次被拒正是这种情况的邻近形态）。
- 非数字主张无法校验：模型把"不享受"写成"享受"且引用正确原文时可逃逸。靠逐字引用要求缓解（模型得把原文抄对），下一步可加语义校验。
- 词法检索对同义词天然弱：知识库写"工卡"，用户说"门卡"若无"卡"字重合会漏。已在 §5.7 记录，混合检索是下一步。
- deepseek-flash 是 reasoning 模型，首 token 较慢；trace 的 elapsed_ms 含思考时间。
