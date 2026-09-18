# ===== 工单管理平台 =====

新能源电站运维工单管理面板的生产化版本。基于阿里云 ACK 部署。

当前代码版本：**v0.6.0**。本地验证记录见 [测试报告](docs/测试报告.html)；生产部署与真实钉钉 OA 联调需另行验收。

> **工单类型**（2026-09-17 起）：来源/工单类型/异常指标大类三合一，`source_code` 承载唯一类型——运营计划、8 类异常（发电量/限电/双细则/设备可靠性/信息化使用/应签未签/成本费用/客户满意度）、关键会议，另可在后台极简新增。8 类异常走五阶段闭环，其余走计划流/三步。

## 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Vue 3 + Vite + TypeScript + TDesign |
| 后端 | Python FastAPI + SQLAlchemy 2.0 + Alembic |
| 数据库 | PostgreSQL 15 (阿里云 RDS) |
| 缓存 | Tair / Redis |
| 文件 | 阿里云 OSS |
| 部署 | ACK 托管集群 + ALB + Docker |

## 目录结构

```
wo-closed-loop/
├── backend/            FastAPI 后端
│   ├── app/
│   │   ├── main.py     应用入口
│   │   ├── core/       配置、数据库、安全
│   │   ├── models/     SQLAlchemy 模型
│   │   ├── schemas/    Pydantic 模型
│   │   ├── api/        路由
│   │   └── services/   业务逻辑
│   ├── alembic/        数据库迁移
│   └── requirements.txt
├── frontend/           Vue 3 前端
│   └── src/
│       ├── views/      页面
│       ├── components/ 组件
│       ├── api/        接口封装
│       ├── stores/     Pinia 状态
│       ├── router/     路由
│       ├── layouts/    布局
│       └── styles/     样式
├── docker/             Dockerfile + nginx
├── config/            系统配置
└── docker-compose.yml  本地开发一键启动
```

## 本地开发

发布前本地校验：`cd backend && DATABASE_URL='<独立测试库连接串>' python -m pytest -q`；`cd frontend && npm run build && npm run test:ui`。测试库会被测试夹具重建，数据库名必须以 `test_` 开头或以 `_test` 结尾，切勿指向主库。

```bash
# 1. 启动依赖（PG + Redis）
docker compose up -d db redis

# 2. 后端
cd backend
cp .env.example .env
pip install -r requirements.txt
alembic upgrade head           # 建表
python -m app.seed             # 灌种子数据
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000  # http://localhost:8000

# 3. 前端
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

> 本地开发**无需起 Celery**：SLA 扫描 + 升级告警已由后端进程内轮询（`app/services/sla_poller.py`，每 300s 一轮，`notify=False` 不发钉钉通知）自动跑，工单「告警」列会在截止过期后自动亮起；异常指标增量同步（每 `anomaly_sync_interval` 秒、只落新增）+ 年度运营计划「初稿」非EAM 导入（每 `plan_sync_interval` 秒、默认 3600，source=plan）由 `app/services/sync_poller.py` 进程内轮询兜底。生产仍由 Celery beat 负责（`sync-anomaly-daily` 每 300s + `sync-plan-draft` 每 3600s + SLA/升级扫描）。年度计划工单导入后落 `scheduled`（排期）不再立即发起 OA，由 Celery beat `dispatch-monthly-plan-oa`（每月 1 日 09:00）挑「计划开始日在当月且必填完整」的计划单统一发起 OA（`app/services/plan_dispatch.py`，幂等）。

> 局域网试用（2026-09-03 验证）：前后端均已 `0.0.0.0` 监听，**固定入口 `http://10.10.147.200:5173`**（en0 手动静态配置，255.255.252.0 / 网关 10.10.144.1；旧地址 10.10.147.84 作废）。本机无 Docker，PG/Redis 为原生运行；若开防火墙需放行 node/python 传入连接。OA 同步走钉钉 Stream + 10s 轮询，无需公网回调。

## 日志 / 告警 / 巡检（可观测性）

- **文件日志**：后端启动即写 `backend/logs/app.log`（全量）+ `backend/logs/error.log`（仅 ERROR 起）、按天滚动保留 `LOG_RETENTION_DAYS` 天；未捕获异常（500）会带 traceback 落 error.log。建单/流转/派发/OA 发起/同步等关键点均有日志，出问题先翻这里。
- **错误告警**：未捕获异常、OA 发起失败（已配置钉钉但未生成审批实例）自动单发钉钉工作通知给 `ALERT_NOTIFY_USERID`（空则回落 `DINGTALK_FALLBACK_USERID`）；同类告警在 `ALERT_DEBOUNCE_SECONDS` 秒内去重，不轰炸。
- **主动巡检**：每 `SWEEP_INTERVAL` 秒扫一轮静默失效——待派发却缺 OA 必填字段（派发会被 422 拦）、异常指标/计划同步疑似中断（超 3×interval 没成功）——发现即汇总告警并附「怎么修」。本地 dev 由进程内轮询跑，生产由 Celery beat 的 `app.tasks.sweep` 跑。

## 生产运行方式

```bash
# API（4 worker）
uvicorn app.main:app --workers 4
# Celery worker（异步通知、OA 发起）
celery -A app.celery_app worker -l info --concurrency=4
# Celery beat（定时 SLA/升级扫描）
celery -A app.celery_app beat -l info
```

ACK 部署：`backend` / `worker` / `scheduler` 三个 Deployment + ALB Ingress，见 `docker/k8s.yaml`。

## 对外建单接口（X-API-Key）

供外部系统 / Agent 不登录平台即可创建、查询工单。鉴权走请求头 `X-API-Key`（环境变量 `EXTERNAL_API_KEY`，为空则整接口禁用；生成 `openssl rand -hex 32`）：

```bash
curl -X POST http://localhost:8000/api/external/work-orders \
  -H "X-API-Key: $EXTERNAL_API_KEY" -H "Content-Type: application/json" \
  -d '{"title":"AGM 双细则考核纠偏","project_name":"通辽永兴风电场","person_name":"王小宁"}'
```

入参按「名称/编码」传入（后端解析为内部 ID，找不到报错不自动建实体），支持 `client_request_id` 幂等去重；外部建单默认落「待派发」、不自动发起钉钉审批。详见 [`docs/外部建单接口.md`](docs/外部建单接口.md)。

## Phase 进度

- [x] Phase 1：后端 API + 数据库 + 前端骨架 + 工作台
- [x] Phase 2：工单列表/详情/创建（手动）+ 闭环归档
- [x] Phase 3：审批流引擎 + 通知引擎 + 钉钉 OA 对接 + 群机器人
- [ ] Phase 4：听记/表格导入 + LLM 解析 + 配置管理后台
- [ ] Phase 5：测试 + 安全加固 + ACK 部署
