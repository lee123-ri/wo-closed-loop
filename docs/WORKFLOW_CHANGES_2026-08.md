# 软工单平台 · 三条流程改造设计方案（2026-08-21）

> 状态：**方案稿（只出方案，不动代码）** —— 待业务/开发评审后按「七、实施顺序」落地。
> 关联：基线需求见 [[../.claude/projects/-Users-lee-Documents-work-wo-closed-loop/memory/wo-workflow-2026-08-spec]]；OA 联动联调断点见 memory `dingtalk-oa-integration-gap`。

---

## 0. 结论与前置依赖（先读这段）

三条需求 + 评审已拍板的三个决策：

| # | 需求 | 决策 |
|---|---|---|
| 1 | 异常指标来源：AI表格→异常指标工单→荣的agent解析→PMO确认/补充/删除/发单→措施工单走闭环 | 保留导出/导入桥接，仅补 PMO 操作缺口 |
| 2 | 其他类型：成单→发起人发OA→责任人回填原因+附件→审批人检闭环条件，不满足退回重填 | **系统级退回（新状态 `returned`）+ 重新发起一张新 OA** |
| 3 | 不发现场：判断是否必要发到现场，不必要则删除关闭并记原因，存入异常指标 AITable 新建 table | **Agent 自动判（`no_action_needed`）+ PMO 确认**；关闭原因写 AITable 新表 |

**⚠️ 前置依赖（最重要的一条）**：第 2 点依赖的「完整版 OA 联动」目前**不在当前分支** `feature/wo-judgment-measure`，而在另一个**未合入分支 `feat/dingtalk-oa-role-flow`**（commit `ad712aa`）。该分支实现了：

- `services/roles.py::resolve_oa_chain` —— 角色审批链 → 具体审批人（stage：approve/execute/accept）
- `services/dingtalk.py::create_oa_approval(chain)` 填 `approvers` + `terminate_oa_approval`
- `work_orders.oa_progress`（JSONB）逐节点推进 + 闭环回写「执行结论/执行附件」（`_sync_oa_results`）

当前分支的 `api/dingtalk.py::oa_callback` 仍是无 `oa_progress` 的简化版（`refuse→rejected` 终态）。

**做第 2 点前必须先合入 `feat/dingtalk-oa-role-flow`**，否则「退回重填」无从谈起。第 3 点**不依赖**它，可先行独立实施。

---

## 1. 第 3 点：不发现场关闭 + 记原因入 AITable 新表（可独立实施）

### 1.1 流程定义

```
异常指标工单（alert，status=judging）
   └─ 荣的agent 判定 verdict ∈ {approved_suggested, approved_as_is, rejected, no_action_needed}
        ├─ no_action_needed → 工单 judgment_status=no_action_needed，PMO 看到「建议不发现场」
        └─ 其它 → 正常走措施工单闭环
   └─ PMO 确认环节：点「不发现场并关闭」→ 弹窗必填「关闭原因」→ 提交
        → 工单 status=closed（软关闭，不物理删）+ conclusion/关闭原因落库 + 写 AITable 新表
```

要点：
- **软关闭而非物理删除**：工单保留在列表（`status=closed`），`StatusLog` 留痕，可追溯审计。物理删会丢失溯源与统计。
- **PMO 可主动判**：即使 Agent 没判（或判了要发），PMO 也能在确认环节手点「不发现场并关闭」——只要填原因即可。
- 关闭原因双写：本地 DB（`StatusLog.note` + 工单字段）+ AITable 新表（业务要的台账）。

### 1.2 AITable 新表设计

- **Base**：`ANOMALY_BASE = OG9lyrgJPzMw9B5jSvpyvdQLWzN67Mw4`（数据池-异常指标，见 `services/aitable.py:10`）
- **表名**：`不发现场关闭台账`（建议）
- **字段**（`dws aitable table create` 建表时一并带，单次 ≤15 个）：

| 字段名 | 类型 | config | 说明 |
|---|---|---|---|
| 标题 | primaryDoc（首列） | — | 自动生成：`{项目}-{异常指标}-不发现场` |
| 工单编号 | text | — | `RW-2026-xxxx` |
| 项目名称 | text | — | 工单关联项目 |
| 异常指标 | text | — | 取 `pool.raw_data.anomaly_type` |
| 异常月份 | text | — | 取 `pool.raw_data.month` |
| 关闭原因 | text | — | PMO 填写的必填原因 |
| 判断来源 | singleSelect | `[{name:"agent_no_action"},{name:"pmo_manual"}]` | Agent 建议 / PMO 主动 |
| 操作人 | text | — | 当前 PMO 姓名 |
| 操作时间 | date | `{"formatter":"YYYY-MM-DD HH:mm"}` | 关闭时间 |

> 建表后把返回的 `tableId` 落库（`config_definitions`，category=`aitable`，code=`no_dispatch_table_id`，extra 存 tableId）。每次写入前用 `dws aitable resolve-table` 按名兜底，避免 tableId 过期。

### 1.3 后端改动清单

1. **`services/aitable.py`** 新增两个写函数：
   - `ensure_no_dispatch_table() -> table_id`：幂等建表（`table create` 附带字段；已存在则 `resolve-table` 复用），并把 tableId 写 `config_definitions`。
   - `write_no_dispatch_record(wo, pool, reason, operator) -> bool`：`record create` 写入新表；返回是否成功。
2. **`models/workorder.py`** 新增字段：
   - `no_dispatch_reason: Text|None`（关闭原因落库副本，AITable 写失败时兜底）
   - `no_dispatch_synced: bool`（默认 False，AITable 写成功置 True，供定时补偿扫描）
   - `closed_without_dispatch: bool`（默认 False，标记这条是「不发现场关闭」，前端/统计可筛）
   （可选：复用 `conclusion` 存原因，不必加字段；但独立字段更清晰，推荐新增。）
3. **`api/workorders.py`** 新增接口：
   - `POST /work-orders/{id}/close-no-dispatch`，body `{reason: str}`：校验（来源为 alert、状态在 judging/pending/approving 之一、reason 非空）→ 写 `StatusLog(note="不发现场关闭："+reason)`、`status=closed`、`completed_date`、`conclusion=reason`、`no_dispatch_*` 字段 → 调 `write_no_dispatch_record` → 成功置 `no_dispatch_synced=True`，失败保持 False（不阻断关闭）。
4. **补偿**：`tasks.py` 增一个周期任务（或搭现有 beat）扫描 `closed_without_dispatch=True AND no_dispatch_synced=False AND no_dispatch_reason is not None` 的工单，重试 `write_no_dispatch_record`。理由：AITable 写失败不应影响工单关闭，但要保证台账最终一致。

### 1.4 数据来源（关键字段从哪拿）

关闭时按 `wo.parent_pool_id` 取 `DataPoolItem`，其 `raw_data` 里已有可读键（`sync_anomaly_to_pool` 写入）：
- `anomaly_type`（异常指标）、`month`（异常月份）、`region`、`project_name`（data_pool 的 `project_name` 列）
- 项目优先用 `wo` 关联的 `Project.name`，异常指标/月份用 `pool.raw_data`。

### 1.5 风险与前提

- **AITable 写权限**：现在 `aitable.py` 只读（`dws aitable record query`）。写 `record create`/`table create` 要求当前 `dws` 登录账号对 `ANOMALY_BASE` 是**编辑者/所有者**。**需先确认账号权限**——否则建表/写记录会失败，需由 AITable owner 授权。
- **建表幂等**：`table create` 重名会自动续号「原名 1」，故必须 `resolve-table` 按名查再用，不能每次建。
- **软关闭对 SLA/统计的影响**：`closed` 会被 `list_closed` 归档并计入耗时；`closed_without_dispatch` 标记保证可从「正常闭环」里筛出来。
- 名词口径：本点按「异常指标（alert）来源」工单设计。若「异常原因」指 `PLAN_BASE`（异常原因表/非EAM）那类工单，新表应建在 `PLAN_BASE`，字段几乎一致——实施时确认一下口径即可。

---

## 2. 第 2 点：其他类型工单 OA 闭环（**依赖 feat/dingtalk-oa-role-flow 先合入**）

### 2.1 目标流程 vs 现状

目标：`成单 → 发起人发OA → 责任人(执行人)在钉钉OA表单回填【根因+附件】 → 审批人(验收)节点检验闭环条件 → 不满足退回责任人重填再提交 / 满足闭环`

现状（`feat/dingtalk-oa-role-flow` 已是「审批→执行→验收确认」3 节点，闭环回写执行结论/附件）的差距只有两处：

1. **责任人回填「根因」**：钉钉表单目前执行人节点只有「执行结论」「执行附件」，没有独立的「根因分析」字段。
2. **退回重填**：现在 `refuse→rejected`（终态）。钉钉审批实例一旦拒绝就结束，**不能原地改稿重提**。

### 2.2 责任人回填原因 + 附件

- **钉钉 OA 模板**补一个字段「根因分析」（文本，节点 2 执行人必填/选填视业务）；
- **`api/dingtalk.py::_sync_oa_results`** 扩展：闭环时除 `执行结论→conclusion`、`执行附件→attachments` 外，把 `根因分析→wo.backfill_reason`（并回传 `DataPoolItem.backfill_reason`），`backfill_status=filled`、`backfilled_at` 置时间。

### 2.3 退回重填（系统级 `returned` + 重发起 OA）

钉钉无法「原地改稿」，采用「平台重填 → 重新发起一张新 OA 实例」：

1. **新状态 `returned`（退回重填）**：审批人节点（stage=accept 的验收确认）`refuse` → 工单 `status=returned`（**不再直接 `rejected`**），`StatusLog` 记录拒绝原因（从回调 `formComponentValues` 里取审批人填的「驳回意见」）。
   - 仅验收节点退回给责任人重填；节点 1（确认派发）驳回仍走 `rejected`（派发前退回无意义）。
2. **平台重填**：责任人在平台侧编辑「根因/附件」→ 调 `POST /work-orders/{id}/resubmit`：
   - 先 `terminate_oa_approval(wo.oa_id)` 终止旧实例（`feat` 分支已有）；
   - 清空 `wo.oa_progress`、`oa_id`，`status=approving`（或按角色链回到对应阶段）；
   - `create_oa_approval(chain=resolve_oa_chain(...))` 发起**新**实例，回填新 `oa_id`；
   - `StatusLog` 记「退回重填后重新发起OA」。
3. **闭环条件校验**：审批人验收节点看到的「是否具备闭环条件」= 执行结论非空 + 附件≥1（是否必填可配，见 §4 `config_definitions` 提建议值）。满足才 agree→closed；不满足则 refuse→returned。
   - 校验本身由审批人人工判断（钉钉 OA 无服务端脚本节点，本系统只做辅助：`oa/check` 兜底时把「缺附件/缺结论」标黄提示，不强行拦截）。

### 2.4 状态机扩展（`config_definitions` + `transition`）

- 状态枚举加 `returned`（颜色配条可审的）；`transition` 动作表加：
  - `return`：`{"accept"阶段被拒}` 触发，目标 `returned`
  - `resubmit`：`{"returned"}` → `approving`（并重发 OA）
- `api/dingtalk.py::oa_callback` 的 `refuse` 分支改为：按 `_compute_status`/`oa_progress` 判断是「验收节点」还是「派发节点」，分别 `returned` / `rejected`。

### 2.5 待业务确认的细则

- 「闭环条件」到底由哪几项组成？（附件是否必填？结论是否必填？需不需要验收报告？）
- 退回次数上限？（无限重填会拖死 SLA，建议最多 2 次，超次升级）
- 退回后 SLA/截止日期是否顺延？（建议按重提时间重新起算，或顺延固定 N 小时）

---

## 3. 第 1 点：异常指标来源补 PMO 操作缺口

后端数据链路已齐（`sync_anomaly_to_pool`→`generate_from_pool`→export/import-judgment→`transition dispatch_measure`），缺的是**前端 PMO 操作面板**，需补三个动作入口（方案层面列出，实施时再细化组件）：

| 动作 | 后端现状 | 缺口 |
|---|---|---|
| 确认工单（生成措施工单） | `transition dispatch_measure`（支持 `triggered_wo_tasks` 多任务） | 前端缺少把 Agent 导入的 `tasks` 可视化为「措施工单草稿」并逐条编辑/删除的确认界面 |
| 补充工单（加措施任务） | `triggered_wo_tasks` JSONB 已支持 `[{title,person_name,deadline,priority,reason,action,type_id}]` | 前端缺「添加措施任务」表单 |
| 删除工单（不发现场关闭） | 无（即本篇 §1 的第 3 点） | 新增 `close-no-dispatch` 接口 + 弹窗 |

> 补充工单的草稿保存空标题已修（commit `e2962db`），说明多任务草稿 UI 已有雏形——第 1 点主要是把「确认/删除」两个动作补全，工作量集中在前端。

---

## 4. 数据库迁移汇总（alembic）

| 表 | 变更 | 来源 |
|---|---|---|
| `work_orders` | `+oa_progress` JSONB | 来自 `feat/dingtalk-oa-role-flow`（已定） |
| `work_orders` | `+no_dispatch_reason` Text、`+no_dispatch_synced` bool、`+closed_without_dispatch` bool | 本篇 §1 新增 |
| `config_definitions` | 增 `aitable` 类配置项（`no_dispatch_table_id`；若需要「闭环必填附件」开关也放这） | §1.2 / §2.3 |
| `status_log` | 无结构变更（新状态 `returned` 直接写 `to_status`） | §2.3 |
| `data_pool_items` | 复用 `skip_reason`（不需新增；若要存「不发现场原因」也可加列，暂时用工单侧字段即可） | §1.3 |

> `region` 有 `CheckConstraint`（`ck_work_orders_region`），新增字段不涉及；`status` 无 CHECK 约束，加 `returned` 无需改表结构，只需在 `config_definitions` 补状态定义。

---

## 5. AITable 建表后场（`dws` 命令示例）

```bash
# 1. 建表 + 首建字段（幂等前先 resolve-table 探一次）
dws aitable table create \
  --base-id OG9lyrgJPzMw9B5jSvpyvdQLWzN67Mw4 \
  --name "不发现场关闭台账" \
  --fields '[{"fieldName":"标题","type":"primaryDoc"},
              {"fieldName":"工单编号","type":"text"},
              {"fieldName":"项目名称","type":"text"},
              {"fieldName":"异常指标","type":"text"},
              {"fieldName":"异常月份","type":"text"},
              {"fieldName":"关闭原因","type":"text"},
              {"fieldName":"判断来源","type":"singleSelect","config":{"options":[{"name":"agent_no_action"},{"name":"pmo_manual"}]}},
              {"fieldName":"操作人","type":"text"},
              {"fieldName":"操作时间","type":"date","config":{"formatter":"YYYY-MM-DD HH:mm"}}]'

# 2. 写记录（cells 的 key 用 column table get 查到的 fieldId）
dws aitable record create \
  --base-id OG9lyrgJPzMw9B5jSvpyvdQLWzN67Mw4 \
  --table-id <新表tableId> \
  --records '[{"cells":{"fld工单编号":"RW-2026-0007","fld关闭原因":"非设备问题，无需现场处置", ...}}]'
```

---

## 6. 实施顺序与风险

**建议顺序**（每步可独立合并验证）：
1. **合入 `feat/dingtalk-oa-role-flow`**（第 2 点前置，且是已交付未合入的存量）
2. **第 3 点**：AITable 新表 + `close-no-dispatch` 接口 + 补偿任务（自包含，先落地闭环台账）
3. **第 2 点**：`returned` 状态 + 责任人回填根因 + 重发起 OA
4. **第 1 点前端**：PMO 确认/补充/删除操作面板

**风险清单**：

| 风险 | 影响 | 缓解 |
|---|---|---|
| AITable 写权限不足 | §1 落不了库 | 先确认 `dws` 账号对 `ANOMALY_BASE` 权限；权限不足则退回「仅本地落库 + 手动导出」兜底 |
| 回调乱序/漏回调（`feat` 分支已知未硬化点） | `returned`/`closed` 错位 | 沿用 `oa_progress` 顺序判定 + `oa/check` 主动查兜底；退回流用 `activityName` 粗判 |
| 钉钉 `refuse` 无法区分节点 | 退回链错 | 用 `oa_progress` 当前未过节点 stage 判定（accept→returned，approve→rejected） |
| 退回无限循环拖延 SLA | 工单长期不闭环 | 上限退回次数 + 超次升级（§2.5 待业务确认） |
| 事务边界：AITable 写失败 | 台账漏记 | 本地字段 + 定时补偿（§1.3.4） |

---

## 7. 提请业务/开发再次确认的 Open Questions

1. **AITable 写权限**：`dws` 登录账号对「数据池-异常指标」Base 是否有编辑权限？（决定第 3 点能否真写，还是退化为导出兜底）
2. **「异常原因工单」口径**：第 3 点到底覆盖「异常指标汇总表(alert)」还是也含「异常原因表(非EAM/plan)」那类？新表建在哪个 Base？
3. **闭环条件**（第 2 点）：附件是否必填？结论是否必填？退回上限几次？
4. **退回后 SLA**：是否顺延/重算？
5. **责任人回填「根因」**：在 OA 模板上是否必填？（影响 `_sync_oa_results` 回写时 `backfill_status` 的判定）