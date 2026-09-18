"""simplify project-side business roles

Revision ID: p004_simplify_roles
Revises: p003_menu_access
"""
from alembic import op


revision = "p004_simplify_roles"
down_revision = "p003_menu_access"
branch_labels = None
depends_on = None


REMOVED_ROLE_CODES = ("site_member", "inspection_engineer", "project_manager")


def upgrade():
    # 迁移前已核对线上本地库没有这三类岗位的分配；仍先删除关联行，
    # 以兼容后续数据环境中可能残留的历史分配。
    role_codes = ", ".join(f"'{code}'" for code in REMOVED_ROLE_CODES)
    op.execute(f"""
        DELETE FROM business_role_assignments
        WHERE business_role_id IN (
            SELECT id FROM business_roles WHERE code IN ({role_codes})
        )
    """)
    op.execute(f"DELETE FROM role_data_scopes WHERE role_code IN ({role_codes})")
    op.execute(f"DELETE FROM business_roles WHERE code IN ({role_codes})")
    op.execute("UPDATE business_roles SET name = '事业部PMO' WHERE code = 'pmo'")
    op.execute("UPDATE role_data_scopes SET role_name = '事业部PMO' WHERE role_code = 'pmo'")


def downgrade():
    op.execute("UPDATE business_roles SET name = 'PMO' WHERE code = 'pmo'")
    op.execute("UPDATE role_data_scopes SET role_name = 'PMO' WHERE role_code = 'pmo'")
    for code, name in (
        ("site_member", "场站人员"),
        ("inspection_engineer", "运检工程师"),
        ("project_manager", "项目经理"),
    ):
        op.execute(f"""
            INSERT INTO business_roles (code, name, scope_type, is_active, is_system)
            SELECT '{code}', '{name}', 'project', true, true
            WHERE NOT EXISTS (SELECT 1 FROM business_roles WHERE code = '{code}')
        """)
        op.execute(f"""
            INSERT INTO role_data_scopes (role_code, role_name, scopes, is_locked, sort_order)
            SELECT '{code}', '{name}', jsonb_build_array('self'), false, 100
            WHERE NOT EXISTS (SELECT 1 FROM role_data_scopes WHERE role_code = '{code}')
        """)
