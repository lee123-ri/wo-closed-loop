# ===== 软工单闭环管理系统 =====

新能源电站运维软工单闭环管理面板的生产化版本。基于阿里云 ACK 部署。

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

```bash
# 1. 启动依赖（PG + Redis）
docker compose up -d db redis

# 2. 后端
cd backend
cp .env.example .env
pip install -r requirements.txt
alembic upgrade head           # 建表
python -m app.seed             # 灌种子数据
uvicorn app.main:app --reload  # http://localhost:8000

# 3. 前端
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

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

## Phase 进度

- [x] Phase 1：后端 API + 数据库 + 前端骨架 + 工作台
- [x] Phase 2：工单列表/详情/创建（手动）+ 闭环归档
- [x] Phase 3：审批流引擎 + 通知引擎 + 钉钉 OA 对接 + 群机器人
- [ ] Phase 4：听记/表格导入 + LLM 解析 + 配置管理后台
- [ ] Phase 5：测试 + 安全加固 + ACK 部署
