# 评测报告

- 用例数：14；通过 14，失败 0
- 模式：真实模型

## 用例结果

| 用例 | 状态 | 步数 | 引用文档 | 改写次数 | 结果 |
|---|---|---|---|---|---|
| C01_direct | answered | 3 | D06 | 0 | ✓ |
| C02_paraphrase | answered | 4 | D06 | 1 | ✓ |
| C03_conflict | conflict | 4 | D01、D02 | 0 | ✓ |
| C04_conflict_removed | answered | 4 | D01 | 0 | ✓ |
| C05_conflict_scoped | answered | 5 | D01、D02 | 0 | ✓ |
| C06_superseded | answered | 5 | D05 | 0 | ✓ |
| C07_out_of_scope | no_evidence | 4 | — | 2 | ✓ |
| C08_followup | answered | 5 | D03 | 0 | ✓ |
| C09_tool_fail_once | answered | 5 | D06 | 1 | ✓ |
| C10_tool_fail_always | tool_error | 4 | — | 0 | ✓ |
| C11_step_limit | incomplete | 2 | — | 0 | ✓ |
| C12_ambiguous | need_clarification | 2 | — | 0 | ✓ |
| C13_no_supersede | conflict | 4 | D04、D05 | 0 | ✓ |
| C14_pick_option | answered | 4 | D02 | 0 | ✓ |

## 检索改写效果（只记录）

| 用例 | 检索次数 | 首次命中 | 最终命中 | 改写次数 | 查询序列 |
|---|---|---|---|---|---|
| C01_direct | 1 | 是 | 是 | 0 | 工卡补办 |
| C02_paraphrase | 2 | 是 | 是 | 1 | 门禁卡丢失补办 → 员工工卡挂失补办流程 |
| C03_conflict | 1 | 是 | 是 | 0 | 报销期限 |
| C04_conflict_removed | 1 | 是 | 是 | 0 | 报销期限 |
| C05_conflict_scoped | 1 | 是 | 是 | 0 | 报销期限 |
| C06_superseded | 1 | 是 | 是 | 0 | 居家办公 申请 审批 |
| C07_out_of_scope | 3 | 否 | 否 | 2 | 股价目标 → 年度经营目标 业绩指标 → 市值管理 股票信息披露 |
| C08_followup | 1 | 是 | 是 | 0 | 员工手册 试用期 假期 |
| C09_tool_fail_once | 2 | 是 | 是 | 1 | 工卡遗失 挂失 补办流程 → 门禁卡 工本费 制卡 |
| C11_step_limit | 1 | 否 | 否 | 0 | 报销期限 |
| C12_ambiguous | 1 | 否 | 否 | 0 | 办理时限 多久 时长 |
| C13_no_supersede | 1 | 是 | 是 | 0 | 远程办公 |

改写挽回的用例（首次未命中、最终命中）：无

## 改文档复测（--perturb）

| 用例 | 段落 | 数字改动 | 新答案摘要 | 结果 |
|---|---|---|---|---|
| C01_direct | D06#p2 | 20 → 27 | 工卡遗失后，请立即在 OA 系统「行政服务-工卡补办」提交补办申请。补办需缴纳工 | ✓ 通过 |
| C02_paraphrase | D06#p2 | 20 → 27 | 按《工卡（门禁卡）管理规定》：工卡遗失后应立即在 OA 系统「行政服务-工卡补办 | ✓ 通过 |
| C04_conflict_removed | D01#p2 | 30 → 37 | 根据《费用报销管理办法》（2023-01-01，适用全体员工）：员工应在费用发生 | ✓ 通过 |
| C05_conflict_scoped | D02#p1 | 15 → 22 | 报销期限分两种情形：差旅费用需在出差结束后 22 天内提交报销申请；其他费用需在 | ✓ 通过 |
| C06_superseded | D05#p2 | 2 → 9 | 按现行《远程办公管理办法（2024修订）》，员工每周最多可申请 9 天远程办公， | ✓ 通过 |
| — | — | — | — | 跳过：答案无可用数字 |
| C09_tool_fail_once | D06#p2 | 20 → 27 | 工卡遗失后请立即在 OA 系统「行政服务-工卡补办」提交申请。补办收取工本费 2 | ✓ 通过 |
| C14_pick_option | D02#p1 | 15 → 22 | 按您适用的《关于加强报销时效管理的通知》，报销期限为：各部门员工应在费用发生后  | ✓ 通过 |
