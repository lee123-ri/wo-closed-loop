"""align business roles with configurable data scopes

Revision ID: o002_align_business_role_scopes
Revises: n001_add_unified_role_center
"""
from alembic import op


revision = "o002_align_business_role_scopes"
down_revision = "n001_add_unified_role_center"
branch_labels = None
depends_on = None


def upgrade():
    # 用岗位编码而非旧的 member/division_pmo 等派生角色配置数据范围。
    # 只补行，不删除旧行，确保已部署库可平滑回滚和审计。
    op.execute("""
        INSERT INTO role_data_scopes (role_code, role_name, scopes, is_locked, sort_order)
        SELECT
            business_roles.code,
            business_roles.name,
            CASE business_roles.code
                WHEN 'pmo' THEN jsonb_build_array('all')
                WHEN 'regional_pmo' THEN jsonb_build_array('self', 'region')
                WHEN 'regional_gm' THEN jsonb_build_array('self', 'region')
                WHEN 'regional_deputy_gm' THEN jsonb_build_array('self', 'region')
                ELSE jsonb_build_array('self')
            END,
            false,
            100
        FROM business_roles
        WHERE NOT EXISTS (
            SELECT 1 FROM role_data_scopes
            WHERE role_data_scopes.role_code = business_roles.code
        )
    """)


def downgrade():
    op.execute("""
        DELETE FROM role_data_scopes
        WHERE role_code IN (
            'site_member', 'inspection_engineer', 'project_manager', 'pmo',
            'regional_pmo', 'regional_gm', 'regional_deputy_gm', 'headquarters_member'
        )
    """)
