"""replace readonly identity with menu access and add project member fallback

Revision ID: p003_menu_access
Revises: o002_align_business_role_scopes
"""
from alembic import op


revision = "p003_menu_access"
down_revision = "o002_align_business_role_scopes"
branch_labels = None
depends_on = None


def upgrade():
    # 旧“只读人员”改为执行人；具体只读能力由每个菜单项的 access 配置决定。
    op.execute("UPDATE users SET role = 'executor' WHERE role = 'readonly'")
    op.execute("""
        INSERT INTO business_roles (code, name, scope_type, is_active, is_system)
        SELECT 'project_member', '项目人员', 'global', true, true
        WHERE NOT EXISTS (SELECT 1 FROM business_roles WHERE code = 'project_member')
    """)
    op.execute("""
        INSERT INTO role_data_scopes (role_code, role_name, scopes, is_locked, sort_order)
        SELECT 'project_member', '项目人员', jsonb_build_array('self'), false, 99
        WHERE NOT EXISTS (SELECT 1 FROM role_data_scopes WHERE role_code = 'project_member')
    """)


def downgrade():
    # 不能可靠地识别迁移前哪些人是 readonly，故不回写用户身份。
    op.execute("DELETE FROM role_data_scopes WHERE role_code = 'project_member'")
    op.execute("DELETE FROM business_roles WHERE code = 'project_member'")
