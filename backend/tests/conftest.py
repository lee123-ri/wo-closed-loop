"""pytest 配置：测试用独立数据库（PG 同库不同 schema 或直接用主库测试库）。

策略：用真实 PG（wo_closed_loop 库），每个测试函数自动回滚，互不污染。
"""
import os

# 测试环境用 development（开 eager celery）
os.environ["APP_ENV"] = "development"
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/wo_closed_loop")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import Base, SessionLocal, get_db, engine
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """建表（如不存在）+ 灌种子（如空）"""
    Base.metadata.create_all(bind=engine)
    from app.seed import run as seed_run
    # 若无工单类型则灌种子
    db = SessionLocal()
    need_seed = db.execute(text("SELECT count(*) FROM workorder_type_kb")).scalar() == 0
    db.close()
    if need_seed:
        seed_run()
    yield


@pytest.fixture(autouse=True)
def db():
    """每个测试用独立事务 + savepoint，app 代码的 commit() 只提交 savepoint 不污染真实库。"""
    conn = engine.connect()
    trans = conn.begin()
    session = SessionLocal(bind=conn, join_transaction_mode="create_savepoint")
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.pop(get_db, None)
    session.close()
    trans.rollback()
    conn.close()


@pytest.fixture
def client():
    return TestClient(app)
