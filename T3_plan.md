# 工程方案：T3 企业知识问答 Agent（溯源问答 · Evidence-First QA）

> 交付形式：HTTP API + 同源网页（FastAPI 后端 + 无构建原生前端）
> 题面：`T3.md`；总要求：`requirement.md`。本方案自包含，实现者无需阅读原始对话。

---

## 0. 一页概览

**定位**：员工在网页里提问制度或产品问题。Agent 自主决定检索、读原文、改写查询、追问或停止，给出带**逐字可核验引用**的答案。资料冲突时列出冲突并请用户确认，不擅自选一个答案。

**创新点**：收敛为三条主线和一个交互闭环。每条都对应审核要点，并且用代码校验或对照实验给出**证据**，不只是描述机制。

**主线一：可核验**（对应"检查引用原文是否支持回答""无依据回答或错误引用属于关键缺陷"）

| # | 创新点 | 做法 | 成本 |
|---|---|---|---|
| 1 | **提交即校验（Verify-on-Submit）** | 结束动作 `submit_answer` 本身是一个工具。代码校验提交内容；不通过时，把拒绝原因作为观察结果返回给模型，由模型自行修正 | ~60 行 |
| 2 | **证据账本 + 预览与原文分离** | 检索只返回预览，不能引用；只有 `read_doc` 读过并登记的段落才可引用，且 quote 必须逐字匹配 | ~30 行 |
| 3 | **数字溯源** | `answered` / `conflict` 的回答里，每个阿拉伯数字都必须出现在引用片段中；冲突主张里的数字必须出现在对应段落中。堵住"引用是真的，但回答里的数字是编的"这一漏洞 | ~25 行 |
| 4 | **裁决也要引用** | 冲突标记为"依据文档已消解"时，必须给出 `basis_para_id + basis_quote` 并逐字校验，模型不能空口说"新文件替代了旧文件" | ~10 行 |

**主线二：检索可改进**（对应"高分依据是检索改进"）

| # | 创新点 | 做法 | 成本 |
|---|---|---|---|
| 5 | **命中词反馈 + 改写效果量化** | 检索层保持简单透明（自写 bigram 分词 + 现成 `rank-bm25` 打分 + 命中阈值），每条结果附 `matched_terms`。模型据此判断结果是否真的切题、要不要改写查询；评测报告统计首次检索命中率、最终命中率和改写次数 | ~30 行 |

**主线三：结论可证伪**（对应"替换文档内容，核对答案与动作是否改变""资料冲突时说明冲突并查证"）

| # | 创新点 | 做法 | 成本 |
|---|---|---|---|
| 6 | **评审控制台** | 网页内一键切换知识库变体、注入工具故障、调节步数上限、选择预设用例；实时显示决策时间线，引用可点击查看并高亮原文 | 前端 ~300 行 |
| 7 | **冲突对照变体** | 同一问题配三种知识库：`no_conflict`（删掉冲突文档）、`scoped_d02`（注明适用范围）、`no_supersede`（删掉替代声明）。证明模型依据原文裁决，而不是按日期新旧挑一个 | 数据 + 1 个用例 |
| 8 | **自动改文档复测（`--perturb`）** | 评测脚本对每个已回答用例，把引用段落中的数字改掉（如 20 元 → 27 元）后重跑，检查答案和引用是否跟着变。评审会手动做的检查，这里做成了自动测试 | ~40 行 |

**交互闭环**（对应"资料冲突时……请求确认"）

| # | 创新点 | 做法 | 成本 |
|---|---|---|---|
| 9 | **可点选的澄清选项** | `conflict` / `need_clarification` 时，模型给出 2–4 个 `clarify_options`（如"我适用《费用报销管理办法》"）；网页渲染成按钮，点击后作为下一轮提问并带上历史，Agent 按用户确认的制度作答 | 后端 ~5 行 + 前端 ~20 行 |

**工程约定**（不单列为创新点）：每个工具调用必须带 `reason`（≤30 字），trace 因此自带"简要决策依据"，又不暴露思维链。

**复杂度控制**：单进程，不用数据库、向量库和 npm 构建；运行时依赖 5 个（fastapi、uvicorn、httpx、python-dotenv、rank-bm25，后者连带 numpy）。Agent 循环原生实现，不引入框架。

---

## 1. 目标

1. 员工通过网页或 HTTP API 提问，得到以下交付：**回答、引用（文档 ID + 版本日期 + 原文片段）、资料缺口、任务状态**。
2. 至少一个由模型驱动的"选择动作 → 执行工具 → 观察 → 调整或结束"循环，并带步数上限。
3. 覆盖 T3 的 6 个必须验收点，并提交真实模型的运行记录（`examples/`）。
4. 评审者 5 分钟内能启动、复现，并亲手改变工具结果，观察 Agent 动作是否随之变化。
5. 关键结论都能被核实：引用和数字由代码校验，裁决依据有原文引用，"改文档后答案跟着变"由对照实验和 `--perturb` 自动复测给出证据。

## 2. 预期行为（示例）

| 输入 | 知识库变体 / 故障 | 预期动作路径 | 预期状态 |
|---|---|---|---|
| 工卡丢了怎么补办？ | default | search → read D06 → submit | `answered`，引用 D06 |
| 进公司刷的那张卡找不着了，咋整？ | default | search（无命中）→ **改写** search → read D06 → submit | `answered`，与上一行引用一致 |
| 报销期限是多久？ | default | search → read D01 → read D02 → submit | `conflict`：列出 D01 的 30 天与 D02 的 15 天，给出两个可点选的澄清选项，请用户确认适用制度 |
| （历史：上一行的冲突回答）点选"我适用《关于加强报销时效管理的通知》" | default | search → read D02 → submit | `answered`：15 天，引用 D02，冲突标记为"用户已确认" |
| 报销期限是多久？ | no_conflict（移除 D02） | search → read D01 → submit | `answered`：30 天，引用 D01 |
| 报销期限是多久？ | scoped_d02（D02 注明仅适用差旅） | search → read D01 → read D02 → submit | `answered`：差旅 15 天、其他 30 天，引用两份文档 |
| 每周可以远程办公几天？ | default | search → read D04 → read D05 → submit | `answered`：2 天，裁决依据引用 D05 的"同时废止"原文 |
| 每周可以远程办公几天？ | no_supersede（D05 去掉替代声明） | search → read D04 → read D05 → submit | `conflict`：1 天与 2 天并列，不按日期新旧自选 |
| 任意已回答问题 | 提交时回答里的数字不在引用中 | … → submit ✗（数字无出处）→ 补充引用或修正回答 → submit ✓ | 校验拒绝后由模型自行修正 |
| 公司明年的股价目标是多少？ | default | search → 改写 search → submit | `no_evidence`，无引用，gaps 说明缺什么资料 |
| （历史：年假有几天）那试用期的呢？ | default | 结合历史改写为"试用期员工年假" → search → read D03 → submit | `answered`，引用 D03#p2 |
| 工卡丢了怎么补办？ | search 失败 1 次 | search ✗ → 模型决定重试 → search ✓ → read → submit | `answered` |
| 工卡丢了怎么补办？ | search 持续失败 | search ✗ → 重试 ✗ → submit | `tool_error`，如实说明 |
| 报销期限是多久？ | max_steps=2 | search → read → **触达上限** | `incomplete`，附已读证据 |
| 这个要多久？（无历史） | default | submit need_clarification（可能先检索一次） | `need_clarification` + 追问 |

## 3. 当前状态

仓库目前只有题面文件：`requirement.md`、`T1.md`~`T4.md`，没有代码、git 仓库和依赖。本方案属于**全新项目**。

已确认的环境事实：

- 系统默认 `python3` 是 3.15.2（版本太新，部分依赖可能没有 wheel）。uv 管理着 3.12.13 和 3.11.15，因此**项目固定使用 3.12**。
- 已安装 `uv 0.13.6`、`git 2.50.1`、`gh 2.103.3`、`node v24.13.1`（前端不需要用到）。
- 环境里**没有任何模型 API Key**（见 §16 未解决问题）。
- PyPI 当前版本：fastapi 0.162.0、uvicorn 0.54.0、httpx 0.28.1、python-dotenv 1.2.4、rank-bm25 0.2.2（只依赖 numpy；numpy 2.5.4 要求 Python ≥ 3.12 且有 cp312 macOS wheel；3.11 下 pip 会自动选更早的 numpy）、pytest 9.2.0、openai 3.40.0（本项目不使用）。
- **检索预演**（在 §8.1 数据上用 bigram + rank-bm25 0.2.2 + 命中阈值试跑过）："工卡丢了怎么补办？"命中 D06；C02 的口语原句**无命中**，改写为"门禁卡 补办"后命中 D06；"每周可以远程办公几天？"同时命中 D04、D05；"公司明年的股价目标是多少？"和"这个要多久？"无命中。另外发现：如果 D01/D02 原文里没有"报销期限"这个词，"报销期限是多久？"只命中"报销"一个词项，会被阈值过滤掉。因此 §8.1 在这两段原文里写入了"报销期限"，写入后两段都能命中。

## 4. 需求

### 4.1 功能要求（验收点映射）

| T3 验收点 | 实现机制 | 用例 ID |
|---|---|---|
| 明确答案 | 检索 → 读原文 → 引用校验通过 → `answered` | C01 |
| 文档冲突 | 冲突三分法：不可消解 → `conflict` + 澄清选项；依据文档可消解 → 按引用的依据回答 | C03、C04、C05、C06、C13 |
| 资料外问题 | 检索阈值 + 模型改写后仍无果 → `no_evidence` | C07 |
| 改写后的相似问题 | 模型改写查询；断言与 C01 引用同一文档 | C02 |
| 上下文追问 | 请求携带 `history`，模型补全问题后再检索 | C08 |
| 工具失败 | 故障注入，模型决定重试或报告 `tool_error`（代码不自动重试） | C09、C10 |
| 步数上限（总要求） | `max_steps` 由代码强制，触达返回 `incomplete` | C11 |
| 追问澄清（加分） | `need_clarification` / `conflict` + `clarifying_question` + 可点选的 `clarify_options`；用户点选后按确认的制度作答 | C12、C14 |
| 审核：引用是否支持回答 | 逐字校验 + 数字溯源 + 裁决依据引用（guard 代码兜底） | test_guard；全部用例 |
| 审核：替换文档内容后答案和动作是否改变 | KB 变体对照 + `--perturb` 自动改数字复测 | C03/C04/C05、C06/C13、`examples/perturb/` |

### 4.2 技术约束

- Python 3.12；运行方式为 HTTP API + 网页（`requirement.md` 三选一中的 HTTP API）。
- 模型调用使用 **OpenAI 兼容 Chat Completions + tools 协议**，可接 DeepSeek、通义千问（DashScope 兼容模式）、OpenAI、Moonshot 等。
- 没有 Key 时自动进入离线 Mock，页面显著标注"Mock 仅验证流程，不证明决策效果"。
- 不提交真实密钥；`.env` 加入 `.gitignore`。

### 4.3 非目标

用户登录、多租户、向量/混合检索、重排模型、LLM 裁判、文档上传、线上部署、多 Agent、持久化数据库、生产级并发与限流。

### 4.4 假设

- 评审机有 Python ≥ 3.11，以及 uv 或 pip。
- 知识库规模很小（< 50 篇），每次请求在内存中建索引，开销可忽略。
- 所有文档和产品都是**合成虚构**的。产品名用虚构的「剪影星 App」，避免冒用真实产品事实。

---

## 5. 架构设计

### 5.1 总体架构

```text
┌──────────────────────── Browser（web/，原生 HTML/JS，无构建）────────────────────────┐
│  对话区 │ 决策时间线（实时） │ 评审控制台（KB 变体 / 故障注入 / 步数 / 预设用例）│ 原文抽屉 │
└───────────────┬─────────────────────────────────────────────────────────────────┘
                │ fetch POST /api/ask/stream  ← NDJSON 逐行事件
                │ GET /api/health, /api/cases, /api/kb/{variant}/docs[/{doc_id}]
┌───────────────▼──────────────── FastAPI（src/kbqa/api.py）─────────────────────────┐
│  请求校验（pydantic schemas）→ run_agent() 生成器 → 事件流 / 汇总 JSON；静态托管 web/   │
└───────────────┬─────────────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────── Agent 核心（src/kbqa/agent.py）────────────────────┐
│  ReAct 循环：LLM 选择工具 → ToolBox 执行 → 观察写回消息 → LLM 决定下一步或提交      │
│  代码强制：步数预算 │ 协议纠偏（无工具调用 → 提示一次）│ 结果组装 │ Trace 事件          │
└──────┬──────────────────────────┬──────────────────────────────┬────────────────┘
       │                          │                              │
┌──────▼──────────┐   ┌───────────▼──────────────┐   ┌──────────▼──────────────┐
│ LLM Provider    │   │ ToolBox（tools.py）       │   │ Guard（guard.py）        │
│ (llm.py)        │   │ search_docs / read_doc /  │   │ verify_submission():    │
│ OpenAICompat    │   │ submit_answer             │◄──┤ 引用逐字校验、状态约束   │
│ (httpx)         │   │ EvidenceLedger 证据账本    │   └─────────────────────────┘
│ MockProvider    │   │ FaultInjector 故障注入     │
└─────────────────┘   └───────────┬──────────────┘
                                  │
                      ┌───────────▼──────────────┐
                      │ KB（kb.py + retrieval.py）│
                      │ Markdown+front matter 加载│
                      │ 变体组合、mtime 热加载     │
                      │ bigram BM25 + 命中阈值    │
                      └───────────┬──────────────┘
                                  │
                         data/kb/docs/*.md, extra/*.md, variants.json
```

### 5.2 分层职责与边界

| 层 | 负责 | 不负责 |
|---|---|---|
| **模型（LLM）** | 检索词、是否读原文、读哪篇、是否改写重搜、冲突如何定性、何时追问或停止、答案措辞 | 预算、引用真伪、状态格式 |
| **Agent 循环（代码）** | 驱动循环、计步、触达上限返回 `incomplete`、无工具调用时纠偏、组装最终结果 | 任何业务判断（不写"结果为空就改写"这类分支） |
| **ToolBox（代码）** | 执行工具、登记证据、注入故障、返回结构化观察 | 重试（是否重试由模型决定） |
| **Guard（代码）** | 校验提交：引用必须逐字存在于已读段落；回答中的数字必须有引用出处；裁决依据必须有引用；各状态的必填约束 | 非数字类主张的语义正确性（交给提示词和评测，见 §13） |
| **API 层** | 校验输入、序列化、流式传输、静态托管 | 业务逻辑 |

原则：**确定性约束交给代码，判断与决策交给模型。** 这样既满足"仅有固定条件分支不算 ReAct"的要求，也让关键缺陷（错误引用、超预算）由代码兜底。

### 5.3 决策循环（核心伪代码，`src/kbqa/agent.py: run_agent`）

```python
def run_agent(req: AskRequest, provider: LLMProvider, kb: KnowledgeBase) -> Iterator[dict]:
    toolbox = ToolBox(kb, EvidenceLedger(), FaultInjector(req.faults), req.question, req.history)  # 后两者供数字溯源校验
    messages = build_messages(req.question, req.history)        # prompts.py
    yield {"type": "run_started", "run_id": rid, "provider": ..., "kb": req.kb, "max_steps": req.max_steps}
    steps, trace = 0, []
    while steps < req.max_steps:
        try:
            reply = provider.chat(messages, TOOL_SCHEMAS)
        except LLMError as e:
            yield final(status="failed", gaps=[f"模型调用失败：{e}"]); return
        messages.append(reply.raw_message)                       # 原样回写 assistant（含 tool_calls）
        if not reply.tool_calls:                                 # 协议纠偏：计 1 步并提示，不替模型做决定
            steps += 1
            messages.append({"role": "user", "content": NUDGE_MESSAGE})
            ev = step_event(steps, "(no_tool_call)", {}, "模型未调用工具", ok=False); trace.append(ev); yield ev
            continue
        for call in reply.tool_calls:
            if steps >= req.max_steps: break
            steps += 1
            obs = toolbox.execute(call.name, call.arguments, remaining=req.max_steps - steps)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(obs, ensure_ascii=False)})
            ev = step_event(steps, call, obs); trace.append(ev); yield ev
            if call.name == "submit_answer" and obs.get("accepted"):
                yield final_from_submission(obs["submission"], toolbox.ledger, steps, trace); return
    yield final(status="incomplete", gaps=[f"已达到最大步数 {req.max_steps}，任务未完成"],
                evidence_read=toolbox.ledger.para_ids(), trace=trace)
```

不变量：

- 事件流**有且只有一个** `final` 事件，并且总是最后一个。
- 只有 `submit_answer` 校验通过，或出现 `incomplete` / `failed`，循环才结束。模型不能直接提交 `incomplete` 或 `failed`。
- 计步口径：**每次工具调用（含 `submit_answer`）或每次无工具调用的回复都计 1 步**。因此 LLM 调用次数 ≤ 步数，不会死循环。
- 代码对工具失败**不自动重试**，重试与否完全取决于模型的下一步动作（规则明确"自动重试"不算 ReAct）。

### 5.4 工具设计（`src/kbqa/tools.py: TOOL_SCHEMAS`）

所有工具都带必填参数 `reason: string`（≤30 字，本步决策依据），观察结果都带 `remaining_steps`。

**① `search_docs(query, top_k=4, reason)`**：检索段落，**只返回预览，不能引用**。每条结果附 `matched_terms`（命中的查询词项），观察顶层附 `query_terms`（查询被切成了哪些词项）。模型据此判断结果是否真的切题：比如只命中"公司""管理"这类泛词，就说明需要改写。

```json
{"ok": true, "query": "报销期限", "query_terms": ["报销", "销期", "期限"], "hits": [
  {"doc_id": "D01", "para_id": "D01#p2", "title": "费用报销管理办法", "version_date": "2023-01-01",
   "score": 4.82, "matched_terms": ["报销", "销期", "期限"], "preview": "第二条 报销期限：员工应在费用发生之日起 30 天内…"}],
 "remaining_steps": 9}
```

无命中时返回 `{"ok": true, "query_terms": [...], "hits": [], "note": "no_match：没有段落命中足够的查询词项", ...}`；故障时返回 `{"ok": false, "error": {"type": "timeout", "message": "检索服务超时", "retryable": true}, ...}`。`top_k` 限制在 1..5，预览截取前 40 字。

**② `read_doc(doc_id, reason)`**：读取全文和元数据，并把每个段落**登记进证据账本**。

```json
{"ok": true, "doc_id": "D05", "title": "远程办公管理办法（2024修订）", "version_date": "2024-09-01",
 "scope": "全体员工", "supersedes": "D04",
 "paragraphs": [{"para_id": "D05#p1", "text": "本办法自 2024 年 9 月 1 日起施行，原《远程办公管理办法（2023版）》同时废止。"}, ...],
 "remaining_steps": 5}
```

`doc_id` 不存在时返回 `{"ok": false, "error": {"type": "not_found", "retryable": false}}`。

**③ `submit_answer(status, answer, citations, conflicts, gaps, clarifying_question, clarify_options, reason)`**：唯一的结束动作。

- `status` ∈ `answered | conflict | need_clarification | no_evidence | tool_error`
- `citations`: `[{para_id, quote}]`
- `conflicts`: `[{topic, positions: [{para_id, claim}], resolution, basis, basis_para_id, basis_quote}]`
  - `resolution` ∈ `unresolved`（未消解）、`resolved_by_doc`（原文的替代声明或适用范围可以消解）、`resolved_by_user`（用户在对话中确认了适用制度）
  - `resolved_by_doc` 时，`basis_para_id` 和 `basis_quote` 必填，即裁决依据的原文引用
- `gaps`: `[string]`
- `clarifying_question`: string；`clarify_options`: `[string]`，2–4 个，每个 ≤30 字，是用户可以直接发送的一句确认语，例如"我适用《费用报销管理办法》"

校验通过时返回 `{"accepted": true, "submission": {...}}`，循环结束。校验不通过时返回 `{"accepted": false, "errors": ["引用 D02#p3 尚未读取，请先 read_doc", "回答中的数字 27 未出现在任何引用片段中"], "remaining_steps": 2}`，**由模型决定如何修正**（这是第二个 ReAct 回路）。

### 5.5 证据账本与提交校验（`tools.py: EvidenceLedger`，`guard.py: verify_submission`）

`EvidenceLedger` 维护 `dict[para_id, (doc_meta, text)]`，只有 `read_doc` 成功时才写入。

`verify_submission(sub, ledger, question, history) -> (accepted: bool, errors: list[str], normalized: dict)` 的规则：

| 规则 | 说明 |
|---|---|
| 引用已读 | 每个 `citations[].para_id`、`conflicts[].positions[].para_id`、`basis_para_id` 都必须在账本中 |
| 逐字匹配 | 去掉空白后，`quote` / `basis_quote` 必须是该段原文的子串，且长度 ≥ 4 |
| **数字溯源** | 仅对 `answered` 和 `conflict` 生效。先从 `answer` 中去掉 `D\d+(#p\d+)?` 这类编号，再用 `\d+(\.\d+)?` 提取数字，去掉前导零后比较。每个数字都必须出现在以下来源之一：有效引用的 `quote`、当前问题和历史中 `role=user` 的消息、被引用文档的 `version_date`。历史里的 assistant 消息不算来源：后端无状态，history 由客户端传入，可以被伪造。`conflicts[].positions[].claim` 中的数字必须出现在对应段落原文中。错误信息写明是哪个数字，方便模型修正 |
| **裁决依据** | `resolved_by_doc` 必须带有效的 `basis_para_id + basis_quote`；`resolved_by_user` 要求 `history` 非空（首轮对话里不能声称"用户已确认"），且 `basis` 非空 |
| answered | 至少 1 条有效引用；`conflicts` 中不得有 `unresolved`（有未消解冲突就应提交 conflict） |
| conflict | 有效引用至少覆盖 2 个不同 `doc_id`；至少 1 条 `unresolved` 冲突；`clarifying_question` 非空；`clarify_options` 2–4 个 |
| need_clarification | `clarifying_question` 非空；`clarify_options` 可选，若提供则须为 2–4 个 |
| clarify_options 格式 | 每项非空、≤30 字、不重复 |
| no_evidence / tool_error | `gaps` 非空；`no_evidence` 不得带引用 |
| 状态白名单 | 模型不能提交 `incomplete` / `failed` |

数字溯源代码旁加注释：`shortcut: 只核对阿拉伯数字，中文数字（"三十天"）不会被检查；提示词要求数字与原文写法一致，若真实 trace 中出现中文数字再加转换`。

通过后，用账本补全每条引用的 `doc_id / title / version_date`，最终输出不依赖模型复述元数据。

### 5.6 冲突三分法（提示词 + 数据共同实现）

| 情形 | 判定依据（模型读原文和元数据） | 动作 |
|---|---|---|
| 无冲突 | 只有一份相关文档，或多份一致 | `answered` |
| 可消解冲突 | 原文写明替代关系（D05 写有"原《…》同时废止"），或写明适用范围（scoped_d02 写有"差旅费用…其他费用仍按…执行"）；`supersedes` / `scope` 元数据只作为提示 | `answered`，`resolution="resolved_by_doc"`，**依据必须引用原文**（`basis_para_id + basis_quote`，由 guard 校验） |
| 不可消解冲突 | 规定不同，又没有替代声明或适用范围说明（D01 vs D02；`no_supersede` 变体下的 D04 vs D05） | `conflict`：列出各方原文，给出 `clarifying_question` 和可点选的 `clarify_options`；**不得按日期新旧自选** |
| 用户已确认 | 上一轮是 conflict，本轮用户点选或输入了适用制度 | `answered`，按所确认的制度作答，`resolution="resolved_by_user"` |

对照证据：C06（有替代声明 → answered）与 C13（`no_supersede`，同一问题 → conflict）只差一句原文。如果模型是按日期新旧选答案，两者会给出相同结果。

### 5.7 检索设计（`retrieval.py`）

定位：**检索层保持简单透明，检索改进放在 Agent 闭环里**。检索每次都把命中了哪些词告诉模型，模型据此决定是否改写；评测则量化改写的效果。

- **分词（自写，约 10 行）**：用 `re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+")` 切段。中文段取相邻两字 bigram；连续的 ASCII 字母和数字保持整体并转大写（如 `4K`、`OA`、`30`）。另有一个很小的停用 bigram 表（`什么、怎么、多少、多久、如何、可以、是否、请问`）。
- **索引单位**：段落；每个段落的词项前面拼上文档标题的词项。
- **打分（现成库）**：`rank_bm25.BM25Okapi(corpus_tokens).get_scores(query_terms)`，使用默认参数（k1=1.5，b=0.75）。排序键为 `(-score, para_id)`，保证结果确定。
- **命中阈值与 `matched_terms`（自写，约 5 行）**：`matched = set(query_terms) & set(para_terms)`。段落至少命中 2 个不同查询词项才返回（查询词项 ≤ 2 个时只需 1 个）。阈值只看命中词数，不看分数，因此不受 rank-bm25 小语料 IDF 下限的影响。资料外问题能得到干净的空结果。
- **改写效果量化**（`run_eval.py`，只观察记录，不参与通过判定）：
  - 首次检索命中率：第一次成功的 `search_docs` 是否已召回 `must_cite_docs` 中的文档；
  - 最终命中率：任一次检索是否召回；
  - 改写次数：不同 query 的数量减 1；
  - 改写挽回的用例：首次未命中、最终命中的用例列表。
- **为什么不用向量检索**：向量检索会掩盖口语改写，比如"刷的那张卡"直接命中"工卡"，评审就看不到模型做检索决策；而且还要多一个 embedding Key 和依赖。这里的选择是为了**透明、可解释**，不是故意把检索做弱。取舍写入 `docs/02-solution.md`，混合检索列为 05 的下一步。
- **为什么 BM25 用现成库**：公式本身没有创新价值，自写还要多 30 行和对应测试；rank-bm25 只依赖 numpy。

### 5.8 知识库与变体（`kb.py`）

文档格式为 Markdown + 简单 front matter，按行解析 `key: value`，不依赖 PyYAML：

```markdown
---
doc_id: D01
title: 费用报销管理办法
version_date: 2023-01-01
scope: 全体员工
supersedes:
category: 制度
---
第一条 为规范公司费用报销管理，制定本办法。

第二条 报销期限：员工应在费用发生之日起 30 天内提交报销申请，逾期不予受理。
```

- 段落按空行切分，`para_id = f"{doc_id}#p{i}"`，`i` 从 1 开始。
- 变体在 `data/kb/variants.json` 中声明：`{name: {description, exclude: [doc_id], extra: [filename]}}`。`extra` 里的文件来自 `data/kb/extra/`，与基础文档 `doc_id` 相同时**覆盖**原文档（用于"替换文档内容"）。
- **热加载**：按变体缓存，缓存键为相关文件的最大 mtime；评审者直接编辑 md 后重新提问即可，**不用重启**。缓存用 `threading.Lock` 保护。
- 变体名必须在白名单（`variants.json` 的键）内，防止路径穿越。

### 5.9 预算与终止状态

| status | 中文标签 | 由谁产生 |
|---|---|---|
| `answered` | 已回答 | 模型提交并通过校验 |
| `conflict` | 资料冲突，待确认 | 模型 |
| `need_clarification` | 需要补充信息 | 模型 |
| `no_evidence` | 资料不足或超出范围 | 模型 |
| `tool_error` | 工具失败 | 模型 |
| `incomplete` | 未完成（达到步数上限） | 代码 |
| `failed` | 系统错误（模型不可用） | 代码 |

- `max_steps` 默认取 `AGENT_MAX_STEPS`（10），请求可覆盖，范围 1..12。默认值从 8 提到 10，是为了给"提交被拒后修正"留出 1–2 步余量。
- 每次观察都带 `remaining_steps`，模型可据此自行收敛。

### 5.10 模型接入（`llm.py`）

```python
@dataclass
class ToolCall:  id: str; name: str; arguments: str          # arguments 为原始 JSON 字符串
@dataclass
class LLMReply:  content: str | None; tool_calls: list[ToolCall]; raw_message: dict
class LLMError(Exception): ...
class LLMProvider(Protocol):
    name: str; model: str; is_mock: bool
    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply: ...
```

- **`OpenAICompatProvider`**：用 `httpx.Client(timeout=LLM_TIMEOUT)` 发送 `POST {LLM_BASE_URL}/chat/completions`，请求体为 `{model, messages, tools, tool_choice: "auto", temperature: 0.1}`。
  - 超时、5xx 或 429 时在传输层重试 1 次（属于基础设施重试，与业务决策无关，文档中说明）。
  - `raw_message` 按 OpenAI 格式回写 `tool_calls`。
  - 工具参数 JSON 不合法时，由 `ToolBox.execute` 返回 `{"ok": false, "error": {"type": "bad_arguments"}}`，交给模型修正。
- **`MockProvider`**（离线）：根据消息里最近的工具结果做**启发式**决策。
  - 失败不足 2 次就原参数重试，否则提交 `tool_error`。
  - 没检索过就检索；问题少于 8 字且有历史时，拼接上一轮用户问题。
  - 无命中且检索不足 2 次时，去掉疑问词再检索，否则提交 `no_evidence`。
  - 有命中就读 top1 文档，然后以 top1 段落全文为引用提交 `answered`。
  - 提交 `answered` 时，回答直接使用引用段落的全文，因此天然满足数字溯源。
  - **边界**：不识别冲突、不做语义改写、不生成 `clarify_options`，只用于验证流程和离线演示；页面、README 和 03 文档都要明确标注。
- **`make_provider(settings, force_mock)`**：有 Key 且没有强制 Mock 时返回 `OpenAICompatProvider`，否则返回 `MockProvider`。
- **为什么不用 openai SDK**：SDK 当前已到 3.x，主版本迭代快；直接用 httpx 调协议约 50 行，更透明，也少一个依赖。

### 5.11 系统提示词（`prompts.py: SYSTEM_PROMPT`，实现时可微调措辞，规则不变）

```text
你是企业知识问答助手，只能依据知识库原文回答员工关于制度和产品的问题。
你通过工具行动：search_docs 检索段落预览；read_doc 读取文档原文与元数据；submit_answer 提交最终结果（唯一的结束方式）。
规则：
1. 证据：只有 read_doc 读到的段落可以引用；citations.quote 必须逐字摘自该段落（连续片段，≥4 字）。检索预览不能作为引用。answer 中的每个数字都必须出现在你的引用片段里，使用与原文一致的阿拉伯数字，不要自行换算或汇总。
2. 检索改进：查看 query_terms 与每条结果的 matched_terms。结果为空，或只命中泛词（如"公司""管理"），就改用制度/产品术语、同义词或拆分关键词重新检索；累计 3 次仍无相关结果，提交 no_evidence 并在 gaps 说明缺什么资料。
3. 冲突查证：多份文档对同一问题规定不同时，读取全部相关文档，比较 version_date、scope、supersedes 与原文中的替代/适用范围说明。
   - 原文明确写有替代关系或适用范围 → answered，按适用范围作答；conflicts 中 resolution=resolved_by_doc，并用 basis_para_id + basis_quote 逐字引用该依据原文；
   - 否则 → conflict，列出各文档规定与引用，给出 clarifying_question，以及 2–4 个 clarify_options（用户可直接发送的确认语，如"我适用《XX》"，≤30 字）。不得仅凭日期新旧或主观判断选择其一。
4. 追问：结合对话历史把当前问题补全为完整问题后再检索；缺少关键对象且历史无法补全时，提交 need_clarification，给出 clarifying_question，可附 clarify_options。如果上一轮你提出过冲突追问、本轮用户确认了适用制度，就重新读取并按该制度作答，conflicts 中 resolution=resolved_by_user，basis 写明用户的选择。
5. 工具失败：根据错误信息决定是否重试或调整参数；同一工具连续失败 2 次，提交 tool_error，在 gaps 说明失败工具与已获得的信息。
6. 资料外问题：知识库无依据时提交 no_evidence，不得用常识补答。
7. 每次调用工具都要填写 reason（≤30 字，本步决策依据）；留意观察结果中的 remaining_steps，在预算内结束。
8. answer 使用简体中文，简洁；数字与原文一致。
```

`NUDGE_MESSAGE = "请通过调用工具继续；如已可作答，请调用 submit_answer 结束。"`

`build_messages(question, history)` 的结构：`[system] + history[-12:]（role 仅限 user/assistant）+ [user: question]`。

### 5.12 Trace（`trace.py`）

- **step 事件字段**：`step, action, args（不含 reason）, reason, ok, observation_summary, observation（原始观察，截断至 600 字）, elapsed_ms`。
- **`summarize_observation(action, obs)`** 生成简短摘要：
  - 检索："命中 2 条：D01#p2[报销,期限]、D02#p1[报销,期限]"；"无命中（词项：进公、公司…）"；"失败：timeout"
  - 读取："读取 D01《费用报销管理办法》3 段，版本 2023-01-01，适用：全体员工"
  - 提交："已接受：conflict（2 个澄清选项）"；"被拒绝：D01#p2 的 quote 与原文不一致"；"被拒绝：数字 27 无出处"
- **持久化**：每次 API 运行都写 `runs/<yyyymmdd-HHMMSS>_<run_id>.jsonl`（已 gitignore）。评测脚本另写 `examples/cases/<case_id>/trace.jsonl`。

---

## 6. 前后端选型与对接

### 6.1 选型结论

| 维度 | 选择 | 主要备选 | 取舍理由 |
|---|---|---|---|
| 后端框架 | **FastAPI 0.162 + uvicorn 0.54** | Flask、原生 http.server | pydantic 自动校验请求，自带 `/docs` OpenAPI 页面方便评审直接调用；`StreamingResponse` 原生支持流式；`TestClient` 便于测试 |
| Agent 编排 | **原生循环（约 80 行）** | LangGraph、Google ADK、AgentScope | 题目要求的循环很简单，框架带来的状态图和抽象会增加解释成本；"框架名称不加分"，原生实现每一行都能讲清楚 |
| 模型接入 | **httpx 0.28 直调 OpenAI 兼容协议** | openai SDK 3.x、LiteLLM | 一套协议覆盖 DeepSeek、通义、OpenAI；依赖少，报文透明，便于在 trace 中解释 |
| 检索 | **自写 bigram 分词 + rank-bm25 0.2.2 + 命中阈值** | 向量检索、jieba + BM25、自写 BM25 | 见 §5.7：让改写成为模型的真实决策；BM25 公式用现成库，只自写项目特有的分词和阈值；jieba 会把"门禁卡"切成整词，反而更难和"工卡"对上 |
| 流式协议 | **NDJSON over fetch POST** | SSE（EventSource 或 sse-starlette）、WebSocket | EventSource 只支持 GET，没法传 history；NDJSON 一行一个 JSON，前端解析约 15 行，后端不需要额外依赖 |
| 前端 | **原生 HTML + ES Module JS + 手写 CSS，由 FastAPI 同源托管** | React/Vite、Vue、Streamlit、Gradio | 不需要 npm 构建，评审一条命令就能起服务；同源免 CORS；Streamlit/Gradio 难以定制"时间线 + 原文高亮"这类评审交互 |
| 测试 | **pytest 9.2** | unittest | 生态标准，fixture 简洁 |
| Python | **3.12（`.python-version`）** | 系统 3.15 | 3.15 太新，依赖可能缺 wheel |

### 6.2 后端 API 契约（`src/kbqa/api.py` + `src/kbqa/schemas.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 网页（`StaticFiles(directory=web, html=True)` 挂载在 `/`，**在所有 `/api` 路由之后注册**） |
| GET | `/api/health` | `{provider, model, is_mock, kb_variants: [{name, description}], default_max_steps, max_steps_limit}`，**不返回 Key** |
| POST | `/api/ask` | 一次性返回 `AskResponse`（供 curl、测试、评测脚本使用） |
| POST | `/api/ask/stream` | `application/x-ndjson` 流式事件；响应头 `Cache-Control: no-cache`、`X-Accel-Buffering: no` |
| GET | `/api/cases` | 返回 `data/eval_cases.json`（前端"预设用例"下拉框使用） |
| GET | `/api/kb/{variant}/docs` | 文档元数据列表 |
| GET | `/api/kb/{variant}/docs/{doc_id}` | 文档全文 + 段落（原文抽屉使用），不存在时返回 404 |

**请求 `AskRequest`**：

```json
{
  "question": "那试用期的呢？",
  "history": [{"role": "user", "content": "年假有几天？"},
              {"role": "assistant", "content": "正式员工工作满1年不满10年的年假5天……"}],
  "kb": "default",
  "max_steps": 10,
  "faults": {"search_docs": "fail_once"},
  "mock": false
}
```

校验规则：

- `question`：1..500 字。
- `history`：≤ 12 条，`role` ∈ {user, assistant}。
- `kb`：必须是已知变体。
- `max_steps`：1..12，默认取环境变量。
- `faults` 的键 ∈ {`search_docs`, `read_doc`}，值 ∈ {`fail_once`, `fail_always`}。
- `mock=true` 时强制使用 Mock。

违反规则时返回 **422**（pydantic）；未知变体由自定义校验器报错，同样返回 422。

**响应 `AskResponse`**：

```json
{
  "run_id": "a1b2c3", "question": "报销期限是多久？",
  "status": "conflict", "status_label": "资料冲突，待确认",
  "answer": "现有两份制度对报销期限规定不一致：D01 规定 30 天，D02 规定 15 天，且未说明适用范围或替代关系。请确认您适用哪份制度。",
  "citations": [
    {"doc_id": "D01", "para_id": "D01#p2", "title": "费用报销管理办法", "version_date": "2023-01-01", "quote": "员工应在费用发生之日起 30 天内提交报销申请"},
    {"doc_id": "D02", "para_id": "D02#p1", "title": "关于加强报销时效管理的通知", "version_date": "2024-06-01", "quote": "应在费用发生后 15 天内完成报销提交"}
  ],
  "conflicts": [{"topic": "报销期限", "positions": [{"para_id": "D01#p2", "claim": "30 天"}, {"para_id": "D02#p1", "claim": "15 天"}],
                 "resolution": "unresolved", "basis": "两份文档均未声明替代关系或适用范围", "basis_para_id": null, "basis_quote": null}],
  "gaps": ["缺少两份制度的适用范围或优先级说明"],
  "clarifying_question": "请确认您适用哪份制度？",
  "clarify_options": ["我适用《费用报销管理办法》", "我适用《关于加强报销时效管理的通知》"],
  "evidence_read": ["D01#p1", "D01#p2", "D01#p3", "D02#p1", "D02#p2"],
  "steps_used": 4, "max_steps": 10,
  "provider": {"name": "openai_compat", "model": "deepseek-chat", "is_mock": false},
  "kb": "default", "faults": {},
  "trace": [ /* StepEvent[] */ ],
  "elapsed_ms": 5230
}
```

**NDJSON 事件流**（每行一个 JSON，**最后一行一定是 `final`**）：

```text
{"type":"run_started","run_id":"a1b2c3","provider":{...},"kb":"default","max_steps":10}
{"type":"step","step":1,"action":"search_docs","args":{"query":"报销期限","top_k":4},"reason":"先检索报销期限相关制度","ok":true,"observation_summary":"命中 2 条：D02#p1[报销,销期,期限]、D01#p2[报销,销期,期限]","elapsed_ms":3}
{"type":"step","step":2,"action":"read_doc","args":{"doc_id":"D01"},"reason":"读取最高分文档原文","ok":true,"observation_summary":"读取 D01《费用报销管理办法》3 段……","elapsed_ms":1}
...
{"type":"final","result":{ /* AskResponse */ }}
```

**错误约定**：

- 输入错误返回 HTTP 422。
- 业务结果（包括 `tool_error`、`incomplete`、`failed`）**一律返回 HTTP 200**，通过 `status` 区分，前端只需一套渲染逻辑。
- 流式过程中出现未预期异常时，后端捕获并输出 `final(status="failed")`，保证前端总能收到 `final`。

### 6.3 前端页面设计（`web/index.html`、`web/app.js`、`web/style.css`）

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│ 溯源问答 Agent      模型：deepseek-chat ● 真实模型      ⚠ Mock 模式横幅（仅 Mock 时显示）│
├──────────────────────────────────┬────────────────────────────────────────────┤
│ 对话区                             │ 决策时间线（实时）        步数 ■■■■□□□□□□ 4/10 │
│ 你：报销期限是多久？                 │ ① search_docs {query:"报销 期限"}            │
│ Agent：[资料冲突，待确认]（状态徽章） │    依据：先检索报销期限相关制度               │
│   回答正文……                        │    → 命中 3 条：D01#p2、D02#p1…              │
│   冲突表：D01#p2 30天 │ D02#p1 15天  │ ② read_doc {doc_id:"D01"}  ✓                │
│   引用：[D01#p2] [D02#p1] ← 可点击   │ ③ read_doc {doc_id:"D02"}  ✓                │
│   资料缺口：…   追问：请确认适用哪份制度？│ ④ submit_answer ✗ 被拒：数字 27 无出处        │
│   [我适用《费用报销管理办法》]       │ ⑤ submit_answer ✓ conflict                 │
│   [我适用《关于加强…通知》] ← 可点击  │                                            │
│ [ 输入问题……                ][提问] │                         [导出 Trace JSON]   │
├──────────────────────────────────┴────────────────────────────────────────────┤
│ 评审控制台：预设用例[▾] 知识库[default ▾] 故障[无│检索失败1次│检索持续失败│读取失败1次]│
│            步数上限[10] □强制Mock  [新会话]                                        │
└───────────────────────────────────────────────────────────────────────────────┘
右侧抽屉（点击引用打开）：D01《费用报销管理办法》 版本 2023-01-01 · 适用：全体员工 · 替代：—
   p1 ……   p2 员工应在<mark>费用发生之日起 30 天内提交报销申请</mark>，逾期不予受理。
```

`app.js` 的主要函数（单文件约 300 行，模块化函数，不用框架）：

| 函数 | 职责 |
|---|---|
| `init()` | 调用 `/api/health` 渲染模型标识与 Mock 横幅、KB 变体下拉框；调用 `/api/cases` 填充预设用例 |
| `ask()` | 收集 `question/history/kb/faults/max_steps/mock`，调用 `streamNdjson('/api/ask/stream', body, onEvent)` |
| `streamNdjson(url, body, onEvent)` | `fetch` POST → `res.body.getReader()` → `TextDecoder` 累积缓冲 → 按 `\n` 切分 → `JSON.parse` → 回调 |
| `renderStep(ev)` | 往时间线追加一张步骤卡，更新步数进度条；`ok=false` 或被拒时标红 |
| `renderFinal(result)` | 渲染状态徽章、回答、冲突表（含裁决依据引用）、引用标签、缺口、追问；`clarify_options` 渲染成按钮；把 `{user, assistant: answer + "\n" + clarifying_question}` 追加到 `state.history`（带上追问，下一轮模型才知道自己问过什么） |
| `pickOption(text)` | 澄清按钮的点击回调：把 `text` 填入输入框并调用 `ask()`；新一轮开始后，旧按钮全部禁用 |
| `openDoc(variant, docId, quote)` | 调用 `/api/kb/{variant}/docs/{doc_id}`，渲染段落并高亮 `quote` |
| `applyCase(c)` | 把预设用例的 question、history、kb、faults、max_steps 填入表单 |
| `exportTrace()` | 把最近一次 `result` 下载为 `trace-<run_id>.json` |

前端安全：所有文本都用 `textContent` 或 `createElement` 插入，**不用 `innerHTML` 拼接**，避免 XSS（澄清按钮文字来自模型，同样走 `textContent`）。只有 `<mark>` 高亮通过拆分文本节点实现。

会话状态：`state.history` 保存在内存中，"新会话"按钮清空。**后端无状态**，每次请求都携带 history，便于测试和复现。

### 6.4 前后端对接时序

```text
Browser                     FastAPI                     run_agent              LLM API            ToolBox/KB
  │ POST /api/ask/stream      │                            │                      │                    │
  │──────────────────────────▶│ AskRequest 校验             │                      │                    │
  │                           │ make_provider / load_kb    │                      │                    │
  │                           │ StreamingResponse(gen) ───▶│                      │                    │
  │◀── run_started ───────────│◀───────────────────────────│ chat(messages,tools)─▶│                    │
  │                           │                            │◀── tool_call search ─│                    │
  │                           │                            │ execute ─────────────────────────────────▶│
  │◀── step #1 ───────────────│◀───────────────────────────│◀──────────────── observation ────────────│
  │   …（循环，直到 submit 被接受 / 预算耗尽 / 模型异常）……                                                  │
  │◀── final(AskResponse) ────│◀───────────────────────────│ 写 runs/*.jsonl       │                    │
  │ renderFinal + 追加 history │                            │                      │                    │
  │ 点击引用 → GET /api/kb/{v}/docs/{id} → 抽屉高亮                                                         │
```

实现要点：

- `run_agent` 是**同步生成器**。`StreamingResponse` 接受同步迭代器，Starlette 会在线程池中迭代它，不阻塞事件循环。因此整个项目**不需要 async 和 pytest-asyncio**。
- `/api/ask` 和 `/api/ask/stream` 共用同一个生成器：前者消费完整个生成器后返回 `final.result`。
- 每个请求独立创建 `ToolBox`、`EvidenceLedger` 和 `FaultInjector`，请求之间没有共享的可变状态；只有 KB 缓存是共享的，且只读并加锁。

---

## 7. 目录结构与文件变更（全部为新建）

```text
.
├── README.md                     # 环境、安装、运行、评审 5 分钟路径
├── T3_plan.md                    # 本方案
├── pyproject.toml                # 项目元数据、依赖、pytest 配置
├── requirements.txt              # pip 用户的固定版本依赖
├── .python-version               # 3.12
├── .env.example
├── .gitignore                    # .venv/ .env runs/ __pycache__/ .pytest_cache/
├── src/kbqa/
│   ├── __init__.py
│   ├── config.py                 # Settings、load_settings()
│   ├── kb.py                     # 文档模型、加载、变体、热加载
│   ├── retrieval.py              # tokenize()、BM25Index（封装 rank_bm25.BM25Okapi + 命中阈值）
│   ├── tools.py                  # TOOL_SCHEMAS、EvidenceLedger、FaultInjector、ToolBox
│   ├── guard.py                  # verify_submission()、extract_numbers()
│   ├── llm.py                    # Provider 协议、OpenAICompatProvider、MockProvider、make_provider()
│   ├── prompts.py                # SYSTEM_PROMPT、NUDGE_MESSAGE、build_messages()
│   ├── agent.py                  # run_agent()、run_to_result()
│   ├── trace.py                  # summarize_observation()、TraceWriter
│   ├── schemas.py                # AskRequest、AskResponse、Citation、Conflict、StepEvent
│   └── api.py                    # FastAPI app 与路由、静态托管
├── web/{index.html, app.js, style.css}
├── data/
│   ├── kb/docs/D01.md … D08.md
│   ├── kb/extra/{D02_scoped.md, D05_no_supersede.md}
│   ├── kb/variants.json
│   └── eval_cases.json
├── scripts/run_eval.py
├── tests/{conftest.py, test_retrieval.py, test_kb.py, test_tools.py, test_guard.py, test_agent.py, test_api.py}
├── examples/                     # 评测脚本生成，提交入库
│   ├── cases/<case_id>/{input.json, output.json, trace.jsonl}
│   ├── perturb/<case_id>/{diff.json, output.json, trace.jsonl}   # --perturb 产出
│   ├── eval_report.md
│   └── pytest_output.txt
└── docs/{01-requirements.md … 05-retrospective.md}
```

### 逐文件说明

| 文件 | 关键符号 | 职责与要点 | 交互 |
|---|---|---|---|
| `pyproject.toml`（必需） | `[project]`、`[tool.pytest.ini_options]` | `requires-python=">=3.11"`；依赖 `fastapi==0.162.0`、`uvicorn==0.54.0`、`httpx==0.28.1`、`python-dotenv==1.2.4`、`rank-bm25==0.2.2`（numpy 由它传递引入，不单独固定，3.11/3.12 各自解析到有 wheel 的版本）；dev 依赖 `pytest==9.2.0`；`pythonpath=["src"]`、`testpaths=["tests"]` | pytest 据此找到 `kbqa` |
| `requirements.txt`（必需） | — | 与上面相同的固定版本（含 pytest），供 `uv pip install -r` 或 `pip install -r` 使用 | README 安装步骤 |
| `.env.example`（必需） | — | `LLM_BASE_URL=https://api.deepseek.com`、`LLM_API_KEY=`、`LLM_MODEL=deepseek-chat`、`LLM_TIMEOUT=60`、`AGENT_MAX_STEPS=10`、`TRACE_DIR=runs`；注释说明"留空 Key 即进入离线 Mock"，并列出通义、OpenAI 的 base_url 示例 | `config.py` |
| `src/kbqa/config.py`（必需） | `Settings`（frozen dataclass）、`load_settings()`、`REPO_ROOT` | `load_dotenv()` 后读取环境变量；`REPO_ROOT = Path(__file__).resolve().parents[2]`；`KB_ROOT`、`WEB_DIR`、`CASES_PATH` 由它派生 | 所有模块的路径和配置来源 |
| `src/kbqa/kb.py`（必需） | `Paragraph`、`Document`、`KnowledgeBase(docs, index)`、`.with_text(para_id, new_text)`、`parse_doc(path)`、`list_variants()`、`load_kb(variant)` | 解析 front matter 和段落；按 variants.json 组合 exclude/extra（同 id 覆盖）；mtime 缓存加锁；未知变体抛 `KeyError` | 被 `tools.py`、`api.py` 使用；内部构建 `BM25Index` |
| `src/kbqa/retrieval.py`（必需） | `tokenize(text) -> list[str]`、`BM25Index(paragraphs)`、`.search(query, top_k) -> list[Hit]`（`Hit` 含 `matched_terms`） | §5.7 的分词、`rank_bm25.BM25Okapi` 打分和命中阈值 | 被 `kb.py` 构建，被 `ToolBox.search_docs` 调用 |
| `src/kbqa/tools.py`（必需） | `TOOL_SCHEMAS`、`EvidenceLedger`（`add`/`get`/`para_ids`）、`FaultInjector(faults)`（`.check(tool) -> error|None`）、`ToolBox(kb, ledger, faults, question, history)`、`.execute(name, raw_args, remaining)` | 解析 JSON 参数，非法时返回 `bad_arguments`；未知工具返回 `unknown_tool`；故障注入优先于执行；`submit_answer` 调用 `guard.verify_submission` | 被 `agent.py` 调用；依赖 `kb`、`guard` |
| `src/kbqa/guard.py`（必需） | `verify_submission(sub, ledger, question, history) -> tuple[bool, list[str], dict]`、`extract_numbers(text) -> set[str]`、`_norm(s)` | §5.5 全部规则；纯函数，便于测试。`extract_numbers` 同时被 `run_eval.py --perturb` 复用，保证两边对"数字"的口径一致 | 被 `ToolBox` 调用 |
| `src/kbqa/llm.py`（必需） | `ToolCall`、`LLMReply`、`LLMError`、`OpenAICompatProvider`、`MockProvider`、`make_provider(settings, force_mock)` | §5.10 | 被 `api.py` 创建，传入 `run_agent` |
| `src/kbqa/prompts.py`（必需） | `SYSTEM_PROMPT`、`NUDGE_MESSAGE`、`build_messages()` | §5.11 | 被 `agent.py` 使用 |
| `src/kbqa/agent.py`（必需） | `run_agent(req, provider, kb, trace_writer=None) -> Iterator[dict]`、`run_to_result(...) -> dict` | §5.3 循环；`STATUS_LABELS` 映射；最终结果组装（用账本补全引用元数据） | 被 `api.py`、`scripts/run_eval.py` 使用 |
| `src/kbqa/trace.py`（必需） | `summarize_observation(action, obs)`、`TraceWriter(dir).write(run_id, events)` | §5.12 | 被 `agent.py` 使用 |
| `src/kbqa/schemas.py`（必需） | `HistoryMsg`、`AskRequest`（含 `field_validator`）、`Citation`、`Conflict`（含 `resolution`、`basis_para_id`、`basis_quote`）、`StepEvent`、`AskResponse`（含 `clarify_options`） | §6.2 契约的唯一来源 | 被 `api.py`、`agent.py` 使用 |
| `src/kbqa/api.py`（必需） | `app`、`health()`、`ask()`、`ask_stream()`、`cases()`、`list_docs()`、`get_doc()` | §6.2；静态目录挂载放在最后 | 前端和评测脚本的唯一入口 |
| `web/*`（必需） | §6.3 函数表 | §6.3 | 只通过 §6.2 的 API 与后端交互 |
| `data/kb/*`（必需） | — | 见 §8 | `kb.py` |
| `data/eval_cases.json`（必需） | — | 见 §8.2 | `run_eval.py`、`/api/cases` |
| `scripts/run_eval.py`（必需） | `main()`、`check(case, result) -> list[CheckResult]` | 自行把 `src` 加入 `sys.path`；用 `fastapi.testclient.TestClient(app)` 走**完整 HTTP 层**调用 `/api/ask`；参数 `--mock`、`--only C01,C03`、`--out examples`、`--perturb`；写入每个用例的 input/output/trace 和 `eval_report.md`（含 §5.7 改写效果量化）；`--perturb` 见 §9；退出码等于失败用例数 | 产出 `examples/` |
| `docs/01~05`、`README.md`（必需） | — | 见 §11 | 引用 `examples/` 中的文件 |

---

## 8. 数据设计（合成数据，全部虚构）

### 8.1 知识库 `data/kb/docs/`

| doc_id | 标题 | version_date | scope | supersedes | 关键段落（实现时按此写入，措辞可微调，数字不变） |
|---|---|---|---|---|---|
| D01 | 费用报销管理办法 | 2023-01-01 | 全体员工 | — | p1 总则；p2 "第二条 报销期限：员工应在费用发生之日起 30 天内提交报销申请，逾期不予受理。"；p3 "报销须提供合规发票，单张发票金额超过 5000 元需部门负责人审批。" |
| D02 | 关于加强报销时效管理的通知 | 2024-06-01 | 未注明 | — | p1 "报销期限：各部门员工应在费用发生后 15 天内完成报销提交。"；p2 "请各部门遵照执行。" |
| D03 | 年休假管理规定 | 2024-01-01 | 全体员工 | — | p1 "正式员工累计工作满 1 年不满 10 年的，年休假 5 天；满 10 年不满 20 年的，年休假 10 天。"；p2 "试用期员工不享受带薪年休假，如需休息可申请事假。"；p3 "当年未休完的年休假最多可顺延至次年 3 月 31 日。" |
| D04 | 远程办公管理办法（2023版） | 2023-03-01 | 全体员工 | — | p1 "员工每周最多可申请 1 天远程办公，需提前一天经直属上级审批。" |
| D05 | 远程办公管理办法（2024修订） | 2024-09-01 | 全体员工 | D04 | p1 "本办法自 2024 年 9 月 1 日起施行，原《远程办公管理办法（2023版）》同时废止。"；p2 "员工每周最多可申请 2 天远程办公，需提前一天经直属上级审批。" |
| D06 | 工卡（门禁卡）管理规定 | 2024-02-01 | 全体员工 | — | p1 "工卡遗失后，员工应立即在 OA 系统「行政服务-工卡补办」提交申请。"；p2 "补办工卡收取工本费 20 元，行政部在 3 个工作日内完成制卡，员工凭工号到前台领取。" |
| D07 | 剪影星 App 会员权益 FAQ | 2024-05-01 | 产品用户 | — | p1 "免费版导出视频带有品牌水印，最高支持 1080P。"；p2 "会员可去除水印并导出 4K 视频。"；p3 "会员可在「我的-订阅管理」中随时取消自动续费，已支付周期内权益不受影响。" |
| D08 | 剪影星 App 字幕功能 FAQ | 2024-04-01 | 产品用户 | — | p1 "自动字幕支持中文、英文、日文三种语言。"；p2 "单个视频自动识别字幕的时长上限为 30 分钟。" |

D01#p2 和 D02#p1 里的"报销期限"字样不要删：检索预演显示，缺了它，"报销期限是多久？"只命中"报销"一个词项，会被命中阈值过滤掉。

`data/kb/extra/D02_scoped.md`：`doc_id: D02`，`scope: 差旅费用`，p1 为"差旅费用的报销期限为出差结束后 15 天内；其他费用仍按《费用报销管理办法》执行。"

`data/kb/extra/D05_no_supersede.md`：`doc_id: D05`，标题"关于远程办公安排的通知"，`version_date: 2024-09-01`，`scope: 全体员工`，`supersedes` 留空，只有 p1"员工每周最多可申请 2 天远程办公，需提前一天经直属上级审批。"。标题也不再写"2024修订"，避免标题本身暗示替代关系。

`data/kb/variants.json`：

```json
{
  "default":     {"description": "完整知识库（含 D01/D02 报销期限冲突）", "exclude": [], "extra": []},
  "no_conflict": {"description": "移除 D02，仅保留 D01", "exclude": ["D02"], "extra": []},
  "scoped_d02":  {"description": "D02 替换为注明仅适用差旅费用的版本", "exclude": [], "extra": ["D02_scoped.md"]},
  "no_supersede": {"description": "D05 去掉替代声明，与 D04 构成不可消解冲突", "exclude": [], "extra": ["D05_no_supersede.md"]}
}
```

- **扰动接口**（供 `--perturb` 使用）：`KnowledgeBase.with_text(para_id, new_text) -> KnowledgeBase`，返回替换了一个段落、并重建索引的新实例，原实例不变。不经过 HTTP，也不接受外部输入。

### 8.2 评测用例 `data/eval_cases.json`

用例格式：

```json
{"id": "C01_direct", "title": "明确答案", "covers": ["明确答案"],
 "request": {"question": "工卡丢了怎么补办？", "kb": "default"},
 "expect": {"status": ["answered"], "must_cite_docs": ["D06"], "answer_contains_any": ["OA", "20"]}}
```

`expect` 支持以下断言（全部为硬性检查）：`status`（允许的列表）、`must_cite_docs`、`must_not_cite_docs`、`answer_contains_any`、`answer_not_contains`、`max_citations`、`conflict_resolution`（`conflicts` 中至少有一条是该 resolution）、`min_clarify_options`。`run_eval.py` 另外会**观察并记录**（不作为判定依据）动作路径，例如 `search→search→read→submit`，以及各工具的调用次数。

| ID | 覆盖验收点 | request | expect |
|---|---|---|---|
| C01_direct | 明确答案 | "工卡丢了怎么补办？" | answered；cite D06 |
| C02_paraphrase | 改写相似问题 | "进公司刷的那张卡找不着了，咋整？" | answered；cite D06（与 C01 一致） |
| C03_conflict | 文档冲突 | "报销期限是多久？" | conflict；cite D01、D02；min_clarify_options 2 |
| C04_conflict_removed | 替换文档→动作变化 | 同 C03，kb=no_conflict | answered；cite D01；must_not_cite D02；contains "30" |
| C05_conflict_scoped | 替换文档→可消解 | 同 C03，kb=scoped_d02 | answered；cite D01、D02；contains "15" |
| C06_superseded | 可消解冲突（替代声明） | "每周可以远程办公几天？" | answered；cite D05；contains "2"；conflict_resolution resolved_by_doc |
| C07_out_of_scope | 资料外问题 | "公司明年的股价目标是多少？" | no_evidence；max_citations 0 |
| C08_followup | 上下文追问 | history 为年假问答，question "那试用期的呢？" | answered；cite D03；contains_any ["不享受", "事假"] |
| C09_tool_fail_once | 工具失败→重试成功 | 同 C01，faults.search_docs=fail_once | answered；cite D06 |
| C10_tool_fail_always | 工具失败→如实失败 | 同 C01，faults.search_docs=fail_always | tool_error 或 incomplete；max_citations 0 |
| C11_step_limit | 步数上限 | 同 C03，max_steps=2 | incomplete |
| C12_ambiguous | 追问澄清 | "这个要多久？" | need_clarification 或 no_evidence |
| C13_no_supersede | 不可消解冲突（与 C06 对照） | 同 C06，kb=no_supersede | conflict；cite D04、D05；min_clarify_options 2 |
| C14_pick_option | 点选澄清后继续 | history 为 C03 的问题 + 固定的冲突回答和追问，question "我适用《关于加强报销时效管理的通知》" | answered；cite D02；contains "15"；conflict_resolution resolved_by_user |

**两条以上执行路径的对照**（写入 `docs/03-evaluation.md`）：

| 对照组 | 控制变量 | 差异 |
|---|---|---|
| A | 同一问题 | 只改知识库：C03 / C04 / C05；C06 / C13（只差一句替代声明） |
| B | 同一问题 | 只改工具结果：C01 / C09 / C10 |
| C | 同一意图 | 只改措辞：C01 / C02 |
| D | 同一问题 | 只改引用段落里的数字：`--perturb` 前后对比（`examples/perturb/`） |

---

## 9. 测试方案（pytest，离线、确定性、不消耗 token）

`tests/conftest.py` 提供：

- `kb_default`、`kb_no_conflict`、`kb_no_supersede` fixture；
- `ScriptedProvider(script)`：`script` 是函数 `(messages) -> LLMReply`，可读取最近的工具观察后作出反应，用于验证"观察确实回传给了模型"；
- `make_reply(tool_name, **args)` 辅助函数。

### test_retrieval.py

| 场景 | 前置 / 操作 | 预期 | 目的 |
|---|---|---|---|
| bigram 分词 | `tokenize("工卡丢了怎么补办？")` | 包含 `工卡`、`补办`，不含停用 bigram `怎么`，不含标点 | 分词正确 |
| ASCII 词保留 | `tokenize("导出4K视频")` | 包含 `4K` | 英文数字整体 |
| 冲突文档同时召回 | default 检索 "报销期限是多久？" | top 结果同时包含 D01#p2 与 D02#p1 | 冲突可被发现 |
| matched_terms | 同上 | D01#p2 的 `matched_terms` 包含 `报销`、`期限`，且都在 `tokenize(query)` 中 | 命中词反馈可信 |
| no_supersede 召回 | no_supersede 检索 "每周可以远程办公几天？" | 同时包含 D04#p1 与 D05#p1 | C13 的前提成立 |
| 资料外为空 | 检索 "公司明年的股价目标是多少" | `[]` | 阈值生效（不通过则调停用表或阈值并在测试中固定） |
| 口语改写弱命中 | 检索 C02 原句 | 不含 D06，**或** D06 排名不在第一 | 记录词法检索的局限，证明改写有必要（若断言不成立，调整用例措辞） |

### test_kb.py

| 场景 | 预期 |
|---|---|
| 解析 D01 front matter 和段落 | `doc_id/title/version_date/scope` 正确，`para_id` 为 `D01#p1..p3` |
| no_conflict 变体 | 不含 D02 |
| scoped_d02 变体 | D02 的 scope 为"差旅费用"，内容来自 extra |
| no_supersede 变体 | D05 的 `supersedes` 为空，只有 1 段，原文不含"废止" |
| `with_text` | 替换 D06#p2 后，新实例的段落和检索结果都是新文本；原实例不变；未知 `para_id` 抛 `KeyError` |
| 未知变体 `../etc` | 抛 `KeyError`，不访问文件系统 |
| 热加载 | 在 `tmp_path` 构造 KB，第一次加载后修改文件并更新 mtime，再次 `load_kb` 返回新内容（通过把 `KB_ROOT` 指向 `tmp_path` 的 monkeypatch 实现） |

### test_tools.py

| 场景 | 预期 |
|---|---|
| `read_doc("D01")` | 返回 3 段；账本含 `D01#p1..p3` |
| `read_doc("D99")` | `ok=false`，`error.type="not_found"`，账本不变 |
| `search_docs` 预览 | 每条 preview ≤ 40 字；账本**不**登记（预览不可引用）；观察含 `query_terms`，每条 hit 含 `matched_terms` |
| `search_docs` 无命中 | `hits=[]`，`note` 以 `no_match` 开头，仍返回 `query_terms` |
| `fail_once` | 第一次 `ok=false`、`retryable=true`，第二次 `ok=true` |
| `fail_always` | 连续 3 次都失败 |
| 非法 JSON 参数 | `ok=false`，`error.type="bad_arguments"` |
| `remaining_steps` | 观察中的值等于传入值 |

### test_guard.py

| 场景 | 预期 |
|---|---|
| 合法 answered（quote 为已读段落子串） | accepted |
| quote 被篡改（"30 天"改成"15 天"） | rejected，错误信息含 para_id |
| 引用未读段落 | rejected，提示先 read_doc |
| answered 无引用 | rejected |
| conflict 仅 1 个 doc | rejected |
| no_evidence 带引用 | rejected |
| status=`incomplete` | rejected（白名单） |
| quote 含多余空格 | accepted（空白归一化） |
| quote 少于 4 字 | rejected |
| **数字无出处**：answer "工本费 27 元"，引用的 quote 含"20 元" | rejected，错误信息含 `27` |
| 数字来自引用 / 问题 / version_date | 三种来源各一个用例 | accepted |
| 编号不算数字 | answer 写"见 D06#p2"，其他数字都有出处 | accepted |
| `claim` 数字与段落不符 | positions 中 D02#p1 的 claim 写"30 天" | rejected |
| 数字规则不管 no_evidence | no_evidence 的 answer 含数字 | accepted |
| `resolved_by_doc` 缺依据 / 依据不在原文 | 缺 `basis_quote`；`basis_quote` 被篡改 | 均 rejected |
| `resolved_by_user` 无历史 | history 为空 | rejected |
| answered 带 unresolved 冲突 | — | rejected，提示改为 conflict |
| conflict 的澄清选项 | 0 个 / 1 个 / 5 个 / 有重复 / 单项超 30 字 | 均 rejected；2 个合法选项 accepted |
| `extract_numbers` | `"D01#p2 规定 030 天，约 1.5 周"` | `{"30", "1.5"}` |

### test_agent.py（ScriptedProvider）

| 场景 | 脚本 | 预期 |
|---|---|---|
| 正常路径 | search → read D06 → submit answered | `final.status=answered`；引用补全了 title/version_date；trace 共 3 步，`reason` 字段存在 |
| **观察驱动分叉** | 脚本读取上一条 search 结果：hits 为空就用新 query 再搜，否则 read。分别在 fail/no-hit 与 hit 条件下运行 | 两次运行动作序列不同，证明观察回传到了模型输入 |
| 校验拒绝后修正 | 第一次提交的 answer 含无出处数字，脚本读到 errors 后第二次修正 | 第一次 step `ok=false` 且摘要含"数字"，最终 answered |
| 点选后继续 | history 含上一轮冲突回答，脚本 read D02 后提交 `resolved_by_user` | answered；结果里的冲突 resolution 为 `resolved_by_user` |
| 工具失败不自动重试 | `fail_once` + 脚本在失败后直接提交 tool_error | search 只被调用 1 次（代码没有自动重试），状态 tool_error |
| 步数上限 | 脚本永远调用 search，`max_steps=3` | `status=incomplete`；`steps_used=3`；gaps 含"最大步数" |
| 无工具调用纠偏 | 第一次返回纯文本，第二次正常 | 插入了 NUDGE；trace 中有 `(no_tool_call)` 步；最终正常 |
| 多个 tool_calls 同轮 | 一次返回 2 个 read_doc | 都执行，各计 1 步 |
| LLM 异常 | provider 抛 `LLMError` | `status=failed`；事件流最后一个是 final |

### test_api.py（`TestClient`，强制 `mock=true`）

| 场景 | 预期 |
|---|---|
| `GET /api/health` | 200；含 `is_mock`、`kb_variants`；**响应文本不含** `LLM_API_KEY` 的值（monkeypatch 设一个假 key 后断言） |
| `POST /api/ask` C01 | 200；`status` 属于合法枚举；schema 完整（含 `clarify_options` 字段，Mock 下为空列表） |
| `POST /api/ask/stream` | 每一行都能 JSON 解析；第一行 `run_started`；最后一行 `final`；`final` 恰好 1 个 |
| 非法 kb、`max_steps=0`、空 question | 422 |
| `GET /api/kb/default/docs/D01` | 200，含段落；`D99` 返回 404 |
| `GET /` | 200，返回 HTML |
| `GET /api/cases` | 200，长度 ≥ 14 |

### 真实模型评测（`scripts/run_eval.py`，不在 pytest 中运行）

用真实模型跑完 C01–C14，产出 `examples/cases/*`、`examples/eval_report.md`（含改写效果量化）。失败用例**如实保留**，并在 03 文档中分析原因和改进。另跑一次 `--mock --out examples/mock`，用于展示离线流程，报告中标注"Mock 结果不代表决策能力"。

**`--perturb` 自动改文档复测**（把评审"替换文档内容，核对答案是否变化"的手工检查做成脚本）：

1. 只处理正常运行中状态为 `answered` 的用例。从它的引用里找第一个同时出现在 `answer` 里的数字 `n`（用 `guard.extract_numbers`）；找不到就跳过（如 C08 没有数字），并在报告里写明"跳过：答案无数字"。
2. 取 `m = n + 7`（例如 20 → 27、30 → 37），若 `m` 已出现在该段就继续加 7。用正则 `(?<![\d.])n(?![\d.])` 只替换该段第一处，得到 `kb.with_text(para_id, new_text)`。
3. 同一请求在新 KB 上调用 `run_to_result` 重跑（不走 HTTP，因为扰动 KB 不应对外暴露）。
4. 判定通过：状态仍为 `answered`；`m` 在新答案的数字里；`n` 不在新答案里（若 `n` 也出现在问题或其他引用段落中，则只检查 `m`）；引用仍指向被改的段落。
5. 产出 `examples/perturb/<case_id>/{diff.json, output.json, trace.jsonl}`，`eval_report.md` 增加"改文档复测"表：用例、段落、`n → m`、新旧答案摘要、是否通过。失败数计入退出码。

实现约 40 行。它的价值在于区分"从原文里读出来的答案"和"模型先验编出来的答案"：后者在改数字后仍会答旧值，且在 guard 的数字溯源下会被拦住。

---

## 10. 验证方式

```bash
# 0. 环境（一次性）
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -r requirements.txt          # 或：python3.12 -m venv .venv && pip install -r requirements.txt
cp .env.example .env                        # 填 LLM_API_KEY；留空则自动进入离线 Mock

# 1. 针对性单测（离线）
pytest -q tests/test_retrieval.py tests/test_guard.py tests/test_tools.py
pytest -q tests/test_agent.py tests/test_api.py

# 2. 全量单测并存档
pytest -q | tee examples/pytest_output.txt

# 3. 启动服务（网页 + API）
uvicorn kbqa.api:app --app-dir src --host 127.0.0.1 --port 8000
# 浏览器打开 http://127.0.0.1:8000 ；OpenAPI 文档 http://127.0.0.1:8000/docs

# 4. curl 冒烟
curl -s http://127.0.0.1:8000/api/ask -H 'content-type: application/json' \
  -d '{"question":"报销期限是多久？","kb":"default"}' | python -m json.tool
curl -sN http://127.0.0.1:8000/api/ask/stream -H 'content-type: application/json' \
  -d '{"question":"工卡丢了怎么补办？","faults":{"search_docs":"fail_once"}}'

# 5. 评测（真实模型；会写入 examples/）
python scripts/run_eval.py --out examples
python scripts/run_eval.py --out examples --perturb   # 自动改文档复测，写入 examples/perturb/
python scripts/run_eval.py --mock --out examples/mock
```

## 11. 文档要点（`docs/`）

| 文件 | 必写内容 |
|---|---|
| 01-requirements.md | 用户（员工、HR/行政知识维护者）、目标、范围与非目标、6 个验收点 → 成功标准（引用逐字可核验、冲突不擅自裁决、预算内结束） |
| 02-solution.md | §5 架构图与决策循环、工具契约、冲突三分法（含裁决依据引用）、Verify-on-Submit（含数字溯源及其中文数字限制）、检索取舍（为什么不用向量、为什么 BM25 用现成库）、前后端选型表（§6.1）、Mock 边界 |
| 03-evaluation.md | 用例表（引用 `examples/cases/*/trace.jsonl` 与 `eval_report.md`）、四组执行路径对照（§8.2）、改写效果量化、`--perturb` 复测结果、guard 拒绝统计（真实运行中被拦下的错误引用和无出处数字各几次、模型是否自行修正）、pytest 结果（引用 `examples/pytest_output.txt`）、真实失败与限制 |
| 04-ai-usage.md | 使用的 AI 工具与范围（方案、代码生成、测试草拟）、本人修改与决策点、如何验证 AI 产出（单测、评测、人工检查 trace）。另附 **AI 缺陷台账**：表格记录 AI 产出中被发现的问题——现象、发现方式（哪个测试 / 哪条 trace / 人工审查）、修复方式。已知的一条可直接写入：方案阶段检索预演发现原数据里没有"报销期限"字样，C03 会因命中阈值无结果，改了 §8.1 的数据。只写真实发生的，不凑数 |
| 05-retrospective.md | 最难问题（例如模型冲突判断不稳定、引用逐字匹配）、收获、下一步（混合检索、多次运行稳定性统计、中文数字归一、引用语义校验） |
| README.md | 一句话介绍、5 分钟评审路径（启动 → 选预设用例 C03 → 点一个澄清按钮继续 → 切换 KB 到 no_conflict 再问 → 用 C06/C13 对比替代声明 → 开启检索故障）、目录说明、模型配置、Mock 边界、**实际用时与未完成项** |

## 12. 验收标准

1. `pytest -q` 全部通过，且不需要网络和 Key。
2. 无 Key 时服务能启动，页面显示 Mock 横幅，C01 能走完整个循环并返回 `answered`。
3. 有 Key 时，`run_eval.py` 产出 14 个用例的 input/output/trace 和报告。核心用例 C01、C03、C04、C07、C08、C09、C11 必须通过；其余用例失败时如实记录并分析。`--perturb` 产出 `examples/perturb/` 和报告中的复测表。
4. 任何 `answered` 或 `conflict` 结果中，每条引用的 quote 都能在对应 `para_id` 原文中逐字找到，回答中的每个阿拉伯数字都有出处，`resolved_by_doc` 的裁决都带有原文依据（由 guard 保证，并由 test_guard 证明）。
5. C03 和 C04 的 trace 动作序列不同、状态不同；C09 和 C10 的 trace 动作序列不同、状态不同。
6. `conflict` 结果在网页上显示澄清按钮，点击后发起新一轮并带上历史（手工验证，C14 用固定历史验证后端半边）。
7. 步数达到上限时返回 `incomplete`，且事件流以 `final` 结束。
8. 仓库中没有真实 Key；`.env` 已被忽略。

## 13. 风险与边界情况

| 风险 | 影响 | 对策 |
|---|---|---|
| 模型冲突判断不稳（把 D01/D02 冲突答成 answered） | 关键缺陷 | 提示词规则 3 + 证据要求；评测如实记录；可选：`temperature=0.1` 并多次运行统计 |
| 模型不调用工具或参数 JSON 非法 | 循环卡住 | NUDGE 纠偏和 `bad_arguments` 观察都计步，最终由预算兜底 |
| 模型提前改写，C02 第一次检索就命中 | "改写路径"不出现 | 可接受：评测断言的是**结果一致性**；改写行为单独观察记录；可用 C08 的历史补全作为改写证据 |
| 逐字校验对全角半角和标点敏感 | 合法引用被拒 | 只做空白归一化，并提示模型逐字复制；被拒后模型可自行修正 |
| 词法检索噪声（如"年的"误命中） | 资料外问题出现误召回 | 停用 bigram + 命中阈值，并用 test_retrieval 固定行为 |
| 流式响应被缓冲 | 时间线不实时 | 本地直连无代理；设置 no-cache 和 X-Accel-Buffering 响应头 |
| Guard 只能校验"引用存在 + 数字有出处"，不能校验非数字的语义支持（如"不享受"改成"享受"） | 语义层面的漏判 | 数字溯源已覆盖制度问答里最常见的错误（天数、金额）；其余列为已知限制（03/05） |
| 数字溯源误拒（模型自行换算，如"2 天"推出"每月约 8 天"） | 合理回答被拒，多耗步数 | 提示词要求不自行换算；拒绝信息写明数字便于修正；max_steps 默认 10 留余量；03 统计误拒次数 |
| 模型不生成或生成不合规的 `clarify_options` | conflict 提交被拒 | 拒绝信息说明格式要求，由模型修正；按钮只是快捷输入，用户仍可自由输入 |
| Python 3.15 缺少 wheel | 安装失败 | 固定 3.12，README 写明 |
| 并发请求 | 状态串扰 | 每请求独立 ToolBox；KB 缓存只读并加锁 |

## 14. 实施排期（按 3 小时压缩）

| 时段 | 内容 | 产出 |
|---|---|---|
| 0:00–0:20 | 脚手架、配置、数据（D01–D08、两个 extra、变体、C01–C14） | 可加载的 KB |
| 0:20–0:40 | retrieval、kb 及其单测 | 检索可用 |
| 0:40–1:15 | tools、guard、llm、prompts、agent 及其单测 | 核心循环 Mock 跑通 |
| 1:15–1:35 | api、schemas、test_api | HTTP 可用 |
| 1:35–2:10 | web 三件套 | 网页可演示 |
| 2:10–2:35 | 接真实模型，跑 run_eval（含 `--perturb`），调提示词 | examples/ |
| 2:35–3:00 | docs 01–05、README、git 推送 | 提交 SHA |

**可裁剪项**（时间不够时按顺序裁掉）：C12 → 澄清按钮的前端渲染（后端仍返回 `clarify_options`，用户手动输入）→ 原文抽屉高亮（改为纯文本展示）→ `runs/` 持久化 → Mock 评测目录 → `--perturb`。
**不可裁剪项**：Verify-on-Submit（含数字溯源和裁决依据）、步数上限、故障注入、KB 变体（含 no_supersede）、真实模型 trace。

## 15. 实现备注

- 回写 OpenAI 协议的 assistant 消息时，必须原样保留 `tool_calls`，每个 `tool_call_id` 都要有对应的 tool 消息，否则下一次请求会报 400。循环提前结束时不受影响。
- DeepSeek 使用 `deepseek-chat`（支持 function calling）；`deepseek-reasoner` 对 tools 的支持有限，不要使用。
- 静态文件挂载 `app.mount("/", StaticFiles(directory=WEB_DIR, html=True))` 必须写在所有 `/api` 路由之后。
- `run_eval.py` 通过 `TestClient` 调用，覆盖了 HTTP 层且不需要先启动服务。
- 所有面向用户的 `status_label` 映射只在后端 `agent.STATUS_LABELS` 定义，前端直接显示。

## 16. 未解决问题

1. **模型与 Key**：使用哪家模型（默认按 DeepSeek `deepseek-chat` 设计，切换只需改 `.env` 三个变量）？Key 由谁提供？没有 Key 时只能交付 Mock 运行记录，达不到"真实模型决策"的验收要求。
2. **剩余作答时间**：决定 §14 的裁剪程度。
3. **GitHub 仓库**：公开还是私有？如果私有，需要添加评审账号（题面未给出账号名）。
