import copy
import csv
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from domain import Workbench


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bugdesk-domain-")
        self.root = Path(self.temporary.name)
        self.data = self.root / "工作区数据"
        self.evidence = self.root / "公司Bug" / "10.13"
        self.evidence.mkdir(parents=True)
        self.workbench = Workbench(self.data)

    def tearDown(self):
        self.temporary.cleanup()

    def bug_folder(self, title="1. 中文视频暂停错误", attachment=True, root=None):
        folder = (root or self.evidence) / title
        folder.mkdir(parents=True, exist_ok=True)
        if attachment:
            (folder / "复现截图.png").write_bytes(b"example evidence")
        return folder

    def ready(self, bug_id=None):
        if bug_id is None:
            bug_id = self.workbench.state()["bugs"][0]["id"]
        self.workbench.save({"settings": {"product": "1", "openedBuild": ["2"], "product_name": "智慧中屏"},
                             "bugs": [{"id": bug_id, "steps": "播放视频后点击暂停。", "actual": "进度条继续前进。", "expected": "进度条停止。"}]})
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True}]})
        return bug_id

    def test_scan_reads_recursive_chinese_evidence_without_inventing_facts_or_writing_inputs(self):
        first = self.bug_folder("10. 保存失败")
        second = self.bug_folder("2. 中文暂停错误")
        (second / "日志目录").mkdir()
        (second / "日志目录" / "日志.txt").write_text("这是中文日志", encoding="utf-8")
        (second / "~$临时文件.docx").write_bytes(b"ignore")
        (second / ".隐藏文件").write_bytes(b"ignore")
        (second / "缓存.tmp").write_bytes(b"ignore")
        before = {str(item): (item.stat().st_mtime_ns, item.read_bytes()) for item in self.evidence.rglob("*") if item.is_file()}
        state = self.workbench.scan(str(self.evidence))
        self.assertEqual([item["original_title"] for item in state["bugs"]], [second.name, first.name])
        bug = state["bugs"][0]
        self.assertEqual(bug["title"], second.name)
        self.assertEqual((bug["steps"], bug["actual"], bug["expected"]), ("", "", ""))
        self.assertEqual(bug["status"], "draft")
        self.assertEqual([item["name"] for item in bug["attachments"]], ["复现截图.png", "日志目录/日志.txt"])
        after = {str(item): (item.stat().st_mtime_ns, item.read_bytes()) for item in self.evidence.rglob("*") if item.is_file()}
        self.assertEqual(before, after)

    def test_batches_keep_separate_drafts_and_settings_across_restart(self):
        self.bug_folder()
        first = self.workbench.scan(str(self.evidence))
        first_id = self.ready()
        other = self.root / "公司Bug" / "10.14"
        self.bug_folder(root=other)
        second = self.workbench.scan(str(other))
        self.assertNotEqual(first["batch_key"], second["batch_key"])
        self.assertNotEqual(first_id, second["bugs"][0]["id"])
        self.assertEqual(second["bugs"][0]["steps"], "")
        self.workbench.save({"settings": {"product": "99"}})
        restarted = Workbench(self.data)
        restored = restarted.scan(str(self.evidence))
        self.assertEqual(restored["settings"]["product"], "1")
        self.assertEqual(restored["bugs"][0]["steps"], "播放视频后点击暂停。")
        self.assertTrue(restored["bugs"][0]["reviewed"])

    def test_submitted_title_preserves_actual_prefix_and_edited_title_without_renaming_evidence(self):
        folder = self.bug_folder()
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        self.workbench.save({"settings": {"title_prefix": "【测试版本】"},
                             "bugs": [{"id": bug_id, "title": "【投屏】关闭后未退出"}]})
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True}]})
        self.workbench.set_submission(bug_id, status="submitting")
        self.workbench.set_submission(bug_id, status="submitted", remote_id=123)
        expected = "【测试版本】【投屏】关闭后未退出"
        self.workbench.save({"settings": {"title_prefix": "【后续版本】"}})
        restarted = Workbench(self.data)
        self.assertEqual(restarted.get_bug(bug_id)["submitted_title"], expected)
        self.assertEqual(restarted.scan(str(self.evidence))["bugs"][0]["submitted_title"], expected)
        backup = json.loads(Path(restarted.export("json")).read_text(encoding="utf-8"))
        restored = Workbench(self.root / "迁移工作区").import_backup(backup)
        self.assertEqual(restored["bugs"][0]["submitted_title"], expected)
        self.assertTrue(folder.is_dir())
        self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})
        self.assertFalse((self.evidence / "【投屏】关闭后未退出").exists())

    def test_old_backup_cannot_replace_known_submission_title(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        old = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        self.workbench.set_submission(bug_id, status="submitting")
        expected = self.workbench.get_bug(bug_id)["submitted_title"]
        self.workbench.set_submission(bug_id, status="submitted", remote_id=456)
        old["state"]["bugs"][0]["submitted_title"] = "旧备份中的不同标题"
        imported = self.workbench.import_backup(old)
        self.assertEqual(imported["bugs"][0]["submitted_title"], expected)
        self.assertEqual(imported["bugs"][0]["remote_id"], 456)

    def test_title_snapshot_survives_ambiguous_submission_and_manual_confirmation(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        self.workbench.save({"settings": {"title_prefix": "【原版本】"}})
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True}]})
        self.workbench.set_submission(bug_id, status="submitting")
        expected = self.workbench.get_bug(bug_id)["submitted_title"]
        self.workbench.set_submission(bug_id, status="uncertain")
        self.workbench.save({"settings": {"title_prefix": "【新版本】"}})
        confirmed = self.workbench.reconcile_submission(bug_id, "created", remote_id=789)
        self.assertEqual(confirmed["bugs"][0]["submitted_title"], expected)

    def test_import_rejects_invalid_submission_title_without_partial_changes(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        self.ready()
        backup = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        before = self.workbench.state()
        for value in (None, [], "x" * 120001, "bad\x00title"):
            with self.subTest(value_type=type(value).__name__):
                backup["state"]["bugs"][0]["submitted_title"] = value
                with self.assertRaisesRegex(ValueError, "提交标题"):
                    self.workbench.import_backup(backup)
                self.assertEqual(self.workbench.state(), before)

    def test_invalid_title_cannot_persist_a_broken_submission_snapshot(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        self.workbench.save({"bugs": [{"id": bug_id, "title": "无效\x00标题"}]})
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True}]})
        before = self.workbench.state()
        with self.assertRaisesRegex(ValueError, "空字符"):
            self.workbench.set_submission(bug_id, status="submitting")
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(Workbench(self.data).state(), before)

    def test_rescan_preserves_edits_submission_and_restores_temporarily_missing_folder(self):
        folder = self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        self.workbench.set_submission(bug_id, status="submitting")
        self.workbench.set_submission(bug_id, status="submitted", remote_id=42, remote_url="http://zentao/bug/42")
        moved = self.root / "暂时移走"
        folder.rename(moved)
        state = self.workbench.scan(str(self.evidence))
        self.assertEqual(state["bugs"], [])
        self.assertTrue(any("草稿仍保留" in warning for warning in state["warnings"]))
        moved.rename(folder)
        restored = self.workbench.scan(str(self.evidence))["bugs"][0]
        self.assertEqual(restored["id"], bug_id)
        self.assertEqual(restored["remote_id"], 42)
        self.assertEqual(restored["status"], "submitted")
        self.assertEqual(restored["expected"], "进度条停止。")
        with self.assertRaisesRegex(ValueError, "不能重复"):
            self.workbench.validate_submission([bug_id])

    def test_removed_and_modified_attachments_require_rescan_and_new_review(self):
        folder = self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        (folder / "复现截图.png").unlink()
        with self.assertRaisesRegex(ValueError, "附件已不存在"):
            self.workbench.validate_submission([bug_id])
        state = self.workbench.scan(str(self.evidence))
        self.assertFalse(state["bugs"][0]["reviewed"])
        self.assertTrue(any("原附件已不存在" in warning for warning in state["warnings"]))
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True}]})
        (folder / "新附件.txt").write_text("new", encoding="utf-8")
        state = self.workbench.scan(str(self.evidence))
        self.assertFalse(state["bugs"][0]["reviewed"])
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True}]})
        (folder / "新附件.txt").write_text("changed evidence", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "附件已经变化"):
            self.workbench.validate_submission([bug_id])

    def test_content_and_shared_settings_clear_review_even_when_editor_sends_stale_true(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        state = self.workbench.save({"bugs": [{"id": bug_id, "actual": "修改后的实际结果", "reviewed": True}]})
        self.assertFalse(state["bugs"][0]["reviewed"])
        self.assertEqual(state["bugs"][0]["status"], "needs_review")
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True}]})
        state = self.workbench.save({"settings": {"assignedTo": "developer"}, "bugs": [{"id": bug_id, "reviewed": True}]})
        self.assertFalse(state["bugs"][0]["reviewed"])
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True}]})
        state = self.workbench.save({"bugs": [{"id": bug_id, "selected": False}]})
        self.assertTrue(state["bugs"][0]["reviewed"])

    def test_same_second_other_window_edit_rejects_review_of_unseen_content_atomically(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        with patch("domain._now", return_value="2026-10-13T10:00:00+00:00"):
            self.workbench.save({"bugs": [{"id": bug_id, "actual": "第一次窗口修改"}]})
            first_window = self.workbench.get_bug(bug_id)
            self.workbench.save({"bugs": [{"id": bug_id, "actual": "第二个窗口的新结果"}]})
            second_window = self.workbench.get_bug(bug_id)
            self.assertEqual(first_window["updated_at"], second_window["updated_at"])
            self.assertNotEqual(first_window["review_token"], second_window["review_token"])
            before = self.workbench.state()
            with self.assertRaisesRegex(ValueError, "重新打开复核"):
                self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True, "review_token": first_window["review_token"]}]})
            self.assertEqual(self.workbench.state(), before)
            self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True, "review_token": second_window["review_token"]}]})
            self.assertTrue(self.workbench.get_bug(bug_id)["reviewed"])

    def test_changed_shared_settings_reject_old_review_token_even_in_same_second(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        with patch("domain._now", return_value="2026-10-13T10:00:00+00:00"):
            self.workbench.save({"settings": {"assignedTo": "甲开发"}})
            old = self.workbench.state()["bugs"][0]
            self.workbench.save({"settings": {"assignedTo": "乙开发"}})
            current = self.workbench.state()["bugs"][0]
            self.assertEqual(old["updated_at"], current["updated_at"])
            self.assertNotEqual(old["review_token"], current["review_token"])
            with self.assertRaisesRegex(ValueError, "公共信息或附件已变化"):
                self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True, "review_token": old["review_token"]}]})
            self.assertFalse(self.workbench.get_bug(bug_id)["reviewed"])

    def test_review_token_tracks_all_evidence_but_not_selected_or_review_flags(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        before = self.workbench.get_bug(bug_id)
        self.workbench.save({"bugs": [{"id": bug_id, "selected": False, "reviewed": False}]})
        unselected = self.workbench.get_bug(bug_id)
        self.assertEqual(before["review_token"], unselected["review_token"])
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True, "review_token": before["review_token"]}]})
        (Path(before["folder"]) / "extra.log").write_text("new synthetic evidence", encoding="utf-8")
        self.workbench.scan(str(self.evidence))
        current = self.workbench.get_bug(bug_id)
        self.assertNotEqual(before["review_token"], current["review_token"])
        with self.assertRaisesRegex(ValueError, "重新打开复核"):
            self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True, "review_token": before["review_token"]}]})
        stored = json.loads((self.data / "state.json").read_text(encoding="utf-8"))
        stored_bug = next(iter(stored["batches"].values()))["bugs"][0]
        self.assertNotIn("review_token", stored_bug)

    def test_submission_validates_fields_and_merges_individual_overrides(self):
        self.bug_folder()
        state = self.workbench.scan(str(self.evidence))
        bug_id = state["bugs"][0]["id"]
        with self.assertRaisesRegex(ValueError, "复现步骤"):
            self.workbench.validate_submission([bug_id])
        self.ready(bug_id)
        self.workbench.save({"settings": {"preconditions": "已登录", "title_prefix": "【1.0版本】"},
                             "bugs": [{"id": bug_id, "preconditions": "打开播放页", "overrides": {"pri": "2", "assignedTo": "张三"}}]})
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True}]})
        bug, settings = self.workbench.validate_submission([bug_id])[0]
        self.assertTrue(bug["title"].startswith("【1.0版本】"))
        self.assertEqual(bug["preconditions"], "已登录\n\n打开播放页")
        self.assertEqual(settings["pri"], "2")
        self.assertEqual(settings["assignedTo"], "张三")
        self.assertFalse(self.workbench.get_bug(bug_id)["title"].startswith("【1.0版本】"))

    def test_interrupted_submission_is_uncertain_on_restart_and_cannot_retry(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        self.workbench.set_submission(bug_id, status="submitting")
        with self.assertRaisesRegex(ValueError, "正在提交"):
            self.workbench.save({"bugs": [{"id": bug_id, "steps": "试图修改提交中描述"}]})
        with self.assertRaisesRegex(ValueError, "正在提交"):
            self.workbench.scan(str(self.evidence))
        restarted = Workbench(self.data)
        self.assertEqual(restarted.get_bug(bug_id)["status"], "uncertain")
        with self.assertRaisesRegex(ValueError, "不能重复"):
            restarted.validate_submission([bug_id])
        with self.assertRaisesRegex(ValueError, "不能被标记"):
            restarted.set_submission(bug_id, status="failed")

    def test_remote_id_and_partial_state_cannot_create_duplicate_bug(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        self.workbench.set_submission(bug_id, status="submitting")
        self.workbench.set_submission(bug_id, status="partial", remote_id="88", error="已创建但附件上传失败")
        before = self.workbench.get_bug(bug_id)
        with self.assertRaisesRegex(ValueError, "已提交、等待核对或已锁定"):
            self.workbench.save({"bugs": [{"id": bug_id, "steps": "更新后的步骤"}]})
        self.assertEqual(self.workbench.get_bug(bug_id), before)
        self.workbench.scan(str(self.evidence))
        with self.assertRaisesRegex(ValueError, "不能重复"):
            self.workbench.validate_submission([bug_id])
        with self.assertRaisesRegex(ValueError, "不能被清除"):
            self.workbench.set_submission(bug_id, status="uncertain", remote_id=None)

    def test_failed_before_creation_can_retry_after_confirmation(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        self.workbench.set_submission(bug_id, status="submitting")
        self.workbench.set_submission(bug_id, status="failed", error="禅道明确拒绝创建")
        self.assertEqual(len(self.workbench.validate_submission([bug_id])), 1)
        self.workbench.set_submission(bug_id, status="submitting")
        self.assertEqual(self.workbench.get_bug(bug_id)["status"], "submitting")

    def test_explicit_user_reconciliation_allows_safe_retry_only_without_created_id(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        self.workbench.set_submission(bug_id, status="submitting")
        self.workbench.set_submission(bug_id, status="uncertain", error="网络断开")
        result = self.workbench.reconcile_submission(bug_id, "not_created")
        self.assertEqual(result["bugs"][0]["status"], "failed")
        self.assertFalse(result["bugs"][0]["reviewed"])
        with self.assertRaisesRegex(ValueError, "尚未复核"):
            self.workbench.validate_submission([bug_id])
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True}]})
        self.workbench.set_submission(bug_id, status="submitting")
        self.workbench.set_submission(bug_id, status="partial", remote_id=55)
        with self.assertRaisesRegex(ValueError, "已有禅道编号"):
            self.workbench.reconcile_submission(bug_id, "not_created")
        with self.assertRaisesRegex(ValueError, "不能替换"):
            self.workbench.reconcile_submission(bug_id, "created", remote_id=56)
        result = self.workbench.reconcile_submission(bug_id, "created", remote_id="55", remote_url="http://zentao/bug/55")
        self.assertEqual(result["bugs"][0]["status"], "submitted")
        self.assertEqual(Workbench(self.data).get_bug(bug_id)["remote_id"], "55")
        with self.assertRaisesRegex(ValueError, "不能重复"):
            self.workbench.validate_submission([bug_id])

    def test_reconciliation_requires_ambiguous_status_and_valid_remote_id(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        with self.assertRaisesRegex(ValueError, "只有待核对"):
            self.workbench.reconcile_submission(bug_id, "created", remote_id=1)
        self.workbench.set_submission(bug_id, status="submitting")
        self.workbench.set_submission(bug_id, status="uncertain")
        for invalid in (None, "abc", 0, -1, True):
            with self.assertRaisesRegex(ValueError, "正整数"):
                self.workbench.reconcile_submission(bug_id, "created", remote_id=invalid)
        reconciled = self.workbench.reconcile_submission(bug_id, "created", remote_id=6)
        self.assertEqual(reconciled["bugs"][0]["remote_id"], 6)

    def test_demo_is_clear_reusable_and_cannot_be_made_submittable_by_rescan(self):
        state = self.workbench.create_demo()
        self.assertTrue(state["demo"])
        self.assertEqual(len(state["bugs"]), 3)
        self.assertTrue(all("演示事实" in bug["preconditions"] for bug in state["bugs"]))
        bug_id = state["bugs"][0]["id"]
        self.workbench.save({"bugs": [{"id": bug_id, "actual": "用户修改的示例"}]})
        again = self.workbench.create_demo()
        self.assertEqual(again["bugs"][0]["actual"], "用户修改的示例")
        self.assertTrue(self.workbench.scan(state["root_dir"], demo=False)["demo"])
        with self.assertRaisesRegex(ValueError, "演示数据"):
            self.workbench.validate_submission([bug_id])

    def test_demo_settings_edits_do_not_replace_real_defaults_and_explicit_profiles_are_kept(self):
        self.bug_folder()
        for label, real_settings in (
            ("未配置", {"product": "", "product_name": "", "openedBuild": [], "build_name": ""}),
            ("已配置", {"product": "8", "product_name": "公司真实产品", "openedBuild": ["12"], "build_name": "正式测试版本"}),
        ):
            with self.subTest(label=label):
                workbench = Workbench(self.data / label)
                workbench.save({"settings": real_settings})
                workbench.create_demo()
                demo_settings = {"product": "demo", "product_name": "示例产品", "openedBuild": ["demo-build"], "build_name": "示例版本"}
                edited = workbench.save({"settings": demo_settings,
                                         "profiles": [{"id": "saved-demo", "name": "手动另存示例配置", "settings": demo_settings}]})
                self.assertEqual(edited["settings"]["product"], "demo")
                state = workbench.scan(str(self.evidence))
                for field, expected in real_settings.items():
                    self.assertEqual(state["settings"][field], expected)
                self.assertFalse(state["demo"])
                self.assertEqual(state["profiles"][0]["settings"]["product"], "demo")
                persisted = Workbench(self.data / label).state()
                self.assertEqual(persisted["settings"]["product_name"], real_settings["product_name"])
                self.assertEqual(persisted["profiles"][0]["name"], "手动另存示例配置")

    def test_importing_demo_backup_does_not_replace_real_or_empty_defaults(self):
        self.bug_folder()
        self.workbench.create_demo()
        self.workbench.save({"settings": {"product": "demo", "product_name": "示例产品", "openedBuild": ["demo-build"], "build_name": "示例版本"}})
        backup = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        for label, real_settings in (
            ("空默认", {"product": "", "product_name": "", "openedBuild": [], "build_name": ""}),
            ("真实默认", {"product": "18", "product_name": "真实产品", "openedBuild": ["20"], "build_name": "真实版本"}),
        ):
            with self.subTest(label=label):
                destination = Workbench(self.data / label)
                destination.save({"settings": real_settings})
                imported = destination.import_backup(backup)
                self.assertTrue(imported["demo"])
                self.assertEqual(imported["settings"]["product"], "demo")
                # Restart before scanning so the protection also covers persisted defaults.
                destination = Workbench(self.data / label)
                state = destination.scan(str(self.evidence))
                self.assertFalse(state["demo"])
                for field, expected in real_settings.items():
                    self.assertEqual(state["settings"][field], expected)

    def test_corrupt_state_recovers_backup_and_preserves_original_with_notice(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        # The previous valid state must contain the complete descriptions.
        self.workbench.save({"bugs": [{"id": bug_id, "selected": False}]})
        (self.data / "state.json").write_text("{broken-json", encoding="utf-8")
        recovered = Workbench(self.data)
        self.assertEqual(recovered.get_bug(bug_id)["steps"], "播放视频后点击暂停。")
        self.assertTrue(any("备份恢复" in warning for warning in recovered.state()["warnings"]))
        corrupt = list(self.data.glob("state.corrupt-*.json"))
        self.assertEqual(len(corrupt), 1)
        self.assertEqual(corrupt[0].read_text(encoding="utf-8"), "{broken-json")

    def test_invalid_save_does_not_partially_change_other_bug_or_settings(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        before = self.workbench.state()
        with self.assertRaises(ValueError):
            self.workbench.save({"settings": {"product": "changed"}, "bugs": [{"id": before["bugs"][0]["id"], "actual": "would be partial"}, {"id": "missing"}]})
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(Workbench(self.data).state(), before)

    def test_json_import_does_not_trust_attachment_paths_or_preserve_old_review(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        exported = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        exported["state"]["bugs"][0]["attachments"] = [{"id": "x", "path": "C:/Windows/secrets.txt", "name": "secret", "size": 100}]
        imported = self.workbench.import_backup(exported)
        self.assertTrue(imported["requires_rescan"])
        self.assertEqual(imported["bugs"][0]["attachments"], [])
        self.assertFalse(imported["bugs"][0]["reviewed"])
        with self.assertRaisesRegex(ValueError, "重新扫描"):
            self.workbench.validate_submission([bug_id])
        scanned = self.workbench.scan(str(self.evidence))
        self.assertFalse(scanned["requires_rescan"])
        self.assertEqual(scanned["bugs"][0]["steps"], "播放视频后点击暂停。")
        self.assertEqual(scanned["bugs"][0]["attachments"][0]["name"], "复现截图.png")

    def test_importing_old_export_never_erases_local_created_id(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        draft_export = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        self.workbench.set_submission(bug_id, status="submitting")
        self.workbench.set_submission(bug_id, status="submitted", remote_id=67)
        imported = self.workbench.import_backup(draft_export)
        self.assertEqual(imported["bugs"][0]["remote_id"], 67)
        self.workbench.scan(str(self.evidence))
        with self.assertRaisesRegex(ValueError, "不能重复"):
            self.workbench.validate_submission([bug_id])

    def test_portable_export_restores_profiles_history_and_known_created_id_in_new_storage(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        self.workbench.save({"profiles": [{"id": "company", "name": "公司智慧中屏", "settings": self.workbench.get_settings()}],
                             "active_profile": "company"})
        self.workbench.set_submission(bug_id, status="submitting")
        self.workbench.set_submission(bug_id, status="submitted", remote_id=123)
        backup = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        portable = Workbench(self.root / "便携工作区")
        first = portable.import_backup(backup)
        self.assertEqual(first["profiles"][0]["name"], "公司智慧中屏")
        self.assertEqual(first["active_profile"], "company")
        self.assertEqual(first["bugs"][0]["remote_id"], 123)
        self.assertEqual(first["history"][-1]["remote_id"], 123)
        repeated = portable.import_backup(backup)
        self.assertEqual(len(repeated["history"]), len(first["history"]))
        portable.scan(str(self.evidence))
        with self.assertRaisesRegex(ValueError, "不能重复"):
            portable.validate_submission([bug_id])

    def test_exports_preserve_multiline_unicode_and_csv_cannot_start_formulas(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        self.workbench.save({"bugs": [{"id": bug_id, "title": "=SUM(1,2)", "steps": "+危险公式\n第二行中文", "expected": "正常结果"}]})
        csv_path = Path(self.workbench.export("csv"))
        raw = csv_path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
        self.assertEqual(rows[1][0], "'=SUM(1,2)")
        self.assertEqual(rows[1][2], "'+危险公式\n第二行中文")
        markdown = Path(self.workbench.export("markdown")).read_text(encoding="utf-8")
        self.assertIn("[期望]\n正常结果", markdown)
        self.assertIn("复现截图.png", markdown)
        backup = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        self.assertEqual(backup["state"]["bugs"][0]["steps"], "+危险公式\n第二行中文")

    def test_feedback_name_survives_restart_profiles_and_portable_exports(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        self.ready()
        self.workbench.save({"settings": {"feedbackBy": "示例测试员"}})
        self.workbench.save({"profiles": [{"id": "company", "name": "公司配置", "settings": self.workbench.get_settings()}],
                             "active_profile": "company"})
        restarted = Workbench(self.data)
        self.assertEqual(restarted.get_settings()["feedbackBy"], "示例测试员")
        self.assertEqual(restarted.state()["profiles"][0]["settings"]["feedbackBy"], "示例测试员")
        markdown = Path(restarted.export("markdown")).read_text(encoding="utf-8")
        self.assertIn("反馈者：示例测试员", markdown)
        csv_rows = list(csv.DictReader(io.StringIO(Path(restarted.export("csv")).read_text(encoding="utf-8-sig"))))
        self.assertEqual(csv_rows[0]["反馈者"], "示例测试员")
        backup = json.loads(Path(restarted.export("json")).read_text(encoding="utf-8"))
        imported = Workbench(self.root / "导入工作区").import_backup(backup)
        self.assertEqual(imported["settings"]["feedbackBy"], "示例测试员")
        self.assertEqual(imported["profiles"][0]["settings"]["feedbackBy"], "示例测试员")
        restarted.save({"settings": {"feedbackBy": "=SUM(1,2)"}})
        csv_rows = list(csv.DictReader(io.StringIO(Path(restarted.export("csv")).read_text(encoding="utf-8-sig"))))
        self.assertEqual(csv_rows[0]["反馈者"], "'=SUM(1,2)")

    def test_legacy_drafts_profiles_and_import_default_feedback_to_blank(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        self.workbench.save({"profiles": [{"id": "company", "name": "旧配置", "settings": self.workbench.get_settings()}]})
        backup = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        backup["state"]["settings"].pop("feedbackBy")
        backup["state"]["profiles"][0]["settings"].pop("feedbackBy")
        state_path = self.data / "state.json"
        stored = json.loads(state_path.read_text(encoding="utf-8"))
        stored["default_settings"].pop("feedbackBy")
        stored["profiles"][0]["settings"].pop("feedbackBy")
        for batch in stored["batches"].values():
            batch["settings"].pop("feedbackBy")
        state_path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
        restarted = Workbench(self.data)
        self.assertEqual(restarted.get_settings()["feedbackBy"], "")
        self.assertEqual(restarted.state()["profiles"][0]["settings"]["feedbackBy"], "")
        self.assertEqual(restarted.get_bug(bug_id)["steps"], "播放视频后点击暂停。")
        self.assertTrue(restarted.get_bug(bug_id)["reviewed"])
        other = self.root / "公司Bug" / "10.14"
        self.bug_folder(root=other)
        self.assertEqual(restarted.scan(str(other))["settings"]["feedbackBy"], "")
        imported = Workbench(self.root / "旧版导入工作区").import_backup(backup)
        self.assertEqual(imported["settings"]["feedbackBy"], "")
        self.assertEqual(imported["profiles"][0]["settings"]["feedbackBy"], "")

    def test_feedback_change_requires_new_review_and_length_error_preserves_saved_draft(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        old_bug = self.workbench.get_bug(bug_id)
        self.workbench.save({"settings": {"feedbackBy": "示例测试员"}, "bugs": [{"id": bug_id, "reviewed": True}]})
        current = self.workbench.get_bug(bug_id)
        self.assertFalse(current["reviewed"])
        self.assertNotEqual(old_bug["review_token"], current["review_token"])
        with self.assertRaisesRegex(ValueError, "公共信息或附件已变化"):
            self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True, "review_token": old_bug["review_token"]}]})
        self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True, "review_token": current["review_token"]}]})
        self.assertEqual(self.workbench.validate_submission([bug_id])[0][1]["feedbackBy"], "示例测试员")
        before = self.workbench.state()
        with self.assertRaisesRegex(ValueError, "反馈者最多填写 100 个字符"):
            self.workbench.save({"settings": {"feedbackBy": "姓" * 101}, "bugs": [{"id": bug_id, "steps": "不会被保存的修改"}]})
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(Workbench(self.data).state(), before)
        self.workbench.save({"settings": {"feedbackBy": "姓" * 100}})
        self.assertEqual(self.workbench.get_settings()["feedbackBy"], "姓" * 100)

    def test_legacy_draft_exclusions_are_retired_and_require_a_new_review(self):
        folder = self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        original = (folder / "复现截图.png").read_bytes()
        path = self.data / "state.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        bug = next(iter(stored["batches"].values()))["bugs"][0]
        bug["excluded_attachments"] = [bug["attachments"][0]["id"]]
        path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
        restored = Workbench(self.data)
        current = restored.get_bug(bug_id)
        self.assertEqual(current["excluded_attachments"], [])
        self.assertFalse(current["reviewed"])
        self.assertTrue(any("排除的附件已恢复" in warning for warning in restored.state()["warnings"]))
        with self.assertRaisesRegex(ValueError, "尚未复核"):
            restored.validate_submission([bug_id])
        self.assertEqual(Workbench(self.data).state(), restored.state())
        self.assertEqual((folder / "复现截图.png").read_bytes(), original)

    def test_legacy_submission_records_are_not_rewritten_by_attachment_migration(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        path = self.data / "state.json"
        template = json.loads(path.read_text(encoding="utf-8"))
        for status in ("submitted", "partial", "uncertain"):
            with self.subTest(status=status):
                stored = copy.deepcopy(template)
                bug = next(iter(stored["batches"].values()))["bugs"][0]
                excluded = [bug["attachments"][0]["id"]]
                bug.update(status=status, remote_id=123, excluded_attachments=excluded)
                path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
                restored = Workbench(self.data).get_bug(bug_id)
                self.assertEqual(restored["status"], status)
                self.assertEqual(restored["remote_id"], 123)
                self.assertEqual(restored["excluded_attachments"], excluded)
                self.assertEqual(restored["reviewed"], bug["reviewed"])

    def test_legacy_backup_cannot_restore_an_active_attachment_exclusion(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        self.ready()
        backup = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        bug = backup["state"]["bugs"][0]
        bug["excluded_attachments"] = [bug["attachments"][0]["id"]]
        destination = Workbench(self.root / "restored")
        imported = destination.import_backup(backup)
        self.assertEqual(imported["bugs"][0]["excluded_attachments"], [])
        self.assertFalse(imported["bugs"][0]["reviewed"])
        rescanned = destination.scan(str(self.evidence))
        self.assertEqual(len(rescanned["bugs"][0]["attachments"]), 1)
        self.assertEqual(rescanned["bugs"][0]["excluded_attachments"], [])

    def test_rejected_attachment_exclusion_does_not_save_other_changes(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        before = self.workbench.state()
        with self.assertRaisesRegex(ValueError, "不再支持单独排除"):
            self.workbench.save({"settings": {"product": "99"}, "bugs": [{
                "id": bug_id, "actual": "should not be saved",
                "excluded_attachments": [before["bugs"][0]["attachments"][0]["id"]]}]})
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(Workbench(self.data).state(), before)

    def test_oversize_attachment_requires_local_file_change_and_rescan(self):
        self.bug_folder()
        with patch("domain.MAX_ATTACHMENT_SIZE", 4):
            state = self.workbench.scan(str(self.evidence))
            self.assertTrue(any("500 MB" in warning for warning in state["warnings"]))
            bug_id = self.ready()
            with self.assertRaisesRegex(ValueError, "超过 500 MB"):
                self.workbench.validate_submission([bug_id])
            attachment_id = state["bugs"][0]["attachments"][0]["id"]
            with self.assertRaisesRegex(ValueError, "不再支持单独排除"):
                self.workbench.save({"bugs": [{"id": bug_id, "excluded_attachments": [attachment_id]}]})
            Path(state["bugs"][0]["attachments"][0]["path"]).unlink()
            self.workbench.scan(str(self.evidence))
            self.workbench.save({"bugs": [{"id": bug_id, "reviewed": True}]})
            self.assertEqual(len(self.workbench.validate_submission([bug_id])), 1)

    def test_symlink_folder_and_attachment_are_never_scanned(self):
        folder = self.bug_folder()
        outside = self.root / "机密.txt"
        outside.write_text("outside", encoding="utf-8")
        try:
            os.symlink(outside, folder / "链接附件.txt")
            os.symlink(folder, self.evidence / "链接Bug", target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"当前 Windows 环境不允许创建 symlink: {exc}")
        state = self.workbench.scan(str(self.evidence))
        self.assertEqual(len(state["bugs"]), 1)
        self.assertEqual(len(state["bugs"][0]["attachments"]), 1)
        self.assertTrue(any("已跳过链接" in warning for warning in state["warnings"]))

    @unittest.skipUnless(os.name == "nt", "junction 是 Windows 文件系统功能")
    def test_windows_junction_does_not_import_another_bugs_evidence(self):
        folder = self.bug_folder()
        outside = self.root / "其它资料"
        outside.mkdir()
        (outside / "不属于这个Bug.txt").write_text("external", encoding="utf-8")
        link = folder / "外部映射"
        process = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if process.returncode:
            self.skipTest("当前文件系统不支持创建 junction")
        state = self.workbench.scan(str(self.evidence))
        self.assertEqual([item["name"] for item in state["bugs"][0]["attachments"]], ["复现截图.png"])
        self.assertTrue(any("外部映射" in warning for warning in state["warnings"]))

    def test_structurally_damaged_valid_json_uses_backup_instead_of_crashing(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        self.ready()
        state_file = self.data / "state.json"
        content = json.loads(state_file.read_text(encoding="utf-8"))
        next(iter(content["batches"].values()))["bugs"][0].pop("folder")
        state_file.write_text(json.dumps(content), encoding="utf-8")
        recovered = Workbench(self.data)
        self.assertEqual(len(recovered.state()["bugs"]), 1)
        self.assertTrue(any("备份恢复" in warning for warning in recovered.state()["warnings"]))

    def test_import_rejects_drive_escape_folder_name_without_mutating_workbench(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        exported = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        exported["state"]["bugs"][0]["original_title"] = "C:"
        before = self.workbench.state()
        with self.assertRaisesRegex(ValueError, "不安全"):
            self.workbench.import_backup(exported)
        self.assertEqual(self.workbench.state(), before)

    def test_state_is_detached_and_concurrent_saves_leave_valid_persistent_json(self):
        self.bug_folder()
        self.workbench.scan(str(self.evidence))
        bug_id = self.ready()
        state = self.workbench.state()
        state["settings"]["product"] = "tampered"
        state["bugs"][0]["attachments"].clear()
        self.assertEqual(self.workbench.get_settings()["product"], "1")
        self.assertEqual(len(self.workbench.get_bug(bug_id)["attachments"]), 1)
        failures = []
        def writer(index):
            try:
                for iteration in range(8):
                    self.workbench.save({"bugs": [{"id": bug_id, "actual": f"线程 {index} 的结果 {iteration}"}]})
                    self.workbench.state()
            except Exception as exc:
                failures.append(exc)
        threads = [threading.Thread(target=writer, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [])
        persisted = Workbench(self.data)
        self.assertEqual(persisted.get_bug(bug_id)["actual"], self.workbench.get_bug(bug_id)["actual"])
        self.assertFalse(persisted.get_bug(bug_id)["reviewed"])


if __name__ == "__main__":
    unittest.main()
