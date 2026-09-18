# 交接终端 prompt —— 数据范围角色可配置化（2026-09-17）

> 沙盒已改完代码，因沙盒无 sqlalchemy/PG，请在本机（Mac arm64，cd ~/Documents/work/wo-closed-loop）跑迁移 + pytest 验收。

## 一、本轮改了什么

数据范围从 `scope.py` 硬编码改为后台可配，并新增「事业部 PMO」数据范围角色：

- 新表 `role_data_scopes`（alembic `k001_add_role_data_scopes`，4 行种子）：admin(锁死 all) / division_pmo(事业部PMO,默认 all) / region_pmo(区域PMO,默认 self+region) / member(普通成员,默认 self)
- `app/services/scope.py` 重写：`resolve_data_role` 归角色（admin → role_assignments 的 division_head/pmo → region_pmos → member），`apply_scope_to_query` 读勾选落 OR 并集；admin 锁死全部；勾选空集=显式无范围
- `app/api/config.py` + `schemas/config.py`：`GET /api/config/role-scopes`、`PUT /api/config/role-scopes/{role_code}`（require_admin、admin 行 400 锁定）
- `app/seed.py`：`seed_role_scopes`
- 前端 `ConfigPage.vue` + `api/config.ts`：新增「🔐 数据权限」卡片（每角色三 checkbox，admin 置灰）

## 二、本机要跑什么

```bash
cd ~/Documents/work/wo-closed-loop/backend

# 1. 迁移（k001 建表 + 种子）
alembic upgrade head

# 2. 灌种子（幂等，补齐 role_data_scopes 4 行）
python -m app.seed

# 3. 先跑本轮相关用例
pytest tests/test_role_data_scope.py tests/test_scope.py -v

# 4. 全量回归
pytest -q
```

## 三、验收标准（重点看这几点）

1. `test_role_data_scope.py` 9 用例全过（admin 锁定 / 事业部PMO 全量 / 区域PMO 去掉 self 后本人跨区单不出现 / 成员授 all / 空集无范围 / API 校验 / 404）。
2. `test_scope.py` 既有 11 用例不红（admin=全量、executor=仅本人、区域PMO=区域+本人跨区、闭环记录 scope=mine、personal 严格双角色口径）。
3. **潜在行为变化**：事业部 PMO（role_assignments.pmo=金惠良）`scope=mine` 由「仅本人」变成「全部」——如果 `test_api.py` / `test_dashboard_list_filters.py` 里有「approver 只看自己」的断言请核对，必要时按新口径更新（这是本轮刻意为之的产品变更）。
4. `GET /api/config/role-scopes` 返回 4 行、admin 行 `is_locked=true`；`PUT /api/config/role-scopes/admin` 返回 400。

## 四、已知遗留（非本轮引入，不要在本轮修）

前端 `vue-tsc --noEmit` 有 **并发重构遗留** 的报错：`@/api/config` 已去掉 `getSources / getAnomalyCategories / updateAnomalyCategory` 导出，但 `ConfigPage.vue`、`stores/config.ts`、`ClosedRecords.vue`、`WorkOrderCreate.vue`、`WorkOrderList.vue` 还在 import 它们。这是「来源/类型/异常大类三合一」重构做到一半的状态，属于另一条线，本轮不改。

跑通后把 pytest 结果（通过数/失败项）回给我验收。