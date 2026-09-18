#!/usr/bin/env python3
"""在本项目 backend venv 里造一个测试 JWT（复用同一把 JWT_SECRET）。

    cd backend && .venv/bin/python ../scripts/loadtest/mint_token.py [user_id] [name] [role]

默认 admin(id=1)。user_id 必须是数据库里真实存在的用户（get_current_user 会 db.get(User, id)）。
"""
import sys

from app.core.security import create_access_token

uid = sys.argv[1] if len(sys.argv) > 1 else "1"
name = sys.argv[2] if len(sys.argv) > 2 else "admin"
role = sys.argv[3] if len(sys.argv) > 3 else "admin"

print(create_access_token(uid, {"name": name, "role": role}))