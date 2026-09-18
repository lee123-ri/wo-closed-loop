#!/usr/bin/env python3
"""一次性清洗 projects 表「项目名」（2026-09-11）。

背景：老 aitable 同步把「项目简称」截断凑码，并在名称末尾堆省份/年份后缀
（如 `国电投别力古台500MW-YH`、`协合瓜州二期2025`），还混入「不统计 / 华北临时数据 / #N/A」
等占位脏名。项目管理页名称列一片错。

规则（与 app/services/oa_ledger.py::_clean_name 一致，去尾部 ASCII 噪声，保留中间
「1号/4号」「HS300」等有区分含义的标记）：
  1. 垃圾名软删：清洗后中文不足 2 字（#N/A 等）或命中占位词（不统计/临时数据/测试/示例/…）；
  2. 去尾部字母代号/年份/容量：clean(name) = 截到最后一个中文字符为止；
  3. 按 clean 名去重：同名保留 canonical（已是干净名者优先，否则取最小 id），
     其余软删，并把引用它的 work_orders.project_id / person_project_map 改指向 canonical；
  4. 编码归一：幸存项目 code 非 PRJ-#### 的，用 next_project_code 规则重新编。

软删 = is_active=False（项目下拉/列表不再出现，工单里已引用 project_id 的历史不受影响）。

用法（在 backend 目录跑，.venv 已装好依赖）：
  python ../scripts/cleanup_project_names_20260911.py            # dry-run，只打印计划
  python ../scripts/cleanup_project_names_20260911.py --apply    # 真正执行
"""
import re
import sys

sys.path.insert(0, ".")  # 让 `from app...` 可导入（从 backend 目录跑）

from sqlalchemy import text

from app.core.database import engine, SessionLocal  # noqa: E402
from app.models import Project  # noqa: E402
from app.services.project_codes import plan_code_normalization, PROJECT_CODE_RE  # noqa: E402

# 占位/脏名关键词（清洗后仍含这些的，视为「明显不对」删除）
JUNK_KEYWORDS = ("不统计", "临时数据", "#N/A", "#REF", "测试", "示例", "占位", "其他", "合计", "小计", "总计")


def clean(name: str | None) -> str:
    """去尾部噪声后缀（口径与 oa_ledger._clean_name 一致）。

    只削两类尾部噪声，逐层剥离直到干净：
      1. 短字母代号：`-FJ`/`-HN`/`-D`（连字符+1~2 大写）或 `DE`/`HN`/`TN`/`D`（中文后 1~2 大写）；
      2. 纯年份：`20xx`（前一位是中文）。
    保留容量（40MW/50MW/18.3MW）、合同号（XHZN-XS-202508-177、-177）、业务缩写（EMC）——
    这些是区分标记，削了会把不同项目并成一个（曾误并「沙电阳山黎埠镇40MW/50MW」）。
    纯字母数字（无中文）→ 空串 = 脏数据。
    """
    if not name:
        return ""
    s = name.strip()
    if not any("一" <= ch <= "鿿" for ch in s):
        return ""
    while True:
        m = re.search(r"-([A-Z]{1,2})$", s)          # -YH/-FJ/-HN/-D（连字符+1~2 大写）
        if m:
            s = s[: m.start()]
            continue
        m = re.search(r"(?<=[一-鿿])([A-Z]{1,2})$", s)  # DE/HN/TN/D（中文后 1~2 大写）
        if m:
            s = s[: m.start()]
            continue
        m = re.search(r"(?<=[一-鿿])(20\d{2})$", s)      # 中文后纯年份
        if m:
            s = s[: m.start()]
            continue
        break
    return s


def is_junk(name: str | None) -> bool:
    name = name or ""
    if len(clean(name)) < 2:
        return True
    return any(k in name for k in JUNK_KEYWORDS)


def build_plan(db):
    # 只清洗活动项目；已停用(=已软删)的不再动
    projects = db.query(Project).filter(Project.is_active.is_(True)).order_by(Project.id).all()

    junk: list[Project] = []          # 垃圾名 → 软删
    groups: dict[str, list[Project]] = {}  # clean 名 → 组
    for p in projects:
        c = clean(p.name)
        if is_junk(p.name):
            junk.append(p)
            continue
        groups.setdefault(c, []).append(p)

    renames: list[tuple[Project, str]] = []   # (canonical, new_name)
    dedup_delete: list[tuple[Project, Project]] = []  # (dup, canonical)  dup 软删 + 引用改指 canonical
    for c, members in groups.items():
        members.sort(key=lambda p: p.id)
        already = [m for m in members if m.name == c]
        canonical = min(already, key=lambda m: m.id) if already else min(members, key=lambda m: m.id)
        if canonical.name != c:
            renames.append((canonical, c))
        for m in members:
            if m.id != canonical.id:
                dedup_delete.append((m, canonical))

    survivors = [min(([m for m in ms if m.name == k] or ms), key=lambda m: m.id) for k, ms in groups.items()]
    code_fix = [(p, p.code) for p in survivors if not PROJECT_CODE_RE.match(p.code or "")]
    # 编码归一起点必须基于**全库**（含已停用）最大 PRJ 序号 +1，只增不回收，避免与历史/停用项目撞码
    all_pairs = [(pid, code or "") for pid, code in db.query(Project.id, Project.code).all()]
    new_codes = plan_code_normalization(all_pairs)

    return {
        "projects": projects,
        "junk": junk,
        "renames": renames,
        "dedup_delete": dedup_delete,
        "code_fix": code_fix,
        "new_codes": new_codes,
        "final_count": len(groups),
    }


def ref_counts(dup_ids):
    """返回待改指的工单/人员映射条数（用于 dry-run 展示）。"""
    if not dup_ids:
        return 0, 0
    ids = ",".join(str(i) for i in dup_ids)
    with engine.connect() as conn:
        wo = conn.execute(text(f"SELECT count(*) FROM work_orders WHERE project_id IN ({ids})")).scalar()
        mp = conn.execute(text(f"SELECT count(*) FROM person_project_map WHERE project_id IN ({ids})")).scalar()
    return int(wo or 0), int(mp or 0)


def apply_plan(plan):
    db = SessionLocal()
    try:
        dup_ids = [d.id for d, _ in plan["dedup_delete"]]

        # 1) 引用改指：工单 + 人员映射 → canonical
        for dup, canonical in plan["dedup_delete"]:
            db.execute(text("UPDATE work_orders SET project_id = :c WHERE project_id = :d"),
                       {"c": canonical.id, "d": dup.id})
            # 人员映射：目标 canonical 已有同一 user 的映射则删（避免重复），否则改指
            for (user_id,) in db.execute(text("SELECT user_id FROM person_project_map WHERE project_id = :d"),
                                        {"d": dup.id}).all():
                exists = db.execute(text(
                    "SELECT 1 FROM person_project_map WHERE project_id = :c AND user_id = :u"
                ), {"c": canonical.id, "u": user_id}).first()
                if exists:
                    db.execute(text("DELETE FROM person_project_map WHERE project_id = :d AND user_id = :u"),
                               {"d": dup.id, "u": user_id})
                else:
                    db.execute(text("UPDATE person_project_map SET project_id = :c WHERE project_id = :d AND user_id = :u"),
                               {"c": canonical.id, "d": dup.id, "u": user_id})

        # 2) 垃圾名 + 去重重复项 软删
        for p in list(plan["junk"]) + [d for d, _ in plan["dedup_delete"]]:
            db.execute(text("UPDATE projects SET is_active = false WHERE id = :i"), {"i": p.id})

        # 3) canonical 改名
        for p, new_name in plan["renames"]:
            db.execute(text("UPDATE projects SET name = :n WHERE id = :i"), {"n": new_name, "i": p.id})

        # 4) 编码归一
        for p, _ in plan["code_fix"]:
            nc = plan["new_codes"].get(p.id)
            if nc:
                db.execute(text("UPDATE projects SET code = :c WHERE id = :i"), {"c": nc, "i": p.id})

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main():
    apply_ = "--apply" in sys.argv
    db = SessionLocal()
    try:
        plan = build_plan(db)
    finally:
        db.close()

    dup_ids = [d.id for d, _ in plan["dedup_delete"]]
    wo_cnt, mp_cnt = ref_counts(dup_ids)

    print("=" * 70)
    print("项目名清洗计划（dry-run, 不落库）" if not apply_ else "项目名清洗（执行中）")
    print("=" * 70)
    print(f"当前活动项目：{len([p for p in plan['projects'] if p.is_active])}")
    print(f"垃圾名软删：{len(plan['junk'])}  去重重复软删：{len(plan['dedup_delete'])}  "
          f"（其中 {wo_cnt} 条工单、{mp_cnt} 条人员映射将改指 canonical）")
    print(f"改名：{len(plan['renames'])}   编码归一：{len(plan['code_fix'])}")
    print(f"清洗后活动项目：{plan['final_count']}")

    print("\n── 垃圾名（软删）──")
    for p in plan["junk"]:
        print(f"  id={p.id} code={p.code!r} name={p.name!r}")

    print("\n── 改名（canonical 带后缀 → 干净名）──")
    for p, n in plan["renames"]:
        print(f"  id={p.id} {p.name!r} -> {n!r}")

    print("\n── 去重重复（软删，引用改指 canonical）──")
    for dup, canonical in plan["dedup_delete"]:
        print(f"  id={dup.id} {dup.name!r} -> 并入 canonical id={canonical.id} {canonical.name!r}")

    print("\n── 编码归一（非 PRJ-#### → 新码）──")
    for p, old in plan["code_fix"]:
        print(f"  id={p.id} {old!r} -> {plan['new_codes'].get(p.id)!r}   (name={p.name!r})")

    if not apply_:
        print("\n[dry-run] 未做任何改动；确认无误后加 --apply 真正执行。")
        return

    apply_plan(plan)
    print(f"\n✓ 执行完成：软删 {len(plan['junk']) + len(plan['dedup_delete'])}，改名 {len(plan['renames'])}，编码归一 {len(plan['code_fix'])}。清洗后 {plan['final_count']} 个活动项目。")


if __name__ == "__main__":
    main()