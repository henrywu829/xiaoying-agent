# 02 解决方案

## 架构

```
┌─ 浏览器 web/（原生 JS，无构建）── NDJSON 流式时间线 ──┐
│                                                     │
└→ FastAPI (api.py) ─→ run_agent (agent.py, 生成器) ──→┤ 事件 run_started/step/final
                          │                           │
        messages ─→ LLM (llm.py, OpenAI 兼容, httpx)   │
                          │ tool_calls                 │
        ToolBox (tools.py)│                            │
          ├─ search_docs → retrieval.py (bigram+BM25)  │
          ├─ read_doc    → kb.py → EvidenceLedger      │
          └─ submit_answer → guard.verify_submission ──┤ 拒→观察回模型
```

## 决策循环

`run_agent` 把工具结果作为 tool 消息回填，assistant 消息原样保留 `tool_calls`（DeepSeek 要求每个 tool_call_id 都有对应 tool 消息）。模型在每一步可自由决定：检索、读哪篇、改写重搜、放弃、提交哪种状态。

代码只做三件事：计步、执行工具、写事件。是否重试、如何改写交给由模型定，在故障注入时尤为明显（C09 模型自行重试，C10 重试无果后如实报 `tool_error`）。

## 工具契约（§5.4）

- `search_docs(query, top_k, reason)`：返回 `query_terms`、每条命中的 `para_id/preview(40字)/matched_terms`。预览不可引用；`matched_terms` 让模型看到"命中了哪些词"，判断要不要改写。无命中返回 `note=no_match ...`。
- `read_doc(doc_id, reason)`：返回全部段落+元数据，**同时登记证据账本**。只有账本里的 `para_id` 才能被引用。
- `submit_answer(...)`：唯一结束动作。接受 → final；拒绝 → `{"accepted": false, "errors": [...], "remaining_steps": N}` 回给模型修正。

## Guard 校验（guard.py，纯函数）

| 规则 | 说明 |
|---|---|
| 引用已读 | citations / conflicts.positions / basis_para_id 都必须在账本 |
| 逐字匹配 | 空白归一后 quote 是段落子串且 ≥4 字 |
| **数字溯源** | 仅 answered/conflict。answer 里的阿拉伯数字（剔除 `D\d+#p\d+` 编号、去前导零）必须出现在：有效 quote、用户消息、被引文档 version_date 之一。claim 里的数字必须出现在对应段落 |
| **裁决依据** | `resolved_by_doc` 必须带已读段的 `basis_para_id`+逐字 `basis_quote`；`resolved_by_user` 要求 history 非空且 basis 非空（首轮不能伪造"用户已确认"） |
| answered | ≥1 有效引用；不得含 unresolved 冲突 |
| conflict | 引用覆盖 ≥2 文档；≥1 unresolved；`clarifying_question` 非空；`clarify_options` 2–4 个（非空、≤30字、不重复） |
| no_evidence / tool_error | gaps 非空；no_evidence 不得带引用 |
| 白名单 | 模型不能提交 `incomplete` / `failed` |

通过后由账本补全每条引用的 `doc_id/title/version_date`——元数据不依赖模型复述。

已知边界：只核**阿拉伯**数字（中文"三十天"不查）；非数字主张的语义正确性（"不享受"写成"享受"）校验不了，靠提示词+评测。

## 冲突三分法

| 情形 | 依据 | 结果 |
|---|---|---|
| 可消解 | 原文有"同时废止"或适用范围声明 | `answered`，`resolved_by_doc`+原文依据 |
| 不可消解 | 都没有 | `conflict`+追问+可点选澄清选项 |
| 用户已确认 | 上轮流 conflict，本轮用户点选 | `answered`，`resolved_by_user` |

`version_date` 只作展示，模型按**原文声明**裁决。对照证据：C06（有废止声明 → answered 2 天）vs C13（no_supersede 去掉声明 → conflict）。

## 检索取舍

- **自写 bigram 分词**（~15 行）：中文相邻两字做 bigram，ASCII 串整体保留大写；小停用表（什么/怎么/多少/多久…）。不用 jieba——"门禁卡"会被切成整词反而更难对上"工卡"。
- **rank-bm25** 打分（BM25Okapi 默认参数）：公式无创新价值，自写只会多 30 行+测试。
- **命中阈值自写**：段落须命中 ≥2 个不同查询词项（查询 ≤2 词项时 1 个）。阈值只看命中词数不看分数，小语料上很稳；资料外问题得到干净的空结果。
- **不用向量检索**：会掩盖口语改写（"刷的那张卡"直接命中"工卡"），评审看不到模型做检索决策；还要 embedding key 和依赖。混合检索列为下一步。

## 前后端选型

| 维度 | 选择 | 理由 |
|---|---|---|
| 后端 | FastAPI + uvicorn | pydantic 校验、原生流式、TestClient 测试 |
| 模型接入 | httpx 直调 OpenAI 兼容 | 报文透明，DeepSeek/通义/OpenAI 一套协议；传输层对超时/5xx/429 重试 1 次 |
| 流式 | NDJSON fetch POST | SSE/EventSource 只支持 GET 传不了 history |
| 前端 | 原生 HTML+JS，FastAPI 同源托管 | 无 npm 构建，评审一条命令启动 |
| 测试 | pytest | fixture 简洁 |


