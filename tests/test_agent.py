"""Agent harness、工具、复习记录增删改查、脱敏源码导出，以及 Agent 模式下的 HTTP 全流程。"""

import io
import itertools
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_ai  # noqa: E402
from clms import creation, drafts, harness, library, ledger, projections, records, sessions  # noqa: E402
from clms.agent_draft import Workspace, draft_tools  # noqa: E402
from clms.common import save_config  # noqa: E402
from clms.source_export import create_source_export  # noqa: E402
import test_core  # noqa: E402
from test_core import TempVault, _group_a  # noqa: E402

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def call(name, **args):
    return {"id": f"c{name}{len(args)}", "name": name, "arguments": json.dumps(args, ensure_ascii=False)}


class HarnessTests(unittest.TestCase):
    def make(self, replies, tools, **kw):
        seen = []

        def llm(messages, schemas):
            seen.append(messages)
            return replies.pop(0)
        agent = harness.Agent(llm=llm, tools=tools, system_prompt="SYS", render_images=lambda refs: ["data:x"] * len(refs),
                              run_id="r2", **kw)
        return agent, seen

    def test_loop_runs_tools_and_reports_errors_back(self):
        log = []
        echo = harness.Tool("echo", "", {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
                            lambda a, ctx: log.append(a["n"]) or f"got {a['n']}")
        agent, seen = self.make([{"tool_calls": [call("echo", n="3"), call("echo"), call("nope")]},
                                 {"content": "完成"}], [echo])
        new = agent.run([], [{"role": "user", "content": "go"}])
        self.assertEqual(log, [3])                                   # "3" 被按 schema 转成整数
        tool_msgs = [m["content"] for m in new if m["role"] == "tool"]
        self.assertIn("缺少必填参数", tool_msgs[1])
        self.assertIn("没有工具 nope", tool_msgs[2])
        self.assertEqual(harness.final_text(new), "完成")
        self.assertTrue(seen[0][0]["content"].startswith("SYS"))   # 系统说明并进第一条用户消息

    def test_truncated_tool_calls_are_not_executed(self):
        log = []
        echo = harness.Tool("echo", "", {"type": "object", "properties": {}}, lambda a, ctx: log.append(1) or "ok")
        agent, _ = self.make([{"tool_calls": [call("echo")], "finish_reason": "length"}, {"content": "好"}], [echo])
        new = agent.run([], [{"role": "user", "content": "go"}])
        self.assertEqual(log, [])
        self.assertIn("超出了输出上限", [m for m in new if m["role"] == "tool"][0]["content"])

    def test_old_images_are_elided_and_steering_is_injected(self):
        queue = [[{"role": "user", "content": "再补一句"}], []]
        agent, seen = self.make([{"content": "一"}, {"content": "二"}], [], steering=lambda: queue.pop(0))
        history = [{"role": "user", "content": "旧图", "images": [{"page": 1}], "run": "r1"},
                   {"role": "assistant", "content": "好"}]
        agent.run(history, [{"role": "user", "content": "新图", "images": [{"page": 1}]}])
        first = seen[0]
        self.assertIsInstance(first[0]["content"], str)              # 上一次 run 的图不再发
        self.assertIn("不再重发", first[0]["content"])
        self.assertIsInstance(first[2]["content"], list)             # 本次 run 的图照发
        self.assertEqual(seen[1][-1]["content"], "再补一句")          # 插话进了下一次请求

    def test_abort_stops_before_next_request(self):
        stop = threading.Event()
        tool = harness.Tool("slow", "", {"type": "object", "properties": {}}, lambda a, ctx: stop.set() or "ok")
        agent, seen = self.make([{"tool_calls": [call("slow")]}, {"content": "不该到这"}], [tool], abort=stop)
        with self.assertRaises(harness.Aborted):
            agent.run([], [{"role": "user", "content": "go"}])
        self.assertEqual(len(seen), 1)


class DraftToolTests(TempVault):
    def tools(self, ws, **kw):
        return {t.name: t for t in draft_tools(ws, **kw)}

    def run_tool(self, tools, name, **args):
        return tools[name].execute(args, None)

    def test_build_and_edit_draft_item_by_item(self):
        changes = []
        ws = Workspace(self.vault, [], ["a.png"], on_change=changes.append)
        t = self.tools(ws)
        self.run_tool(t, "group_add", genre="现代文阅读", title="老街的灯", text="①老街在城的东头，街不长。")
        self.run_tool(t, "items_add", gid="g1", items=[{"no": "7", "qtype": "意象作用题", "stem": "分析灯的作用", "answer": "线索", "score": 6},
                                                         {"no": "8", "stem": "赏析句子"}])
        out = self.run_tool(t, "item_update", ref="第7题", blank_lines=9, answer="①线索②象征")
        self.assertIn("答案", out.content)
        item = ws.groups[0]["items"][0]
        self.assertEqual((item["iid"], item["blank_lines"], item["answer_origin"]), ("i1", 9, "ai"))
        self.run_tool(t, "dictation_add", entries=[{"template": "床前明月光，{书写区域1}。", "blanks": {"1": "疑是地上霜"}}])
        self.assertEqual([g["genre"] for g in ws.groups], ["modern", "dictation"])
        self.assertIn("默写已有", self.run_tool(t, "group_add", genre="名句默写").content.replace("名句默写只用一个板块，已有", "默写已有"))
        view = json.loads(self.run_tool(t, "draft_view").content)
        self.assertEqual(view["dedupe"]["new_units"], 3)
        self.assertTrue(any("没有答案" in p["message"] for p in view["issues"]))
        self.assertTrue(changes)

    def test_subagent_scope_is_enforced(self):
        ws = Workspace(self.vault, _group_a(), ["a.png"])
        sub = self.tools(ws, scope="g1", structure=False)
        self.assertNotIn("group_add", sub)
        with self.assertRaises(harness.ToolError):
            self.run_tool(sub, "dictation_add", gid="g2", entries=[{"template": "{书写区域1}", "blanks": {"1": "某"}}])
        self.run_tool(sub, "items_add", items=[{"no": "9", "stem": "新题", "answer": "答"}])
        self.assertEqual(ws.groups[0]["items"][-1]["no"], "9")


class RecordTests(TempVault):
    def setUp(self):
        super().setUp()
        result = creation.commit_draft(self.vault, {"id": "D-x", "images": []}, _group_a())
        self.ids = result["item_ids"]
        self.sid = sessions.create(self.vault, self.ids)["id"]

    def test_record_crud_is_append_only(self):
        q = self.ids[0]
        added = records.add(self.vault, q, 1, "漏了采分点", date="2026-01-02")
        self.assertEqual(added["at"][:10], "2026-01-02")
        changed = records.update(self.vault, added["commit_id"], grade=3)
        self.assertEqual((changed["grade"], changed["note"], changed["replaces"]), (3, "漏了采分点", added["commit_id"]))
        records.delete(self.vault, changed["commit_id"])
        listing = records.list_records(self.vault, item_id=q)["records"]
        self.assertTrue(all(r["voided"] for r in listing))
        restored = records.restore(self.vault, changed["commit_id"])
        self.assertEqual(restored["restored_from"], changed["commit_id"])
        with self.assertRaises(ValueError):
            records.restore(self.vault, changed["commit_id"])
        item = projections.get_state(self.vault).item_view(q, projections.context(self.vault))
        self.assertEqual(item["sched"]["reviews"], 1)
        with self.assertRaises(ValueError):
            records.add(self.vault, self.ids[-1], 2)                  # 默写没有 2 档
        self.assertTrue(ledger.verify_ledger(self.vault)["ok"])

    def test_restore_in_session_voids_current_grade(self):
        q = self.ids[0]
        sessions.grade(self.vault, self.sid, q, 1, "第一次")
        first = sessions.view(self.vault, self.sid)["items"][0]["grade"]["commit_id"]
        sessions.grade(self.vault, self.sid, q, 3)
        records.restore(self.vault, first)
        grade = sessions.view(self.vault, self.sid)["items"][0]["grade"]
        self.assertEqual((grade["grade"], grade["note"]), (1, "第一次"))
        self.assertEqual(sessions.view(self.vault, self.sid)["progress"]["done"], 1)

    def test_grade_many_and_item_delete_restore(self):
        state = projections.get_state(self.vault)
        result = sessions.grade_many(self.vault, self.sid, [
            {"item_id": i, "grade": 3 if state.items[i]["genre"] == "dictation" else 2, "note": "AI"} for i in self.ids])
        self.assertTrue(result["session"]["progress"]["complete"])
        library.delete(self.vault, self.ids[0])
        self.assertEqual(library.list_items(self.vault, status="deleted")["total"], 1)
        library.restore(self.vault, self.ids[0])
        self.assertIn(self.ids[0], projections.get_state(self.vault).items)
        self.assertEqual(len(library.item_detail(self.vault, self.ids[0])["records"]), 1)


class SourceExportTests(unittest.TestCase):
    def test_export_skips_data_and_redacts_key(self):
        root = tempfile.mkdtemp(prefix="clms-src-")
        os.makedirs(os.path.join(root, "clms"))
        os.makedirs(os.path.join(root, "语文", ".clms"))
        os.makedirs(os.path.join(root, "clms", "__pycache__"))
        secret = "sk-test1234567890abcdef"
        open(os.path.join(root, "clms", "a.py"), "w", encoding="utf-8").write(f"KEY = '{secret}'\n")
        open(os.path.join(root, "clms", "__pycache__", "a.pyc"), "wb").write(b"x")
        open(os.path.join(root, "语文", ".clms", "config.json"), "w").write("{}")
        open(os.path.join(root, "README.md"), "w", encoding="utf-8").write("说明")
        save_config(root, {"ai_api_key": secret})
        data, name, meta = create_source_export(root, root=root)
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        self.assertTrue(name.startswith("CLMS-source-sanitized-"))
        self.assertEqual(sorted(names), ["CLMS/README.md", "CLMS/SOURCE_EXPORT_MANIFEST.txt", "CLMS/clms/a.py"])
        body = zipfile.ZipFile(io.BytesIO(data)).read("CLMS/clms/a.py").decode()
        self.assertNotIn(secret, body)
        self.assertEqual(meta["redacted"], ["clms/a.py（1 处）"])


class AgentFlowTests(test_core.ServerFlowTests):
    """Agent 模式：上传 → 主代理委派子代理 → 对话逐题改 → 插话 / 停止 → 对话入库 → 继续查改题库 → 拍照批改。"""

    AGENT = True
    test_full_flow = None

    def setUp(self):
        super().setUp()
        fake_ai._keys = itertools.cycle(["A", "B", "C"])
        os.environ.pop("FAKE_AI_DELAY", None)

    def tearDown(self):
        os.environ.pop("FAKE_AI_DELAY", None)
        super().tearDown()

    def upload(self, **extra):
        code, res = self.call("/api/drafts", dict({"images": [{"name": "a.png", "data": PNG}]}, **extra))
        self.assertEqual(code, 200, res)
        return self.wait_ready(res["drafts"][0]["id"])

    def test_agent_extract_chat_commit_and_review(self):
        draft = self.upload()
        self.assertEqual(draft["status"], "ready", draft.get("error"))
        self.assertEqual([g["genre"] for g in draft["groups"]], ["modern", "dictation"])
        seg = draft["messages"][-1]
        delegate = next(s for s in seg["steps"] if s.get("name") == "delegate")
        self.assertEqual([t["status"] for t in delegate["tasks"]], ["done", "done"])
        self.assertEqual(len(draft["revisions"]), 1)                    # 整次 run 只占一版
        self.assertEqual(draft["groups"][0]["items"][1]["iid"], "i2")
        self.call("/api/draft/message", {"id": draft["id"], "text": "第7题答案按采分点重写，留白 8 行"})
        draft = self.wait_ready(draft["id"])
        last = draft["messages"][-1]
        self.assertEqual({c["field"] for c in last["changes"]}, {"answer", "blank_lines"})
        self.assertEqual(last["base_revision"], 1)
        self.call("/api/draft/message", {"id": draft["id"], "text": "没问题了，入库"})
        draft = self.wait_ready(draft["id"])
        self.assertEqual(draft["status"], "committed", draft["messages"][-2:])
        self.assertEqual(draft["committed"]["created"], 6)
        self.call("/api/draft/message", {"id": draft["id"], "text": "把 Q-000001 停用 Q-000001"})
        draft = self.wait_ready(draft["id"])
        self.assertEqual(draft["status"], "committed")
        _, item = self.call("/api/item?id=Q-000001")
        self.assertTrue(item["suspended"])
        _, sess = self.call("/api/sessions", {"item_ids": ["Q-000002", "Q-000004"], "minutes": 10})
        review = self.upload(review_session=sess["id"])
        self.assertEqual(review["kind"], "review")
        _, graded = self.call(f"/api/session?id={sess['id']}")
        self.assertTrue(graded["progress"]["complete"])
        self.assertEqual({i["grade"]["note"] for i in graded["items"]}, {"要点基本齐全", "全对"})
        _, recs = self.call(f"/api/records?session_id={sess['id']}")
        self.assertEqual(recs["total"], 2)
        code, rec = self.call("/api/record/update", {"commit_id": recs["records"][0]["commit_id"], "note": "改了反馈"})
        self.assertEqual((code, rec["note"]), (200, "改了反馈"))

    def test_steering_and_abort(self):
        _, res = self.call("/api/drafts", {"manual": "modern"})
        draft_id = res["drafts"][0]["id"]
        groups = res["drafts"][0]["groups"]
        groups[0]["material"]["text"] = "①老街在城的东头。"
        groups[0]["items"] = [{"no": "7", "stem": "甲", "answer": "乙"}, {"no": "8", "stem": "丙", "answer": "丁"}]
        self.call("/api/draft/edit", {"id": draft_id, "groups": groups, "revision": 1})
        os.environ["FAKE_AI_DELAY"] = "0.4"
        self.call("/api/draft/message", {"id": draft_id, "text": "第7题留白 5 行"})
        time.sleep(0.1)
        _, queued = self.call("/api/draft/message", {"id": draft_id, "text": "第8题留白 6 行"})
        self.assertEqual(queued["queued"], 1)
        draft = self.wait_ready(draft_id, rounds=200)
        lines = {i["no"]: i["blank_lines"] for i in draft["groups"][0]["items"]}
        self.assertEqual((lines["7"], lines["8"]), (5, 6))
        roles = [m["role"] for m in draft["messages"][-3:]]
        self.assertEqual(roles, ["ai", "user", "ai"])                     # 插话排在当时的位置
        self.assertIn("手动改了", json.dumps(drafts.load(self.vault, draft_id)["agent"]["messages"], ensure_ascii=False))
        self.call("/api/draft/message", {"id": draft_id, "text": "第7题留白 9 行"})
        code, stopped = self.call("/api/draft/abort", {"id": draft_id})
        self.assertEqual((code, stopped["status"]), (200, "ready"))
        count = len(stopped["messages"])
        time.sleep(1.2)
        _, after = self.call(f"/api/draft?id={draft_id}")
        self.assertEqual(len(after["messages"]), count)                  # 停止后的写入被丢弃
        self.assertEqual(after["status"], "ready")
        self.assertFalse(any(m.get("status") == "running" for m in after["messages"]))   # 没开始就停了，或停在半路

    def test_source_export_endpoint(self):
        with urllib_open(self.base + "/api/source/export") as res:
            self.assertEqual(res.headers["Content-Type"], "application/zip")
            self.assertIn("CLMS-source-sanitized-", res.headers["Content-Disposition"])
            names = zipfile.ZipFile(io.BytesIO(res.read())).namelist()
        self.assertIn("CLMS/clms/harness.py", names)
        self.assertFalse(any("__pycache__" in n or "/语文/" in n for n in names))

    def wait_ready(self, draft_id, rounds=200):
        for _ in range(rounds):
            _, d = self.call(f"/api/draft?id={draft_id}")
            if d["status"] not in ("queued", "extracting", "thinking"):
                return d
            time.sleep(0.05)
        self.fail("草稿一直在处理中")


def urllib_open(url):
    import urllib.request
    return urllib.request.urlopen(url, timeout=20)


if __name__ == "__main__":
    unittest.main()
