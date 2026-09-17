"""异常指标大类分类器单元测试（纯逻辑，无 DB/无 fastapi）。

沙盒可跑：pytest --noconftest tests/test_metric_types.py
（--noconftest 跳过依赖 fastapi/PG 的 conftest，本文件只 import 纯函数。）
"""
import pytest

from app.services.metric_types import classify_metric_type, CATEGORY_ORDER

# 实测 42 种 abnormal_type 的非空值 → 期望大类（源自 backup_wo_20260903.sql 去重全集）
_EXPECTED = {
    "power_gen": [
        "全年累计电量完成率低于90%",
        "每50MW计划损失电量",
        "每50MW发电设备-年故障损失电量",
        "每50MW变电设备-年故障损失电量",
        "电量指标-2026上半年发电量完成率偏低",
        "每50MW风机损失超过标准",
        "损失电量-计划性停机损失电量超对标值",
        "损失电量-变电故障损失电量超对标值",
        "损失电量-风机故障损失电量超对标值",
    ],
    "reliability": [
        "B.5 变配电设备可利用率-实际值",
        "B.9.1 整场风机可利用率-实际值",
        "B.11 平均故障时长-实际值",
        "B.8 变电设备故障时长-实际值",
        "B.10 故障频次-实际值",
        "每50MW计划性停机超过标准",
        "每50MW变电故障超过标准",
    ],
    "curtailment": [
        "全年累计还原限电小时数低于下边界",
        "全年累计还原限电小时数高于上边界",
        "限电指标-2026年上半年比2025年上半年增幅较多",
    ],
    "dual_rule": ["双细则考核指标-低于中位数"],
    "info_quality": [
        "信息化使用-新建工单未派发未执行",
        "信息化使用-0缺陷",
        "信息化使用-故障延迟上报条数",
        "信息化使用-故障管理-漏报值",
        "信息化使用-未按时上传风机离线数据",
        "信息化使用-EAM无巡检计划工单",
    ],
    "contract": [
        "应签未签-正在沟通考核",
        "应签未签-单据修改中",
        "应签未签-签约延误",
        "应签未签-P0风险（逾期天数超合同期）",
        "应签未签-P0风险（逾期天数超历史最高）",
        "应签未签-P1风险（逾期天数超P90）",
    ],
    "cost": [
        "人工成本超支-实际值多于计划值",
        "车辆成本超支-实际值多于计划值",
        "日常费用-实际值多于计划值",
        "生产成本-实际值多于计划值",
        "成本管理-备品备件审批超预算",
        "成本管理-安全专项费用执行率低于10%",
        "成本管理-外委费用执行率低于10%",
    ],
    "satisfaction": [
        "客户满意度有效建议",
        "客户满意度≤80分",
    ],
}


@pytest.mark.parametrize("code, texts", list(_EXPECTED.items()))
def test_each_category_classified(code, texts):
    for t in texts:
        assert classify_metric_type(t) == code, f"「{t}」应归 {code}"


def test_all_real_values_cover_every_category():
    """8 大类都有样本、且无样本落空——回归时若漏返回 None 直接红。"""
    assert set(_EXPECTED) == set(CATEGORY_ORDER)


def test_empty_or_none_returns_none():
    assert classify_metric_type(None) is None
    assert classify_metric_type("") is None
    assert classify_metric_type("   ") is None


def test_ambiguous_orderings():
    """区分度争议点：含「计划性停机」但带「损失电量」的归发电量，纯计划性停机归可靠性。"""
    assert classify_metric_type("损失电量-计划性停机损失电量超对标值") == "power_gen"
    assert classify_metric_type("每50MW计划性停机超过标准") == "reliability"
    assert classify_metric_type("每50MW变电故障超过标准") == "reliability"
    assert classify_metric_type("每50MW风机损失超过标准") == "power_gen"