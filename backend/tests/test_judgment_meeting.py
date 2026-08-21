"""试运营判定会自动建会服务测试。"""
from datetime import date, timedelta

from app.services import judgment_meeting as jm


def _fake_project(**kw):
    class P:
        name = "测试项目"
        entry_date = None
        product_series = None
        judgment_date = None
        judgment_event_id = None
        judgment_status = None
        judgment_error = None
        region = "华北"
    p = P()
    for k, v in kw.items():
        setattr(p, k, v)
    return p


class _FakeDB:
    def commit(self):
        pass


# ── 纯函数 ──────────────────────────────────────────────

def test_age_in_days():
    assert jm.age_in_days("HS100") == 20
    assert jm.age_in_days("HS200") == 20
    assert jm.age_in_days("HS300") == 25
    assert jm.age_in_days("HS300A") == 25
    assert jm.age_in_days("HS400") == 25
    assert jm.age_in_days("HS500") == 40
    assert jm.age_in_days("500Pro") == 40
    assert jm.age_in_days(None) is None
    assert jm.age_in_days("XXX") is None


def test_compute_judgment_date():
    d = date(2026, 8, 20)
    # 判定日 = 入场日期 + (判定天数 - 1)
    assert jm.compute_judgment_date(d, "HS200") == date(2026, 9, 8)   # +19
    assert jm.compute_judgment_date(d, "HS400") == date(2026, 9, 13)  # +24
    assert jm.compute_judgment_date(d, "HS500") == date(2026, 9, 28)  # +39
    assert jm.compute_judgment_date(d, None) is None
    assert jm.compute_judgment_date(d, "未知") is None


def test_agenda_html_contains_key_sections():
    html = jm._agenda_html("中节能通辽永兴")
    for kw in ["试运营判定会议", "会议组织：金惠良", "会议议程", "一页纸SOP", "HS500/500Pro", "红线规定", "转正常运营通知书"]:
        assert kw in html, f"模板缺少 {kw}"


# ── 建会编排（monkeypatch 掉网络）────────────────────────

def test_meeting_skipped_without_entry_or_series():
    assert jm.create_or_update_judgment_meeting(_fake_project(), _FakeDB())["skipped"]
    assert jm.create_or_update_judgment_meeting(
        _fake_project(product_series="HS200"), _FakeDB())["skipped"]  # 无入场日期


def test_meeting_skipped_unknown_series():
    r = jm.create_or_update_judgment_meeting(
        _fake_project(entry_date=date(2026, 8, 20), product_series="HS999"), _FakeDB())
    assert r["skipped"]


def test_meeting_idempotent_when_unchanged():
    p = _fake_project(entry_date=date(2026, 8, 20), product_series="HS200",
                      judgment_date=date(2026, 9, 8), judgment_event_id="evt-123")
    r = jm.create_or_update_judgment_meeting(p, _FakeDB())
    assert r["skipped"] and r["event_id"] == "evt-123"


def test_meeting_created_and_fields_set(monkeypatch):
    monkeypatch.setattr(jm, "build_meeting_args",
                        lambda name, entry, series: {"title": f"{name}试运营判定会议",
                                                      "start": "2026-09-08T10:00:00+08:00",
                                                      "end": "2026-09-08T11:00:00+08:00",
                                                      "attendees": ["u1", "u2"]})
    monkeypatch.setattr(jm, "_create_event", lambda args: "evt-456")
    p = _fake_project(entry_date=date(2026, 8, 20), product_series="HS200")
    r = jm.create_or_update_judgment_meeting(p, _FakeDB())
    assert r["ok"] and r["event_id"] == "evt-456"
    assert p.judgment_date == date(2026, 9, 8)
    assert p.judgment_event_id == "evt-456"
    assert p.judgment_status == "created"
    assert p.judgment_error is None


def test_meeting_failure_records_error(monkeypatch):
    monkeypatch.setattr(jm, "build_meeting_args",
                        lambda name, entry, series: {"title": "t", "start": "s", "end": "e", "attendees": []})
    monkeypatch.setattr(jm, "_create_event", lambda args: (_ for _ in ()).throw(RuntimeError("dws down")))
    p = _fake_project(entry_date=date(2026, 8, 20), product_series="HS200")
    r = jm.create_or_update_judgment_meeting(p, _FakeDB())
    assert not r["ok"]
    assert p.judgment_status == "failed"
    assert "dws down" in (p.judgment_error or "")