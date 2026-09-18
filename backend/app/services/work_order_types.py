"""工单类型（统一口径）。

来源(source_code) / 工单类型(type_id→workorder_type_kb) / 异常指标大类(metric_type)
三合一后的唯一分类维度。`WorkOrder.source_code` 自此承载「工单类型 code」：
10 个内置 + 后台可新增（见 config_definitions.category=work_order_type）。

- 8 类异常（metric_type 落在这些 code 上）→ alert 五阶段闭环
- plan = 运营计划工单（排期 + 必填门禁 + 按月自动派发）
- meeting = 关键会议工单
- 后台新增类型：flow 见 config_definitions.extra.flow

流程区分是硬约束（2026-09-17 用户二次强调）：告警拆成 8 个异常小项后，
五阶段闭环仍按「metric_type 非空」判定，绝不能被统一类型拍平成三步。
凡是旧代码里 `source_code == "alert"` 的地方，改成 `wo.metric_type is not None`。
"""
from app.services.metric_types import CATEGORY_ORDER

# 8 类异常 =「告警拆出来的异常小项」，与 metric_types.CATEGORY_ORDER 完全重合
ANOMALY_TYPE_CODES = frozenset(CATEGORY_ORDER)

# 10 个内置工单类型（有序，供种子 / 兜底 / 后台初始配置）
BUILTIN_TYPE_CODES: list[str] = ["plan", *CATEGORY_ORDER, "meeting"]

FLOW_ALERT = "alert"      # 五阶段闭环
FLOW_PLAN = "plan"        # 运营计划流（排期+门禁+按月派发）
FLOW_DEFAULT = "default"  # 普通三步闭环


def is_anomaly_type(code: str | None) -> bool:
    """code 是否某类异常（8 类）——决定工单走五阶段还是普通三步/计划流。"""
    return code in ANOMALY_TYPE_CODES


def is_anomaly_workorder(wo) -> bool:
    """工单是否「异常类」（走 alert 五阶段）。异常工单与措施工单都带 metric_type。"""
    return bool(getattr(wo, "metric_type", None))


def builtin_flow(code: str) -> str:
    """内置类型的默认流程（后台新增类型以 config extra.flow 为准）。"""
    if code in ANOMALY_TYPE_CODES:
        return FLOW_ALERT
    if code == "plan":
        return FLOW_PLAN
    return FLOW_DEFAULT


def load_type_configs(db):
    """db -> {code: ConfigDefinition}（category=work_order_type）。"""
    from app.models import ConfigDefinition

    return {cd.code: cd for cd in db.query(ConfigDefinition).filter_by(category="work_order_type").all()}


def _extra(db, code: str) -> dict:
    cfg = load_type_configs(db).get(code)
    return (cfg.extra or {}) if cfg else {}


def type_name(db, code: str | None) -> str | None:
    """类型显示名（按 code 查配置）。"""
    if not code:
        return None
    cfg = load_type_configs(db).get(code)
    return cfg.name if cfg else None


def type_approver_name(db, code: str | None) -> str | None:
    """类型默认审批人姓名（10 类都配；后台可改）。"""
    if not code:
        return None
    return _extra(db, code).get("default_approver_name") or None


def type_person_name(db, code: str | None) -> str | None:
    """类型默认责任人姓名（仅 8 类异常用，告警分派的系统兜底责任人）。"""
    if not code:
        return None
    return _extra(db, code).get("default_person_name") or None