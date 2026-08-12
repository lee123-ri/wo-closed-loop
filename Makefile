.PHONY: help dev db redis migrate seed backend frontend build

help:
	@echo "可用命令:"
	@echo "  make dev        - 启动开发依赖 (PG + Redis via docker)"
	@echo "  make migrate    - 执行数据库迁移"
	@echo "  make seed       - 灌入种子数据"
	@echo "  make backend    - 启动后端 (uvicorn --reload)"
	@echo "  make frontend   - 启动前端 (vite dev)"
	@echo "  make build      - 构建前端生产包"

dev:
	docker compose up -d db redis

migrate:
	cd backend && . .venv/bin/activate && alembic upgrade head

seed:
	cd backend && . .venv/bin/activate && python -m app.seed

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

reset-db:
	cd backend && . .venv/bin/activate && alembic downgrade base && alembic upgrade head && python -m app.seed

clean-data:
	cd backend && . .venv/bin/activate && python -c "from app.api.admin import clear_transactional_data; from app.core.database import SessionLocal; print(clear_transactional_data(SessionLocal()))"
