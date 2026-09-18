# 交接终端 prompt —— 三合一收口验证（2026-09-17 续）

> 上一轮「数据范围角色可配置」已验收通过。本轮把「来源/类型/异常大类三合一」(j001) 的半成品残留收口了，请本机跑一次全量 pytest 验收。

## 本轮改了什么

- 后端 `tests/test_api.py`：`test_config_sources` 改为 `test_config_work_order_types`（`GET /api/config/work-order-types`，断言 ≥10 类型）。
- 后端 `tests/test_auth_enforcement.py`：401 断言元组的 `/api/config/sources` 改为 `/api/config/work-order-types`（/config 路由整体 require_auth，仍 401）。
- 前端 `ConfigPage.vue`：通用弹窗「类别」去掉「来源」选项（默认/新增均强制 status）、标题「新增/编辑来源/状态」→「新增/编辑状态」。
- 前端 `ClosedRecords.vue`：`source_code` 列标题 + 导出表头「来源」→「工单类型」。

> 其余 13 个红（异常流/告警流/外部API/agent导入/告警合并）由三合一这条线已改好的测试 + system.yaml 10 类型种子消化，本轮未再动它们。

## 本机要跑

```bash
cd ~/Documents/work/wo-closed-loop/backend
pytest -q
```

> 迁移 j001/k001 上一轮已 `alembic upgrade head`、种子已 `python -m app.seed`，本轮无需再跑。

## 验收标准

1. 全量 pytest 全绿（0 failed）——上一轮 15 个红应清零。
2. 若仍有红，把**每个失败的测试名 + 完整 traceback 第一屏**原样贴回，我逐条接着修，不要只给数量。
3. 顺带确认 `cd frontend && npm run build` 无类型报错（沙盒 vue-tsc 已 0）。

跑完把通过/失败数回我。