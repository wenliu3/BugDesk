"""Clipboard testcase links must preserve manual drafts and evidence boundaries."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from domain import Workbench


class CaseImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "10.14"
        for name in ("PD10000-CA20001_埋点上报不全", "PD10000-CA200010_其他问题", "全程语音控制"):
            folder = self.root / name
            folder.mkdir(parents=True)
            (folder / "证据.txt").write_text("original evidence", encoding="utf-8")
        self.workbench = Workbench(self.base / "data")
        self.workbench.scan(str(self.root))

    def bug(self, starts="PD10000-CA20001_"):
        return next(item for item in self.workbench.state()["bugs"] if item["original_title"].startswith(starts))

    @staticmethod
    def row(row_id="row-1", case_id="PD10000-CA20001", **values):
        result = {"row_id": row_id, "source_row": 1, "case_id": case_id, "title": "学习唤醒词埋点",
                  "group": "示例用例/1.0版本/开机引导", "preconditions": "已绑定设备\n版本 62",
                  "steps": "1. 唤醒设备\n2. 查看上报结果", "actual": "仅 kjyd_hx_tg 上报",
                  "expected": "全部四个埋点正常上报", "tester": "示例测试员", "date": "10月14日", "result": "失败"}
        result.update(values)
        return result

    def assignment(self, row, bug=None, mode="fill"):
        bug = bug or self.bug()
        return {"row_id": row["row_id"], "bug_id": bug["id"], "review_token": bug["review_token"], "mode": mode}

    def apply(self, rows, assignments=None):
        if assignments is None:
            assignments = [self.assignment(rows[0])]
        return self.workbench.apply_cases(rows, assignments, batch_key=self.workbench.state()["batch_key"])

    def review(self, bug=None):
        bug = bug or self.bug()
        return self.workbench.save({"bugs": [{"id": bug["id"], "review_token": bug["review_token"], "reviewed": True}]})

    def test_multiline_facts_applied_without_changing_title_settings_evidence(self):
        before = self.workbench.state()
        row = self.row()
        result = self.apply([row])
        bug = self.bug()
        self.assertEqual(result["applied"], 1)
        for field in ("preconditions", "steps", "actual", "expected"):
            self.assertEqual(bug[field], row[field])
        self.assertEqual(bug["title"], before["bugs"][0]["title"])
        self.assertEqual(result["state"]["settings"], before["settings"])
        self.assertEqual(bug["attachments"], before["bugs"][0]["attachments"])
        self.assertEqual(bug["case_source"]["case_id"], row["case_id"])
        self.assertFalse(bug["reviewed"])
        self.assertEqual((Path(bug["folder"]) / "证据.txt").read_text(encoding="utf-8"), "original evidence")

    def test_fill_preserves_manual_content_and_title(self):
        identifier = self.bug()["id"]
        self.workbench.save({"bugs": [{"id": identifier, "title": "手工写的 Bug 标题", "steps": "手工步骤",
                                       "actual": "手工实际结果", "preconditions": "   "}]})
        result = self.apply([self.row()])
        bug = self.bug()
        self.assertEqual(bug["title"], "手工写的 Bug 标题")
        self.assertEqual(bug["steps"], "手工步骤")
        self.assertEqual(bug["actual"], "手工实际结果")
        self.assertEqual(bug["preconditions"], self.row()["preconditions"])
        self.assertEqual(result["skipped_fields"], 2)

    def test_replace_changes_mapped_nonblank_facts_and_clears_review(self):
        self.apply([self.row()])
        self.review()
        before = self.bug()
        row = self.row(steps="新步骤\n第二行", actual="", preconditions=None, expected="新预期")
        result = self.apply([row], [self.assignment(row, mode="replace")])
        bug = self.bug()
        self.assertEqual(result["applied"], 1)
        self.assertEqual(bug["steps"], row["steps"])
        self.assertEqual(bug["expected"], row["expected"])
        self.assertEqual(bug["actual"], before["actual"])
        self.assertEqual(bug["preconditions"], before["preconditions"])
        self.assertFalse(bug["reviewed"])
        self.assertNotEqual(bug["review_token"], before["review_token"])

    def test_source_only_change_invalidates_review_and_missing_actual_stays_empty(self):
        row = self.row(actual="")
        self.apply([row])
        self.assertEqual(self.bug()["actual"], "")
        self.workbench.save({"bugs": [{"id": self.bug()["id"], "actual": "后来补充的事实"}]})
        self.review()
        before = self.bug()
        row["tester"] = "另一测试人"
        self.apply([row])
        bug = self.bug()
        self.assertFalse(bug["reviewed"])
        self.assertNotEqual(bug["review_token"], before["review_token"])
        self.assertEqual(bug["actual"], "后来补充的事实")

    def test_exact_repeat_is_idempotent_and_does_not_persist(self):
        row = self.row()
        self.apply([row])
        self.review()
        before = self.workbench.state()
        with patch.object(self.workbench, "_persist") as persist:
            result = self.apply([row])
        persist.assert_not_called()
        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["skipped_fields"], 0)
        self.assertEqual(self.workbench.state(), before)

    def test_preview_matches_complete_id_not_similar_title_or_id_substring(self):
        rows = [self.row(), self.row("row-2", "PD10000-CA2000"), self.row("row-3", "", title="全程语音控制")]
        before = copy.deepcopy(rows)
        result = self.workbench.preview_case_links(rows)
        self.assertEqual(result[0]["suggested_bug_id"], self.bug()["id"])
        self.assertEqual(result[1]["suggested_bug_id"], "")
        self.assertEqual(result[2]["suggested_bug_id"], "")
        self.assertEqual(rows, before)

    def test_preview_remembers_manual_link_after_title_edit(self):
        row = self.row(case_id="PD10000-CA10004")
        plain = self.bug("全程语音控制")
        self.apply([row], [self.assignment(row, plain)])
        self.workbench.save({"bugs": [{"id": plain["id"], "title": "重新整理的手工标题"}]})
        self.assertEqual(self.workbench.preview_case_links([row])[0]["suggested_bug_id"], plain["id"])

    def test_preview_ambiguous_ids_and_locked_targets_have_no_automatic_link(self):
        row = self.row()
        duplicate = self.row("row-2")
        self.assertTrue(all(not item["suggested_bug_id"] for item in self.workbench.preview_case_links([row, duplicate])))
        plain = self.bug("全程语音控制")
        self.apply([row], [self.assignment(row, plain)])
        self.assertEqual(self.workbench.preview_case_links([row])[0]["suggested_bug_id"], "")
        self.workbench.set_submission(plain["id"], status="submitted", remote_id=7654)
        self.assertEqual(self.workbench.preview_case_links([row])[0]["suggested_bug_id"], self.bug()["id"])
        self.workbench.set_submission(self.bug()["id"], status="uncertain")
        self.assertEqual(self.workbench.preview_case_links([row])[0]["suggested_bug_id"], "")

    def test_explicit_same_case_can_fill_two_different_bugs(self):
        row = self.row()
        bugs = [self.bug(), self.bug("全程语音控制")]
        result = self.apply([row], [self.assignment(row, item) for item in bugs])
        self.assertEqual(result["applied"], 2)
        self.assertTrue(all(self.workbench.get_bug(item["id"])["case_source"]["case_id"] == row["case_id"] for item in bugs))
        self.assertEqual(self.workbench.preview_case_links([row])[0]["suggested_bug_id"], "")

    def test_stale_second_assignment_aborts_every_change(self):
        rows = [self.row(), self.row("row-2", "PD10000-CA10004")]
        assignments = [self.assignment(rows[0]), self.assignment(rows[1], self.bug("全程语音控制"))]
        self.workbench.save({"bugs": [{"id": assignments[1]["bug_id"], "steps": "用户刚刚编辑了步骤"}]})
        before = self.workbench.state()
        with self.assertRaisesRegex(ValueError, "内容已变化"):
            self.apply(rows, assignments)
        self.assertEqual(self.workbench.state(), before)

    def test_wrong_batch_duplicate_target_and_unknown_row_are_atomic(self):
        row = self.row()
        before = self.workbench.state()
        with self.assertRaisesRegex(ValueError, "批次"):
            self.workbench.apply_cases([row], [self.assignment(row)], batch_key="a different batch")
        with self.assertRaisesRegex(ValueError, "一条 Bug"):
            self.apply([row], [self.assignment(row), self.assignment(row)])
        assignment = self.assignment(row)
        assignment["row_id"] = "not parsed"
        with self.assertRaisesRegex(ValueError, "用例行"):
            self.apply([row], [assignment])
        self.assertEqual(self.workbench.state(), before)

    def test_all_submission_lock_states_and_remote_ids_refuse_mutation(self):
        row = self.row()
        for status, remote_id in (("submitting", None), ("submitted", 3), ("uncertain", None), ("partial", 4), ("failed", 5)):
            with self.subTest(status=status):
                store = copy.deepcopy(self.workbench._store)
                stored = next(item for item in self.workbench._batch()["bugs"] if item["id"] == self.bug()["id"])
                stored.update(status=status, remote_id=remote_id)
                before = self.workbench.state()
                with self.assertRaisesRegex(ValueError, "不能填入"):
                    self.apply([row])
                self.assertEqual(self.workbench.state(), before)
                self.workbench._store = store

    def test_source_survives_restart_rescan_and_backup_restore(self):
        self.apply([self.row()])
        source = self.bug()["case_source"]
        self.workbench = Workbench(self.base / "data")
        self.workbench.scan(str(self.root))
        self.assertEqual(self.bug()["case_source"], source)
        payload = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        restored = Workbench(self.base / "restored")
        restored.import_backup(payload)
        restored_bug = next(item for item in restored.state()["bugs"] if item["id"] == self.bug()["id"])
        self.assertEqual(restored_bug["case_source"], source)
        with self.assertRaisesRegex(ValueError, "扫描本机"):
            restored.apply_cases([self.row()], [self.assignment(self.row(), restored_bug)], batch_key=restored.state()["batch_key"])
        restored.scan(str(self.root))
        self.assertEqual(next(item for item in restored.state()["bugs"] if item["id"] == self.bug()["id"])["case_source"], source)

    def test_profiles_shared_settings_and_failed_journal_are_preserved(self):
        self.workbench.save({"settings": {"product": "331", "assignedTo": "company-user"},
                             "profiles": [{"id": "company", "name": "公司配置", "settings": {"product": "331"}}],
                             "active_profile": "company"})
        self.workbench.set_submission(self.bug()["id"], status="failed", error="读取概率失败", upload_status={"checked": False})
        before = self.workbench.state()
        self.apply([self.row()])
        after = self.workbench.state()
        self.assertEqual(after["settings"], before["settings"])
        self.assertEqual(after["profiles"], before["profiles"])
        self.assertEqual(after["history"], before["history"])
        for field in ("status", "error", "upload_status", "remote_id", "remote_url"):
            self.assertEqual(self.bug()[field], before["bugs"][0][field])

    def test_bounds_source_validation_and_ordinary_save_cannot_change_source(self):
        self.apply([self.row()])
        source = self.bug()["case_source"]
        self.workbench.save({"bugs": [{"id": self.bug()["id"], "case_source": {"case_id": "untrusted"}}]})
        self.assertEqual(self.bug()["case_source"], source)
        before = self.workbench.state()
        with self.assertRaises(ValueError):
            self.apply([self.row(steps="a" * 20001)])
        with self.assertRaises(ValueError):
            self.workbench.preview_case_links([self.row(str(index)) for index in range(301)])
        payload = {"version": 1, "root_dir": str(self.root), "bugs": [self.bug()]}
        payload["bugs"][0]["case_source"]["password"] = "must never retain arbitrary metadata"
        with self.assertRaisesRegex(ValueError, "用例来源"):
            self.workbench.import_backup(payload)
        self.assertEqual(self.workbench.state(), before)

    def test_persist_failure_rolls_back_in_memory_and_keeps_existing_state(self):
        before = self.workbench.state()
        with patch.object(self.workbench, "_persist", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.apply([self.row()])
        self.assertEqual(self.workbench.state(), before)

    def test_inactive_target_is_not_linked_or_mutated(self):
        row = self.row()
        before_bug = self.bug()
        folder = Path(before_bug["folder"])
        relocated = self.base / folder.name
        folder.rename(relocated)
        self.workbench.scan(str(self.root))
        self.assertEqual(self.workbench.preview_case_links([row])[0]["suggested_bug_id"], "")
        before = self.workbench.state()
        with self.assertRaisesRegex(ValueError, "不在当前批次"):
            self.apply([row], [self.assignment(row, before_bug)])
        self.assertEqual(self.workbench.state(), before)

    def test_importing_old_backup_preserves_known_submission_and_source(self):
        old_backup = {"state": self.workbench.state()}
        self.apply([self.row()])
        source = self.bug()["case_source"]
        self.workbench.set_submission(self.bug()["id"], status="submitted", remote_id=8800,
                                      remote_url="https://company.invalid/bug-view-8800.html")
        self.workbench.import_backup(old_backup)
        bug = self.bug()
        self.assertEqual(bug["remote_id"], 8800)
        self.assertEqual(bug["case_source"], source)
        self.assertEqual(bug["status"], "submitted")

    def test_non_string_mode_and_missing_review_token_are_validation_errors(self):
        row = self.row()
        before = self.workbench.state()
        assignment = self.assignment(row)
        assignment["mode"] = []
        with self.assertRaisesRegex(ValueError, "仅补空白"):
            self.apply([row], [assignment])
        assignment = self.assignment(row)
        assignment.pop("review_token")
        with self.assertRaisesRegex(ValueError, "内容已变化"):
            self.apply([row], [assignment])
        self.assertEqual(self.workbench.state(), before)

    def test_legacy_state_without_case_source_still_loads(self):
        self.apply([self.row()])
        raw = json.loads(self.workbench._state_path.read_text(encoding="utf-8"))
        for batch in raw["batches"].values():
            for bug in batch["bugs"]:
                bug.pop("case_source", None)
                bug.pop("case_sources", None)
        self.workbench._state_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        legacy = Workbench(self.base / "data")
        self.assertEqual(len(legacy.state()["bugs"]), 3)
        self.assertTrue(all(item["case_source"] == {} for item in legacy.state()["bugs"]))

    def grouped_row(self, **changes):
        fields = {"case_id", "title", "group", "tester", "date", "preconditions", "steps", "expected", "actual"}
        first = {key: value for key, value in self.row().items() if key in fields}
        second = {**first, "case_id": "PD10000-CA20002", "steps": "另一触发方式", "actual": "另一条原始记录"}
        return self.row(source_cases=[first, second], **changes)

    def test_multiple_sources_survive_restart_rescan_backup_and_exact_matching(self):
        row = self.grouped_row(steps="整理后的完整步骤", actual="多个触发方式均出现问题")
        self.apply([row])
        expected = self.bug()["case_sources"]
        self.assertEqual(len(expected), 2)
        self.workbench = Workbench(self.base / "data")
        self.workbench.scan(str(self.root))
        self.assertEqual(self.bug()["case_sources"], expected)
        for source in expected:
            linked = self.workbench.preview_case_links([self.row(case_id=source["case_id"])])[0]
            self.assertEqual(linked["suggested_bug_id"], self.bug()["id"])
        self.assertEqual(self.workbench.preview_case_links([self.row(case_id="PD10000-CA2000")])[0]["suggested_bug_id"], "")
        backup = json.loads(Path(self.workbench.export("json")).read_text(encoding="utf-8"))
        restored = Workbench(self.base / "restored")
        restored.import_backup(backup)
        restored.scan(str(self.root))
        bug = next(item for item in restored.state()["bugs"] if item["id"] == self.bug()["id"])
        self.assertEqual(bug["case_sources"], expected)
        self.assertEqual(bug["case_source"], expected[0])
        stored = json.loads(restored._state_path.read_text(encoding="utf-8"))
        self.assertNotIn("另一条原始记录", json.dumps(stored, ensure_ascii=False))

    def test_grouped_fill_conflict_requires_replace_before_linking_new_sources(self):
        self.apply([self.row()])
        self.review()
        before = self.workbench.state()
        stored = self.workbench._state_path.read_bytes()
        row = self.grouped_row(steps="1.分别执行 A、B 两种操作", actual="A、B 均出现同一问题")
        with patch.object(self.workbench, "_persist") as persist:
            with self.assertRaisesRegex(ValueError, "合并报告与已有内容不同.*覆盖已有内容"):
                self.apply([row])
        persist.assert_not_called()
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(self.workbench._state_path.read_bytes(), stored)
        result = self.apply([row], [self.assignment(row, mode="replace")])
        self.assertEqual(result["applied"], 1)
        self.assertEqual(self.bug()["steps"], row["steps"])
        self.assertEqual(self.bug()["actual"], row["actual"])
        self.assertEqual(len(self.bug()["case_sources"]), 2)
        self.assertFalse(self.bug()["reviewed"])
        self.review()
        before = self.workbench.state()
        with patch.object(self.workbench, "_persist") as persist:
            repeated = self.apply([row])
        persist.assert_not_called()
        self.assertEqual(repeated["unchanged"], 1)
        self.assertEqual(repeated["applied"], 0)
        self.assertEqual(self.workbench.state(), before)

    def test_grouped_fill_can_complete_blank_facts_with_matching_existing_facts(self):
        self.apply([self.row(actual="")])
        row = self.grouped_row(actual="A、B 均出现同一问题")
        result = self.apply([row])
        self.assertEqual(result["applied"], 1)
        self.assertEqual(self.bug()["actual"], row["actual"])
        self.assertEqual(self.bug()["steps"], row["steps"])
        self.assertEqual(len(self.bug()["case_sources"]), 2)

    def test_late_grouped_fill_conflict_rejects_other_bug_changes_atomically(self):
        self.apply([self.row()])
        row = self.grouped_row(steps="合并 A、B 的完整步骤")
        blank = self.bug("全程语音控制")
        before = self.workbench.state()
        stored = self.workbench._state_path.read_bytes()
        assignments = [self.assignment(row, blank), self.assignment(row)]
        with patch.object(self.workbench, "_persist") as persist:
            with self.assertRaisesRegex(ValueError, "合并报告与已有内容不同"):
                self.apply([row], assignments)
        persist.assert_not_called()
        self.assertEqual(self.workbench.state(), before)
        self.assertEqual(self.workbench._state_path.read_bytes(), stored)

    def test_changing_only_nonfirst_source_invalidates_review_and_legacy_apply_clears_it(self):
        row = self.grouped_row()
        self.apply([row])
        self.review()
        before = self.bug()
        row["source_cases"][1]["tester"] = "另一测试人员"
        self.apply([row])
        self.assertEqual(self.bug()["case_source"], before["case_source"])
        self.assertNotEqual(self.bug()["review_token"], before["review_token"])
        self.assertFalse(self.bug()["reviewed"])
        self.apply([self.row()])
        self.assertEqual(self.bug()["case_sources"], [self.bug()["case_source"]])
        self.assertEqual(self.workbench.preview_case_links([self.row(case_id="PD10000-CA20002")])[0]["suggested_bug_id"], "")

    def test_legacy_source_migrates_and_invalid_multiple_source_backups_are_atomic(self):
        self.apply([self.row()])
        payload = {"version": 1, "root_dir": str(self.root), "bugs": [self.bug()]}
        payload["bugs"][0].pop("case_sources")
        restored = Workbench(self.base / "restored")
        migrated = restored.import_backup(payload)["bugs"][0]
        self.assertEqual(migrated["case_sources"], [migrated["case_source"]])
        raw = json.loads(self.workbench._state_path.read_text(encoding="utf-8"))
        for batch in raw["batches"].values():
            for bug in batch["bugs"]:
                bug.pop("case_sources", None)
        decoded = Workbench._decode(json.dumps(raw))
        decoded_bug = next(bug for batch in decoded["batches"].values() for bug in batch["bugs"] if bug["id"] == self.bug()["id"])
        self.assertEqual(decoded_bug["case_sources"], [decoded_bug["case_source"]])
        invalid = [None, {}, [None], [{"steps": "must stay preview-only"}], [{"case_id": 3}],
                   [{"case_title": "x" * 1001}], [{}] * 301]
        before = self.workbench.state()
        for value in invalid:
            bad = copy.deepcopy(payload)
            bad["bugs"][0]["case_sources"] = value
            with self.subTest(value=str(value)[:80]), self.assertRaisesRegex(ValueError, "用例来源"):
                self.workbench.import_backup(bad)
            self.assertEqual(self.workbench.state(), before)
            damaged = copy.deepcopy(raw)
            next(iter(damaged["batches"].values()))["bugs"][0]["case_sources"] = value
            with self.assertRaisesRegex(ValueError, "用例来源"):
                Workbench._decode(json.dumps(damaged))

    def test_submitted_multiple_sources_survive_old_backup_and_save_cannot_forge_them(self):
        old = {"state": self.workbench.state()}
        self.apply([self.grouped_row()])
        sources = self.bug()["case_sources"]
        self.workbench.save({"bugs": [{"id": self.bug()["id"], "case_sources": [{"case_id": "FORGED"}]}]})
        self.assertEqual(self.bug()["case_sources"], sources)
        self.workbench.set_submission(self.bug()["id"], status="submitted", remote_id=8800)
        self.workbench.import_backup(old)
        self.assertEqual(self.bug()["case_sources"], sources)
        self.assertEqual(self.bug()["case_source"], sources[0])


if __name__ == "__main__":
    unittest.main()
