"""统计卡的列表筛选与 /dashboard/mine 计数保持同一口径。"""


def test_dashboard_buckets_match_list_totals(client_auth):
    stats_response = client_auth.get("/api/dashboard/mine")
    assert stats_response.status_code == 200
    stats = stats_response.json()["stats"]

    for bucket in ("pending", "executing", "need_backfill"):
        response = client_auth.get("/api/work-orders", params={"scope": "personal", "role": "all", "bucket": bucket})
        assert response.status_code == 200
        assert response.json()["total"] == stats[bucket], bucket


def test_unknown_dashboard_bucket_rejected(client_auth):
    response = client_auth.get("/api/work-orders", params={"bucket": "not-a-bucket"})
    assert response.status_code == 422
