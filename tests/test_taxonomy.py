"""v0.7 用户题型：旧库迁移、配置操作、AI 与 Agent 边界、未分类复习。"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clms import ai_assist, creation, draft_schema, ledger, library, projections, records, scheduling, sessions, taxonomy  # noqa: E402
from clms.agent_draft import Workspace, draft_tools  # noqa: E402
from clms.common import config_path, load_config, save_config  # noqa: E402
from test_core import TempVault  # noqa: E402


def groups(qtype="", stem="分析第①段的作用。"):
    return draft_schema.normalize_groups([{"genre": "现代文阅读", "material": {"title": "短文", "text": "①春风吹过，树影摇动。"},
                                           "items": [{"no": "1", "qtype": qtype, "stem": stem, "answer": "照应下文"}]}])


class TaxonomyTests(TempVault):
    def test_new_vault_empty_and_add_reorder_duplicate(self):
        self.assertEqual(taxonomy.qtypes(self.vault)["modern"], [])
        self.assertEqual(taxonomy.qtypes(self.vault)["classical"], [])
        self.assertEqual(taxonomy.qtypes(self.vault)["poetry"], [])
        taxonomy.add(self.vault, "modern", " 段落作用题 ")
        taxonomy.add(self.vault, "modern", "人物形象题")
        self.assertEqual(taxonomy.reorder(self.vault, "modern", ["人物形象题", "段落作用题"])["qtypes"]["modern"],
                         ["人物形象题", "段落作用题"])
        with self.assertRaisesRegex(ValueError, "同名"):
            taxonomy.add(self.vault, "modern", "段落作用题")
        with self.assertRaises(ValueError):
            taxonomy.reorder(self.vault, "modern", ["段落作用题", "段落作用题"])
        with self.assertRaises(ValueError):
            taxonomy.add(self.vault, "dictation", "自造默写")
        taxonomy.delete(self.vault, "modern", "人物形象题")
        self.assertEqual(taxonomy.qtypes(self.vault)["modern"], ["段落作用题"])
        taxonomy.delete(self.vault, "modern", "段落作用题")
        self.assertEqual(taxonomy.qtypes(self.vault)["modern"], [])  # 删光后不会回退预置表

    def test_rename_migrates_items_and_kind_and_retries(self):
        taxonomy.add(self.vault, "modern", "句子赏析题")
        taxonomy.set_kind(self.vault, "modern", "句子赏析题", "recall")
        one = creation.commit_draft(self.vault, {"id": "D1"}, groups("句子赏析题"))["item_ids"][0]
        two = creation.commit_draft(self.vault, {"id": "D2"}, groups("句子赏析题", "解释第②段。"))["item_ids"][0]
        records.add(self.vault, one, 1)
        result = taxonomy.rename(self.vault, "modern", "句子赏析题", "赏析题")
        self.assertEqual(result["qtypes"]["modern"], ["赏析题"])
        self.assertEqual(result["qtype_kinds"]["modern"]["赏析题"], "recall")
        self.assertEqual([projections.get_state(self.vault).items[i]["qtype"] for i in (one, two)], ["赏析题", "赏析题"])
        self.assertEqual(library.item_detail(self.vault, one)["sched"]["kind"], "recall")
        self.assertEqual(records.list_records(self.vault, item_id=one)["records"][0]["qtype"], "赏析题")
        self.assertEqual(taxonomy.rename(self.vault, "modern", "句子赏析题", "赏析题")["qtypes"]["modern"], ["赏析题"])
        self.assertTrue(ledger.verify_ledger(self.vault)["ok"])

    def test_interrupted_rename_and_delete_resume_without_ghosts(self):
        taxonomy.add(self.vault, "modern", "旧题型")
        taxonomy.add(self.vault, "modern", "目标题型")
        ids = [creation.commit_draft(self.vault, {"id": f"D{n}"}, groups("旧题型", f"题干第{n}段"))["item_ids"][0]
               for n in (1, 2)]
        original = creation.update_item
        calls = 0

        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("模拟中断")
            return original(*args)

        with patch.object(creation, "update_item", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "模拟中断"):
                taxonomy.rename(self.vault, "modern", "旧题型", "新题型")
        self.assertEqual(load_config(self.vault)["qtype_migration"]["new_name"], "新题型")
        taxonomy.rename(self.vault, "modern", "旧题型", "新题型")
        self.assertEqual([projections.get_state(self.vault).items[i]["qtype"] for i in ids], ["新题型"] * 2)
        self.assertEqual(load_config(self.vault)["qtype_migration"], {})
        calls = 0
        with patch.object(creation, "update_item", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "模拟中断"):
                taxonomy.delete(self.vault, "modern", "新题型", "目标题型")
        taxonomy.delete(self.vault, "modern", "新题型", "目标题型")
        self.assertEqual([projections.get_state(self.vault).items[i]["qtype"] for i in ids], ["目标题型"] * 2)
        self.assertEqual(taxonomy.qtypes(self.vault)["modern"], ["目标题型"])

    def test_delete_requires_migration_and_allows_uncategorized(self):
        taxonomy.add(self.vault, "modern", "作用题")
        taxonomy.add(self.vault, "modern", "赏析题")
        one = creation.commit_draft(self.vault, {"id": "D1"}, groups("作用题"))["item_ids"][0]
        records.add(self.vault, one, 1)
        with self.assertRaisesRegex(ValueError, "还有 1 道题"):
            taxonomy.delete(self.vault, "modern", "作用题")
        with self.assertRaises(ValueError):
            taxonomy.delete(self.vault, "modern", "作用题", "别的板块题型")
        taxonomy.delete(self.vault, "modern", "作用题", "赏析题")
        self.assertEqual(projections.get_state(self.vault).items[one]["qtype"], "赏析题")
        taxonomy.delete(self.vault, "modern", "赏析题", "")
        self.assertEqual(projections.get_state(self.vault).items[one]["qtype"], "")
        self.assertEqual(taxonomy.taxonomy_payload(self.vault)["uncategorized"]["modern"], 1)
        self.assertEqual(library.list_items(self.vault, qtype="__unclassified__")["total"], 1)
        self.assertEqual(library.item_detail(self.vault, one)["sched"]["kind"], "skill")
        self.assertEqual(records.list_records(self.vault, item_id=one)["total"], 1)
        with patch.dict(os.environ, {"CLMS_TODAY": "2027-12-31"}):
            self.assertTrue(sessions.plan(self.vault, minutes=40)["items"])

    def test_deleted_item_is_migrated_before_restore(self):
        taxonomy.add(self.vault, "modern", "旧题型")
        item_id = creation.commit_draft(self.vault, {"id": "D1"}, groups("旧题型"))["item_ids"][0]
        library.delete(self.vault, item_id)
        taxonomy.rename(self.vault, "modern", "旧题型", "新题型")
        self.assertEqual(projections.get_state(self.vault).deleted[item_id]["qtype"], "新题型")
        library.restore(self.vault, item_id)
        self.assertEqual(library.item_detail(self.vault, item_id)["qtype"], "新题型")

    def test_ai_unknown_is_blank_in_extract_revise_and_agent_tool(self):
        raw = {"groups": [{"genre": "现代文阅读", "material": {"title": "短文", "text": "①春风吹过，树影摇动。"},
                           "items": [{"no": "1", "qtype": "一个用户从未创建的题型", "stem": "问？", "answer": "答"}]}]}
        with patch.object(ai_assist, "image_data_urls", return_value=["data:x"]), \
             patch.object(ai_assist, "call_model", return_value=json.dumps(raw, ensure_ascii=False)):
            result = ai_assist.extract(self.vault, ["fake.png"])
        self.assertEqual(result["groups"][0]["items"][0]["qtype"], "")
        with patch.object(ai_assist, "call_model", return_value=json.dumps({"draft": raw}, ensure_ascii=False)):
            self.assertEqual(ai_assist.revise(self.vault, result["groups"], [], "改题型", [])["groups"][0]["items"][0]["qtype"], "")
        ws = Workspace(self.vault, [], [])
        tools = {tool.name: tool for tool in draft_tools(ws)}
        tools["group_add"].execute({"genre": "现代文阅读"}, None)
        tools["items_add"].execute({"gid": "g1", "items": raw["groups"][0]["items"]}, None)
        self.assertEqual(ws.groups[0]["items"][0]["qtype"], "")
        taxonomy.add(self.vault, "modern", "一个用户从未创建的题型")
        tools["item_update"].execute({"ref": "i1", "qtype": "一个用户从未创建的题型"}, None)
        self.assertEqual(ws.groups[0]["items"][0]["qtype"], "一个用户从未创建的题型")
        with patch.object(ai_assist, "image_data_urls", return_value=["data:x"]), \
             patch.object(ai_assist, "call_model", return_value=json.dumps(raw, ensure_ascii=False)):
            self.assertEqual(ai_assist.extract(self.vault, ["fake.png"])["groups"][0]["items"][0]["qtype"],
                             "一个用户从未创建的题型")

    def test_old_draft_unknown_type_commits_as_uncategorized(self):
        result = creation.commit_draft(self.vault, {"id": "D-old"}, groups("旧草稿自带题型"))
        self.assertEqual(projections.get_state(self.vault).items[result["item_ids"][0]]["qtype"], "")

    def test_uncategorized_does_not_cluster_and_kind_changes_schedule(self):
        one = creation.commit_draft(self.vault, {"id": "D1"}, groups())["item_ids"][0]
        self.assertEqual(library.item_detail(self.vault, one)["sched"]["kind"], "skill")
        self.assertEqual(scheduling.weak_qtypes([library.item_detail(self.vault, one)]), set())
        taxonomy.add(self.vault, "modern", "自定义名称")
        creation.update_item(self.vault, one, {"qtype": "自定义名称"})
        taxonomy.set_kind(self.vault, "modern", "自定义名称", "recall")
        self.assertEqual(library.item_detail(self.vault, one)["sched"]["kind"], "recall")
        taxonomy.rename(self.vault, "modern", "自定义名称", "随意改名")
        self.assertEqual(library.item_detail(self.vault, one)["sched"]["kind"], "recall")

    def test_v06_migration_uses_only_actual_types_and_keeps_ledger(self):
        os.makedirs(os.path.dirname(config_path(self.vault)), exist_ok=True)
        with open(config_path(self.vault), "w", encoding="utf-8") as fh:
            json.dump({"qtypes": {}}, fh)
        item = {"id": "Q-000001", "material_id": None, "genre": "classical", "qtype": "实词解释题",
                "stem": "解释俄而", "answer": "不久", "key": "legacy"}
        ledger.append_commit(self.vault, "old", "entry.commit", "旧题", {"draft_id": "D-old", "items": [item]})
        ledger.append_commit(self.vault, "old", "review.grade", "旧评分", {"item_id": item["id"], "grade": 1})
        save_config(self.vault, {"theme": "dark"})  # 其它设置先被保存，也不能把空默认表误当成已迁移
        before = ledger.verify_ledger(self.vault)["count"]
        payload = taxonomy.taxonomy_payload(self.vault)
        self.assertEqual(payload["qtypes"]["classical"], ["实词解释题"])
        self.assertEqual(payload["qtypes"]["modern"], [])
        self.assertEqual(payload["qtype_kinds"]["classical"]["实词解释题"], "recall")
        self.assertEqual(ledger.verify_ledger(self.vault)["count"], before)
        self.assertEqual(library.item_detail(self.vault, item["id"])["sched"]["reviews"], 1)
        self.assertEqual(load_config(self.vault)["qtypes"]["classical"], ["实词解释题"])
        self.assertEqual(taxonomy.qtypes(self.vault)["classical"], ["实词解释题"])


if __name__ == "__main__":
    unittest.main()
