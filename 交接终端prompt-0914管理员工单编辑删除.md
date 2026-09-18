# 交接终端：管理员「详情页编辑基本信息 + 删除废单」本机回归

**目标**：管理员（李沛东/role=admin）在工单详情页能直接改基本信息，并能删掉「起不了状态」的废单。本轮代码已落盘，需本机跑 pytest + 前端 build + UI 点检。

## 改了哪些文件（沙盒已验 py_compile + vue-tsc -b --force 全绿）

- `backend/app/schemas/workorder.py`：新增 `WorkOrderBasicUpdate`（标题/原因/行动/结论/项目/类型/责任人/审批人/优先级/区域/计划开始/截止/完成；region 走 normalize_region）。
- `backend/app/api/workorders.py`：
  - 新增 `PATCH /work-orders/{id}/basic`（`require_admin`，落审计 `update_basic`）——不含 status/流转/回填字段。
  - 新增 `DELETE /work-orders/{id}`（`require_admin`，**仅限删「未发起 OA 审批」的废单**——`oa_id` 为空或本地 `OA-` 占位才算未发起；已关联真实钉钉审批单 409 拦截）——先解除 `data_pool_items.work_order_id` 与其它工单 `triggered_wo_id` 引用，再显式删子记录（anomaly_occurrences/measure_links/notification_log/escalation_log/attachments/status_log/judgment_degradation_log），最后删工单，落审计 `delete`。
- `frontend/src/api/workorders.ts`：新增 `updateWorkOrderBasic` / `deleteWorkOrder`。
- `frontend/src/views/WorkOrderDetail.vue`：gate `isAdmin` 显示「✏️ 编辑基本信息」「🗑 删除工单」，编辑弹窗 + 删除确认（有真实 OA 时点击即 toast 拦截）。
- `backend/tests/test_admin_wo_edit_delete.py`：新增 8 用例。

## 本机回归步骤

1. 后端测试（先清缓存，避免陈旧 nodeids 干扰）：
```bash
cd ~/Documents/work/wo-closed-loop/backend
find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
rm -rf .pytest_cache
.venv/bin/python -m pytest tests/test_admin_wo_edit_delete.py -q
```
预期：8 passed。

2. 全量回归（确认没破既有用例）：
```bash
.venv/bin/python -m pytest -q
```
预期：全绿（现有 160+ 用例基础上 +8，0 failed）。

3. 前端 build（类型闸门）：
```bash
cd ~/Documents/work/wo-closed-loop/frontend
npm run build
```
预期：退出码 0。

## UI 点检（本机 10.10.147.200:5173，开发登录选「李沛东 (admin)」）

- 打开任意一张工单详情：
  - 头部应出现「✏️ 编辑基本信息」「🗑 删除工单」两按钮（admin 才可见）。
  - 点「编辑基本信息」→ 弹窗能改标题/项目(滤组)/类型/优先级/区域/责任人/审批人/计划开始/截止/完成/原因/行动/结论 → 保存后详情页字段刷新。
  - 标题清空保存 → 应弹「标题不能为空」。
- 找一张「起不了状态」的废单（或新造一张未派发/占位 OA 的测试单）→ 点「删除工单」→ 确认后跳回列表，该单消失；到「闭环记录」/主列表搜编号确认无此单。
- 找一张**已发起真实 OA 审批**的工单 → 点「删除工单」→ 应被 toast 拦截（不弹确认）；直接 `curl -X DELETE /api/work-orders/{id}` 也应 409。
- 换非 admin 账号（如 executor）登录看详情 → 不应出现这两个按钮；直接 curl `PATCH/DELETE` 该接口应 403。

## 回报

① 6 条新用例结果；② 全量 pytest 尾部一条（passed/failed 数）；③ `npm run build` 退出码；④ UI 点检三项的通过/异常现象（有异常截图/console 报错原样报）。

**约束**：只跑测试与点检，不改代码。有任何一步报错原样回报，不要自行改代码；需要改代码时回传给我。