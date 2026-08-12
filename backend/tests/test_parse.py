"""听记解析测试（正则 fallback 路径）"""
from app.services.llm_service import parse_minutes, parse_with_regex


def test_parse_multiple_items(db):
    text = """08-04 会议
1. 通辽永兴风电场变桨系统异响排查 王小宁 8月15日前完成
2. 瓮安建中客户投诉处理 于鸿飞"""
    result = parse_minutes(text)
    assert result["engine"] == "regex"
    assert result["count"] >= 2


def test_parse_extracts_person(db):
    text = "1. 变桨排查 王小宁 8月15日前"
    result = parse_with_regex(text)
    assert len(result) >= 1
    # 应能匹配到责任人
    items_with_person = [r for r in result if r.get("person")]
    assert any(r["person"] == "王小宁" for r in items_with_person)


def test_low_confidence_filtered(db):
    """无关内容应得低分"""
    text = "1. 顺便买杯咖啡"
    result = parse_with_regex(text)
    assert len(result) == 1
    assert result[0]["score"] < 5


def test_empty_text(db):
    result = parse_minutes("")
    assert result["count"] == 0
