"""Undo is a durable, atomic draft edit, never a submission rollback."""

import copy
import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from domain import Workbench
from draft_undo import STORE_KEY, validate_record
from workbuddy import WorkBuddyBridge


class DraftUndoTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "synthetic-bugs"
        for name in ("Bug A", "Bug B", "Bug C"):
            folder = self.root / name
            folder.mkdir(parents=True)
            (folder / "evidence.txt").write_text("synthetic evidence", encoding="utf-8")
        self.workbench = Workbench(self.base / "data")
        self.workbench.scan(str(self.root))
        self.ids = [bug["id"] for bug in self.workbench.state()["bugs"]]

    @staticmethod
    def row(index=1, **changes):
        row = {"row_id": f"row-{index}", "case_id": f"CASE-{index}", "title": f"用例 {index}",
               "group": "合成数据", "tester": "测试员", "date": "2026-10-19",
               "preconditions": f"前提 {index}", "steps": f"步骤 {index}",
               "actual": f"实际 {index}", "expected": f"预期 {index}"}
        row.update(changes)
        return row

    def apply(self, indices=(0,), *, record_undo=True, rows=None):
        state = self.workbench.state()
        bugs = {bug["id"]: bug for bug in state["bugs"]}
        rows = rows or [self.row(index + 1) for index in indices]
        assignments = [{"row_id": row["row_id"], "bug_id": self.ids[index], "mode": "replace",
                        "review_token": bugs[self.ids[index]]["review_token"]}
                       for index, row in zip(indices, rows)]
        return self.workbench.apply_cases(rows, assignments, batch_key=state["batch_key"], record_undo=record_undo)

    def undo(self):
        return self.workbench.undo_last_import(self.workbench.undo_status()["transaction_id"])

    def test_durable_transaction_restores_facts_and_all_source_metadata(self):
        originals = [self.row(index) for index in (8, 9, 10)]
        for source in originals:
            source.pop("row_id")
        self.apply(record_undo=False, rows=[self.row(8, source_cases=originals)])
        before = self.workbench.state()["bugs"][0]
        self.apply()
        summary = self.workbench.undo_status()
        self.assertTrue(summary["available"])
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["titles"], ["Bug A"])
        self.assertEqual(set(summary), {"transaction_id", "count", "titles", "available", "reason"})
        self.workbench = Workbench(self.base / "data")
        self.assertEqual(self.workbench.undo_status(), summary)
        result = self.undo()
        self.assertEqual(result["undone"], 1)
        self.assertIsNone(result["undo"])
        restored = result["state"]["bugs"][0]
        for key in ("preconditions", "steps", "actual", "expected", "case_source", "case_sources"):
            self.assertEqual(restored[key], before[key])
        self.assertFalse(restored["reviewed"])
        self.assertIsNone(Workbench(self.base / "data").undo_status())

    def test_only_latest_changed_targets_are_undone(self):
        self.apply((0, 1))
        first = copy.deepcopy(self.workbench.state()["bugs"])
        old_id = self.workbench.undo_status()["transaction_id"]
        self.apply((2,))
        summary = self.workbench.undo_status()
        self.assertNotEqual(summary["transaction_id"], old_id)
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["titles"], ["Bug C"])
        with self.assertRaises(ValueError):
            self.workbench.undo_last_import(old_id)
        result = self.undo()
        for index in (0, 1):
            self.assertEqual(result["state"]["bugs"][index], first[index])
        self.assertEqual(result["state"]["bugs"][2]["steps"], "")

    def test_noop_does_not_replace_the_previous_transaction(self):
        self.apply()
        summary = self.workbench.undo_status()
        result = self.apply()
        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(self.workbench.undo_status(), summary)
        self.undo()
        self.assertEqual(self.workbench.state()["bugs"][0]["steps"], "")

    def test_unchanged_assignment_is_excluded_from_transaction(self):
        self.apply((0,), record_undo=False)
        self.apply((0, 1))
        self.assertEqual(self.workbench.undo_status()["titles"], ["Bug B"])
        self.undo()
        self.assertEqual(self.workbench.state()["bugs"][0]["steps"], "步骤 1")

    def test_one_stale_target_rejects_the_whole_undo(self):
        self.apply((0, 1))
        identifier = self.workbench.undo_status()["transaction_id"]
        self.workbench.save({"bugs": [{"id": self.ids[1], "actual": "后续人工编辑"}]})
        before = self.workbench.state()
        self.assertFalse(self.workbench.undo_status()["available"])
        with self.assertRaisesRegex(ValueError, "已变化"):
            self.workbench.undo_last_import(identifier)
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(Workbench(self.base / "data").state(), before)

    def test_review_and_selection_are_allowed_but_undo_cancels_review(self):
        self.apply()
        bug = self.workbench.state()["bugs"][0]
        self.workbench.save({"bugs": [{"id": bug["id"], "selected": False, "reviewed": True,
                                        "review_token": bug["review_token"]}]})
        self.assertTrue(self.workbench.undo_status()["available"])
        bug = self.undo()["state"]["bugs"][0]
        self.assertFalse(bug["selected"])
        self.assertFalse(bug["reviewed"])
        self.assertEqual(bug["title"], "Bug A")
        self.assertEqual(bug["attachments"][0]["name"], "evidence.txt")

    def test_public_settings_and_title_block_undo(self):
        for patch_value in ({"settings": {"product": "3"}},
                            {"bugs": [{"id": self.ids[0], "title": "新标题"}]}):
            with self.subTest(patch=patch_value):
                self.apply()
                self.workbench.save(patch_value)
                self.assertFalse(self.workbench.undo_status()["available"])
                with self.assertRaises(ValueError):
                    self.undo()

    def test_all_submission_attempts_block_undo_and_preserve_journal(self):
        for status in ("submitted", "partial", "uncertain", "failed"):
            with self.subTest(status=status):
                temporary = tempfile.TemporaryDirectory()
                self.addCleanup(temporary.cleanup)
                self.workbench = Workbench(Path(temporary.name))
                self.workbench.scan(str(self.root))
                self.apply()
                values = {"status": status, "error": "模拟提交记录"}
                if status in {"submitted", "partial"}:
                    values.update(remote_id=123, remote_url="https://example.invalid/bug-123")
                self.workbench.set_submission(self.ids[0], **values)
                before = self.workbench.state()
                self.assertFalse(self.workbench.undo_status()["available"])
                with self.assertRaises(ValueError):
                    self.undo()
                self.assertEqual(self.workbench.state(), before)

    def test_initial_failed_status_is_preserved_if_no_later_attempt(self):
        self.workbench.set_submission(self.ids[0], status="failed", error="已有失败记录")
        before = self.workbench.state()
        self.apply()
        self.assertTrue(self.workbench.undo_status()["available"])
        result = self.undo()["state"]
        self.assertEqual(result["history"], before["history"])
        self.assertEqual(result["bugs"][0]["status"], "failed")
        self.assertEqual(result["bugs"][0]["error"], "已有失败记录")

    def test_later_failed_attempt_stays_blocked_after_manual_status_reset(self):
        self.apply()
        self.workbench.set_submission(self.ids[0], status="failed", error="模拟失败")
        self.workbench.save({"bugs": [{"id": self.ids[0], "actual": "手工补充"}]})
        self.workbench.save({"bugs": [{"id": self.ids[0], "actual": "实际 1"}]})
        self.assertEqual(self.workbench.state()["bugs"][0]["status"], "needs_review")
        self.assertFalse(self.workbench.undo_status()["available"])
        with self.assertRaises(ValueError):
            self.undo()

    def test_undo_persist_failure_rolls_back_memory_and_keeps_transaction(self):
        self.apply((0, 1))
        before = self.workbench.state()
        summary = self.workbench.undo_status()
        with patch.object(self.workbench, "_persist", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.undo()
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(self.workbench.undo_status(), summary)
        self.assertEqual(Workbench(self.base / "data").state(), before)
        self.undo()

    def test_import_persist_failure_does_not_install_new_transaction(self):
        self.apply()
        before = self.workbench.state()
        summary = self.workbench.undo_status()
        with patch.object(self.workbench, "_persist", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.apply((1,))
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(self.workbench.undo_status(), summary)
        self.assertEqual(Workbench(self.base / "data").undo_status(), summary)

    def test_failed_atomic_state_write_leaves_drafts_and_undo_durable(self):
        self.apply((0, 1))
        before = self.workbench.state()
        summary = self.workbench.undo_status()
        write_atomic = self.workbench._write_atomic

        def fail_final_write(path, text):
            if path == self.workbench._state_path:
                raise OSError("模拟替换主数据文件失败")
            return write_atomic(path, text)

        with patch.object(self.workbench, "_write_atomic", side_effect=fail_final_write):
            with self.assertRaises(OSError):
                self.undo()
        self.assertEqual(self.workbench.state(), before)
        restarted = Workbench(self.base / "data")
        self.assertEqual(restarted.state(), before)
        self.assertEqual(restarted.undo_status(), summary)

    def test_backup_import_ignores_external_undo_and_invalidates_local_undo(self):
        self.apply()
        external_record = copy.deepcopy(self.workbench._store[STORE_KEY])
        backup = {"format": "bugdesk-backup", "version": 1, "state": self.workbench.state(),
                  STORE_KEY: external_record}
        backup["state"][STORE_KEY] = external_record
        self.workbench.import_backup(backup)
        self.assertIsNone(self.workbench.undo_status())
        self.assertIsNone(Workbench(self.base / "data").undo_status())

    def test_journal_has_only_facts_provenance_and_hashes_and_is_not_exported(self):
        self.apply()
        record = self.workbench._store[STORE_KEY]
        encoded = json.dumps(record, ensure_ascii=False)
        for excluded in (str(self.root), "attachments", "remote_url", "history", "zentao_url"):
            self.assertNotIn(excluded, encoded)
        self.assertNotIn(STORE_KEY, self.workbench.state())
        path = Path(self.workbench.export("json"))
        self.assertNotIn(STORE_KEY, path.read_text(encoding="utf-8"))

    def test_bad_journal_is_discarded_without_losing_the_main_state(self):
        self.apply()
        before = self.workbench.state()
        record = copy.deepcopy(self.workbench._store[STORE_KEY])
        invalid = [None, [], {"schema": 1}, {**record, "credentials": "not permitted"},
                   {**record, "schema": True}, {**record, "items": record["items"] * 301}]
        duplicate = copy.deepcopy(record)
        duplicate["items"] *= 2
        invalid.append(duplicate)
        invalid_item = copy.deepcopy(record)
        invalid_item["items"][0]["before"]["steps"] = "x" * 100001
        invalid.append(invalid_item)
        nul_fact = copy.deepcopy(record)
        nul_fact["items"][0]["before"]["actual"] = "invalid\x00fact"
        invalid.append(nul_fact)
        for value in invalid:
            with self.subTest(value_type=type(value).__name__):
                self.assertIsNone(validate_record(value))
                store = copy.deepcopy(self.workbench._store)
                store[STORE_KEY] = value
                self.workbench._write_atomic(self.workbench._state_path, json.dumps(store, ensure_ascii=False))
                loaded = Workbench(self.base / "data")
                self.assertIsNone(loaded.undo_status())
                state = loaded.state()
                self.assertEqual(state["bugs"], before["bugs"])
                self.assertFalse(any("损坏" in text for text in state["warnings"]))

    def test_changed_batch_and_changed_evidence_prevent_undo(self):
        self.apply()
        other = self.base / "other"
        (other / "Bug D").mkdir(parents=True)
        self.workbench.scan(str(other))
        self.assertFalse(self.workbench.undo_status()["available"])
        self.workbench.scan(str(self.root))
        self.assertTrue(self.workbench.undo_status()["available"])
        evidence = self.root / "Bug A" / "evidence.txt"
        evidence.write_text("changed synthetic evidence", encoding="utf-8")
        self.workbench.scan(str(self.root))
        self.assertFalse(self.workbench.undo_status()["available"])

    def test_live_file_change_without_rescan_blocks_entire_undo(self):
        self.apply((0, 1))
        before = self.workbench.state()
        path = self.root / "Bug B" / "evidence.txt"
        info = path.stat()
        path.write_text("changed evidence without rescanning", encoding="utf-8")
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 10_000_000))
        self.assertFalse(self.workbench.undo_status()["available"])
        with self.assertRaisesRegex(ValueError, "已变化"):
            self.undo()
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(Workbench(self.base / "data").state(), before)

    def test_live_file_deletion_without_rescan_blocks_undo(self):
        self.apply()
        before = self.workbench.state()
        (self.root / "Bug A" / "evidence.txt").unlink()
        summary = self.workbench.undo_status()
        self.assertFalse(summary["available"])
        self.assertIn("缺失", summary["reason"])
        with self.assertRaises(ValueError):
            self.undo()
        self.assertEqual(self.workbench.state(), before)

    def test_removed_attachment_switch_cannot_modify_drafts_or_break_undo(self):
        self.apply()
        bug = self.workbench.state()["bugs"][0]
        before = self.workbench.state()
        with self.assertRaisesRegex(ValueError, "不再支持单独排除"):
            self.workbench.save({"bugs": [{"id": bug["id"], "excluded_attachments": [bug["attachments"][0]["id"]]}]})
        self.assertEqual(self.workbench.state(), before)
        self.assertTrue(self.workbench.undo_status()["available"])
        self.undo()

    def test_new_file_without_rescan_changes_directory_guard(self):
        self.apply()
        folder = self.root / "Bug A"
        info = folder.stat()
        (folder / "new-evidence.txt").write_text("new synthetic evidence", encoding="utf-8")
        os.utime(folder, ns=(info.st_atime_ns, info.st_mtime_ns + 10_000_000))
        self.assertFalse(self.workbench.undo_status()["available"])
        with self.assertRaises(ValueError):
            self.undo()

    def test_empty_bug_folder_can_import_and_undo(self):
        (self.root / "Bug A" / "evidence.txt").unlink()
        self.workbench.scan(str(self.root))
        self.assertEqual(self.workbench.state()["bugs"][0]["attachments"], [])
        self.apply()
        self.assertTrue(self.workbench.undo_status()["available"])
        self.workbench = Workbench(self.base / "data")
        self.assertTrue(self.workbench.undo_status()["available"])
        self.undo()
        self.assertEqual(self.workbench.state()["bugs"][0]["steps"], "")

    def test_replaced_attachment_symlink_is_rejected_without_following_it(self):
        self.apply()
        evidence = self.root / "Bug A" / "evidence.txt"
        original_lstat = Path.lstat

        def replaced_link(path):
            if path == evidence:
                return SimpleNamespace(st_mode=stat.S_IFLNK)
            return original_lstat(path)

        # Windows symlink creation needs optional system privileges.  Model the
        # lstat result to exercise rejection without requiring those privileges.
        with patch("draft_undo.Path.lstat", new=replaced_link):
            self.assertFalse(self.workbench.undo_status()["available"])
            with self.assertRaises(ValueError):
                self.undo()

    def make_bridge(self):
        app = SimpleNamespace(data_dir=self.workbench.data_dir, workbench=self.workbench,
                              job_lock=threading.RLock(), instance="test-instance",
                              server=SimpleNamespace(server_port=54321), ensure_idle=lambda: None,
                              state=self.workbench.state)
        bridge = WorkBuddyBridge(app)
        self.addCleanup(bridge.close)
        return bridge

    def test_bridge_undo_retires_plans_but_connection_can_stage_fresh_context(self):
        bridge = self.make_bridge()
        bridge.enable()
        token = json.loads(bridge.connection_file.read_text(encoding="utf-8"))["token"]
        context = bridge.context(token)
        row = self.row()
        row.pop("row_id")
        row["suggested_bug_id"] = self.ids[0]
        bridge.stage({"context_id": context["context_id"], "rows": [row]}, token)
        pending = bridge.status()["pending"]
        data = {"plan_id": pending["plan_id"], "review_scope": "bugs", "assignments": [
            {"row_id": pending["rows"][0]["row_id"], "bug_id": self.ids[0]}]}
        result = bridge.apply(data)
        self.assertTrue(result["undo"]["available"])
        self.assertIsNotNone(result["pending"])
        self.assertNotIn(STORE_KEY, json.dumps(bridge.context(token)))
        bridge.undo({"transaction_id": result["undo"]["transaction_id"]})
        self.assertIsNone(bridge.status()["pending"])
        self.assertTrue(bridge.status()["enabled"])
        with self.assertRaises(ValueError):
            bridge.apply(data)
        with self.assertRaises(ValueError):
            bridge.stage({"context_id": context["context_id"], "rows": [row]}, token)
        context = bridge.context(token)
        bridge.stage({"context_id": context["context_id"], "rows": [row]}, token)
        self.assertIsNotNone(bridge.status()["pending"])

    def test_bridge_undo_works_without_an_enabled_connection(self):
        self.apply()
        bridge = self.make_bridge()
        self.assertFalse(bridge.status()["enabled"])
        result = bridge.undo({"transaction_id": bridge.status()["undo"]["transaction_id"]})
        self.assertEqual(result["undone"], 1)
        self.assertIsNone(result["undo"])
        self.assertIsNone(result["pending"])


if __name__ == "__main__":
    unittest.main()
