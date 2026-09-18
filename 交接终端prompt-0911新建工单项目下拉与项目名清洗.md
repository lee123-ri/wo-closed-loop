# 交接：新建工单「项目名称」下拉可搜索 + 项目名清洗（2026-09-11）

> 沙盒已完成前端代码改动并自验（`frontend/vue-tsc -b` 全绿）。
> 以下两件事沙盒做不了（DB 在你 Mac 本机、dev server 也跑本机），需你在 **Mac 本机** 完成，验收后回传结果即可。

## 背景（用户报的两条）

1. 「派发工单」页面（工单详情里的「派发 → 发起OA审批」弹窗）和「新建工单」页的项目名称都是原生 `<select>`，不能输入关键字模糊检索；
2. 项目下拉里一堆乱名（`国电投别力古台500MW-YH`、`协合瓜州二期2025`、`不统计 / 华北临时数据 / #N/A` 等占位脏名），和项目管理页对不上。

根因是两件事：① 两处项目名下拉没接模糊搜索；② `projects` 表本身脏（老 aitable 同步污染，清洗脚本已写但尚未本机执行）。

## 一、项目名清洗（跑脚本，本机 DB）

脚本 `scripts/cleanup_project_names_20260911.py`（代码已落，与 `backend/app/services/oa_ledger.py::_clean_name` 同口径）。在 backend 目录、用 .venv 跑：

```bash
cd backend && . .venv/bin/activate
python ../scripts/cleanup_project_names_20260911.py            # 先 dry-run，看计划
python ../scripts/cleanup_project_names_20260911.py --apply    # 确认无误后真正执行
```

- dry-run 只打印计划、不落库；预期量级：活动项目 **1256 → 667**（垃圾名软删 4 + 去重重复软删 585、改名 29、编码归一 432），以脚本实际输出为准。
- `--apply` 会：垃圾名/重复项 `is_active=false`（软删，可逆）→ 同名去重把 `work_orders.project_id` / `person_project_map` 引用改指 canonical → canonical 去后缀改名 → 非 `PRJ-####` 编码重编。
- 只清活动项目；已停用/历史工单引用不受影响。

## 二、前端重建（本机 dev server）

沙盒已改两处项目名下拉（原生 select → `t-select filterable`，下拉项为「编码 · 名称」，按编码数字序排，支持按名称/编码模糊搜索）：

- `frontend/src/views/WorkOrderDetail.vue` —— 「派发 → 发起OA审批」确认弹窗的项目名（`dispatchProjectId`）
- `frontend/src/views/WorkOrderCreate.vue` —— 新建工单页的项目名

本机确认前端生效（二选一，build 为准）：

```bash
cd frontend && npm run build       # vue-tsc -b && vite build，须过
```

若 dev server（http://10.10.147.200:5173）还在跑，vite HMR 一般会自动热更；没生效就重启一次前端。

## 三、UI 验收清单

进开发登录（李沛东=admin）：

- **工单详情页 → 「派发 → 发起OA审批」弹窗**（`/work-orders/:id`，非 OA 驱动的 pending/approving 工单）：
  - 「项目名称」可点开、能输入关键字（中文名或 `PRJ-xxxx` 编码）模糊检索；
  - 下拉项显示「编码 · 名称」，按编码顺序排列（PRJ-0001 起），不再按拼音散乱；
  - 空校验仍生效（不选项目会拦「请先补齐必填字段：项目」）。
- **新建工单页 `/create`**：
  - 「项目名称」可点开、能输入关键字（中文名或 `PRJ-xxxx` 编码）模糊检索；
  - 下拉项显示「编码 · 名称」，且按编码顺序排列（PRJ-0001 起），默认选中第一个；
  - 清空/重选项目后，「责任人」仍会自动带出该项目默认责任人（原有逻辑不破坏）。
- **项目管理页 `/projects`**：
  - 名称列不再出现 `不统计 / 华北临时数据 / 东北临时数据 / #N/A` 等占位脏名；
  - 列表条数回到约 667（清洗后活动项目）。

## 四、改动文件清单（供回溯）

- `frontend/src/views/WorkOrderDetail.vue` —— 「派发→发起OA审批」弹窗项目名改 `t-select filterable` + `projectOptions`（编码·名称）+ 按编码排序（**本轮新增**）
- `frontend/src/views/WorkOrderCreate.vue` —— 新建工单「项目名称」改 `t-select filterable` + `projectOptions`（编码·名称）+ 按编码排序（**本轮新增**）
- `scripts/cleanup_project_names_20260911.py` —— 项目名清洗脚本（**上轮已落，本轮执行**，未改）

后端本轮无代码改动，`pytest` 用独立测试库、不受清洗影响，可顺带跑 `cd backend && . .venv/bin/activate && python -m pytest -q` 确认仍全绿。

## 五、关键口径（验收时对照）

- 清洗是「软删」不是物理删：`is_active=false`；下拉/列表不再出现，历史工单里已引用的 project_id 仍能正常展示，不会被误伤。
- 下拉与项目管理页现在走同一个 `/config/projects/all` 数据源、同一排序口径（编码数字序），两边显示应一致。
- 若 dry-run 输出与预期量级（1256→667）差异大、或 `--apply` 报错，先别硬跑，把输出回传我来判断。