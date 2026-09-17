"""钉钉 Stream 模式事件接入（取代 HTTP 回调）。

原理：用官方 dingtalk-stream SDK 起一条到钉钉的长连接（api.dingtalk.com 新网关，
ClientID/ClientSecret 鉴权），钉钉把 bpms_instance_change / bpms_task_change 事件推到这条
连接上，不用再暴露公网 HTTPS 回调 URL，也不需要 corp_id / callback_token / aes_key。

事件处理逻辑与 HTTP 回调完全一致（见 oa_event.apply_oa_event），此处只负责收事件、
按 event_type 过滤、转发处理。未安装 SDK 或未配置 AppKey/Secret 时优雅降级，不阻塞启动。

依赖：pip install dingtalk-stream
"""
import asyncio
import json

from app.core.config import get_settings

settings = get_settings()

try:
    import dingtalk_stream
    from dingtalk_stream import AckMessage
    _HAS_SDK = True
except Exception as e:  # noqa: BLE001
    dingtalk_stream = None
    AckMessage = None
    _HAS_SDK = False
    print(f"[dingtalk-stream] 未安装 dingtalk-stream，Stream 模式未启用: {e}", flush=True)

# 关注的 OA 审批事件类型（对应钉钉「事件订阅」里订阅的 bpms_instance_change / bpms_task_change）
OA_EVENT_TYPES = {"bpms_instance_change", "bpms_task_change"}

_client = None
_client_task = None


if _HAS_SDK:

    class OaApprovalEventHandler(dingtalk_stream.EventHandler):
        """收钉钉推来的事件，只处理 OA 审批两类事件。"""

        async def process(self, event: "dingtalk_stream.EventMessage"):
            event_type = getattr(event.headers, "event_type", "") or ""
            print(f"[dingtalk-stream] 收到事件 event_type={event_type!r} data={json.dumps(event.data, ensure_ascii=False)[:300]}", flush=True)
            if event_type not in OA_EVENT_TYPES:
                # 其他类型事件（机器人/卡片等）不在本模块范围，直接 ack
                return AckMessage.STATUS_OK, "OK"

            data = event.data or {}
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    data = {}
            data = dict(data)
            data.setdefault("EventType", event_type)

            # 处理器是同步 DB 逻辑（含 httpx 查询），用线程池跑，避免阻塞 Stream 的连接/心跳
            try:
                await asyncio.to_thread(_handle_event, data)
            except Exception as e:  # noqa: BLE001
                print(f"[dingtalk-stream] 处理 OA 事件失败: {e}", flush=True)
            return AckMessage.STATUS_OK, "OK"


def _handle_event(data: dict):
    from app.core.database import SessionLocal
    from app.services.oa_event import apply_oa_event

    db = SessionLocal()
    try:
        result = apply_oa_event(data, db)
        print(f"[dingtalk-stream] OA 事件处理结果: {result}", flush=True)
    finally:
        db.close()


def start_stream() -> "asyncio.Task | None":
    """在 FastAPI lifespan 里调用：启动 Stream 长连接（挂在后台任务上）。"""
    global _client, _client_task
    if not _HAS_SDK:
        return None
    if not (settings.dingtalk_app_key and settings.dingtalk_app_secret):
        print("[dingtalk-stream] 未配置 AppKey/Secret，跳过 Stream 接入", flush=True)
        return None
    try:
        credential = dingtalk_stream.Credential(settings.dingtalk_app_key, settings.dingtalk_app_secret)
        client = dingtalk_stream.DingTalkStreamClient(credential)
        # register_all_event_handler 会以 topic '*' 订阅所有事件，handler 内按 event_type 过滤
        client.register_all_event_handler(OaApprovalEventHandler())
        _client = client
        _client_task = asyncio.create_task(client.start())
        print("[dingtalk-stream] Stream 客户端已启动（等待钉钉推事件）", flush=True)
        return _client_task
    except Exception as e:  # noqa: BLE001
        print(f"[dingtalk-stream] Stream 启动失败: {e}", flush=True)
        return None


async def stop_stream():
    """在 lifespan 关闭时调用：停止长连接。"""
    global _client, _client_task
    if _client is not None:
        try:
            await _client.stop()
        except Exception as e:  # noqa: BLE001
            print(f"[dingtalk-stream] 停止 Stream 客户端失败: {e}", flush=True)
        _client = None
    _client_task = None