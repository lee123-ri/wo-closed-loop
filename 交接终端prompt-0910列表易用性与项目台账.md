# 交接：列表易用性改动 + 项目台账（OA 网页）同步（2026-09-10）

> 沙盒已完成代码改动并自验（前端 `vue-tsc -b` 全绿、后端改动文件 `py_compile` 通过）。
> 以下事项沙盒做不了，需你在 **Mac 本机** 完成，验收后回传结果即可。

## 背景（一句话）

第 3 条「项目从 OA 找执行中/待执行的名字」的数据源，最终确认为：**公司 OA（泛微 oa.xh-service.com）的「运维项目台账」网页**，取法对齐 `annual-ops-plan` 机器人的 `oa_login`/`oa_fetch`（Playwright 登录 → 台账 customid=97 逐页抓表 → 按「项目状态」过滤）。**不是钉钉 AI 表**。
OA 凭据已写入 `backend/.env`（沿用 liubing 账号）：`OA_BASE_URL / OA_USERNAME / OA_PASSWORD`。

## 一、补 Playwright 依赖（后端）

后端新增了 `app/services/oa_ledger.py`，依赖 `playwright>=1.40`（已加进 requirements.txt）。本机装：

```bash
cd backend && . .venv/bin/activate
pip install playwright
playwright install chromium
```

（`requirements.txt` 也加了 `playwright>=1.40`，若重新 `pip install -r requirements.txt` 会一并装，但 chromium 浏览器还需单独 `playwright install chromium`。）

## 二、回归

- 后端：`cd backend && . .venv/bin/activate && python -m pytest -q`（基线 101 用例须全绿；本轮无新增用例，重点确认 config/workorders 改动不破坏既有）
- 前端：`cd frontend && npm run build`（vite build 须过）

## 三、UI 验收（http://10.10.147.200:5173，开发登录进）

- **项目管理页**：点「从 OA 同步项目」→ 应真机登录 OA、抓运维项目台账、只把「项目状态=执行中/待执行」的项目名入库，列表刷新可见。未装 playwright 时会弹「Playwright 未安装」明确报错（不是假成功）。
- **工单列表 / 闭环记录**：表头列宽可拖拽；每行能看到「触发原因/行动要求」；项目下拉能输入关键字模糊匹配；先选「区域」再展开「项目」只显示该区域项目，切区域会清掉跨区残留项目。

## 四、改动文件清单（供回溯）

- `backend/app/services/oa_ledger.py` —— 新增（Playwright 登录 OA + 台账 customid=97 抓表 + 状态过滤 + upsert projects）
- `backend/app/api/config.py` —— `POST /config/projects/sync-ledger`（require_auth + log_audit）
- `backend/app/api/workorders.py` —— `list_closed` 补 `region` 参数
- `backend/requirements.txt` —— 加 `playwright>=1.40`
- `backend/.env` / `.env.production.example` —— 加 `OA_*` 与 `PROJECT_LEDGER_*`
- `frontend/src/views/WorkOrderList.vue` / `ClosedRecords.vue` —— 列宽可拖 + 触发原因/行动要求列 + 列重排 + 项目 filterable + 区域联动
- `frontend/src/views/ProjectManage.vue` —— 「从 OA 同步项目」按钮 + 结果提示

## 五、关键口径（验收时对照）

- 台账过滤字段：「项目状态」列，取值 `执行中 / 待执行`（`PROJECT_LEDGER_ACTIVE_STATUSES`，逗号分隔可扩）。
- 以 OA 台账为准：只按「项目简称」upsert「执行中/待执行」且名称含中文的项目（纯字母/数字脏名过滤），同步末尾把不在名单里的既有项目**停用**（is_active=False，非删除、可逆）。
- 台账「交付单元」（区域中心/子公司）经 `region_map` 归一为大区回填项目 `region`；识别不了为空，不强行塞默认。
- 若台账列名/状态文案与默认不符（比如状态列不叫「项目状态」），报错回来我按现场 `probe` 校准选择器。