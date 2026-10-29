# 04 AI 使用说明

按考核要求如实记录：本项目允许使用 AI 辅助，此处说明用了什么、改了什么、验证了什么。

## 使用的工具

| 工具 | 承担的工作 |
|---|---|
| Pi（coding agent） | 驱动整个实现过程：读写代码、跑测试、生成评测产物 |
| claude-opus-5.5-xhigh | 方案审核与优化：对人工框架做可行性审查、指出漏洞、给出改法 |
| devin-swe2-max / deepseek-v4.1-flash-max | 在 Pi 内完成具体代码实现（agent 循环、guard、检索、API、前端、测试、脚本） |

运行时的 LLM 另算——那是被评测对象，不是辅助工具：`deepseek-flash`（DeepSeek 官方 API，temperature=0.1）。

## 分工边界

- **框架与取舍：人。** 证据账本、Verify-on-Submit、冲突三分法、bigram+BM25 检索、命中阈值、数字溯源等核心设计由人定稿，写进了 `docs/01`、`docs/02`。
- **可行性审核：AI。** 上述设计交给 claude-opus-5.5-xhigh 审查，采纳的意见包括：guard 不查中文数字（明写为已知边界）、`resolved_by_user` 要求 history 非空（防首轮伪造"用户已确认"）、`search_docs` 只给 40 字预览（强迫模型走 `read_doc` 才能引用）。
- **编码：AI。** `src/kbqa/`、`web/`、`tests/`、`scripts/` 由 AI 生成，人负责验收行为而非逐行审稿——验收方式是跑 `pytest` 和 `scripts/run_eval.py`，看 14 个用例和 60 个单测的结果对不对。
- **文档：人写。** `docs/01–03`、README 由人书写，AI 做语法检查和润色；本篇与 `05` 由 AI 按 README 中已声明的分工事实整理。

## 个人修改与验证

- 所有"要不要"的决定（工具契约字段、guard 规则松紧、要不要向量检索、前端用不用框架）由人拍板，AI 只执行或提建议。
- AI 生成的每一段代码都经过 `pytest -q`（60 个用例，离线可跑）和 `scripts/run_eval.py --out examples`（真实模型 14 用例）验证；评测中暴露的 guard 漏检（C05 数字溯源拦住一次"顺手写无出处数字"）证明校验层确实在工作，不是摆设。
- 未提交真实密钥；`.env` 在 `.gitignore` 中。
