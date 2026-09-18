# 交接终端 prompt —— 0917 OA 双向同步改造（本机回归）

> 供终端 Claude 在本机（Mac）执行。沙盒无 pytest / macOS venv 跑不了，代码与测试已由桌面端写好并过 `py_compile` + 前端 `vue-tsc -b`。

## 背景
软工单平台（`~/Documents/work/wo-closed-loop`）本次做了「OA 审批双向同步 + 年度运营计划改造」，
四拍板口径见 `docs/oa_annual_plan_sync_design.md` 第 0 节。改动文件（均已改好，无需重写）：

后端：`app/models/workorder.py`、`app/schemas/workorder.py`、`app/api/workorders.py`、
`app/services/oa_event.py`、`app/services/dingtalk.py`、`app/services/drive_workorder_import.py`、
新增 `app/services/plan_dispatch.py`、`app/tasks.py`、`app/celery_app.py`、
新增 `alembic/versions/i001_add_task_deliverable.py`
测试：`tests/test_oa_event.py`（增 redirect 回归）、新增 `tests/test_plan_dispatch.py`

## 请在 backend 目录依次执行

```bash
cd ~/Documents/work/wo-closed-loop/backend
source .venv/bin/activate

# 1) 迁移：必须单 head；然后 upgrade
alembic heads
alembic upgrade head
#    预期 heads 只打印一条 = i001_add_task_deliverable (Revises: h002_add_alert_flow)

# 2) 先跑本次改动相关用例（应全绿）
python -m pytest -q \
  tests/test_oa_event.py \
  tests/test_plan_dispatch.py \
  tests/test_drive_import_parse.py \
  tests/test_transition.py \
  tests/test_admin_wo_edit_delete.py

# 3) 全量回归
python -m pytest -q
```

## 验收要点（报告时逐条给结论）

1. `alembic heads` 是否单头；`upgrade head` 是否成功（新增 `work_orders.task_deliverable` Text 列）。
2. `test_oa_event.py` 新增的 `test_redirect_regresses_to_approving` / `test_redirect_active_node_mapping` 是否 PASS（退回→回退状态、不回退过头）。
3. `test_plan_dispatch.py` 四例是否 PASS（月边界、计划类缺交付物门禁、当月完整才派发、已有 OA 幂等跳过）。
4. 全量 pytest：绿=可交付；红=把失败输出整段贴回，别改代码，让我定位。

## 已知边界（不要在本机改动）

- 「年度运营计划」＝`source_code=="plan"` 只有钉盘「工单版」xlsx 一条来源（`drive_workorder_import.py`，已加交付物必填门禁 + scheduled 排期）。AITable「数据池-计划/异常原因表」(`sync_non_eam_to_pool`) 的 `source_system="non_eam"` 经 `pool_service.source_map` 映射后是 `source_code="manual"`，**不是计划类**，其表内也无「交付物」列，故**不纳入交付物门禁**（用户已拍板）。
- 钉钉 OA 模板需在钉钉后台加「任务目标交付物」控件（用户侧配置，代码已按该字段名发送）。