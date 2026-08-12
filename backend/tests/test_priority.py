"""优先级匹配服务测试"""
from app.services.priority_service import match_priority
from app.models import PriorityRule


def test_match_p1_safety(db):
    assert match_priority(db, "发生人身伤亡事故", "") == "P1"


def test_match_p1_penalty(db):
    assert match_priority(db, "双细则考核扣款超标", "") == "P1"


def test_match_p2_complaint(db):
    assert match_priority(db, "业主投诉满意度低", "") == "P2"


def test_match_p3_routine(db):
    assert match_priority(db, "月度例行盘点归档", "") == "P3"


def test_default_p3(db):
    assert match_priority(db, "无关键字的普通事项", "") == "P3"


def test_order_matters(db):
    """含安全关键词即使也含计划关键词，应为 P1（先匹配）"""
    assert match_priority(db, "安全培训年度计划", "") == "P1"
