"""核心配置：环境变量 + 系统配置加载"""
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """环境变量配置（.env 注入）"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 应用
    app_name: str = "工单管理平台"
    app_env: str = "development"
    # 前端访问基地址（拼工单详情跳转链接用，钉钉工作通知卡片「查看工单」按钮）
    frontend_base_url: str = "http://localhost:5173"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    log_dir: str = "logs"               # 文件日志目录：写 app.log（全量）+ error.log（ERROR 起），相对运行目录
    log_retention_days: int = 30        # 按天滚动保留天数
    log_to_stderr: bool = True          # 是否同时打到终端（保留现有排查习惯）
    # 访问日志：毫秒级阈值，超过判定为慢请求升级 WARNING（性能定位抓手）
    access_log_slow_ms: int = 1000
    # 反向代理后的真实客户端 IP：生产 nginx 覆盖写 X-Real-IP（不可伪造），默认采信。
    # 若再前置一层 SLB/Ingress 且确认它会重写 X-Forwarded-For，才置 True 采信 XFF 最左侧。
    trust_x_forwarded_for: bool = False
    auto_seed: bool = True                 # 开发环境空库自动灌演示数据（生产恒为关）
    # 进程内 SLA/升级扫描轮询（本地开发兜底；生产用 Celery beat，is_prod 时本开关失效）
    sla_poller_enabled: bool = True
    sla_poller_interval: int = 300         # 秒
    # 主动巡检（静默失效扫描：待派发缺必填字段/同步中断/钉钉Stream断开 等 → 发现即告警）
    sweep_enabled: bool = True
    sweep_interval: int = 600              # 秒（本地进程内轮询 / 生产 Celery beat 同用）
    # 异常指标每日同步：从该日期起才真正跑（之前直接 skip）。格式 YYYY-MM-DD；空 = 立即生效。
    anomaly_sync_start_date: date | None = None
    # 异常指标增量同步轮询间隔（秒）。本地 dev 由 sync_poller 按此间隔跑；默认 300=5分钟（准实时）
    anomaly_sync_interval: int = 300
    # 年度运营计划「初稿」文件夹（alidocs 节点）——轮询同步非EAM 计划工单的第二个驱动源
    drive_draft_plan_folder_id: str = "b9Y4gmKWrPqYGdg9i4y44M2AJGXn6lpz"
    # 计划初稿（非EAM）轮询同步间隔（秒）。下载解析整批 xlsx 较重，默认 3600=1小时；本地 dev 由 sync_poller 按此间隔跑
    plan_sync_interval: int = 3600

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
    # 企业内部应用 AgentId（工作通知 topapi/message/corpconversation/asyncsend_v2 用，空则工作通知发不出）
    dingtalk_agent_id: str = ""
    # 群机器人 webhook（robot_mention 通道用；钉钉群→机器人→安全设置 里拿 webhook 与加签 secret）
    dingtalk_robot_webhook: str = ""
    dingtalk_robot_secret: str = ""
    # 企业内部机器人 robotCode（发群消息 /v1.0/robot/groupMessages/send 用；本项目 robotCode==AppKey）
    dingtalk_robot_code: str = ""
    # 派发提醒目标群 openConversationId（合并发群消息进这个群）
    dingtalk_notify_group_id: str = ""
    # 异常/派发提醒找不到责任人时的兜底 @ 对象（钉钉 userId；本项目=刘冰）
    dingtalk_fallback_userid: str = ""
    # 错误告警：钉钉工作通知单发（复用 AppKey/Secret/AgentId，不进群、不占群 webhook）
    alert_enabled: bool = True
    alert_notify_userid: str = ""         # 告警接收人 userId；空则回落 dingtalk_fallback_userid
    alert_debounce_seconds: int = 300     # 同类告警防抖窗口（秒），避免短时间轰炸
    dingtalk_oa_template_id: str = ""
    dingtalk_corp_id: str = ""
    # 钉钉 OAuth 登录回跳地址（前端登录页）；需在钉钉开发者后台「安全设置-回调域名」登记
    dingtalk_login_redirect_uri: str = "http://localhost:5173/login"
    dingtalk_callback_token: str = ""   # 事件订阅 Token
    dingtalk_callback_aes_key: str = "" # 事件订阅 AES Key（43位Base64）

    # 登录策略
    login_admin_only: bool = True      # 钉钉登录仅管理员放行（多人开放时置 False）
    name_login_enabled: bool = False   # 姓名登录开关（无口令，默认关）
    dev_login_enabled: bool = False    # 开发登录开关（默认关，生产恒关）

    # 上线默认只采集到数据池，由管理员逐条勾选后才生成工单；避免首次同步倒灌。
    auto_workorder_import_enabled: bool = False
    # 历史工单批量导入唯一授权人（钉钉 userId）；生产必须显式配置，空值即关闭入口。
    bulk_import_owner_dingtalk_id: str = ""

    # 对外开放 API（外部系统/Agent 经 X-API-Key 建单/查询工单；为空=禁用对外接口）
    external_api_key: str = ""

    # OSS（Phase 2）
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""

    # LLM（Phase 4）
    dashscope_api_key: str = ""
    llm_model: str = "qwen-plus"

    # 公司 OA 网页「运维项目台账」抓取（Playwright 登录 oa.xh-service.com）
    oa_base_url: str = "https://oa.xh-service.com"
    oa_username: str = ""
    oa_password: str = ""
    project_ledger_active_statuses: str = "执行中,待执行"  # 逗号分隔
    project_ledger_customid: str = "97"                    # 运维项目台账
    project_ledger_max_pages: int = 100

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
