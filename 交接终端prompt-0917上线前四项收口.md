# 交接终端：上线前四项收口——本机回归

**目标**：对「上线前四项改造」的代码收口做本机回归（pytest + 前端 build + UI 点检）。代码已全部落盘，本 prompt 只跑测试与点检，**不改代码**；任一步报错原样回报，不自行改代码。

设计依据：`docs/design.md`（四项：①管理看板改驾驶舱+筛选 ②我的工单严格双角色+角色口径+日历 ③宽表横向滚动 ④规则配置重分组）。

## 本轮改了什么（供点检对照，无需重做）

- 后端 `services/scope.py`：`apply_personal_scope_to_query(q,user,role="all")` 支持 role 细分 `all/responsible/approver/both`。
- 后端 `api/workorders.py`：`GET /work-orders` 增 `role` 参数（scope=personal 时生效）。
- 后端 `api/dashboard.py`：`/mine`、`/calendar` 增 `role`；`/stats` 增 `project_id/region/month`；`/trends` 增 `project_id/region`。
- 前端 `views/MyDashboard.vue`：角色口径切换（全部相关/本人责任/本人审批/双重角色）；日历空态、同天折叠+“N 更多”、截止<今天标红。
- 前端 `views/Dashboard.vue`：顶部加项目/区域/月份筛选，全部卡片与趋势沿用筛选，跳列表带 project_id/region。
- 前端 `views/WorkOrderList.vue`：从 query 读取 project_id/region。
- 前端 `components/WorkbenchTable.vue`：顶部横滚条宽度由 ResizeObserver 对齐表格真实 scrollWidth（去掉硬编码 1452px）；Shift+滚轮横移。
- 前端 `views/ConfigPage.vue`：顶部导航补全 5 类；区域PMO 卡改名「区域负责人（PMO）」并标注双用途。
- 前端 `api/dashboard.ts`、`api/pool.ts`：签名加参数。

## 本机回归步骤

### 1. 后端测试
```bash
cd ~/Documents/work/wo-closed-loop/backend
find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
rm -rf .pytest_cache
.venv/bin/python -m pytest tests/test_scope.py tests/test_dashboard_list_filters.py -q
```
预期：全绿（test_scope.py 12 条左右 + 筛选相关用例）。

### 2. 全量回归
```bash
.venv/bin/python -m pytest -q
```
预期：0 failed（既有 200+ 用例基础上不回归）。

### 3. 前端 build（类型闸门）
```bash
cd ~/Documents/work/wo-closed-loop/frontend
npm run build
```
预期：退出码 0（vue-tsc -b 与 vite build 均过）。沙盒侧 `vue-tsc --noEmit` 与 `vue-tsc -b` 已绿，此处重点确认 vite build 无缺原生二进制。

## UI 点检（本机 10.10.147.200:5173，开发登录选「李沛东 (admin)」）

- **管理看板**：顶部出现「项目/区域/月份」筛选；选某项目+某区域后，KPI、待办、来源、趋势均收窄；点某张状态卡跳到工单列表且列表自动带 project_id/region 过滤；清除筛选恢复全量。
- **我的工单**：出现「全部相关/本人责任/本人审批/双重角色」四个口径；切「本人责任」只看到本人为责任人的单；统计卡、列表、日历三处数量一致；日历本月无日程时显示空态文案而非空白。
- **工单列表（宽表）**：底部与顶部均有横向滚动条；顶部滚动条拖动可横移列表，无需拉到最底；列宽与顶部滚动条同步；Shift+滚轮在表格上可横移。
- **规则配置**：顶部 5 类导航；「工单类型」与「异常指标大类」分属两个卡片、标注不同用途；「审批流」已更名「平台升级路径」；SLA 标注「已接入默认截止日、SLA 扫描和管理看板违约统计」；「区域负责人（PMO）」标注双用途。

## 回报

① 步骤1、2 的 passed/failed 数；② `npm run build` 退出码（含 vite build 是否因原生二进制报错）；③ 上面 4 项 UI 点检通过/异常（异常原样报 console 报错或截图）。

**约束**：只跑测试与点检，不改代码；需要改代码时回传给我。

---

## 修订（2026-09-17 二轮）

- 首轮回归唯一失败 `test_dashboard_buckets_match_list_totals` 是**测试口径写错**，不是后端功能回归：测试里 `/work-orders?scope=mine`（管理范围）拿去和 `/dashboard/mine`（个人双角色范围）比。已把该测试改为 `scope=personal&role=all`，并新增 `test_personal_scope_role_filter`（覆盖 responsible/approver/both 三档）。请**重跑下面的 ①② 确认 0 failed**：
  ① `pytest tests/test_scope.py tests/test_dashboard_list_filters.py -q` → 预期全绿（约 13 passed）
  ② `pytest -q` → 预期 0 failed（214+ 基础上 +1 新用例）
- UI 点检需登录：后端 `.env` 把 `DEV_LOGIN_ENABLED=true`（点检完记得改回 `false` 并重启），再按上面四项点检。