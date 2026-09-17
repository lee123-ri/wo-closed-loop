"""normalize project codes to PRJ-####

历史杂码（名称截断码如「三一东丰」「三一平台村、-1」、种子旧码 TL-YX 等）
按 id 顺序统一续编为 PRJ-####；已合规的 PRJ-#### 原样保留。
项目对外引用均走 projects.id 外键，改码无副作用。

Revision ID: f001_normalize_project_codes
Revises: e001_merge_heads
"""
import re
from typing import Union

from alembic import op
from sqlalchemy import text

revision: str = "f001_normalize_project_codes"
down_revision: Union[str, None] = "e001_merge_heads"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

PRJ_RE = re.compile(r"^PRJ-(\d{4,})$")


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(text("SELECT id, code FROM projects ORDER BY id")).fetchall()
    nums = [int(m.group(1)) for _, code in rows if (m := PRJ_RE.match(code))]
    nxt = max(nums, default=0) + 1
    for pid, code in rows:
        if not PRJ_RE.match(code):
            bind.execute(text("UPDATE projects SET code = :code WHERE id = :id"),
                         {"code": f"PRJ-{nxt:04d}", "id": pid})
            nxt += 1


def downgrade() -> None:
    # 旧杂码不可逆恢复，保持现状
    pass
