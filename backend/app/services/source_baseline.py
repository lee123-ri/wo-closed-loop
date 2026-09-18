"""上线前来源基线：记录当前外部行，防止历史存量首次同步时建单。"""
from app.core.database import SessionLocal
from app.models import DataPoolItem


def _add(db, system, ref, title):
    if not ref or db.query(DataPoolItem.id).filter_by(source_system=system, source_ref=ref).first(): return False
    db.add(DataPoolItem(pool_type="anomaly", source_system=system, source_ref=ref, title=(title or ref)[:512], status="skipped", skip_reason="上线来源基线")); return True


def capture_current_sources():
    from app.services import aitable
    db = SessionLocal(); anomaly = dual = 0
    try:
        for row in aitable._get_records(aitable.ANOMALY_BASE, aitable.ANOMALY_TABLE):
            anomaly += _add(db, "anomaly_baseline", str(row.get("recordId") or ""), "异常指标历史基线")
        for row in aitable._get_records(aitable.ANOMALY_BASE, aitable.DUAL_RULE_TABLE):
            cells = row.get("cells", {}); ref = aitable._cv(cells, "n2dmwW8") or row.get("recordId")
            dual += _add(db, "dual_rule_baseline", str(ref or ""), "双细则历史基线")
        db.commit()
    finally: db.close()
    return {"anomaly": anomaly, "dual_rule": dual}
