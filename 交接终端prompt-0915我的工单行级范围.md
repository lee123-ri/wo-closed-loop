# 交接终端：「我的工单」行级数据范围收口——本机回归

**目标**：修「我的工单页没按自己 id 切到自己的页面」。原页面带「切换人员」下拉、按 person_name 查，普通执行人能切到任意他人/全体。现已改成按登录人身份收口：admin→全部；区域 PMO→其负责区域 + 本人相关（跨区域被派到的单也含）；其余（executor/approver/readonly）→本人相关（责任人或审批人）。「闭环记录」页也按同口径收口。代码已落盘，需本机跑 pytest + 前端 build + UI 点检。

## 改了哪些文件（沙盒已验 py_compile + vue-tsc -b 全绿）

- 新增 `backend/app/services/scope.py`：`visible_scope(db,user)`（admin→None 全量 / region_pmos 命中→`{"regions":[...]}` / 否则→`{"self":True}`）+ `apply_scope_to_query(q,db,user)`（区域 PMO = region in regions OR 本人责任/审批）。
- `backend/app/api/workorders.py`：`GET /work-orders` 增 `scope` 参数 + `user=Depends(require_auth)`；`GET /work-orders/closed/list` 同样增 `scope=mine`；scope=mine 时套行级范围。
- `backend/app/api/dashboard.py`：新增 `GET /dashboard/mine`（按行级范围聚合统计卡，返回 `scope`=all/region/self）；`GET /dashboard/calendar` 增 `mine=true` 套同样范围。
- `frontend/src/api/pool.ts`：`getPersonDashboard` → `getMyDashboard`(`/dashboard/mine`)；`getCalendar` 增 `mine` 参数。
- `frontend/src/views/MyDashboard.vue`：去掉「切换人员」下拉，固定当前登录人；列表 `listWorkOrders({scope:'mine'})`、统计 `getMyDashboard()`、日历 `getCalendar(y,m,true)`；`users` 由分页 `getUsers()` 改全量 `getUsersAll()`。
- `frontend/src/views/ClosedRecords.vue`：列表带 `scope:'mine'`。
- 新增 `backend/tests/test_scope.py`：8 用例。

## 本机回归步骤

1. 后端新增用例（先清缓存）：
```bash
cd ~/Documents/work/wo-closed-loop/backend
find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
rm -rf .pytest_cache
.venv/bin/python -m pytest tests/test_scope.py -q
```
预期：8 passed。

2. 全量回归（确认没破既有用例）：
```bash
.venv/bin/python -m pytest -q
```
预期：全绿 0 failed（现有 160+ 用例基础上 +8）。

3. 前端 build（类型闸门）：
```bash
cd ~/Documents/work/wo-closed-loop/frontend
npm run build
```
预期：退出码 0。

## UI 点检（本机 10.10.147.200:5173，开发登录选「李沛东 (admin)」）

- admin 进「我的工单」：标题应显示「全部工单」、统计卡与列表是全体工单；上方「切换人员」下拉应已消失。
- 换一个 executor（如王小宁）登录（如需可临时开姓名登录/开发登录造 token，或让 admin 用 dev-login 换 user_id）进「我的工单」：只看到自己作为**责任人或审批人**的工单，看不到他人工单。
- 到「规则配置 → 区域PMO配置」把某个 user 设为某区域（如华东）PMO，再用该 user 进「我的工单」：既看到该区域工单，也看到自己作为责任人被派到其它区域的单。
- 换 executor 进「闭环记录」：应只看到自己相关（责任人/审批人）的闭环单，看不到他人闭环单；admin 进「闭环记录」仍是全量。
- 直接 `curl` 验证：`GET /api/work-orders?scope=mine` 带不同用户 token，返回条数应符合各自范围；`GET /api/dashboard/mine` 的 `scope` 字段应分别为 all/region/self。

## 回报

① test_scope.py 6 条结果；② 全量 pytest 尾部一条（passed/failed 数）；③ `npm run build` 退出码；④ UI 点检四项通过/异常（异常原样报 console 报错或截图）。

**约束**：只跑测试与点检，不改代码。任一步报错原样回报，不要自行改代码；需要改代码时回传给我。