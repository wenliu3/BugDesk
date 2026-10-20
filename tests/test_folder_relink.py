"""Explicit local evidence-folder reassociation, using only synthetic files."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from domain import Workbench, SCAN_PLAN_SECONDS, MAX_SCAN_PLANS
import test_app


class FolderRelinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bugdesk-relink-")
        self.root = Path(self.temp.name)
        self.evidence = self.root / "10.19"
        self.folder = self.evidence / "原文件夹标题"
        self.folder.mkdir(parents=True)
        (self.folder / "截图.png").write_bytes(b"synthetic screenshot")
        (self.folder / "日志.txt").write_bytes(b"synthetic log")
        self.workbench = Workbench(self.root / "data")
        self.batch_key = self.workbench.scan(str(self.evidence))["batch_key"]
        self.bug_id = self.workbench.state()["bugs"][0]["id"]
        bug = self.workbench.get_bug(self.bug_id)
        self.workbench.save({"settings": {"product": "11", "openedBuild": ["12"],
                                           "title_prefix": "【原产品】", "preconditions": "公共条件"},
                             "bugs": [{"id": self.bug_id, "title": "人工编辑标题", "preconditions": "条目条件",
                                       "steps": "独立操作", "actual": "实际现象", "expected": "预期行为",
                                       "overrides": {"assignedTo": "synthetic_owner"},
                                       "excluded_attachments": [bug["attachments"][0]["id"]]}]})
        self.workbench.apply_cases([{"row_id": "source", "case_id": "CASE-1", "title": "合成用例"}],
            [{"row_id": "source", "bug_id": self.bug_id,
              "review_token": self.workbench.get_bug(self.bug_id)["review_token"]}], batch_key=self.batch_key)
        self.workbench.save({"bugs": [{"id": self.bug_id, "reviewed": True}]})

    def tearDown(self):
        self.temp.cleanup()

    def rename(self, name="改名后的证据目录"):
        moved = self.folder.with_name(name)
        self.folder.rename(moved)
        return moved

    @staticmethod
    def mapping(plan, folder_name=None, source_index=0):
        source = plan["sources"][source_index]
        return {"folder_name": folder_name or plan["targets"][0]["folder_name"],
                **{key: source[key] for key in ("source_batch_key", "bug_id", "review_token")}}

    def apply(self, root, plan, mappings=None):
        return self.workbench.scan(str(root), relink_plan_id=plan["plan_id"],
                                   relinks=mappings if mappings is not None else [self.mapping(plan)])

    def test_preview_is_read_only_and_only_missing_records_are_candidates(self):
        state = self.workbench.state()
        disk = self.workbench._state_path.read_bytes()
        plan = self.workbench.preview_scan(str(self.evidence))
        self.assertEqual(plan["sources"], [])
        self.assertEqual(plan["targets"], [])
        self.assertEqual(state, self.workbench.state())
        self.assertEqual(disk, self.workbench._state_path.read_bytes())
        moved = self.rename()
        plan = self.workbench.preview_scan(str(self.evidence))
        self.assertEqual([item["folder_name"] for item in plan["targets"]], [moved.name])
        self.assertEqual(plan["sources"][0]["bug_id"], self.bug_id)
        self.assertEqual(disk, self.workbench._state_path.read_bytes())

    def test_ordinary_rescan_skips_history_and_tree_snapshot_without_new_targets(self):
        with patch.object(self.workbench, "_missing_folder", side_effect=AssertionError("history read")), \
                patch.object(self.workbench, "_scan_tree_token", side_effect=AssertionError("tree read")):
            preview = self.workbench.preview_scan(str(self.evidence))
        self.assertEqual(preview["plan_id"], "")
        self.assertEqual(preview["sources"], [])
        self.assertEqual(preview["target_count"], 0)

    def test_large_history_is_bounded_and_reports_truncation_without_blocking_new_scan(self):
        self.rename()
        batch = self.workbench._batch()
        template = batch["bugs"][0]
        for index in range(305):
            bug = copy.deepcopy(template)
            bug.update(id=f"synthetic-{index}", folder=str(self.root / "missing" / str(index)))
            batch["bugs"].append(bug)
        preview = self.workbench.preview_scan(str(self.evidence))
        self.assertEqual(len(preview["sources"]), 300)
        self.assertEqual(preview["source_count"], 306)
        self.assertTrue(preview["truncated"])
        self.assertIn("300", preview["notice"])
        state = self.workbench.scan(str(self.evidence))
        self.assertEqual(len(state["bugs"]), 1)

    def test_mappings_from_multiple_source_batches_are_rejected_as_one_transaction(self):
        second_root = self.root / "另一天"
        second_folder = second_root / "第二个Bug"
        second_folder.mkdir(parents=True)
        self.workbench.scan(str(second_root))
        destination = self.root / "合并日期"
        destination.mkdir()
        self.folder.rename(destination / "第一个目标")
        second_folder.rename(destination / "第二个目标")
        preview = self.workbench.preview_scan(str(destination))
        before = copy.deepcopy(self.workbench._store)
        mappings = [self.mapping(preview, "第一个目标", 0), self.mapping(preview, "第二个目标", 1)]
        with self.assertRaisesRegex(ValueError, "同一个旧批次"):
            self.apply(destination, preview, mappings)
        self.assertEqual(before, self.workbench._store)

    def test_renamed_record_retains_report_sources_review_exclusions_and_identity(self):
        before = self.workbench.get_bug(self.bug_id)
        moved = self.rename()
        evidence = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in moved.iterdir()}
        plan = self.workbench.preview_scan(str(self.evidence))
        result = self.apply(self.evidence, plan)
        after = result["bugs"][0]
        for field in ("id", "title", "preconditions", "steps", "actual", "expected", "case_source",
                      "case_sources", "excluded_attachments", "overrides", "reviewed", "review_token"):
            self.assertEqual(after[field], before[field], field)
        self.assertEqual(after["original_title"], moved.name)
        self.assertEqual(after["folder"], str(moved))
        self.assertTrue(all(str(moved) in item["path"] for item in after["attachments"]))
        self.assertEqual(evidence, {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in moved.iterdir()})
        rescanned = self.workbench.scan(str(self.evidence))["bugs"][0]
        self.assertEqual(rescanned["id"], self.bug_id)
        restarted = Workbench(self.root / "data")
        self.assertEqual(restarted.get_bug(self.bug_id)["folder"], str(moved))

    def test_submitted_records_move_with_remote_identity_and_journal_but_never_retry(self):
        self.workbench.set_submission(self.bug_id, status="submitted", remote_id=123,
            remote_url="https://synthetic.test/bug/123", upload_status={"synthetic": "uploaded"})
        history = self.workbench.state()["history"]
        self.rename()
        state = self.apply(self.evidence, self.workbench.preview_scan(str(self.evidence)))
        bug = state["bugs"][0]
        self.assertEqual((bug["id"], bug["remote_id"], bug["status"]), (self.bug_id, 123, "submitted"))
        self.assertEqual(bug["upload_status"], {"synthetic": "uploaded"})
        self.assertEqual(history, state["history"])
        with self.assertRaisesRegex(ValueError, "不能重复"):
            self.workbench.validate_submission([self.bug_id])

    def test_whole_date_directory_moves_across_batches_and_original_path_can_reappear_safely(self):
        before = self.workbench.state()
        destination = self.root / "归档" / "10.19"
        destination.parent.mkdir()
        self.evidence.rename(destination)
        plan = self.workbench.preview_scan(str(destination))
        state = self.apply(destination, plan)
        self.assertNotEqual(state["batch_key"], self.batch_key)
        self.assertEqual(state["settings"], before["settings"])
        self.assertEqual(state["bugs"][0]["review_token"], before["bugs"][0]["review_token"])
        old_batch = self.workbench._store["batches"][self.batch_key]
        self.assertEqual(old_batch["bugs"], [])
        self.assertEqual(old_batch["active_ids"], [])
        self.folder.mkdir(parents=True)
        new_bug = self.workbench.scan(str(self.evidence))["bugs"][0]
        self.assertNotEqual(new_bug["id"], self.bug_id)
        self.assertEqual(new_bug["steps"], "")
        original = self.workbench.scan(str(destination))["bugs"][0]
        self.assertEqual(original["id"], self.bug_id)

    def test_migration_into_existing_batch_keeps_each_reports_effective_settings(self):
        source_before = self.workbench.get_bug(self.bug_id)
        source_effective = self.workbench._effective(source_before)[1]
        destination = self.root / "另一日期"
        (destination / "已存在Bug").mkdir(parents=True)
        self.workbench.scan(str(destination))
        self.workbench.save({"settings": {"product": "99", "openedBuild": ["100"],
                                           "title_prefix": "【目标产品】", "preconditions": "目标条件"}})
        destination_settings = self.workbench.get_settings()
        self.folder.rename(destination / "迁入目录")
        plan = self.workbench.preview_scan(str(destination))
        state = self.apply(destination, plan)
        self.assertEqual(state["settings"], destination_settings)
        migrated = self.workbench.get_bug(self.bug_id)
        self.assertEqual(self.workbench._effective(migrated)[1], source_effective)
        self.assertEqual(migrated["review_token"], source_before["review_token"])
        self.assertTrue(migrated["reviewed"])

    def test_changed_evidence_requires_review_and_preserves_only_available_exclusions(self):
        moved = self.rename()
        (moved / "截图.png").write_bytes(b"updated screenshot")
        (moved / "新证据.txt").write_bytes(b"new")
        plan = self.workbench.preview_scan(str(self.evidence))
        state = self.apply(self.evidence, plan)
        self.assertFalse(state["bugs"][0]["reviewed"])
        self.assertEqual(len(state["bugs"][0]["excluded_attachments"]), 1)

    def test_no_selection_creates_new_draft_without_inheriting_similar_title_or_remote_id(self):
        self.workbench.set_submission(self.bug_id, status="submitted", remote_id=123)
        self.rename()
        plan = self.workbench.preview_scan(str(self.evidence))
        result = self.apply(self.evidence, plan, [])
        self.assertNotEqual(result["bugs"][0]["id"], self.bug_id)
        self.assertIsNone(result["bugs"][0]["remote_id"])
        self.assertEqual(result["bugs"][0]["steps"], "")
        self.assertTrue(any(item["id"] == self.bug_id for item in self.workbench._batch()["bugs"]))

    def test_duplicate_invalid_and_traversal_mappings_reject_atomically(self):
        self.rename()
        plan = self.workbench.preview_scan(str(self.evidence))
        good = self.mapping(plan)
        before = copy.deepcopy(self.workbench._store)
        for invalid in ([good, good], [{**good, "folder_name": "../outside"}],
                        [{**good, "review_token": "old"}], [{**good, "source_batch_key": "unknown"}]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.apply(self.evidence, plan, invalid)
            self.assertEqual(before, self.workbench._store)

    def test_unrelated_draft_or_target_tree_edits_invalidate_plan(self):
        moved = self.rename()
        plan = self.workbench.preview_scan(str(self.evidence))
        self.workbench.save({"bugs": [{"id": self.bug_id, "actual": "人工修改"}]})
        with self.assertRaisesRegex(ValueError, "已经变化"):
            self.apply(self.evidence, plan)
        plan = self.workbench.preview_scan(str(self.evidence))
        (moved / "新建空目录").mkdir()
        with self.assertRaisesRegex(ValueError, "已经变化"):
            self.apply(self.evidence, plan)

    def test_source_reappearing_and_concurrent_evidence_edit_cannot_reassociate(self):
        destination = self.root / "目的日期"
        destination.mkdir()
        self.folder.rename(destination / "搬家目录")
        plan = self.workbench.preview_scan(str(destination))
        self.folder.mkdir()
        with self.assertRaisesRegex(ValueError, "仍然存在"):
            self.apply(destination, plan)
        self.folder.rmdir()
        plan = self.workbench.preview_scan(str(destination))
        before = copy.deepcopy(self.workbench._store)
        original = self.workbench._attachments
        def changed(folder, warnings):
            result = original(folder, warnings)
            (folder / "稍后新增.txt").write_bytes(b"race")
            return result
        with patch.object(self.workbench, "_attachments", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "关联期间"):
                self.apply(destination, plan)
        self.assertEqual(before, self.workbench._store)

    def test_submitting_lock_and_expired_bounded_plans(self):
        self.workbench.set_submission(self.bug_id, status="submitting")
        self.rename()
        with self.assertRaisesRegex(ValueError, "正在提交"):
            self.workbench.preview_scan(str(self.evidence))
        with self.assertRaisesRegex(ValueError, "正在提交"):
            self.workbench.scan(str(self.evidence))
        self.workbench.set_submission(self.bug_id, status="failed")
        for _ in range(MAX_SCAN_PLANS + 3):
            plan = self.workbench.preview_scan(str(self.evidence))
        self.assertEqual(len(self.workbench._scan_plans), MAX_SCAN_PLANS)
        self.workbench._scan_plans[plan["plan_id"]]["created"] -= SCAN_PLAN_SECONDS + 1
        with self.assertRaisesRegex(ValueError, "已过期"):
            self.apply(self.evidence, plan)

    def test_persist_failure_rolls_back_relink_and_ordinary_scan(self):
        self.rename()
        plan = self.workbench.preview_scan(str(self.evidence))
        before = copy.deepcopy(self.workbench._store)
        disk = self.workbench._state_path.read_bytes()
        with patch.object(self.workbench, "_persist", side_effect=OSError("synthetic disk full")):
            with self.assertRaises(OSError):
                self.apply(self.evidence, plan)
            self.assertEqual(before, self.workbench._store)
            with self.assertRaises(OSError):
                self.workbench.scan(str(self.evidence))
        self.assertEqual(before, self.workbench._store)
        self.assertEqual(disk, self.workbench._state_path.read_bytes())
        self.assertEqual(self.apply(self.evidence, plan)["bugs"][0]["id"], self.bug_id)

    def test_state_file_replace_failure_after_backup_write_keeps_original_active_batch(self):
        self.rename()
        plan = self.workbench.preview_scan(str(self.evidence))
        before = copy.deepcopy(self.workbench._store)
        disk = self.workbench._state_path.read_bytes()
        original = self.workbench._write_atomic
        def full_state_disk(path, text):
            if path == self.workbench._state_path:
                raise OSError("synthetic state replacement failure")
            return original(path, text)
        with patch.object(self.workbench, "_write_atomic", side_effect=full_state_disk):
            with self.assertRaises(OSError):
                self.apply(self.evidence, plan)
        self.assertEqual(before, self.workbench._store)
        self.assertEqual(disk, self.workbench._state_path.read_bytes())
        self.assertEqual(disk, self.workbench._backup_path.read_bytes())

    def test_renamed_backup_preserves_identity_and_old_location_backup_cannot_duplicate_it(self):
        old_backup = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        self.rename()
        self.apply(self.evidence, self.workbench.preview_scan(str(self.evidence)))
        exported = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        fresh = Workbench(self.root / "portable-data")
        imported = fresh.import_backup(exported)["bugs"][0]
        self.assertEqual(imported["id"], self.bug_id)
        self.assertEqual(imported["original_title"], "改名后的证据目录")
        self.workbench.import_backup(exported)
        self.assertEqual(self.workbench.state()["bugs"][0]["id"], self.bug_id)
        with self.assertRaisesRegex(ValueError, "其他目录关联"):
            self.workbench.import_backup(old_backup)


class FolderRelinkHTTPTests(unittest.TestCase):
    setUp = test_app.HTTPTests.setUp
    tearDown = test_app.HTTPTests.tearDown
    request = test_app.HTTPTests.request
    json = test_app.HTTPTests.json
    prepare_bug = test_app.HTTPTests.prepare_bug

    def test_preview_and_confirm_are_ui_token_protected_and_keep_submitted_identity(self):
        bug = self.prepare_bug()
        self.app.workbench.set_submission(bug["id"], status="submitted", remote_id=42)
        folder = Path(bug["folder"])
        moved = folder.with_name("改名的合成标题")
        folder.rename(moved)
        with self.assertRaises(HTTPError) as rejected:
            self.json("/api/scan/preview", {"path": str(moved.parent)}, {"X-BugDesk-Token": "wrong"})
        self.assertEqual(rejected.exception.code, 403)
        preview = self.json("/api/scan/preview", {"path": str(moved.parent)})
        result = self.json("/api/scan", {"path": str(moved.parent), "relink_plan_id": preview["plan_id"],
                                        "relinks": [FolderRelinkTests.mapping(preview)]})
        self.assertEqual(result["bugs"][0]["id"], bug["id"])
        self.assertEqual(result["bugs"][0]["remote_id"], 42)
        self.assertEqual(result["bugs"][0]["folder"], str(moved))

    def test_http_preview_obeys_running_job_and_serves_local_relink_assets(self):
        bug = self.prepare_bug()
        self.app.job["running"] = True
        try:
            with self.assertRaises(HTTPError) as rejected:
                self.json("/api/scan/preview", {"path": str(Path(bug["folder"]).parent)})
            self.assertEqual(rejected.exception.code, 400)
        finally:
            self.app.job["running"] = False
        for asset in ("relink.js", "relink.css"):
            with self.request("/" + asset) as response:
                self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
