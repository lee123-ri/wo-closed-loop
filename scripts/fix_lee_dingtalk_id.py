#!/usr/bin/env python3
"""一次性修复：李沛东 dingtalk_id 从 union_id 改为 userId。

根因：auth.py OAuth 登录曾把 union_id 写进 users.dingtalk_id，
导致发起钉钉 OA 审批时 originator_user_id 传错（钉钉报 820003），
工单无法生成真实审批实例。本脚本把该记录就地修正为 userId。
（另外 auth.py 已改：以后登录会写 userId 并对旧值自愈，本脚本只作应急数据修正。）

用法（项目根目录）：
    backend/.venv/bin/python scripts/fix_lee_dingtalk_id.py
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

OLD = "O19HojbsuvkV94oQkXiiprQiEiE"          # union_id（错误值）
NEW = "20260629192000997-1218-257858D99"    # userId（正确值，实测 getbyunionid 反查结果）


def _load_db_url() -> str:
    url = "postgresql://postgres:postgres@localhost:5432/wo_closed_loop"
    env_file = BACKEND / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip()
    except Exception:
        pass
    # 去掉 SQLAlchemy 方言前缀，psycopg.connect 只认 postgresql://
    return url.replace("postgresql+psycopg://", "postgresql://")


def main() -> None:
    import psycopg
    url = _load_db_url()
    print(f"连接数据库：{url.split('@')[-1]}")
    conn = psycopg.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, dingtalk_id FROM users WHERE dingtalk_id = %s", (OLD,))
        rows = cur.fetchall()
        if not rows:
            print("未找到 dingtalk_id 为 union_id 的记录（可能已修复），无需处理。")
        else:
            cur.execute("UPDATE users SET dingtalk_id = %s WHERE dingtalk_id = %s", (NEW, OLD))
            conn.commit()
            for r in rows:
                print(f"已修复：id={r[0]} 姓名={r[1]}  dingtalk_id {r[2]} -> {NEW}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()