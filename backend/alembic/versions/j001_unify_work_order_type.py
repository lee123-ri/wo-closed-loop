"""统一工单类型：来源/类型/异常大类三合一（数据迁移，无 DDL）

`WorkOrder.source_code` 语义从「来源」升级为「工单类型 code」，取值收缩为
10 个内置 + 后台新增（见 services/work_order_types.py）。本迁移只做：
1. 存量回填 source_code（metric_type 8 类 + plan + meeting 保留，其余粗映射）；
2. 灌入 config_definitions(category=work_order_type) 的 10 个内置类型。

粗映射口径（可复核、可后台补分类）：
- metric_type ∈ 8 异常类 → source_code = metric_type（异常工单与措施工单）；
- source_code=plan / meeting 保留不动；
- measure 措施工单缺 metric_type → 从宿主主单继承；
- 历史 alert 主单缺 metric_type → 从 data_pool_items 继承；
- 剩余 manual / external / measure / alert（仍无法判定）→ meeting（关键会议工单）兜底。

Revision ID: j001_unify_work_order_type
Revises: i001_add_task_deliverable
"""
import json
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "j001_unify_work_order_type"
down_revision: Union[str, None] = "i001_add_task_deliverable"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_ANOMALY_CODES = (
    "power_gen", "curtailment", "dual_rule", "reliability",
    "info_quality", "contract", "cost", "satisfaction",
)

# (code, name, color, flow, default_approver_name, default_person_name)
_TYPES = [
    ("plan", "运营计划工单", "#2563eb", "plan", "金惠良", None),
    ("power_gen", "发电量异常工单", "#dc2626", "alert", "金惠良", "金惠良"),
    ("curtailment", "限电量异常工单", "#d97706", "alert", "金惠良", "金惠良"),
    ("dual_rule", "双细则异常工单", "#7c3aed", "alert", "金惠良", "徐林杰"),
    ("reliability", "设备可靠性异常工单", "#ea580c", "alert", "金惠良", "金惠良"),
    ("info_quality", "信息化使用异常工单", "#2563eb", "alert", "金惠良", "金惠良"),
    ("contract", "应签未签工单", "#0891b2", "alert", "金惠良", "金惠良"),
    ("cost", "成本费用工单", "#059669", "alert", "金惠良", "金惠良"),
    ("satisfaction", "客户满意度工单", "#db2777", "alert", "金惠良", "金惠良"),
    ("meeting", "关键会议工单", "#d97706", "default", "金惠良", None),
]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. 措施工单缺 metric_type → 从宿主主单继承（含 source_code）
    bind.execute(sa.text("""
        UPDATE work_orders AS m
        SET metric_type = h.metric_type, source_code = h.metric_type
        FROM work_order_measure_links AS l
        JOIN work_orders AS h ON h.id = l.host_wo_id
        WHERE m.id = l.measure_wo_id
          AND m.metric_type IS NULL
          AND h.metric_type IS NOT NULL
    """))

    # 2. metric_type 已是 8 异常类 → source_code = metric_type（异常主单 + 已带类的措施）
    bind.execute(sa.text("""
        UPDATE work_orders
        SET source_code = metric_type
        WHERE metric_type IN :codes
    """).bindparams(sa.bindparam("codes", expanding=True)), {"codes": list(_ANOMALY_CODES)})

    # 3. 历史 alert 主单缺 metric_type → 从 data_pool_items 继承
    bind.execute(sa.text("""
        UPDATE work_orders AS w
        SET metric_type = p.metric_type, source_code = p.metric_type
        FROM data_pool_items AS p
        WHERE w.parent_pool_id = p.id
          AND w.source_code = 'alert'
          AND w.metric_type IS NULL
          AND p.metric_type IS NOT NULL
    """))

    # 4. 仍无法判定的 manual / external / measure / alert 残留 → meeting 兜底（可后台补分类）
    bind.execute(sa.text("""
        UPDATE work_orders
        SET source_code = 'meeting'
        WHERE source_code IN ('manual', 'external', 'measure', 'alert')
    """))

    # 5. 灌入 10 个内置工单类型（幂等：已存在则跳过）
    for i, (code, name, color, flow, approver, person) in enumerate(_TYPES):
        exists = bind.execute(
            sa.text("SELECT 1 FROM config_definitions WHERE category='work_order_type' AND code=:c"),
            {"c": code},
        ).scalar()
        if exists:
            continue
        extra = {
            "flow": flow,
            "default_approver_name": approver,
            "default_person_name": person,
        }
        bind.execute(sa.text("""
            INSERT INTO config_definitions (category, code, name, color, sort_order, extra)
            VALUES ('work_order_type', :code, :name, :color, :sort, CAST(:extra AS jsonb))
        """), {
            "code": code,
            "name": name,
            "color": color,
            "sort": i,
            "extra": json.dumps(extra, ensure_ascii=False),
        })


def downgrade() -> None:
    # 工单类型口径不可逆（source_code 已按新语义回填，无法还原为旧「来源」），
    # 仅清理新增的 work_order_type 配置（业务数据不动）。
    bind = op.get_bind()
    bind.execute(sa.text(
        "DELETE FROM config_definitions WHERE category='work_order_type'"
    ))