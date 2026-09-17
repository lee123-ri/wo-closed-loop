"""年度运营计划时间列解析回归（纯 stdlib，沙盒可跑）。

覆盖 drive_workorder_import 新依赖的 plan_time 解析：
「计划时间 / 时间窗口」各种写法 → (计划开始, 截止)。
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.plan_time import parse_deadline, parse_time_window  # noqa: E402

D = date


def test_full_year():
    assert parse_time_window("2026年全年") == (D(2026, 1, 1), D(2026, 12, 31))
    assert parse_time_window("2026年全年持续") == (D(2026, 1, 1), D(2026, 12, 31))


def test_month_list():
    assert parse_time_window("2026年4月、10月") == (D(2026, 4, 1), D(2026, 10, 31))


def test_month_ranges():
    assert parse_time_window("4-5月、9-10月") == (D(2026, 4, 1), D(2026, 10, 31))
    assert parse_time_window("7-9月") == (D(2026, 7, 1), D(2026, 9, 30))
    assert parse_time_window("2027年2-3月") == (D(2027, 2, 1), D(2027, 3, 31))


def test_date_range():
    assert parse_time_window("2026-06-01~06-07") == (D(2026, 6, 1), D(2026, 6, 7))
    assert parse_time_window("2026-06-01~2026-06-07") == (D(2026, 6, 1), D(2026, 6, 7))


def test_open_ended_range():
    assert parse_time_window("2026-06~并网日") == (D(2026, 6, 1), None)
    assert parse_time_window("入场~并网日") == (None, None)


def test_before_month():
    assert parse_time_window("2026年6月前完成测评") == (None, D(2026, 6, 30))


def test_since_month():
    assert parse_time_window("2026年3月起执行") == (D(2026, 3, 1), D(2026, 12, 31))
    assert parse_time_window("2026年1月起常态执行") == (D(2026, 1, 1), D(2026, 12, 31))


def test_recurring():
    assert parse_time_window("每月") == (None, D(2026, 12, 31))
    assert parse_time_window("持续") == (None, D(2026, 12, 31))
    assert parse_time_window("2月/次") == (None, D(2026, 12, 31))


def test_duration_months_no_fake_date():
    # 「X个月内」是时长不是时点，不臆造日期
    assert parse_time_window("并网6个月内") == (None, None)
    assert parse_time_window("并网起6个月内") == (None, None)


def test_single_date():
    assert parse_time_window("2026-12-31") == (None, D(2026, 12, 31))


def test_no_month_fallback():
    assert parse_time_window("2026年供暖季前落实") == (None, D(2026, 12, 31))


def test_empty():
    assert parse_time_window("") == (None, None)
    assert parse_time_window(None) == (None, None)


def test_parse_deadline_compat():
    assert parse_deadline("2026年全年") == D(2026, 12, 31)
    assert parse_deadline("2026-10-01 00:00:00") == D(2026, 10, 1)
    assert parse_deadline("") is None
    assert parse_deadline("2026-06-01~06-07") == D(2026, 6, 7)
