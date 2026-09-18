#!/usr/bin/env python3
"""一次性软删「项目管理」里的非场站条目（2026-09-11）。

背景：projects 表经 OA 台账同步，混入大量「不是场站项目」的条目——销售/采购合同、
软件研发/系统、数据接入/测评、运维工单（预试/技改/定检/维修/试验）、售前售后库存。
用户确认（2026-09-11）：这 544 条软删（is_active=False）。
「投资商+客户厂名」类（中新旭德/松下/国顺等，多为分布式光伏真项目）保留不动。

判定口径：不含场站关键词（风电场/光伏/电站/风电/储能/分布式…）且命中任一非场站信号。
软删 = is_active=False，可逆；工单历史 project_id 引用不丢（但下拉不再显示该项目）。

用法（在 backend 目录跑）：
  python ../scripts/cleanup_nonproject_20260911.py            # dry-run，只打印计划
  python ../scripts/cleanup_nonproject_20260911.py --apply    # 真正执行
"""
import re
import sys
from collections import Counter

sys.path.insert(0, ".")

from sqlalchemy import text

from app.core.database import engine, SessionLocal  # noqa: E402
from app.models import Project  # noqa: E402

ELECTRIC = re.compile(r"风电场|光伏|电站|风电|储能|分布式|光储|风储|风力|太阳能|升压站|场站|电厂|能源")
# 「平台」是村名（三一平台村），非「软件/平台」信号，防误删真场站
EXCLUDE_NAMES = {"三一平台村、老盐池"}
# 非场站信号（优先级分桶——某条命中靠前桶即归该类，口径与分类分析一致）
NON_PROJECT_BUCKETS = [
    ("销售/采购/合同/协议", re.compile(r"销售|采购|合同|协议|框架|入市|零售|售电|购电|市场化|交易")),
    ("软件研发/系统/数据/测评", re.compile(r"SAAS|SaaS|软件|平台|系统|研发|试点|算法|域名|标准化|基线|数据|接入|采集|转发|流量|红外|采集棒|监控|测评")),
    ("运维工单/技术服务", re.compile(r"预试|定检|技改|技服|维修|试验|轴承|叶片|齿轮箱|伺服|偏航|解锁|变桨|SVG|备件|备品|漏水|水泵|电梯|制冷|绿化|保洁|清洗")),
    ("售前/售后/库存", re.compile(r"售前|售后|库存")),
]


def classify(name: str) -> str:
    if name in EXCLUDE_NAMES:
        return "场站"
    if ELECTRIC.search(name):
        return "场站"
    for label, pat in NON_PROJECT_BUCKETS:
        if pat.search(name):
            return label
    return "客户名/其他"


def is_non_project(name: str) -> bool:
    return classify(name) not in ("场站", "客户名/其他")


def main() -> None:
    apply_ = "--apply" in sys.argv
    db = SessionLocal()
    try:
        projects = db.query(Project).filter(Project.is_active.is_(True)).order_by(Project.id).all()
    finally:
        db.close()

    to_delete = [p for p in projects if is_non_project(p.name)]
    cnt = Counter(classify(p.name) for p in to_delete)

    wo = mp = 0
    if to_delete:
        idlist = ",".join(str(p.id) for p in to_delete)
        with engine.connect() as conn:
            wo = int(conn.execute(text(f"SELECT count(*) FROM work_orders WHERE project_id IN ({idlist})")).scalar() or 0)
            mp = int(conn.execute(text(f"SELECT count(*) FROM person_project_map WHERE project_id IN ({idlist})")).scalar() or 0)

    print("=" * 70)
    print("非场站条目软删计划（dry-run，不落库）" if not apply_ else "非场站条目软删（执行中）")
    print("=" * 70)
    print(f"当前 active 项目：{len(projects)}   待软删：{len(to_delete)}   软删后 active：{len(projects) - len(to_delete)}")
    print(f"分类：{dict(cnt)}")
    print(f"其中引用了 {wo} 条工单、{mp} 条人员映射（软删后这些工单的项目下拉将不再显示该项目）")
    print("\n── 待软删样本（前 80 / 共 %d）──" % len(to_delete))
    for p in to_delete[:80]:
        print(f"  id={p.id} [{classify(p.name)}] {p.name!r}")

    if not apply_:
        print("\n[dry-run] 未做任何改动；确认无误后加 --apply 真正执行。")
        return

    db = SessionLocal()
    try:
        for p in to_delete:
            db.execute(text("UPDATE projects SET is_active = false WHERE id = :i"), {"i": p.id})
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"\n✓ 已软删 {len(to_delete)} 条非场站条目，active 剩 {len(projects) - len(to_delete)}。")


if __name__ == "__main__":
    main()