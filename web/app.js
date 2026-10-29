const $ = (id) => document.getElementById(id);
const state = { history: [], lastResult: null, cases: [], asking: false };

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text; // 不用 innerHTML，防 XSS（含模型返回的按钮文字）
  if (cls) e.className = cls;
  return e;
}

async function init() {
  const [health, cases] = await Promise.all([
    fetch("/api/health").then(r => r.json()),
    fetch("/api/cases").then(r => r.json()),
  ]);
  $("model-badge").textContent = `${health.model} · ${health.is_mock ? "Mock" : "真实模型"}`;
  $("mock-banner").hidden = !health.is_mock;
  $("max-steps").value = health.default_max_steps;
  for (const v of health.kb_variants)
    $("kb-select").append(new Option(`${v.name} — ${v.description}`, v.name));
  state.cases = cases;
  for (const c of cases) $("case-select").append(new Option(`${c.id} ${c.title}`, c.id));
  $("case-select").onchange = () => {
    const c = state.cases.find(x => x.id === $("case-select").value);
    if (c) applyCase(c);
  };
  $("ask-btn").onclick = ask;
  $("question").addEventListener("keydown", e => { if (e.key === "Enter") ask(); });
  $("export-btn").onclick = exportTrace;
  $("reset-btn").onclick = () => { state.history = []; $("chat").innerHTML = ""; $("timeline").innerHTML = ""; $("steps-bar").textContent = ""; };
  $("drawer-close").onclick = () => $("drawer").hidden = true;
}

function applyCase(c) {
  const r = c.request;
  $("question").value = r.question || "";
  if (r.kb) $("kb-select").value = r.kb;
  if (r.max_steps) $("max-steps").value = r.max_steps;
  const f = r.faults || {};
  $("fault-select").value =
    f.search_docs === "fail_once" ? "search_once" :
    f.search_docs === "fail_always" ? "search_always" :
    f.read_doc === "fail_once" ? "read_once" : "";
  state.history = (r.history || []).map(m => ({ role: m.role, content: m.content }));
  $("chat").innerHTML = "";
  for (const m of state.history) addMsg(m.role, m.content);
  addMsg("system", `已载入用例 ${c.id}（${c.title}），点击"提问"运行`);
}

function faultsFromUI() {
  const v = $("fault-select").value;
  return v === "search_once" ? { search_docs: "fail_once" }
       : v === "search_always" ? { search_docs: "fail_always" }
       : v === "read_once" ? { read_doc: "fail_once" } : {};
}

function addMsg(role, textOrNode, cls) {
  const wrap = el("div", null, `msg ${role}`);
  wrap.append(el("div", role === "user" ? "你" : role === "system" ? "系统" : "Agent", "role"));
  const bubble = el("div", null, "bubble");
  if (typeof textOrNode === "string") bubble.append(textOrNode); else bubble.append(textOrNode);
  wrap.append(bubble);
  $("chat").append(wrap);
  $("chat").scrollTop = $("chat").scrollHeight;
  return bubble;
}

async function ask() {
  const question = $("question").value.trim();
  if (!question || state.asking) return;
  state.asking = true;
  $("ask-btn").disabled = true;
  addMsg("user", question);
  state.history.push({ role: "user", content: question });
  $("question").value = "";
  $("timeline").innerHTML = "";
  $("steps-bar").textContent = "";
  document.querySelectorAll(".opt-btn").forEach(b => b.disabled = true);

  const body = {
    question,
    history: state.history.slice(0, -1), // 当前问题在 question 字段，历史不含它
    kb: $("kb-select").value,
    max_steps: parseInt($("max-steps").value, 10) || 10,
    faults: faultsFromUI(),
    mock: $("force-mock").checked,
  };

  try {
    await streamNdjson("/api/ask/stream", body, (ev) => {
      if (ev.type === "step") renderStep(ev);
      if (ev.type === "run_started") {
        $("steps-bar").textContent = `0/${ev.max_steps}` + (ev.provider.is_mock ? " · Mock" : "");
      }
      if (ev.type === "final") renderFinal(ev.result);
    });
  } catch (e) {
    addMsg("system", `请求失败：${e.message}`);
  } finally {
    state.asking = false;
    $("ask-btn").disabled = false;
  }
}

async function streamNdjson(url, body, onEvent) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) { onEvent({ type: "final", result: { status: "failed", status_label: "请求失败", answer: `HTTP ${res.status}`, citations: [], conflicts: [], gaps: [], clarify_options: [], trace: [], steps_used: 0 } }); return; }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (line) onEvent(JSON.parse(line));
    }
  }
}

function renderStep(ev) {
  const li = el("li", null, ev.ok ? "" : "bad");
  li.append(el("span", `${ev.action} `));
  const args = Object.entries(ev.args || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(" ");
  if (args) li.append(el("span", args, "args"));
  li.append(el("div", `依据：${ev.reason || "—"}`));
  li.append(el("div", `→ ${ev.observation_summary}${ev.ok ? "" : " ✗"}`, "obs"));
  $("timeline").append(li);
  $("timeline").scrollTop = $("timeline").scrollHeight;
  $("steps-bar").textContent = $("steps-bar").textContent.replace(/^\d+/, String(ev.step));
}

function pickOption(text) {
  $("question").value = text;
  ask();
}

function renderFinal(r) {
  state.lastResult = r;
  $("export-btn").disabled = false;
  const frag = document.createDocumentFragment();
  const head = el("div");
  head.append(el("span", r.status_label || r.status, `status-chip status-${r.status}`));
  frag.append(head);
  if (r.answer) frag.append(el("p", r.answer));

  if (r.conflicts && r.conflicts.length) {
    const tbl = el("table", null, "conflict-tbl");
    const headRow = el("tr");
    headRow.append(el("th", "文档"), el("th", "主张"));
    tbl.append(headRow);
    for (const cf of r.conflicts) {
      for (const p of cf.positions || []) {
        const row = el("tr");
        row.append(el("td", p.para_id), el("td", p.claim));
        tbl.append(row);
      }
      if (cf.resolution !== "unresolved" && cf.basis_quote)
        frag.append(el("div", `裁决依据（${cf.resolution}）：${cf.basis_para_id}「${cf.basis_quote}」`, "gaps"));
      else if (cf.basis)
        frag.append(el("div", `裁决说明：${cf.basis}`, "gaps"));
    }
    frag.append(tbl);
  }

  for (const c of r.citations || []) {
    const tag = el("span", `${c.doc_id}${c.para_id ? "#" + c.para_id.split("#")[1] : ""}`, "cite-tag");
    tag.title = `${c.title} ${c.version_date}`;
    tag.onclick = () => openDoc(r.kb, c.doc_id, c.quote);
    frag.append(tag);
  }
  if (r.gaps && r.gaps.length) frag.append(el("div", `资料缺口：${r.gaps.join("；")}`, "gaps"));
  if (r.clarifying_question) frag.append(el("p", `追问：${r.clarifying_question}`));
  for (const opt of r.clarify_options || []) {
    const b = el("button", opt, "opt-btn");
    b.onclick = () => pickOption(opt);
    frag.append(b);
  }
  frag.append(el("div", `步骤 ${r.steps_used}/${r.max_steps} · ${r.elapsed_ms}ms · ${r.provider.is_mock ? "Mock" : r.provider.model}`, "gaps"));
  addMsg("agent", frag);

  // 历史追加：带上追问，下一轮模型才知道自己问过什么
  let hist = r.answer || "";
  if (r.clarifying_question) hist += `\n${r.clarifying_question}`;
  if (!hist) hist = r.status_label;
  state.history.push({ role: "assistant", content: hist });
}

async function openDoc(variant, docId, quote) {
  const d = await fetch(`/api/kb/${variant}/docs/${docId}`).then(r => r.json());
  $("drawer").hidden = false;
  $("drawer-title").textContent = `${d.doc_id}《${d.title}》`;
  $("drawer-meta").textContent = `版本 ${d.version_date} · 适用：${d.scope || "未注明"} · 替代：${d.supersedes || "—"}`;
  const body = $("drawer-body");
  body.innerHTML = "";
  for (const p of d.paragraphs) {
    const div = el("div", null, "para");
    div.append(el("span", p.para_id, "pid"));
    // <mark> 高亮只通过拆分文本节点实现
    const text = p.text, q = quote || "";
    const idx = q ? text.indexOf(q.slice(0, 20)) : -1;
    if (idx >= 0) {
      div.append(text.slice(0, idx));
      div.append(el("mark", text.slice(idx, idx + q.length)));
      div.append(text.slice(idx + q.length));
    } else {
      div.append(text);
    }
    body.append(div);
  }
}

function exportTrace() {
  if (!state.lastResult) return;
  const blob = new Blob([JSON.stringify(state.lastResult, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `trace-${state.lastResult.run_id}.json`;
  a.click();
}

init();
