"""Integration tests with a dedicated PostgreSQL database and synthetic records.

Run from backend/ with ../tests/test_pmomini_bridge_db.py. Never resets main DB.
"""
from datetime import date, timedelta
import os
from pathlib import Path
import sys
import unittest

if __name__ != "__main__":
    raise unittest.SkipTest("Run this isolated PostgreSQL check explicitly as documented; no collection-time DB changes")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import get_settings
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

source = make_url(get_settings().database_url)
test_name = "wo_pmomini_20261023_test"
assert test_name.endswith("_test") and test_name != source.database
admin_engine = create_engine(source.set(database="postgres"), isolation_level="AUTOCOMMIT")
with admin_engine.connect() as connection:
    exists = connection.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": test_name}).scalar()
    if not exists:
        connection.execute(text('CREATE DATABASE "' + test_name + '"'))
admin_engine.dispose()
os.environ["DATABASE_URL"] = source.set(database=test_name).render_as_string(hide_password=False)
get_settings.cache_clear()

from app.core.database import Base, engine, SessionLocal
from app.models import ConfigDefinition, Project, User, WorkOrder, SLADefinition
from pmomini_bridge.data import query_session, QueryBlocked, query
from test_pmomini_bridge import event, plan
from sqlalchemy.exc import DBAPIError


class DatabaseIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert engine.url.database == test_name
        Base.metadata.create_all(engine)

    def setUp(self):
        self.db = SessionLocal()
        self.a = User(name="桥接测试人员", dingtalk_id="test-user", role="executor", is_active=True)
        self.b = User(name="桥接测试他人", dingtalk_id="test-other", role="executor", is_active=True)
        self.admin = User(name="桥接测试管理员", dingtalk_id="test-admin", role="admin", is_active=True)
        self.p = Project(code="PMOMINI-SYNTHETIC-A", name="桥接测试项目A", region="华北", is_active=True)
        self.p2 = Project(code="PMOMINI-SYNTHETIC-B", name="桥接测试项目B", region="华南", is_active=True)
        self.db.add_all([self.a,self.b,self.admin,self.p,self.p2]);self.db.flush()
        for status in ["executing","pending","closed"]:
            self.db.add(ConfigDefinition(category="status",code=status,name=status))
        today=date.today()
        for code, person, project, status in [
            ("RW-9999-00001",self.a,self.p,"executing"),
            ("RW-9999-00002",self.b,self.p2,"executing"),
            ("RW-9999-00003",self.a,self.p,"pending"),
            ("RW-9999-00004",self.a,self.p,"closed")]:
            self.db.add(WorkOrder(code=code,title="合成验证记录",person_id=person.id,project_id=project.id,
                                  source_code="plan",region=project.region,priority="P2",status=status,created_date=today,deadline=today-timedelta(days=2)))
        self.db.flush()

    def tearDown(self):
        self.db.rollback();self.db.close()

    def test_private_scope_excludes_other_person(self):
        result=query_session(self.db,plan("stats"),event(),{})
        self.assertEqual(result["total"],3)

    def test_overdue_excludes_pending_and_closed(self):
        result=query_session(self.db,plan("overdue"),event(),{})
        self.assertEqual(result["total"],1)

    def test_group_missing_range_blocks(self):
        with self.assertRaises(QueryBlocked): query_session(self.db,plan(),event(conversationType="2"),{})

    def test_group_range_intersects_person_scope(self):
        result=query_session(self.db,plan("stats"),event(conversationType="2"),{"test-chat":[self.p2.id]})
        self.assertEqual(result["total"],0)

    def test_admin_still_limited_by_group(self):
        result=query_session(self.db,plan("stats"),event(senderStaffId="test-admin",conversationType="2"),{"test-chat":[self.p2.id]})
        self.assertEqual(result["total"],1)

    def test_unmapped_staff_and_unknown_filter_block(self):
        with self.assertRaises(QueryBlocked): query_session(self.db,plan(),event(senderStaffId="unknown"),{})
        with self.assertRaises(QueryBlocked): query_session(self.db,plan(status="made_up"),event(),{})
        with self.assertRaises(QueryBlocked): query_session(self.db,plan(region="北京"),event(),{})

    def test_model_cannot_invent_workorder_code(self):
        with self.assertRaises(QueryBlocked): query_session(self.db,plan("work_order",work_order_code="RW-9999-00001"),event(),{})

    def test_duplicate_staff_mapping_blocks(self):
        self.db.add(User(name="重名映射",dingtalk_id="test-user",role="executor",is_active=True));self.db.flush()
        with self.assertRaises(QueryBlocked): query_session(self.db,plan(),event(),{})

    def test_sla_policy_reads_config_and_distinguishes_notifications(self):
        self.db.add(SLADefinition(priority="P2", deadline_days=11, warn_before_hours=99, escalate_hours=99,
            followup_nodes=[
                {"code":"before", "enabled":True, "offset_days":-4, "level":0,
                 "channels":["robot_group"], "recipients":{"group_id":"private-group-id"}},
                {"code":"after", "enabled":False, "offset_days":2, "level":1}]))
        self.db.flush()
        result = query_session(self.db, plan("sla_policy"), event(), {})
        self.assertIn("默认截止11天", result["answer"])
        self.assertIn("截止前4天", result["answer"])
        self.assertIn("未配置逾期或更高等级", result["answer"])
        self.assertIn("未核验任务执行或实际送达", result["answer"])
        self.assertNotIn("private-group-id", str(result))
        row = self.db.query(SLADefinition).filter_by(priority="P2").one()
        row.followup_nodes = [{"code":"after", "offset_days":5, "level":2,
                              "channels":["robot_private"], "recipients":{"responsible":True}}]
        self.db.flush()
        changed = query_session(self.db, plan("sla_policy"), event(), {})
        self.assertIn("逾期后5天", changed["answer"])
        self.assertIn("私聊：责任人", changed["answer"])
        self.assertNotIn("未配置逾期或更高等级", changed["answer"])

    def test_sla_policy_empty_nodes_never_uses_legacy_defaults(self):
        self.db.add(SLADefinition(priority="P1", deadline_days=2, warn_before_hours=99,
                                  escalate_hours=99, followup_nodes=[]))
        self.db.flush()
        answer = query_session(self.db, plan("sla_policy"), event(), {})["answer"]
        self.assertIn("未配置启用的跟催节点", answer)
        self.assertNotIn("99", answer)
        with self.assertRaises(QueryBlocked):
            query_session(self.db, plan("sla_policy"), event(conversationType="2"), {})
        with self.assertRaises(QueryBlocked):
            query_session(self.db, plan("sla_policy"), event(senderStaffId="unknown"), {})
        with self.assertRaises(QueryBlocked):
            query_session(self.db, plan("sla_policy", region="华北"), event(), {})

    def test_sla_invalid_node_does_not_claim_complete_policy(self):
        self.db.add(SLADefinition(priority="P3", deadline_days=7, warn_before_hours=1,
            escalate_hours=1, followup_nodes=[{"code":"bad", "offset_days":"later", "level":1}]))
        self.db.flush()
        result = query_session(self.db, plan("sla_policy"), event(), {})
        self.assertFalse(result["policies"][0]["complete"])
        self.assertIn("本次规则不完整", result["answer"])
        self.assertNotIn("未配置逾期或更高等级", result["answer"])

    def test_postgresql_readonly_transaction_denies_writes(self):
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            with self.assertRaises(DBAPIError): conn.execute(text("UPDATE users SET name=name WHERE false"))
            conn.rollback()


if __name__ == "__main__": unittest.main()
