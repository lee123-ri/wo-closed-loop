"""探测机器人发群：试两个候选 robotCode，确定真正能发群的那个。

本机跑：
    cd ~/Documents/work/wo-closed-loop/backend
    .venv/bin/python ../scripts/probe_robot_notify.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import httpx

from app.services import dingtalk as dt

CONV_ID = "cidtSHb8Ry9XOmGVBPITSEJ8A=="  # [Task] A-双细则 agent 群
CANDIDATES = [
    "ding45a26afb1f06aadcf5bf40eda33b7ba0",   # 用户最初给的（ding+32hex，标准 robotCode 形态）
    "dinghxbxwotbgkuhxs7d",                    # =AppKey，用户说「开通的」
]

token = dt.get_new_access_token()
print("[token]", "ok" if token else "MISSING")
if not token:
    raise SystemExit(1)

headers = {"x-acs-dingtalk-access-token": token, "Content-Type": "application/json"}
url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"

markdown = (
    "**工单派发提醒（合并测试）**\n\n"
    "- [RW-2026-0001 测试工单一](http://10.10.147.200:5173/work-orders/1)\n"
    "- [RW-2026-0002 测试工单二](http://10.10.147.200:5173/work-orders/2)"
)

for rc in CANDIDATES:
    body = {
        "robotCode": rc,
        "openConversationId": CONV_ID,
        "msgKey": "sampleMarkdown",
        "msgParam": json.dumps({"title": "工单派发提醒", "text": markdown}, ensure_ascii=False),
    }
    r = httpx.post(url, headers=headers, json=body, timeout=15)
    print(f"[robotCode={rc[:22]}…] HTTP {r.status_code} -> {r.text[:400]}")