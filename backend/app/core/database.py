"""数据库连接与会话管理"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    echo=(not settings.is_prod),
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


class Base(DeclarativeBase):
    """所有模型基类"""


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：注入数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
