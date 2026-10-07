"""打印默认留白只追加事实，批量失败不写入；浏览器测量另见 e2e_print.py。"""
import json
import re
import unittest

from test_core import TempVault, _group_a, seed_types
from clms import creation, ledger, printing, projections, sessions


class PrintTests(TempVault):
    def setUp(self):
        super().setUp()
        seed_types(self.vault)
        self.ids = creation.commit_draft(self.vault, {"id": "D-print", "images": []}, _group_a())["item_ids"]
        self.session = sessions.create(self.vault, self.ids)

    def test_saved_defaults_survive_replay_and_future_session(self):
        before = ledger.read_commits(self.vault)
        result = printing.update_blank_lines(self.vault, self.session["id"], [{"item_id": self.ids[0], "blank_lines": 135}])
        self.assertEqual(result["updated"], [self.ids[0]])
        commits = ledger.read_commits(self.vault)
        self.assertEqual(commits[:len(before)], before)
        self.assertEqual(commits[-1]["commit_type"], "item.update")
        projections.reset_state(self.vault)
        reopened = sessions.view(self.vault, self.session["id"])
        self.assertEqual(reopened["items"][0]["blank_lines"], 135)
        newer = sessions.create(self.vault, self.ids)
        self.assertEqual(newer["items"][0]["blank_lines"], 135)
        self.assertTrue(ledger.verify_ledger(self.vault)["ok"])

    def test_batch_validates_all_members_before_writing(self):
        before = len(ledger.read_commits(self.vault))
        with self.assertRaises(ValueError):
            printing.update_blank_lines(self.vault, self.session["id"], [
                {"item_id": self.ids[0], "blank_lines": 8}, {"item_id": "Q-not-a-member", "blank_lines": 3}])
        self.assertEqual(len(ledger.read_commits(self.vault)), before)
        self.assertEqual(sessions.view(self.vault, self.session["id"])["items"][0]["blank_lines"], 7)

    def test_integer_range_and_duplicates_are_strict(self):
        for invalid in (-1, 1001, 1.2, "3", True, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                printing.update_blank_lines(self.vault, self.session["id"], [{"item_id": self.ids[0], "blank_lines": invalid}])
        with self.assertRaises(ValueError):
            printing.update_blank_lines(self.vault, self.session["id"], [{"item_id": self.ids[0], "blank_lines": 1}] * 2)

    def test_noop_or_opening_print_document_has_no_commit(self):
        before = len(ledger.read_commits(self.vault))
        page = printing.render_session(self.session)
        self.assertIn('id="print-css"', page)
        self.assertIn('/assets/app/domain/print-layout.js', page)
        result = printing.update_blank_lines(self.vault, self.session["id"], [{"item_id": self.ids[0], "blank_lines": 7}])
        self.assertEqual(result["updated"], [])
        self.assertEqual(len(ledger.read_commits(self.vault)), before)

    def test_cancelled_session_cannot_change_defaults(self):
        sessions.cancel(self.vault, self.session["id"])
        with self.assertRaises(KeyError):
            printing.update_blank_lines(self.vault, self.session["id"], [{"item_id": self.ids[0], "blank_lines": 4}])

    def test_print_data_cannot_close_the_json_script(self):
        self.session["items"][0]["answer"] = '</script><script>alert("bad")</script>'
        page = printing.render_session(self.session, with_answers=True)
        content = re.search(r'<script type="application/json" id="print-data">(.*?)</script>', page, re.S).group(1)
        self.assertNotIn('</script>', content)
        self.assertEqual(json.loads(content)["session"]["items"][0]["answer"], self.session["items"][0]["answer"])


if __name__ == "__main__":
    unittest.main()
