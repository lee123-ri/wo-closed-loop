"""主列表默认归档回归：已闭环(closed)工单默认不在主列表显示，归档视图不受影响。

背景（2026-09-03）：主列表定位为「活跃工作台」，已闭环工单默认归档，
在「闭环记录」页（/work-orders/closed/list）查看。
- 默认 GET /work-orders 排除 closed；
- include_closed=true 可含归档；
- 显式 status=closed 视为查归档，仍返回 closed；
- /work-orders/closed/list 归档列表不受影响。
"""


def test_seed_contains_closed_sanity(client_auth):
    """种子数据确含已闭环工单——保证下面「排除」断言不是空转。"""
    r = client_auth.get("/api/work-orders/closed/list", params={"page_size": 100})
    assert r.status_code == 200
    assert r.json()["total"] > 0


def test_default_list_excludes_closed(client_auth):
    r = client_auth.get("/api/work-orders", params={"page_size": 100})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] > 0
    assert "closed" not in {w["status"] for w in data["items"]}


def test_include_closed_returns_closed(client_auth):
    r = client_auth.get("/api/work-orders", params={"include_closed": True, "page_size": 100})
    assert r.status_code == 200
    data = r.json()
    assert "closed" in {w["status"] for w in data["items"]}


def test_explicit_status_closed_still_queryable(client_auth):
    """显式按状态查 closed 视为查归档，不被默认过滤吞掉。"""
    r = client_auth.get("/api/work-orders", params={"status": "closed", "page_size": 100})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] > 0
    assert {w["status"] for w in data["items"]} == {"closed"}


def test_closed_list_unaffected(client_auth):
    r = client_auth.get("/api/work-orders/closed/list", params={"page_size": 100})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] > 0
    assert {w["status"] for w in data["items"]} == {"closed"}
