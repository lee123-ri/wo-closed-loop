#!/usr/bin/env python3
"""从钉钉同步通讯录到系统用户表。

遍历钉钉组织架构，为每个用户创建/更新系统用户记录，
包括 dingtalk_id、部门名称、部门ID。

用法：
  python3 sync_dingtalk_users.py

依赖 dws CLI（已认证）。
"""
import json
import subprocess
import sys
from pathlib import Path

# 加到 sys.path 以便导入项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.database import SessionLocal
from app.models import User


def _dws(*args: str, timeout: int = 30) -> dict:
    """调用 dws CLI 并返回 JSON 结果"""
    result = subprocess.run(
        ["dws", *args, "--format", "json"],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        print(f"[dws] 调用失败: {result.stderr[:200]}")
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _get_dept_members(dept_id: int) -> list[dict]:
    """获取部门成员"""
    data = _dws("contact", "+list-dept-members", "--depts", str(dept_id))
    return data.get("members", data.get("result", []))


def _get_sub_depts(dept_id: int) -> list[dict]:
    """获取子部门"""
    data = _dws("contact", "+list-sub-depts", "--dept", str(dept_id))
    return data.get("depts", [])


def _get_all_members(dept_id: int, dept_name: str = "") -> list[dict]:
    """递归获取部门及其所有子部门的成员，附带部门名称"""
    members = []
    # 获取当前部门成员，标记部门
    raw = _get_dept_members(dept_id)
    for m in raw:
        m["_dept_name"] = dept_name
        m["_dept_id"] = str(dept_id)
        members.append(m)

    # 递归获取子部门成员
    for sub in _get_sub_depts(dept_id):
        sub_id = sub.get("deptId")
        sub_name = sub.get("deptName", "")
        members.extend(_get_all_members(sub_id, sub_name))

    return members


def sync_users():
    db = SessionLocal()
    try:
        print("=" * 60)
        print("🔄 同步钉钉通讯录到系统用户表")
        print("=" * 60)

        # 1. 获取根部门一级子部门
        print("\n📂 获取组织架构...")
        top_depts = _get_sub_depts(1)
        print(f"  找到 {len(top_depts)} 个一级部门")

        # 2. 遍历所有部门获取成员
        print("\n👥 遍历所有部门获取成员...")
        all_members = []
        for dept in top_depts:
            dept_id = dept.get("deptId")
            dept_name = dept.get("deptName", "")
            print(f"  📁 {dept_name} (ID={dept_id})...", end="", flush=True)
            members = _get_all_members(dept_id, dept_name)
            all_members.extend(members)
            print(f" {len(members)} 人")

        print(f"\n  共获取 {len(all_members)} 人（含重复）")

        # 3. 去重（按 userId）
        seen = {}
        for m in all_members:
            uid = m.get("userId", m.get("staffId", ""))
            if uid and uid not in seen:
                seen[uid] = m

        print(f"  去重后 {len(seen)} 人")

        # 4. 同步到数据库
        print("\n💾 同步到数据库...")
        created = 0
        updated = 0
        skipped = 0

        for uid, m in seen.items():
            name = m.get("name", "")
            dept_name = m.get("_dept_name", "")
            dept_id = m.get("_dept_id", "")

            if not name:
                skipped += 1
                continue

            # 查找已有用户（按 dingtalk_id 或 name）
            user = db.query(User).filter(User.dingtalk_id == uid).first()
            if not user:
                user = db.query(User).filter(User.name == name).first()

            if user:
                # 更新
                changed = False
                if user.dingtalk_id != uid:
                    user.dingtalk_id = uid
                    changed = True
                if user.department != dept_name:
                    user.department = dept_name
                    changed = True
                if user.department_id != dept_id:
                    user.department_id = dept_id
                    changed = True
                if user.name != name:
                    user.name = name
                    changed = True
                if changed:
                    updated += 1
            else:
                # 新建
                user = User(
                    name=name,
                    dingtalk_id=uid,
                    department=dept_name,
                    department_id=dept_id,
                    role="executor",
                    is_active=True,
                )
                db.add(user)
                created += 1

        db.commit()
        total = db.query(User).count()

        print(f"\n✅ 同步完成!")
        print(f"  新建: {created}")
        print(f"  更新: {updated}")
        print(f"  跳过: {skipped}")
        print(f"  系统总用户: {total}")

        # 5. 打印统计
        print("\n📊 用户统计:")
        no_dingtalk = db.query(User).filter(User.dingtalk_id.is_(None)).count()
        print(f"  有钉钉ID: {total - no_dingtalk}")
        print(f"  无钉钉ID: {no_dingtalk}")
        has_dept = db.query(User).filter(User.department.isnot(None)).count()
        print(f"  有部门: {has_dept}")

    finally:
        db.close()


if __name__ == "__main__":
    sync_users()