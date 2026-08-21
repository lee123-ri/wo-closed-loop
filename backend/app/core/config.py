"""核心配置：环境变量 + 系统配置加载"""
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """环境变量配置（.env 注入）"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 应用
    app_name: str = "软工单闭环管理系统"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # 数据库
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/wo_closed_loop"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # 鉴权
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 12
    session_cookie_name: str = "wo_session"

    # 钉钉（Phase 3）
    dingtalk_app_key: str = ""
    dingtalk_app_secret: str = ""
    dingtalk_agent_id: str = ""
    dingtalk_oa_template_id: str = ""
    dingtalk_corp_id: str = ""
    dingtalk_callback_url: str = "http://localhost:8000/api/auth/dingtalk/callback"
    dingtalk_callback_token: str = ""   # 事件订阅 Token
    dingtalk_callback_aes_key: str = "" # 事件订阅 AES Key（43位Base64）

    # OSS（Phase 2）
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""

    # LLM（Phase 4）
    dashscope_api_key: str = ""
    llm_model: str = "qwen-plus"

    # 判断Agent（Phase 5）
    judgment_agent_url: str = "http://localhost:8080"
    judgment_agent_token: str = ""
    judgment_timeout: int = 10
    judgment_enabled: bool = True

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def load_system_yaml() -> dict:
    """加载 config/system.yaml 系统配置（种子数据用）"""
    p = Path(__file__).resolve().parents[3] / "config" / "system.yaml"
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
