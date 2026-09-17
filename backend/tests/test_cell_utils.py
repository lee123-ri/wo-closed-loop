"""cell_utils.cell_to_text 抽取逻辑回归（纯函数，沙盒可跑 --noconftest）。

覆盖钉钉 AI 表格各字段类型取值结构，重点是 filterUp 查找引用（含多选嵌套），
对应 2026-09-11 上游改表后新增的「整改人」「原因分类」等 filterUp 字段。
"""
from app.services.cell_utils import cell_to_text


def test_none_and_scalar():
    assert cell_to_text(None) == ""
    assert cell_to_text("") == ""
    assert cell_to_text("文本") == "文本"
    assert cell_to_text(123) == "123"
    assert cell_to_text(4.5) == "4.5"


def test_single_select_dict():
    assert cell_to_text({"id": "x", "name": "信发小草湖"}) == "信发小草湖"


def test_dict_with_text_key():
    assert cell_to_text({"text": "一段说明"}) == "一段说明"


def test_filterup_single_select():
    v = {"refFieldType": "singleSelect", "value": [{"id": "z", "name": "已完成"}]}
    assert cell_to_text(v) == "已完成"


def test_filterup_multiple_select_nested():
    # 多选 filterUp：value 是嵌套 list [[{id,name}, ...]]
    v = {"refFieldType": "multipleSelect", "value": [[{"id": "d", "name": "不可抗力"}]]}
    assert cell_to_text(v) == "不可抗力"


def test_filterup_multiple_select_multi_value():
    v = {"refFieldType": "multipleSelect",
         "value": [[{"id": "a", "name": "不可抗力"}, {"id": "b", "name": "设备老化"}]]}
    assert cell_to_text(v) == "不可抗力, 设备老化"


def test_filterup_text():
    v = {"refFieldType": "text", "value": ["已完成"]}
    assert cell_to_text(v) == "已完成"


def test_filterup_number():
    v = {"refFieldType": "number", "value": [46112]}
    assert cell_to_text(v) == "46112"


def test_filterup_empty_value():
    assert cell_to_text({"refFieldType": "singleSelect", "value": []}) == ""


def test_plain_list_of_dicts():
    assert cell_to_text([{"name": "a"}, {"name": "b"}]) == "a, b"


def test_filterup_user_field_nested():
    # 双细则表「责任人」字段：[[{name,uid}],[{name,uid}]]（同一人重复出现）
    v = {"refFieldType": "user",
         "value": [[{"name": "雷江涛", "uid": "644175426"}],
                   [{"name": "雷江涛", "uid": "644175426"}]]}
    assert cell_to_text(v) == "雷江涛, 雷江涛"