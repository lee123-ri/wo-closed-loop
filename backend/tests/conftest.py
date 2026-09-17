"""pytest 配置：测试用独立数据库 wo_closed_loop_test（绝不动主库）。

策略：session 级重建 schema + 灌种子；每个测试用独立事务 + savepoint 回滚，
并在每个测试前后把 id 序列对齐到 max(id)，抵消 nextval/setval 不随回滚导致的漂移。
"""
import os
from sqlalchemy.engine import make_url

# 测试环境用 development（开 eager celery）
os.environ["APP_ENV"] = "development"
# 独立测试库：绝不碰主库 wo_closed_loop，避免真实数据/序列被污染
# （允许外部环境变量覆盖，例如 CI/沙箱内嵌 PG；默认仍是本地独立测试库）
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/wo_closed_loop_test",
)
_test_database = make_url(os.environ["DATABASE_URL"]).database or ""
if not (_test_database.endswith("_test") or _test_database.startswith("test_")):
    raise RuntimeError("测试仅允许连接名称以 test_ 开头或以 _test 结尾的独立数据库")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import Base, SessionLocal, get_db, engine
from app.main import app


def _resync_sequences():
    """把 public 各表 id 序列对齐到 max(id)。

    PG 的 nextval/setval 不随事务回滚，测试里 clear-data 的 setval(1) 或普通插入
    会把序列打乱；每测完后按表内实际 max(id) 校准，避免下一次插入撞主键。
    """
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT s.sequencename, t.tablename
            FROM pg_sequences s
            JOIN pg_tables t
              ON t.schemaname = 'public'
             AND s.sequencename = t.tablename || '_id_seq'
            WHERE s.schemaname = 'public'
        """)).fetchall()
        for seqname, tablename in rows:
            maxid = conn.execute(text(f'SELECT max(id) FROM "{tablename}"')).scalar()
            if maxid is None:
                conn.execute(text(f"SELECT setval('public.{seqname}', 1, false)"))
            else:
                conn.execute(text(f"SELECT setval('public.{seqname}', {int(maxid)}, true)"))


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """测试库重置：重建 public schema（清表+序列）+ 建表 + 灌种子，保证每次运行从干净状态开始。"""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(bind=engine)
    from app.seed import run as seed_run
    seed_run()
    _resync_sequences()
    yield


@pytest.fixture(autouse=True)
def db():
    """每个测试用独立事务 + savepoint，app 代码的 commit() 只提交 savepoint 不污染真实库。"""
    _resync_sequences()
    conn = engine.connect()
    trans = conn.begin()
    session = SessionLocal(bind=conn, join_transaction_mode="create_savepoint")
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.pop(get_db, None)
    session.close()
    trans.rollback()
    conn.close()
    _resync_sequences()


@pytest.fixture(autouse=True)
def _mock_oa_in_tests(monkeypatch):
    """测试环境无真实钉钉 OA：不打真实接口、不触发 502。

    - oa_configured→False：dispatch 走本地占位单号（OA-yyyymmdd-xxx）路径
    - create_oa_approval→None：双保险，绝不发起真实审批请求
    """
    from app.services import dingtalk as dt
    monkeypatch.setattr(dt, "oa_configured", lambda: False)
    monkeypatch.setattr(dt, "create_oa_approval", lambda wo, token=None: None)


@pytest.fixture(autouse=True)
def _login_switches_product_defaults(monkeypatch):
    """登录开关钉死生产默认值，本机 .env 的应急开关不得泄漏进测试。

    背景：本机 .env 为局域网试用恢复了开发登录（DEV_LOGIN_ENABLED=true），
    pydantic Settings 按 cwd 读 .env，导致 test_dev_login_disabled_by_default
    在本机恒红。测试断言的是「产品默认行为」，故每个用例前强制归位；
    需要开开关的用例在测试体内自行 monkeypatch 覆盖。
    """
    from app.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "name_login_enabled", False)
    monkeypatch.setattr(s, "dev_login_enabled", False)
    monkeypatch.setattr(s, "login_admin_only", True)


@pytest.fixture(autouse=True)
def _anomaly_sync_start_default(monkeypatch):
    """异常每日同步起跑日钉死 None（产品默认=立即生效）。

    本机 .env 曾设 ANOMALY_SYNC_START_DATE（为了先配默认责任人、晚点再开跑），
    若不归位，run_anomaly_daily_sync 的「未到开始日期就 skip」分支会泄漏进测试，
    让 test_daily_sync_smoke 之类按默认行为断言的用例误红。需要验证 gate 的用例自行覆盖。
    """
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "anomaly_sync_start_date", None)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(db):
    """以种子数据中的 admin 身份签发 JWT，供需要鉴权的接口测试使用。"""
    from app.models import User
    from app.core.security import create_access_token
    admin = db.query(User).filter(User.role == "admin").first()
    token = create_access_token(str(admin.id), extra={"name": admin.name, "role": admin.role})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client_auth(auth_headers):
    """自带鉴权头的 TestClient（全路由强制鉴权后，业务接口测试用它）。"""
    c = TestClient(app)
    c.headers.update(auth_headers)
    return c
