"""No production DB writes, no DingTalk sends. Run directly with unittest."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pmomini_bridge.core import (Ledger, RestrictedCodex, candidate, context_key, eligible, SCHEMA)
from pmomini_bridge.core import fast_plan
from pmomini_bridge.service import Pipeline, Receiver, consume, send_reply, connection_is_open


def event(**values):
    return {"msgId": "message-1", "robotCode": "test-robot", "senderCorpId": "test-corp",
            "chatbotCorpId": "test-corp", "senderStaffId": "test-user", "conversationId": "test-chat",
            "conversationType": "1", "msgtype": "text", "isInAtList": True,
            "createAt": int(time.time()*1000), "text": {"content": "工单逾期几张？"}, **values}


def plan(intent="overdue", **values):
    return {"intent": intent, "answer": "", "sources": [], "work_order_code": None,
            "region": None, "status": None, "project_code": None, "page": 1, "scope_complete": True, **values}


class FakeModel:
    def __init__(self, result=None, fail=False):
        self.result, self.fail, self.calls = result or plan(), fail, 0

    async def plan(self, question, context=None):
        self.calls += 1
        if self.fail:
            raise TimeoutError()
        return self.result


class GateTests(unittest.TestCase):
    def test_websockets_new_state_and_old_closed_property(self):
        self.assertTrue(connection_is_open(types.SimpleNamespace(state=types.SimpleNamespace(name="OPEN"))))
        self.assertFalse(connection_is_open(types.SimpleNamespace(state=types.SimpleNamespace(name="CLOSED"))))
        self.assertTrue(connection_is_open(types.SimpleNamespace(closed=False)))

    def test_fast_plan_requires_whole_request_match(self):
        self.assertEqual(fast_plan("查询逾期工单数量")["intent"],"overdue")
        self.assertEqual(fast_plan("工单RW-2026-00650谁负责")["work_order_code"],"RW-2026-00650")
        self.assertIsNone(fast_plan("查询逾期工单数量，然后写首诗"))
        self.assertIsNone(fast_plan("查询上个月逾期工单数量"))

    def test_same_corp_private_and_mentioned_group(self):
        self.assertTrue(eligible(event(), "test-robot", "test-corp"))
        self.assertTrue(eligible(event(conversationType="2"), "test-robot", "test-corp"))

    def test_invalid_identity_and_unmentioned_group_silent(self):
        for patch in ({"senderCorpId":"external"}, {"chatbotCorpId":"external"},
                      {"robotCode":"wrong"}, {"senderStaffId":""},
                      {"conversationType":"2","isInAtList":False},
                      {"msgtype":"picture"}, {"text":{"content":None}}):
            with self.subTest(patch=patch):
                self.assertFalse(eligible(event(**patch), "test-robot", "test-corp"))

    def test_fast_gate_golden_set(self):
        for question in ("你好", "今天天气", "帮我写诗", "电商平台怎么开店", "新闻有什么", "你是谁", "谁负责", "下一页"):
            with self.subTest(question=question):
                self.assertFalse(candidate(question))
        for question in ("工单进度", "软工单平台打不开", "RW-2026-00650谁负责", "非EAM工单", "这个平台怎么登录"):
            with self.subTest(question=question):
                self.assertTrue(candidate(question))
        self.assertTrue(candidate("谁负责", plan()))
        self.assertFalse(candidate("讲个笑话", plan()))

    def test_context_never_crosses_person_or_conversation(self):
        a = event()
        self.assertNotEqual(context_key(a), context_key(event(senderStaffId="other")))
        self.assertNotEqual(context_key(a), context_key(event(conversationId="other")))

    def test_cli_has_no_inherited_tools_and_no_bypass(self):
        args = RestrictedCodex().command("/tmp", "/tmp/schema.json")
        self.assertIn("--ignore-user-config", args)
        self.assertIn("read-only", args)
        self.assertIn("shell_tool", args)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", args)
        self.assertFalse(any("Bearer " in x for x in args))


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.tmp.name) / "messages.sqlite3")
        self.queries = 0

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def query(self, p, e, groups):
        self.queries += 1
        return {"answer":"真实查询示例：2张。", "total":2, "source":"test"}

    def pipeline(self, model):
        return Pipeline(self.ledger, model, self.query, "http://localhost:5173")

    async def test_unrelated_message_never_calls_model_query_or_sender(self):
        model = FakeModel()
        e = event(text={"content":"今天天气"})
        mid = self.ledger.claim(e)
        self.assertIsNone(await self.pipeline(model).answer(e, mid))
        self.assertEqual((model.calls, self.queries), (0,0))
        self.assertEqual(self.ledger.row(mid)["state"], "silent")

    async def test_keyword_with_irrelevant_intent_silent(self):
        e = event(text={"content":"工单不管了，帮我写诗"})
        model = FakeModel(plan("silent"))
        self.assertIsNone(await self.pipeline(model).answer(e, self.ledger.claim(e)))
        self.assertEqual(self.queries, 0)

    async def test_classifier_timeout_silent(self):
        e = event()
        mid = self.ledger.claim(e)
        self.assertIsNone(await self.pipeline(FakeModel(fail=True)).answer(e, mid))
        self.assertEqual(self.ledger.row(mid)["state"], "silent")

    async def test_query_fact_does_not_use_model_answer(self):
        e = event()
        mid = self.ledger.claim(e)
        answer = await self.pipeline(FakeModel(plan(answer="虚构9999张"))).answer(e, mid)
        self.assertIn("2张", answer)
        self.assertNotIn("9999", answer)
        self.assertEqual(self.ledger.row(mid)["state"], "reply_pending")

    async def test_feedback_bound_to_sender_and_answer(self):
        e = event(); mid = self.ledger.claim(e)
        await self.pipeline(FakeModel()).answer(e, mid)
        self.ledger.update(mid, "sent")
        self.assertFalse(self.ledger.feedback(event(senderStaffId="other"), mid, "有误"))
        self.assertTrue(self.ledger.feedback(e, mid, "有误"))
        with self.ledger.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM gaps").fetchone()[0],1)

    async def test_unhandled_filter_never_queries_broader_scope(self):
        e=event(text={"content":"查上个月张三的工单"});mid=self.ledger.claim(e)
        answer=await self.pipeline(FakeModel(plan("stats",scope_complete=False))).answer(e,mid)
        self.assertEqual(self.queries,0)
        self.assertIn("无法完整表达",answer)

    async def test_help_is_exact_evidence_not_hallucinated_answer(self):
        e=event(text={"content":"工单列表在哪里"});mid=self.ledger.claim(e)
        answer=await self.pipeline(FakeModel(plan("help",answer="虚构收费9999元",sources=["platform-pages"]))).answer(e,mid)
        self.assertNotIn("9999",answer)
        self.assertIn("工单列表",answer)

    async def test_duplicate_and_restart_never_replay_unknown_delivery(self):
        e = event(); mid = self.ledger.claim(e)
        self.assertIsNone(self.ledger.claim(e))
        self.ledger.update(mid, "sending")
        recovered = Ledger(self.ledger.path)
        self.assertEqual(recovered.row(mid)["state"], "unknown")
        self.assertIsNone(recovered.claim(e))

    async def test_context_expiry(self):
        e = event(); self.ledger.remember(e, plan())
        self.assertEqual(self.ledger.context(e)["intent"], "overdue")
        with self.ledger.connect() as db:
            db.execute("UPDATE context SET updated=?", (time.time()-901,))
        self.assertIsNone(self.ledger.context(e))

    async def test_callback_drops_old_events_and_deduplicates(self):
        q = asyncio.Queue(maxsize=2)
        r = Receiver(self.ledger, q, "test-robot", "test-corp", {}, time.time()-1)
        await r.process(types.SimpleNamespace(data=event(createAt=1)))
        self.assertTrue(q.empty())
        cb = types.SimpleNamespace(data=event(conversationType="2"))
        await r.process(cb); await r.process(cb)
        self.assertEqual(q.qsize(),1)

    async def test_unverified_sender_result_not_retried(self):
        e = event(); mid=self.ledger.claim(e); q=asyncio.Queue(); q.put_nowait((e,mid))
        calls=[]
        async def sender(*args):
            calls.append(True); raise TimeoutError()
        task=asyncio.create_task(consume(q,self.pipeline(FakeModel()),{},sender=sender))
        await asyncio.wait_for(q.join(),2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(len(calls),1)
        self.assertEqual(self.ledger.row(mid)["state"],"unknown")

    async def test_unrelated_worker_does_not_invoke_sender(self):
        e=event(text={"content":"你好"});mid=self.ledger.claim(e);q=asyncio.Queue();q.put_nowait((e,mid))
        calls=[]
        async def sender(*args): calls.append(args)
        task=asyncio.create_task(consume(q,self.pipeline(FakeModel()),{},sender=sender))
        await asyncio.wait_for(q.join(),2);task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(calls,[])

    async def test_reply_endpoint_rejects_external_url(self):
        with self.assertRaises(ValueError):
            await send_reply(event(sessionWebhook="https://example.com/leak"),"answer")


if __name__ == "__main__":
    unittest.main()
