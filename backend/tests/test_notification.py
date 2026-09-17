"""派发→钉钉提醒 通知链路测试。

覆盖：通知策略解析、消息构造、工作通知(工作通知 asyncsend_v2) payload、
群机器人 webhook 加签、trigger_notify / _trigger_notify 事件映射、数据池派发触发。
真实钉钉 HTTP 一律 mock（httpx.post），不打真网络。
"""
from datetime import date

from app.models import WorkOrder
from app.services import notification_service as ns
from app.services import dingtalk as dt


# ── 策略解析 / 消息构造（纯逻辑，走 db fixture，无需网络）──────────────

def test_resolve_channels_dispatch(db):
    channels = ns.resolve_channels(db, "P1", "dispatch")
    assert "work_notify" in channels
    assert "robot_mention" in channels


def test_build_message_contains_fields(db):
    wo = WorkOrder(
        code="RW-2026-0001", title="测试工单标题", priority="P1",
        deadline=date.today(), status="dispatched",
        person_id=1, approver_id=11,
    )
    title, body = ns.build_message(wo, "dispatch", db)
    assert "新工单待处理" in title
    assert wo.code in title
    assert wo.title in body
    assert "责任人" in body and "审批人" in body


# ── 工作通知（asyncsend_v2 payload，mock httpx）──────────────

class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def test_send_work_notification_uses_asyncsend_v2(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kw):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp({"errcode": 0, "errmsg": "ok", "task_id": 1})

    monkeypatch.setattr(dt, "_configured", lambda: True)
    monkeypatch.setattr(dt.settings, "dingtalk_agent_id", "123456")
    monkeypatch.setattr(dt, "get_access_token", lambda: "tok")
    monkeypatch.setattr(dt.httpx, "post", fake_post)

    ok = dt.send_work_notification("u001", "标题", "正文", action_url="http://x/work-orders/1")
    assert ok is True
    assert "/topapi/message/corpconversation/asyncsend_v2" in captured["url"]
    assert "access_token=tok" in captured["url"]
    body = captured["json"]
    assert body["agent_id"] == 123456
    assert body["userid_list"] == "u001"
    assert body["msg"]["msgtype"] == "action_card"
    assert body["msg"]["action_card"]["markdown"]
    assert body["msg"]["action_card"]["btn_json_list"][0]["action_url"] == "http://x/work-orders/1"


def test_send_work_notification_skips_without_agent_id(monkeypatch):
    monkeypatch.setattr(dt, "_configured", lambda: True)
    monkeypatch.setattr(dt.settings, "dingtalk_agent_id", "")
    called = []
    monkeypatch.setattr(dt.httpx, "post", lambda *a, **k: called.append(1) or _FakeResp({}))
    assert dt.send_work_notification("u001", "t", "c") is False
    assert called == []


def test_send_work_notification_failure_errcode(monkeypatch):
    monkeypatch.setattr(dt, "_configured", lambda: True)
    monkeypatch.setattr(dt.settings, "dingtalk_agent_id", "123456")
    monkeypatch.setattr(dt, "get_access_token", lambda: "tok")
    monkeypatch.setattr(dt.httpx, "post", lambda *a, **k: _FakeResp({"errcode": 88, "errmsg": "invalid userid"}))
    assert dt.send_work_notification("u001", "t", "c") is False


# ── 群机器人（webhook + 加签，mock httpx）──────────────

def test_send_robot_group_posts_and_signs(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None, **kw):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp({"errcode": 0})

    monkeypatch.setattr(dt.httpx, "post", fake_post)
    ok = dt.send_robot_group(
        "https://oapi.dingtalk.com/robot/send?access_token=abc", "sec",
        "标题", "正文", at_userids=["u001"],
    )
    assert ok is True
    assert "access_token=abc" in captured["url"]
    assert "timestamp=" in captured["url"] and "sign=" in captured["url"]
    body = captured["json"]
    assert body["msgtype"] == "markdown"
    assert body["at"]["atUserIds"] == ["u001"]


# ── 通知触发入口 / 事件映射 ──────────────

def test_trigger_notify_calls_task(monkeypatch):
    from app.tasks import send_notification_task
    captured = []
    monkeypatch.setattr(send_notification_task, "delay", lambda wo_id, event: captured.append((wo_id, event)))
    ns.trigger_notify(42, "dispatch")
    assert captured == [(42, "dispatch")]


def test_trigger_notify_swallows_exception(monkeypatch):
    from app.tasks import send_notification_task
    def boom(wo_id, event):
        raise RuntimeError("broker down")
    monkeypatch.setattr(send_notification_task, "delay", boom)
    # 不应向外抛异常
    ns.trigger_notify(1, "dispatch")


def test__trigger_notify_mapping(monkeypatch):
    from app.api.workorders import _trigger_notify
    notified = []
    grouped = []
    monkeypatch.setattr(ns, "trigger_notify", lambda wid, ev: notified.append((wid, ev)))
    monkeypatch.setattr(ns, "trigger_dispatch_group", lambda ids: grouped.append(ids))
    _trigger_notify(7, "dispatch", "dispatched")
    _trigger_notify(8, "submit_evidence", "verifying")
    _trigger_notify(9, "start_exec", "executing")
    assert grouped == [[7]]
    assert notified == [(8, "sla_warn")]


# ── 数据池派发触发 ──────────────

def test_pool_notify_dispatched(monkeypatch):
    from app.services.pool_service import _notify_dispatched
    captured = []
    monkeypatch.setattr(ns, "trigger_dispatch_group", lambda ids: captured.append(ids))
    _notify_dispatched([3, 4, 5])
    assert captured == [[3, 4, 5]]
    _notify_dispatched([])
    assert captured == [[3, 4, 5]]


def test_detail_url_absolute(monkeypatch):
    monkeypatch.setattr(ns.settings, "frontend_base_url", "https://wo.example.com")
    assert ns._detail_url(12) == "https://wo.example.com/work-orders/12"
    monkeypatch.setattr(ns.settings, "frontend_base_url", "")
    assert ns._detail_url(12) == ""


# ── 机器人发群（合并，groupMessages/send）──────────────

def test_send_group_markdown_payload(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp({"processQueryKey": "K1"})

    monkeypatch.setattr(dt.settings, "dingtalk_robot_code", "dinghxbxwotbgkuhxs7d")
    monkeypatch.setattr(dt.settings, "dingtalk_notify_group_id", "cidXXX")
    monkeypatch.setattr(dt, "get_new_access_token", lambda: "tok")
    monkeypatch.setattr(dt.httpx, "post", fake_post)

    ok = dt.send_group_markdown("**李沛东**\n- [RW-1 标题](http://x/work-orders/1)")
    assert ok is True
    assert "/v1.0/robot/groupMessages/send" in captured["url"]
    body = captured["json"]
    assert body["robotCode"] == "dinghxbxwotbgkuhxs7d"
    assert body["openConversationId"] == "cidXXX"
    assert body["msgKey"] == "sampleMarkdown"
    assert "李沛东" in body["msgParam"]
    assert "/work-orders/1" in body["msgParam"]


def test_send_group_markdown_skips_unconfigured(monkeypatch):
    monkeypatch.setattr(dt.settings, "dingtalk_robot_code", "")
    monkeypatch.setattr(dt.settings, "dingtalk_notify_group_id", "")
    called = []
    monkeypatch.setattr(dt.httpx, "post", lambda *a, **k: called.append(1) or _FakeResp({}))
    assert dt.send_group_markdown("x") is False
    assert called == []


def test_build_dispatch_group_markdown_groups_by_person(db):
    from app.models import User
    p1 = db.get(User, 1).name
    p2 = db.get(User, 2).name
    w1 = WorkOrder(code="RW-1", title="甲", status="dispatched", person_id=1, source_code="alert", priority="P1", created_date=date.today())
    w2 = WorkOrder(code="RW-2", title="乙", status="dispatched", person_id=1, source_code="alert", priority="P1", created_date=date.today())
    w3 = WorkOrder(code="RW-3", title="丙", status="dispatched", person_id=2, source_code="alert", priority="P2", created_date=date.today())
    for w in (w1, w2, w3):
        db.add(w)
    db.flush()
    chunks = ns.build_dispatch_group_markdown(db, [w1.id, w2.id, w3.id])
    assert len(chunks) == 2  # 两个责任人 → 两条消息
    joined = "\n".join(chunks)
    assert "RW-1" in joined and "RW-2" in joined and "RW-3" in joined
    assert p1 in joined and p2 in joined
    assert "/work-orders/" in joined  # 每条都带详情链接


# ── 场景1/2 文案与分组（@责任人 / 找不到 @刘冰）──────────────

def test_short_title_strips_sxz():
    assert ns._short_title("SXZ-20260910-01 协合四马桥 AVC投运率") == "协合四马桥 AVC投运率"
    assert ns._short_title("协合四马桥-损失电量异常") == "协合四马桥-损失电量异常"


def test_notify_anomaly_new_groups_and_fallback(db, monkeypatch):
    monkeypatch.setattr(ns, "SessionLocal", lambda: db)
    monkeypatch.setattr(ns.settings, "dingtalk_fallback_userid", "LIUBING")
    sent = []
    monkeypatch.setattr(ns, "_send_group", lambda text, at: sent.append((text, at)) or True)

    w1 = WorkOrder(code="RW-1", title="协合四马桥-损失电量异常", status="judging", person_id=1, priority="P1", source_code="alert", created_date=date.today())
    w2 = WorkOrder(code="RW-2", title="SXZ-20260910-01 四马桥 AVC投运率", status="judging", person_id=None, priority="P2", source_code="alert", created_date=date.today())
    db.add(w1)
    db.add(w2)
    db.flush()

    out = ns.notify_anomaly_new([w1.id, w2.id])
    assert out["total_wo"] == 2
    assert len(sent) == 2  # 一组责任人 + 一组未匹配
    texts = [t for t, _ in sent]
    # 未匹配组 @ 兜底(刘冰)
    orphan_at = [at for t, at in sent if "未匹配责任人" in t]
    assert orphan_at == [["LIUBING"]]
    # SXZ 编号被去掉，字段带上 优先级/截止
    assert "SXZ-" not in "\n".join(texts)
    assert "损失电量异常" in texts[0]


def test_notify_measure_dispatch_text(db, monkeypatch):
    monkeypatch.setattr(ns, "SessionLocal", lambda: db)
    sent = []
    monkeypatch.setattr(ns, "_send_group", lambda text, at: sent.append((text, at)) or True)

    host = WorkOrder(code="RW-H", title="协合四马桥-损失电量异常", status="judging", person_id=1, priority="P1", source_code="alert", created_date=date.today())
    db.add(host)
    db.flush()
    m1 = WorkOrder(code="RW-M1", title="更换SVG散热风扇", status="dispatched", person_id=3, priority="P1", source_code="measure", created_date=date.today())
    m2 = WorkOrder(code="RW-M2", title="核对AVC定值", status="dispatched", person_id=4, priority="P1", source_code="measure", created_date=date.today())
    db.add(m1)
    db.add(m2)
    db.flush()

    out = ns.notify_measure_dispatch(host.id, [m1.id, m2.id])
    assert out["total_wo"] == 2
    assert len(sent) == 1
    text, at = sent[0]
    assert "处置完成" in text           # 首行点完成人
    assert "损失电量异常" in text       # 异常来源
    assert "更换SVG散热风扇" in text and "核对AVC定值" in text
    assert "RW-" not in text            # 不带编号