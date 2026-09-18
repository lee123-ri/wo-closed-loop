# 交接终端：工单列表「项目」筛选栏改为只列列表内项目——本机回归

**目标**：主列表「项目」筛选下拉原本取自 `/config/projects/all`（项目表全量），会列出「有项目但没有任何工单」的无效选项。现已改为由列表接口按当前列表范围（区域 + 行级范围 + 是否闭环）去重返回 `project_options`，只列当前列表里真实出现过的项目。闭环记录页同口径。代码已落盘，需本机跑 pytest + 前端 build + UI 点检。

## 改了哪些文件（沙盒已验 py_compile + vue-tsc 全绿）

- `backend/app/schemas/workorder.py`：新增 `ProjectOption`（id/name/region）+ `WorkOrderListOut.project_options: list[ProjectOption] = []`。
- `backend/app/api/workorders.py`：新增 `_project_options(db,user,region,scope,closed_only)`——按「区域 + 行级范围 + 是否闭环」去重取列表内出现过的项目，刻意不看 project_id/status/source/priority/person_name/search 二级筛选；`GET /work-orders` 与 `GET /work-orders/closed/list` 返回值带上 `project_options`。
- `frontend/src/api/workorders.ts`：`WorkOrderList` 增 `project_options?` 字段。
- `frontend/src/views/WorkOrderList.vue`：项目下拉 `projectOptions` 改读 `list.project_options`，去掉 `getProjectsAll()`；`reload()` 里若已选项目不在新结果中（如切换区域后）自动清空并重拉一次。
- `frontend/src/views/ClosedRecords.vue`：同口径改造。
- 新增 `backend/tests/test_project_filter_options.py`：3 用例（列表内项目集合精确匹配 / 分页无关 / 区域收窄 / 闭环列表）。

## 本机回归步骤

1. 后端新增用例（先清缓存）：
```bash
cd ~/Documents/work/wo-closed-loop/backend
find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
rm -rf .pytest_cache
.venv/bin/python -m pytest tests/test_project_filter_options.py -q
```
预期：3 passed。

2. 全量回归（确认没破既有用例）：
```bash
.venv/bin/python -m pytest -q
```
预期：全绿 0 failed（现有用例基础上 +3）。

3. 前端 build（类型闸门）：
```bash
cd ~/Documents/work/wo-closed-loop/frontend
npm run build
```
预期：退出码 0。

## UI 点检（本机 10.10.147.200:5173，开发登录选「李沛东 (admin)」）

- 进「工单列表」：项目下拉里只应出现**当前列表里有工单的项目**；对照「项目管理」页的项目全集，那些「没有任何工单」的项目不应再出现在下拉里。
- 选一个区域（如华北）→ 项目下拉应立即收窄为该区域里有工单的项目；清空区域 → 下拉恢复为全列表项目。
- 先选一个项目、再切到它不属于的区域 → 该项目选择应被自动清空、列表重拉为该区域全部工单（不出现「空列表」卡死）。
- 进「闭环记录」：项目下拉同理只列已闭环工单里出现过的项目。
- 直接 `curl` 验证：`GET /api/work-orders?page_size=1` 返回体里 `project_options` 应存在且为列表内项目去重集合。

## 回报

① test_project_filter_options.py 结果；② 全量 pytest 尾部一条（passed/failed 数）；③ `npm run build` 退出码；④ UI 点检四项通过/异常（异常原样报 console 报错或截图）。

**约束**：只跑测试与点检，不改代码。任一步报错原样回报，不要自行改代码；需要改代码时回传给我。