# 交接终端 prompt — 工单类型统一（本机迁移 + 全量回归）

> 交付方（沙盒）已把「工单来源/类型/异常指标大类」三套标签合并成单一「工单类型」，代码全改完，
> 后端 `compileall`（含 tests）+ 前端 `vue-tsc --noEmit` 沙盒均 exit 0。下面请你（终端 Claude）在本机跑迁移 + 全量回归，只报结果、不改业务代码。

## 一、这是什么改动（一句话背景）

- `WorkOrder.source_code` 语义从「来源」升级为唯一「工单类型 code」，10 个内置 + 后台可新增：
  `plan`(运营计划工单) / `power_gen`(发电量异常) / `curtailment`(限电量异常) / `dual_rule`(双细则异常) /
  `reliability`(设备可靠性异常) / `info_quality`(信息化使用异常) / `contract`(应签未签) / `cost`(成本费用) /
  `satisfaction`(客户满意度) / `meeting`(关键会议工单)。
- `WorkOrder.metric_type` 保留做异常细分 + 五阶段判定信号；`type_id`/SOP 知识库本轮不动。
- 新增迁移 `j001_unify_work_order_type`（head：i001→j001）：存量回填 source_code + 幂等灌 10 类配置。
- 后端所有 `source_code=="alert"` 五阶段判定已改 `metric_type is not None`；`WorkOrderOut` 新增 `is_measure`。
- 配置 API：`/config/work-order-types`（GET/POST/PATCH，极简新增只输名字）+ SOP CRUD 挪到 `/config/sop-types`。

## 二、前置（本机，老规矩）

本机 PG 原生跑（非 docker），backend 在 `~/Documents/work/wo-closed-loop/backend`，
venv 已建（`.venv`）。全程在该目录下操作。

## 三、执行步骤（按序，每步把结果贴回来）

```bash
cd ~/Documents/work/wo-closed-loop/backend

# 0) 清陈旧缓存，避免口径混乱（沙盒提醒过）
rm -rf .pytest_cache $(find . -type d -name __pycache__)

# 1) 迁移到最新单头（预期 single head = j001_unify_work_order_type）
. .venv/bin/activate
alembic heads          # 应只有一行 j001
alembic upgrade head   # 应报 Running upgrade i001 -> j001
alembic current        # 应显示 j001 (head)
```

核对 10 类配置已灌（j001 + seed 都幂等灌，缺才插）：

```bash
python -c "
from app.core.database import SessionLocal
from app.models import ConfigDefinition
db = SessionLocal()
rows = db.query(ConfigDefinition).filter_by(category='work_order_type').order_by(ConfigDefinition.sort_order).all()
print('work_order_type 条数 =', len(rows))
for r in rows:
    print(r.code, '|', r.name, '| flow=', (r.extra or {}).get('flow'), '| 审批人=', (r.extra or {}).get('default_approver_name'), '| 责任人=', (r.extra or {}).get('default_person_name'))
"
# 预期：10 行；8 异常类责任人 金惠良（dual_rule 徐林杰），plan/meeting 责任人 None；flow = alert/plan/default
```

```bash
# 2) 全量回归
python -m pytest -q 2>&1 | tail -60
```

## 四、报告格式（贴回来，我据此修）

1. `alembic heads` / `upgrade head` / `current` 的实际输出。
2. 上面 python 查配置的 10 行（若条数≠10 或责任人/flow 不对，直接标红）。
3. pytest 最终行：`N passed, M failed, X error`；**只贴 failed/error 的用例名 + 关键 traceback 尾部**，别贴全量日志。
4. 若全绿，回一句「全绿 N passed」即可。

## 五、注意事项

- 测试断言我已随改动更新过（`test_anomaly_flow`/`test_alert_flow`/`test_alert_merge`/`test_agent_import`/
  `test_external_api`/`test_transition`/`test_codes_search_audit` 里原来的 `== "alert"/"measure"/"manual"/"external"`
  都已改成新 code 或 `metric_type` 判定）。**若还有红，先看是否这些文件之外的遗留断言，不要改业务代码，报给我。**
- 钉钉 OA 模板的「工单类型」下拉同步到 10 类 是**你的钉钉后台侧操作**，本轮终端任务不涉及。