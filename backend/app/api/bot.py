"""群机器人入口：在钉钉群里 @机器人 发指令，自动创建工单。

用法（群内）：
  @工单机器人 创建工单：通辽永兴风电场 变桨系统异响排查 明南辉 8月15日前

机器人收到后解析文本，调 createWorkOrder 创建工单，并回复工单链接卡片。

钉钉机器人配置：在钉钉开放平台应用「出站消息」或群自定义机器人，
回调地址配为 https://your-domain/api/bot/command
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import date, timedelta

from app.core.database import get_db
from app.core.security_middleware import limiter
from app.models import Project, User, WorkOrder, WorkOrderTypeKB, StatusLog
from app.services.priority_service import match_priority

router = APIRouter(prefix="/bot", tags=["bot"])


def _parse_create_command(text: str) -> dict | None:
    """解析「创建工单：项目 标题 责任人 截止」格式的指令。

    格式：创建工单：{项目} {标题} {责任人} {截止}
    责任人和截止可省略。标题为剩余部分。
    """
    prefix = "创建工单"
    raw = text.strip()
    for p in (prefix + "：", prefix + ":", prefix):
        if raw.startswith(p):
            raw = raw[len(p):].strip()
            break
    else:
        return None
    parts = raw.split()
    if len(parts) < 2:
        return None
    result = {"project_keyword": parts[0], "title_parts": parts[1:], "person_keyword": None, "deadline": None}
    # 从尾部解析截止日期（如 8月15日前 / 2026-08-15）
    last = result["title_parts"][-1]
    if "月" in last or last.startswith("20") and "-" in last:
        result["deadline"] = last
        result["title_parts"] = result["title_parts"][:-1]
    return result


@router.post("/command")
@limiter.limit("30/minute")
async def bot_command(request: Request, db: Session = Depends(get_db)):
    """群机器人指令入口"""
    body = await request.json()
    # 钉钉 @机器人消息结构（简化）
    text = body.get("text", {}).get("content", "") or body.get("content", "")
    sender_id = body.get("senderStaffId") or body.get("senderId") or ""

    parsed = _parse_create_command(text)
    if not parsed:
        return {
            "msgtype": "text",
            "text": {"content": "未识别指令。用法：创建工单：项目 标题 责任人 截止"},
        }

    # 模糊匹配项目
    proj = db.query(Project).filter(Project.name.like(f"%{parsed['project_keyword']}%")).first()
    # 模糊匹配责任人
    person = None
    if parsed["person_keyword"]:
        person = db.query(User).filter(User.name.like(f"%{parsed['person_keyword']}%")).first()
    # 标题 = 剩余 part 拼接
    title = " ".join(parsed["title_parts"]) or "群机器人创建工单"

    # 自动优先级
    priority = match_priority(db, title, "manual")
    # 默认审批人：按类型知识库
    default_type = db.query(WorkOrderTypeKB).filter(WorkOrderTypeKB.type_code == "other").first()
    approver_id = default_type.default_approver_id if default_type else None

    # 截止日期（简化：匹配到 SLA 天数）
    days = {"P1": 1, "P2": 3, "P3": 7}.get(priority, 7)
    deadline = date.today() + timedelta(days=days)

    # 生成工单编号
    year = date.today().year
    cnt = db.query(WorkOrder).filter(WorkOrder.code.like(f"RW-{year}-%")).count()
    code = f"RW-{year}-{cnt + 1:04d}"

    wo = WorkOrder(
        code=code, title=title, reason="群机器人@创建", action=title,
        project_id=proj.id if proj else None,
        person_id=person.id if person else None,
        approver_id=approver_id,
        type_id=default_type.id if default_type else None,
        source_code="manual", status="pending", priority=priority,
        created_date=date.today(), deadline=deadline,
    )
    db.add(wo)
    db.flush()
    db.add(StatusLog(work_order_id=wo.id, from_status=None, to_status="pending", note="群机器人创建"))
    db.commit()
    db.refresh(wo)

    # 回复工单链接卡片
    return {
        "msgtype": "action_card",
        "action_card": {
            "title": f"✅ 工单已创建 · {code}",
            "text": f"## ✅ 工单已创建\n\n"
                    f"**编号**：{code}\n\n"
                    f"**标题**：{wo.title}\n\n"
                    f"**优先级**：{wo.priority}\n\n"
                    f"**截止**：{wo.deadline}",
            "btn_orientation": "0",
            "btn_json": [{"title": "查看工单", "action_url": f"/work-orders/{wo.id}"}],
        },
    }


@router.get("/demo")
def bot_demo():
    """查看交互示例"""
    return {
        "usage": "@工单机器人 创建工单：通辽永兴 变桨系统异响排查 明南辉 8月15日前",
        "note": "钉钉群内 @机器人 后接指令，机器人自动创建工单并回复链接卡片",
    }
