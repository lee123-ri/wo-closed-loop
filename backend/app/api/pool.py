"""数据池 API：导入 → 查看 → 生成工单 → AI表格同步"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security_middleware import limiter
from app.models import DataPoolItem, WorkOrder
from app.schemas.pool import (
    PoolItemCreate, PoolItemUpdate, PoolItemOut, PoolItemListOut,
    GenerateRequest, GenerateResult, PoolImportResult,
)
from app.services.pool_service import (
    generate_from_pool, parse_csv, sync_from_aitable,
)

router = APIRouter(prefix="/pool", tags=["pool"])


def _enrich(item: DataPoolItem, db: Session) -> PoolItemOut:
    """填充关联名称"""
    wo_code = None
    if item.work_order_id:
        wo = db.get(WorkOrder, item.work_order_id)
        wo_code = wo.code if wo else None
    return PoolItemOut(
        id=item.id, pool_type=item.pool_type, source_system=item.source_system,
        source_ref=item.source_ref, title=item.title, project_name=item.project_name,
        person_name=item.person_name, deadline=item.deadline, description=item.description,
        metric_type=item.metric_type, metric_value=item.metric_value,
        threshold=item.threshold, deviation_pct=item.deviation_pct,
        status=item.status, work_order_id=item.work_order_id, skip_reason=item.skip_reason,
        raw_data=item.raw_data, backfill_reason=item.backfill_reason,
        backfill_action=item.backfill_action, backfilled_at=item.backfilled_at,
        created_at=item.created_at, work_order_code=wo_code,
    )


# ── 手动录入 ──────────────────────────────────────────

@router.post("/items", response_model=PoolItemOut, status_code=201)
def create_pool_item(body: PoolItemCreate, db: Session = Depends(get_db)):
    item = DataPoolItem(**body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _enrich(item, db)


# ── 列表/详情 ─────────────────────────────────────────

@router.get("/items", response_model=PoolItemListOut)
def list_pool_items(
    pool_type: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = select(DataPoolItem).order_by(DataPoolItem.id.desc())
    if pool_type:
        q = q.where(DataPoolItem.pool_type == pool_type)
    if status:
        q = q.where(DataPoolItem.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.execute(q.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    items = [_enrich(r, db) for r in rows]
    return PoolItemListOut(items=items, total=total or 0, page=page, page_size=page_size)


@router.get("/items/{item_id}", response_model=PoolItemOut)
def get_pool_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(DataPoolItem, item_id)
    if not item:
        raise HTTPException(404, "数据池记录不存在")
    return _enrich(item, db)


@router.patch("/items/{item_id}", response_model=PoolItemOut)
def update_pool_item(item_id: int, body: PoolItemUpdate, db: Session = Depends(get_db)):
    item = db.get(DataPoolItem, item_id)
    if not item:
        raise HTTPException(404, "数据池记录不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return _enrich(item, db)


@router.delete("/items/{item_id}")
def delete_pool_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(DataPoolItem, item_id)
    if not item:
        raise HTTPException(404, "数据池记录不存在")
    if item.status == "generated":
        raise HTTPException(409, "已生成工单的记录不可删除")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ── CSV 导入 ──────────────────────────────────────────

@router.post("/upload", response_model=PoolImportResult)
@limiter.limit("10/minute")
async def upload_pool(
    request: Request,
    pool_type: str = Query(..., description="plan|anomaly"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传 CSV/Excel 批量导入数据池"""
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空文件")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("gbk", errors="ignore")

    result = parse_csv(content, pool_type)
    return PoolImportResult(**result)


# ── 工单生成 ──────────────────────────────────────────

@router.post("/generate", response_model=GenerateResult)
def generate_work_orders(body: GenerateRequest, db: Session = Depends(get_db)):
    result = generate_from_pool(db, body.pool_ids)
    return GenerateResult(**result)


@router.post("/generate-all", response_model=GenerateResult)
def generate_all(pool_type: str | None = None, db: Session = Depends(get_db)):
    q = select(DataPoolItem).where(DataPoolItem.status == "pending")
    if pool_type:
        q = q.where(DataPoolItem.pool_type == pool_type)
    items = db.execute(q).scalars().all()
    ids = [i.id for i in items]
    if not ids:
        return GenerateResult(generated=0, skipped=0, errors=["没有待生成的记录"], work_order_ids=[])
    result = generate_from_pool(db, ids)
    return GenerateResult(**result)


# ── AI表格同步 ────────────────────────────────────────

@router.post("/sync-aitable", response_model=PoolImportResult)
def sync_aitable_endpoint(full: bool = False, db: Session = Depends(get_db)):
    """从异常原因表同步非EAM软工单到数据池"""
    from app.services.aitable import sync_anomaly_to_pool
    result = sync_anomaly_to_pool(full=full)
    return PoolImportResult(imported=result["synced"], skipped=result["skipped"], errors=result["errors"])


@router.post("/sync-project-map")
def sync_project_map_endpoint(db: Session = Depends(get_db)):
    """从 AI 表格同步项目信息"""
    from app.services.aitable import sync_project_map_to_db
    return sync_project_map_to_db()