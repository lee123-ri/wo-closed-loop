"""An independent Stream receiver, explicitly authorized alongside the existing bot."""
from __future__ import annotations

import asyncio
from datetime import datetime
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import signal
import threading
import time
from urllib.parse import urlparse

import httpx
import requests
from dotenv import dotenv_values
import dingtalk_stream
from dingtalk_stream import AckMessage, ChatbotMessage
from app.core.config import get_settings
from . import __version__
from .core import Ledger, RestrictedCodex, FEEDBACK, KNOWLEDGE, SOURCE_PATHS, SOURCE_TITLES, candidate, context_key, eligible

RUNTIME = Path.home() / "Library/Application Support/xh-wo-closed-loop/pmomini"
HEALTH_PORT = 8768


def connection_is_open(ws):
    if ws is None:
        return False
    state = getattr(ws, "state", None)
    if state is not None:
        return getattr(state, "name", "") == "OPEN"
    return not getattr(ws, "closed", True)


class Pipeline:
    def __init__(self, ledger, model, query, base_url, group_projects=None):
        self.ledger, self.model, self.query = ledger, model, query
        self.base_url = base_url.rstrip("/")
        self.group_projects = group_projects or {}

    async def answer(self, event, mid):
        question = event["text"]["content"].strip()
        feedback = FEEDBACK.fullmatch(question)
        if feedback:
            ok = self.ledger.feedback(event, feedback[1], feedback[2])
            self.ledger.update(mid, "feedback" if ok else "silent")
            return None
        context = self.ledger.context(event)
        if not candidate(question, context):
            self.ledger.update(mid, "silent", detail="out_of_scope_before_codex")
            return None
        self.ledger.update(mid, "running")
        try:
            plan = await self.model.plan(question, context)
        except Exception as exc:
            # Scope has not been positively established. No error reply or reaction.
            self.ledger.update(mid, "silent", detail="classification_failed:" + type(exc).__name__)
            self.ledger.gap(mid, "classification_failed")
            return None
        self.ledger.update(mid, "running", plan=plan)
        if plan["intent"] == "silent":
            self.ledger.update(mid, "silent", detail="semantic_gate")
            return None
        if plan["intent"] == "unsupported":
            answer = KNOWLEDGE["read-only"]
            evidence = {"source": "read-only"}
        elif plan["intent"] == "help":
            sources = plan.get("sources", [])
            if not sources or not set(sources).issubset(KNOWLEDGE) or not plan.get("answer", "").strip():
                answer = "目前没有足够的平台资料确认这个问题，请补充页面名称、错误提示或工单编号。"
                self.ledger.gap(mid, "no_evidence")
                evidence = {"source": "no_evidence"}
            else:
                # Model chooses relevant evidence; it cannot invent platform facts.
                sources = list(dict.fromkeys(sources))[:3]
                answer = "\n\n".join(KNOWLEDGE[s] for s in sources)
                answer += "\n\n依据：" + "、".join(f"[{SOURCE_TITLES[s]}]({self.base_url}{SOURCE_PATHS[s]})" for s in sources)
                evidence = {"sources": sources, "snippets": {s: KNOWLEDGE[s] for s in sources}}
        else:
            try:
                if plan.get("scope_complete") is not True:
                    from .data import QueryBlocked
                    raise QueryBlocked("目前仅支持按工单编号、区域、状态、项目编码和页码查询，无法完整表达本次筛选条件。请补充精确工单编号或在平台中按所需条件筛选。")
                event_for_query = {**event, "_context": context or {}}
                evidence = await asyncio.to_thread(self.query, plan, event_for_query, self.group_projects)
                answer = evidence["answer"]
            except Exception as exc:
                from .data import QueryBlocked
                answer = str(exc) if isinstance(exc, QueryBlocked) else "平台查询暂不可用，请稍后重试。"
                evidence = {"source": "query_failed", "type": type(exc).__name__}
                self.ledger.gap(mid, "query_blocked_or_failed")
        answer += f"\n\n反馈：回复“反馈 {mid} 有用”或“反馈 {mid} 有误”。"
        self.ledger.update(mid, "reply_pending", evidence=evidence, answer=answer)
        self.ledger.remember(event, plan)
        return answer


async def send_reply(event, answer):
    """One attempt only; ambiguous transport outcomes are never retried automatically."""
    url = event.get("sessionWebhook", "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"oapi.dingtalk.com", "api.dingtalk.com"} or parsed.username:
        raise ValueError("invalid session reply endpoint")
    expiry = int(event.get("sessionWebhookExpiredTime", 0))
    if expiry and expiry < time.time() * 1000:
        raise ValueError("expired reply endpoint")
    # The official SDK uses the same sessionWebhook for text replies in both modes.
    body = {"msgtype": "markdown", "markdown": {"title": "工单与平台答复", "text": answer}, "at": {"atUserIds": [event["senderStaffId"]]}}
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        response = await client.post(url, json=body)
    response.raise_for_status()
    result = response.json()
    if result.get("errcode") != 0:
        raise RuntimeError("DingTalk rejected reply")
    return {"accepted": True, "errcode": 0}


class Receiver(dingtalk_stream.ChatbotHandler):
    def __init__(self, ledger, queue, robot, corp, health, started_at):
        super().__init__()
        self.ledger, self.queue, self.robot, self.corp = ledger, queue, robot, corp
        self.health, self.started_at = health, started_at

    async def process(self, callback):
        event = callback.data
        if not isinstance(event, dict) or not eligible(event, self.robot, self.corp):
            return AckMessage.STATUS_OK, "ignored"
        try:
            created = int(event.get("createAt", 0)) / 1000
        except (TypeError, ValueError):
            return AckMessage.STATUS_OK, "invalid time"
        if created < self.started_at or created > time.time() + 300:
            return AckMessage.STATUS_OK, "old or invalid message"
        if self.queue.full():
            return AckMessage.STATUS_OK, "queue full"
        mid = await asyncio.to_thread(self.ledger.claim, event)
        if mid:
            self.queue.put_nowait((event, mid))
            self.health["last_received_at"] = time.time()
        return AckMessage.STATUS_OK, "OK"


async def consume(queue, pipeline, health, sender=send_reply):
    while True:
        event, mid = await queue.get()
        try:
            answer = await pipeline.answer(event, mid)
            if answer:
                pipeline.ledger.update(mid, "sending")
                try:
                    result = await sender(event, answer)
                    pipeline.ledger.update(mid, "sent", detail=result)
                    health["last_reply_accepted_at"] = time.time()
                except Exception as exc:
                    pipeline.ledger.update(mid, "unknown", detail="reply_not_verified:" + type(exc).__name__)
                    pipeline.ledger.gap(mid, "delivery_not_verified")
        except Exception as exc:
            pipeline.ledger.update(mid, "failed", detail=type(exc).__name__)
            pipeline.ledger.gap(mid, "worker_failed")
        finally:
            queue.task_done()


def make_health_handler(health, queue):
    class HealthHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            snapshot = dict(health)
            snapshot["queue_size"] = queue.qsize()
            snapshot["status"] = "ready" if snapshot.get("stream_connected") and snapshot.get("codex_verified") else "degraded"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(snapshot).encode())
    return HealthHandler


async def run(runtime=RUNTIME):
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime, 0o700)
    lock = (runtime / "receiver.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    settings = get_settings()
    platform_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    policy_path = runtime / "policy.json"
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else {}
    corp = settings.dingtalk_corp_id or policy.get("corp_id", "")
    def platform_setting(name):
        return os.getenv(name.upper()) or getattr(settings, name, "") or platform_env.get(name.upper(), "")
    robot = platform_setting("dingtalk_announcement_robot_code")
    app_key, secret = platform_setting("dingtalk_announcement_app_key"), platform_setting("dingtalk_announcement_app_secret")
    if not robot or robot != app_key or not secret or not corp:
        raise RuntimeError("PMO mini credential/corporation configuration incomplete")
    ledger, queue = Ledger(runtime / "ledger.sqlite3"), asyncio.Queue(maxsize=128)
    health = {"pid": os.getpid(), "started_at": time.time(), "stream_connected": False,
              "codex_verified": False, "group_chat_enabled": True, "private_chat_enabled": True,
              "startup_notification_sent": False, "real_message_received": False,
              "real_delivery_readback_verified": False,
              "policy": "workorders-and-platform-only", "self_help_enabled": True, "sla_policy_enabled": True, "version": __version__}
    model = RestrictedCodex()
    from .data import query
    pipeline = Pipeline(ledger, model, query, settings.frontend_base_url, policy.get("group_projects", {}))
    receiver = Receiver(ledger, queue, robot, corp, health, health["started_at"])

    class SafeStreamClient(dingtalk_stream.DingTalkStreamClient):
        def open_connection(self):
            # The upstream SDK has no HTTP timeout and logs tickets. Bound the
            # handshake and never log any part of its authenticated response.
            try:
                response = requests.post(self.OPEN_CONNECTION_API, json={
                    "clientId": self.credential.client_id,
                    "clientSecret": self.credential.client_secret,
                    "subscriptions": [{"type": "CALLBACK", "topic": ChatbotMessage.TOPIC}],
                    "ua": f"pmomini-codex/{__version__}", "localIp": self.get_host_ip(),
                }, timeout=10)
                response.raise_for_status()
                data = response.json()
                return data if data.get("endpoint") and data.get("ticket") else None
            except Exception:
                return None

    client = SafeStreamClient(dingtalk_stream.Credential(app_key, secret))
    client.register_callback_handler(ChatbotMessage.TOPIC, receiver)
    # SDK logs connection tickets. Disable its logging rather than leak them to files.
    logging.disable(logging.CRITICAL)
    server = ThreadingHTTPServer(("127.0.0.1", HEALTH_PORT), make_health_handler(health, queue))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    worker = asyncio.create_task(consume(queue, pipeline, health))
    stream_task = asyncio.create_task(client.start())

    async def heartbeat():
        while True:
            ws = client.websocket
            health["stream_connected"] = connection_is_open(ws)
            health["heartbeat_at"] = time.time()
            health["real_message_received"] = bool(health.get("last_received_at"))
            tmp = runtime / "health.tmp"
            tmp.write_text(json.dumps(health))
            os.chmod(tmp, 0o600)
            tmp.replace(runtime / "health.json")
            if stream_task.done() or worker.done():
                os._exit(1)  # launchd restarts a dead consumer, not a silent unhealthy process.
            await asyncio.sleep(5)

    async def codex_check():
        while True:
            try:
                result = await model.plan("请说明软工单平台的‘我的工单’页面有什么用途")
                health["codex_verified"] = result["intent"] == "help"
                health["codex_checked_at"] = time.time()
                health.pop("codex_error", None)
            except Exception as exc:
                health["codex_verified"] = False
                health["codex_error"] = type(exc).__name__
            await asyncio.sleep(600 if health["codex_verified"] else 60)

    # Local model checks never enter the ledger, Stream queue or reply sender.
    await asyncio.gather(heartbeat(), codex_check(), stream_task, worker)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as exc:
        print("PMO bridge stopped: " + type(exc).__name__, flush=True)
        raise SystemExit(1)
