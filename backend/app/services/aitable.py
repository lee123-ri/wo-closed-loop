"""钉钉 AI 表格 API 封装

用于从王宁维护的多维表读取数据，以及回填回写。
"""
from typing import Any

import httpx

from app.core.config import get_settings

settings = get_settings()
_API = "https://api.dingtalk.com"


def _token() -> str | None:
    from app.services.dingtalk import get_access_token
    return get_access_token()


def _headers(token: str | None) -> dict:
    return {"x-acs-dingtalk-access-token": token or "", "Content-Type": "application/json"}


def get_aitable_records(base_id: str, table_id: str,
                         page_size: int = 200, max_records: int = 2000) -> list[dict]:
    """拉取 AI 表格记录列表"""
    if not settings.dingtalk_app_key:
        print("[aitable] 未配置钉钉 app key，跳过")
        return []
    token = _token()
    records: list[dict] = []
    next_token = ""
    while len(records) < max_records:
        body: dict[str, Any] = {"maxResults": min(page_size, max_records - len(records))}
        if next_token:
            body["nextToken"] = next_token
        try:
            resp = httpx.get(
                f"{_API}/v1.0/aitable/bases/{base_id}/tables/{table_id}/records",
                headers=_headers(token),
                params=body,
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"[aitable] 读取失败: {resp.status_code} {resp.text[:200]}")
                break
            data = resp.json()
            records.extend(data.get("records", []))
            next_token = data.get("nextToken", "")
            if not data.get("hasMore") or not next_token:
                break
        except Exception as e:
            print(f"[aitable] 读取异常: {e}")
            break
    return records


def update_aitable_record(source_ref: str, fields: dict[str, Any]) -> bool:
    """更新 AI 表格中的一条记录"""
    if not settings.dingtalk_app_key:
        return False
    token = _token()
    try:
        resp = httpx.put(
            f"{_API}/v1.0/aitable/records/{source_ref}",
            headers=_headers(token),
            json={"fields": fields},
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        print(f"[aitable] 更新失败: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        print(f"[aitable] 更新异常: {e}")
    return False