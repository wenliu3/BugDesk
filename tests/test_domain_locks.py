"""Late editor saves cannot rewrite a Bug that has entered a terminal lifecycle."""

import copy
import tempfile
import unittest
from pathlib import Path

from domain import Workbench


class DraftLifecycleLockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.data = base / "data"
        self.root = base / "bugs"
        for name in ("first-bug", "second-bug"):
            folder = self.root / name
            folder.mkdir(parents=True)
            (folder / "evidence.txt").write_text("original evidence", encoding="utf-8")
        self.workbench = Workbench(self.data)
        state = self.workbench.scan(str(self.root))
        self.identifiers = [bug["id"] for bug in state["bugs"]]
        self.workbench.save({"settings": {"product": "331", "openedBuild": ["62"]},
                             "bugs": [{"id": identifier, "steps": "原始步骤", "actual": "原始现象",
                                       "expected": "预期结果"} for identifier in self.identifiers]})

    def mark(self, status, remote_id=None):
        identifier = self.identifiers[0]
        fields = {"status": status}
        if remote_id is not None:
            fields["remote_id"] = remote_id
        if status == "submitting":
            bug = self.workbench.get_bug(identifier)
            self.workbench.save({"bugs": [{"id": identifier, "reviewed": True, "review_token": bug["review_token"]}]})
        if status == "locked":
            next(bug for bug in self.workbench._batch()["bugs"] if bug["id"] == identifier)["locked"] = True
        else:
            self.workbench.set_submission(identifier, **fields)

    def test_delayed_old_window_autosave_cannot_rewrite_a_submitted_bug(self):
        identifier = self.identifiers[0]
        stale_patch = {"id": identifier, "actual": "旧窗口晚到的修改", "reviewed": False}
        self.mark("submitting")
        self.workbench.set_submission(identifier, status="submitted", remote_id=123)
        before = self.workbench.state()
        with self.assertRaisesRegex(ValueError, "已提交、等待核对或已锁定"):
            self.workbench.save({"bugs": [stale_patch]})
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(Workbench(self.data).state(), before)

    def test_terminal_states_and_known_remote_ids_reject_every_editable_content_field(self):
        states = (("submitted", 123), ("uncertain", None), ("partial", 456), ("failed", 789), ("locked", None))
        patches = ({"title": "新标题"}, {"preconditions": "新前置条件"}, {"steps": "新步骤"}, {"actual": "新现象"},
                   {"expected": "新预期"}, {"overrides": {"pri": "1"}}, {"excluded_attachments": []},
                   {"reviewed": False}, {"reviewed": True})
        for status, remote_id in states:
            original = copy.deepcopy(self.workbench._store)
            self.mark(status, remote_id)
            before = self.workbench.state()
            for patch in patches:
                with self.subTest(status=status, field=list(patch)[0]), self.assertRaisesRegex(ValueError, "已锁定"):
                    self.workbench.save({"bugs": [{"id": self.identifiers[0], **patch}]})
                self.assertEqual(self.workbench.state(), before)
            self.workbench._store = original

    def test_selected_only_changes_remain_allowed_for_terminal_and_locked_bugs(self):
        for status, remote_id in (("submitted", 123), ("uncertain", None), ("partial", 456), ("failed", 789), ("locked", None)):
            with self.subTest(status=status):
                original = copy.deepcopy(self.workbench._store)
                self.mark(status, remote_id)
                before = self.workbench.get_bug(self.identifiers[0])
                self.workbench.save({"bugs": [{"id": self.identifiers[0], "selected": False}]})
                after = self.workbench.get_bug(self.identifiers[0])
                self.assertFalse(after["selected"])
                for field in ("title", "steps", "actual", "expected", "overrides", "reviewed", "status", "remote_id", "review_token"):
                    self.assertEqual(after[field], before[field])
                self.workbench.save({"bugs": [{"id": self.identifiers[0], "selected": True}]})
                self.assertTrue(self.workbench.get_bug(self.identifiers[0])["selected"])
                self.workbench._store = original

    def test_later_locked_patch_rejects_whole_batch_without_partial_settings_or_edits(self):
        self.mark("submitted", 123)
        before = self.workbench.state()
        with self.assertRaisesRegex(ValueError, "已锁定"):
            self.workbench.save({"settings": {"assignedTo": "new-user"}, "bugs": [
                {"id": self.identifiers[1], "steps": "不得部分保存"},
                {"id": self.identifiers[0], "actual": "不得覆盖已提交记录"},
            ]})
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(Workbench(self.data).state(), before)

    def test_failed_before_creation_still_allows_edit_review_and_retry(self):
        identifier = self.identifiers[0]
        self.workbench.set_submission(identifier, status="failed", error="禅道明确拒绝创建")
        self.workbench.save({"bugs": [{"id": identifier, "actual": "修正后的实际现象"}]})
        current = self.workbench.get_bug(identifier)
        self.assertEqual(current["status"], "needs_review")
        self.assertEqual(current["actual"], "修正后的实际现象")
        self.assertEqual(current["error"], "")
        self.workbench.save({"bugs": [{"id": identifier, "reviewed": True, "review_token": current["review_token"]}]})
        self.assertEqual(len(self.workbench.validate_submission([identifier])), 1)


if __name__ == "__main__":
    unittest.main()
