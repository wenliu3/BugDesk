"""A local, draft-only WorkBuddy bridge; approval stays in the BugDesk UI."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timezone

from domain import _source_cases


SESSION_SECONDS = 60 * 60
MAX_ROWS = 300
MAX_CONTEXTS = 4
MAX_CANDIDATES = 20
MAX_STAGE_BYTES = 1024 * 1024
METADATA_LIMITS = {"case_id": 200, "title": 1000, "group": 2000, "tester": 200, "date": 100}
FACT_FIELDS = ("preconditions", "steps", "expected", "actual")
FIELD_LABELS = {"case_id": "用例 ID", "title": "用例名称", "group": "用例分组", "tester": "测试人员",
                "date": "测试日期", "preconditions": "前置条件", "steps": "复现步骤",
                "expected": "预期结果", "actual": "实际结果"}
ROW_FIELDS = set(METADATA_LIMITS) | set(FACT_FIELDS) | {
    "suggested_bug_id", "match_reason", "candidate_bug_ids", "source_actual", "review_notes",
    "source_cases",
}
BUG_FIELDS = ("id", "title", "original_title", "case_source", "case_sources", "review_token",
              "preconditions", "steps", "expected", "actual")


def _timestamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def _editable(bug):
    return (bug.get("status") not in {"locked", "submitting", "submitted", "uncertain", "partial"}
            and bug.get("remote_id") in (None, "") and not bug.get("locked"))


def _text(value, label, limit):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError(f"{label}需要是文字，且不能超过 {limit} 个字符。")
    return value


def _separate_actual_notes(row):
    """Keep known administrative prefixes and explicit review notes out of facts.

    This is compatibility cleanup, not a rewrite of the observed behavior.
    Unknown brackets (UI labels, error codes and quoted responses) stay intact.
    """
    original = row["actual"]
    notes = row["review_notes"]

    def move_note(match):
        if match.group(1).strip():
            notes.append(match.group(1).strip())
        return ""

    actual = re.sub(r"(?m)^[ \t]*【(?:待确认|待补充)】[ \t]*([^\r\n]*)", move_note, original)
    groups = {part.strip() for part in re.split(r"[/\\>]+", row["group"]) if part.strip()}
    removed = False
    while match := re.match(r"^\s*【([^】\r\n]{1,80})】[ \t]*", actual):
        tag = match.group(1).strip()
        administrative = tag in {"厂商差异", "第三方", "需求问题", "非需求问题"} or bool(
            re.fullmatch(r"\d+(?:\.\d+)*(?:需求)?版本", tag))
        if not administrative and not (removed and tag in groups):
            break
        actual = actual[match.end():]
        removed = True
    if removed or actual != original:
        row["actual"] = actual.strip()
        if not row["source_actual"]:
            row["source_actual"] = original
    row["review_notes"] = list(dict.fromkeys(notes))


class WorkBuddyBridge:
    def __init__(self, app):
        self.app = app
        self.connection_file = app.data_dir / "workbuddy-session.json"
        self._token = ""
        self._expires = 0
        self._batch_key = ""
        self._contexts = {}
        self._pending = None

    def _clear_locked(self):
        """Only remove the connection file issued by this particular session."""
        try:
            value = json.loads(self.connection_file.read_text(encoding="utf-8"))
            if (isinstance(value, dict) and value.get("instance") == self.app.instance
                    and self._token and value.get("token") == self._token):
                self.connection_file.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        self._token = ""
        self._expires = 0
        self._batch_key = ""
        self._contexts.clear()
        self._pending = None

    def close(self):
        # Shutdown has already marked the application as stopping; it must not
        # require an idle/operational UI in order to retire this capability.
        with self.app.job_lock:
            self._clear_locked()

    def enable(self):
        with self.app.job_lock:
            self.app.ensure_idle()
            current = self.app.workbench.state()
            if not current.get("bugs") or current.get("requires_rescan"):
                raise ValueError("请先扫描今天的 Bug 文件夹，再开启 WorkBuddy 连接。")
            port = getattr(self.app.server, "server_port", None)
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError("BugDesk 本地服务尚未启动，请稍后重新开启连接。")
            self._clear_locked()
            token = secrets.token_urlsafe(32)
            expires = time.time() + SESSION_SECONDS
            record = {"schema": 1, "url": f"http://127.0.0.1:{port}/",
                      "instance": self.app.instance, "token": token, "expires_at": _timestamp(expires)}
            self.app.workbench._write_atomic(self.connection_file, json.dumps(record, ensure_ascii=False, indent=2))
            self._token = token
            self._expires = expires
            self._batch_key = current["batch_key"]
            return self._status_locked()

    def disable(self):
        with self.app.job_lock:
            self.app.ensure_idle()
            self._clear_locked()
            return self._status_locked()

    def _prune_locked(self):
        if self._token and time.time() >= self._expires:
            self._clear_locked()

    def _status_locked(self, known_plan_id=None):
        self._prune_locked()
        if self._token:
            current = self.app.workbench.batch_context()
            if current.get("batch_key") != self._batch_key or current.get("requires_rescan"):
                self._clear_locked()
        pending = None
        if self._pending:
            if known_plan_id and known_plan_id == self._pending["plan_id"]:
                pending = {"plan_id": self._pending["plan_id"], "unchanged": True}
            else:
                pending = copy.deepcopy(self._pending)
        return {"enabled": bool(self._token),
                "connection_file": str(self.connection_file) if self._token else "",
                "expires_at": _timestamp(self._expires) if self._token else "",
                "pending": pending, "undo": self.app.workbench.undo_status()}

    def status(self, known_plan_id=None):
        with self.app.job_lock:
            self.app.ensure_idle()
            if known_plan_id is not None and (not isinstance(known_plan_id, str) or len(known_plan_id) > 200):
                raise ValueError("WorkBuddy 建议编号格式不正确。")
            return self._status_locked(known_plan_id)

    def _validate_locked(self, token):
        self._prune_locked()
        if not self._token:
            raise ValueError("WorkBuddy 连接未开启或已过期，请在 BugDesk 中重新开启。")
        if not isinstance(token, str) or not token.isascii() or not secrets.compare_digest(token, self._token):
            raise ValueError("WorkBuddy 连接令牌不匹配，请重新读取当前连接文件。")
        current = self.app.workbench.state()
        if current.get("batch_key") != self._batch_key or current.get("requires_rescan"):
            self._clear_locked()
            raise ValueError("当前 Bug 批次已变化，请在 BugDesk 中重新开启 WorkBuddy 连接。")
        return current

    def validate(self, token):
        with self.app.job_lock:
            self.app.ensure_idle()
            self._validate_locked(token)
            return True

    @staticmethod
    def _public_bug(bug):
        value = {key: copy.deepcopy(bug.get(key, {} if key == "case_source" else "")) for key in BUG_FIELDS}
        value["case_sources"] = copy.deepcopy(bug.get("case_sources", [bug["case_source"]] if bug.get("case_source") else []))
        excluded = set(bug.get("excluded_attachments", []))
        value["attachments"] = [{"name": item["name"]} for item in bug.get("attachments", [])
                                if item.get("id") not in excluded]
        return value

    def context(self, token):
        with self.app.job_lock:
            self.app.ensure_idle()
            current = self._validate_locked(token)
            bugs = [self._public_bug(bug) for bug in current["bugs"] if _editable(bug)]
            if not bugs:
                raise ValueError("当前批次没有可整理的 Bug，已提交或待核对的 Bug 不参与。")
            context_id = secrets.token_hex(16)
            result = {"schema": 1, "context_id": context_id,
                      "batch_label": current["root_dir"].replace("\\", "/").rstrip("/").rsplit("/", 1)[-1],
                      "demo": bool(current.get("demo")), "bugs": bugs}
            self._contexts[context_id] = {"batch_key": current["batch_key"], "public": copy.deepcopy(result)}
            while len(self._contexts) > MAX_CONTEXTS:
                del self._contexts[next(iter(self._contexts))]
            return result

    def _snapshot_current_locked(self, snapshot, completed_bug_ids=()):
        current = self.app.workbench.state()
        if (current.get("batch_key") != snapshot["batch_key"] or current.get("requires_rescan")
                or current.get("batch_key") != self._batch_key):
            raise ValueError("当前 Bug 批次已变化，请重新读取 WorkBuddy 上下文。")
        completed = set(completed_bug_ids)
        current_bugs = {bug["id"]: bug for bug in current["bugs"]
                        if _editable(bug) and bug["id"] not in completed}
        observed = snapshot["public"]["bugs"]
        if set(current_bugs) != {bug["id"] for bug in observed}:
            raise ValueError("Bug 清单或提交状态已变化，请重新读取 WorkBuddy 上下文。")
        for bug in observed:
            if current_bugs[bug["id"]]["review_token"] != bug["review_token"]:
                raise ValueError("Bug 内容、公共信息或附件已变化，请重新读取 WorkBuddy 上下文。")

    def stage(self, data, token):
        with self.app.job_lock:
            self.app.ensure_idle()
            self._validate_locked(token)
            if not isinstance(data, dict) or set(data) - {"context_id", "rows"}:
                raise ValueError("WorkBuddy 建议格式不正确，只支持用例内容和关联建议。")
            try:
                encoded_size = len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            except (TypeError, ValueError, RecursionError) as error:
                raise ValueError("WorkBuddy 建议不是有效的文字数据。") from error
            if encoded_size > MAX_STAGE_BYTES:
                raise ValueError("WorkBuddy 建议超过 1 MB，请分批整理。")
            context_id = _text(data.get("context_id", ""), "上下文编号", 200)
            snapshot = self._contexts.get(context_id)
            if not snapshot:
                raise ValueError("WorkBuddy 上下文已失效，请重新读取当前 Bug 清单。")
            self._snapshot_current_locked(snapshot)
            source = data.get("rows")
            if not isinstance(source, list) or not source or len(source) > MAX_ROWS:
                raise ValueError("一次最多暂存 300 条用例，请分批整理。")
            allowed_ids = {bug["id"] for bug in snapshot["public"]["bugs"]}
            rows = []
            source_count = 0
            for index, item in enumerate(source, start=1):
                if not isinstance(item, dict) or set(item) - ROW_FIELDS:
                    raise ValueError("用例中含有不支持的字段，请仅提交四项事实和关联建议。")
                row = {key: _text(item.get(key, ""), FIELD_LABELS[key], limit) for key, limit in METADATA_LIMITS.items()}
                row.update({key: _text(item.get(key, ""), FIELD_LABELS[key], 20000) for key in FACT_FIELDS})
                row["source_actual"] = _text(item.get("source_actual", ""), "原始失败备注", 20000)
                if "source_cases" in item:
                    row["source_cases"] = _source_cases(item["source_cases"])
                    source_count += len(row["source_cases"])
                else:
                    source_count += 1
                if source_count > MAX_ROWS:
                    raise ValueError("一次最多暂存 300 条原始用例，请分批整理。")
                notes = item.get("review_notes", [])
                if not isinstance(notes, list) or len(notes) > 20:
                    raise ValueError("待确认事项需要是列表，且最多 20 条。")
                row["review_notes"] = [_text(note, "待确认事项", 2000) for note in notes]
                _separate_actual_notes(row)
                row["suggested_bug_id"] = _text(item.get("suggested_bug_id", ""), "建议关联 Bug", 200)
                if row["suggested_bug_id"] and row["suggested_bug_id"] not in allowed_ids:
                    raise ValueError("建议关联的 Bug 不在当前可编辑清单中，请重新读取上下文。")
                row["match_reason"] = _text(item.get("match_reason", ""), "关联说明", 1000)
                candidates = item.get("candidate_bug_ids", [])
                if (not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES
                        or any(not isinstance(value, str) or value not in allowed_ids for value in candidates)):
                    raise ValueError("候选 Bug 清单无效，每条用例最多提供 20 个当前候选。")
                row["candidate_bug_ids"] = list(dict.fromkeys(candidates))
                row["source_row"] = index
                row["row_id"] = hashlib.sha256(json.dumps([context_id, index, row], ensure_ascii=False,
                                                           sort_keys=True).encode("utf-8")).hexdigest()[:24]
                rows.append(row)
            original = {row["row_id"]: row for row in rows}
            matching_rows = copy.deepcopy(rows)
            for row in matching_rows:
                if "source_cases" in row:
                    # A representative ID must not turn an AI grouping into an
                    # exact link. Single-source groups can use their real ID.
                    row["case_id"] = row["source_cases"][0]["case_id"] if len(row["source_cases"]) == 1 else ""
            linked = self.app.workbench.preview_case_links(matching_rows)
            summary = {"total": len(linked), "exact": 0, "suggested": 0, "unmatched": 0}
            for row in linked:
                proposal = original[row["row_id"]]
                row["case_id"] = proposal["case_id"]
                for key in ("source_cases", "source_actual", "review_notes"):
                    if key in proposal:
                        row[key] = copy.deepcopy(proposal[key])
                if row["suggested_bug_id"]:
                    row["match_type"] = "exact_id"
                    row["candidate_bug_ids"] = [row["suggested_bug_id"]]
                    summary["exact"] += 1
                elif proposal["suggested_bug_id"]:
                    row["match_type"] = "suggested"
                    row["suggested_bug_id"] = proposal["suggested_bug_id"]
                    row["candidate_bug_ids"] = list(dict.fromkeys([proposal["suggested_bug_id"], *proposal["candidate_bug_ids"]]))
                    row["match_reason"] = "AI 建议，待你确认。" + proposal["match_reason"]
                    summary["suggested"] += 1
                else:
                    row["match_type"] = "unmatched"
                    row["candidate_bug_ids"] = proposal["candidate_bug_ids"]
                    row["match_reason"] = "尚未关联，请你选择对应 Bug。" + proposal["match_reason"]
                    summary["unmatched"] += 1
                row["warnings"] = []
                if not row["actual"].strip():
                    row["warnings"].append("实际结果为空，需要按测试事实补充。")
                if not row["steps"].strip() or not row["expected"].strip():
                    row["warnings"].append("复现步骤或预期结果为空，填入后仍需补充。")
            plan_id = secrets.token_hex(16)
            self._pending = {"plan_id": plan_id, "context_id": context_id,
                             "batch_key": snapshot["batch_key"], "rows": linked,
                             "bugs": copy.deepcopy(snapshot["public"]["bugs"]), "summary": summary}
            return {"plan_id": plan_id, "summary": copy.deepcopy(summary),
                    "message": "建议已送到 BugDesk，请在窗口中确认关联和四项内容；草稿尚未修改。"}

    def apply(self, data):
        with self.app.job_lock:
            self.app.ensure_idle()
            self._prune_locked()
            if not self._token or not self._pending:
                raise ValueError("没有待确认的 WorkBuddy 建议，请重新暂存。")
            if (not isinstance(data, dict) or set(data) - {"plan_id", "assignments", "review_scope"}
                    or data.get("plan_id") != self._pending["plan_id"]):
                raise ValueError("WorkBuddy 建议已变化，请刷新预览后再确认。")
            if "review_scope" in data and data["review_scope"] != "bugs":
                raise ValueError("WorkBuddy 确认范围不正确，请刷新预览后再确认。")
            review_scope = data.get("review_scope", self._pending.get("review_scope", "cases"))
            completed_bug_ids = self._pending.get("completed_bug_ids", [])
            snapshot = {"batch_key": self._pending["batch_key"], "public": {"bugs": self._pending["bugs"]}}
            self._snapshot_current_locked(snapshot, completed_bug_ids)
            source = data.get("assignments")
            if not isinstance(source, list) or not source or len(source) > MAX_ROWS:
                raise ValueError("请选择需要填入的关联建议，一次最多确认 300 条。")
            bugs = {bug["id"]: bug for bug in self._pending["bugs"]}
            rows = {row["row_id"]: row for row in self._pending["rows"]}
            assignments = []
            for item in source:
                if not isinstance(item, dict) or set(item) - {"row_id", "bug_id", "mode"}:
                    raise ValueError("确认内容格式不正确，不能修改暂存建议的事实。")
                row_id, bug_id = item.get("row_id"), item.get("bug_id")
                if not isinstance(row_id, str) or row_id not in rows or not isinstance(bug_id, str) or bug_id not in bugs:
                    raise ValueError("选择的用例或 Bug 不在本次建议中，请重新确认。")
                mode = item.get("mode", "fill")
                if not isinstance(mode, str) or mode not in {"fill", "replace"}:
                    raise ValueError("请选择仅补空白或替换四项描述。")
                assignments.append({"row_id": row_id, "bug_id": bug_id, "mode": mode,
                                    "review_token": bugs[bug_id]["review_token"]})
            result = self.app.workbench.apply_cases(self._pending["rows"], assignments,
                                                    batch_key=self._pending["batch_key"], record_undo=True)
            if review_scope == "bugs":
                return self._finish_bug_review_locked(result, assignments, completed_bug_ids)
            consumed = {assignment["row_id"] for assignment in assignments}
            remaining = [row for row in self._pending["rows"] if row["row_id"] not in consumed]
            if remaining:
                # Only this successful write may rebase the pending snapshot.
                # Polling or an unrelated external edit must never advance it.
                current = result["state"]
                bugs = [self._public_bug(bug) for bug in current["bugs"] if _editable(bug)]
                summary = {"total": len(remaining), "exact": 0, "suggested": 0, "unmatched": 0}
                for row in remaining:
                    key = "exact" if row["match_type"] == "exact_id" else row["match_type"]
                    summary[key] += 1
                self._pending = {"plan_id": secrets.token_hex(16), "context_id": self._pending["context_id"],
                                 "batch_key": self._pending["batch_key"], "rows": remaining,
                                 "bugs": bugs, "summary": summary}
            else:
                self._pending = None
            # Draft content changed; retire every pre-write context snapshot.
            self._contexts.clear()
            return {**result, "state": self.app.state(), "remaining": len(remaining),
                    "pending": copy.deepcopy(self._pending), "undo": self.app.workbench.undo_status()}

    def undo(self, data):
        """UI-only undo also works after a restart or an expired AI connection."""
        with self.app.job_lock:
            self.app.ensure_idle()
            if not isinstance(data, dict) or set(data) != {"transaction_id"}:
                raise ValueError("撤销导入格式不正确，请刷新后再确认。")
            result = self.app.workbench.undo_last_import(data["transaction_id"])
            # Retire every pre-undo plan and capability snapshot so an old
            # suggestion cannot silently reapply the reverted facts.  The
            # current local connection remains available for a fresh context.
            self._pending = None
            self._contexts.clear()
            return {**result, "state": self.app.state(), "pending": None}

    def _finish_bug_review_locked(self, result, assignments, completed_bug_ids):
        """Complete reviewed Bugs while retaining the shared source-case pool."""
        total_bugs = self._pending.get("total_bugs", len(self._pending["bugs"]) + len(completed_bug_ids))
        completed_bug_ids = list(dict.fromkeys([*completed_bug_ids,
                                               *(assignment["bug_id"] for assignment in assignments)]))
        completed = set(completed_bug_ids)
        bugs = [self._public_bug(bug) for bug in result["state"]["bugs"]
                if _editable(bug) and bug["id"] not in completed]
        rows = copy.deepcopy(self._pending["rows"]) if bugs else []
        if bugs:
            allowed_ids = {bug["id"] for bug in bugs}
            summary = {"total": len(rows), "exact": 0, "suggested": 0, "unmatched": 0}
            for row in rows:
                if row["suggested_bug_id"] and row["suggested_bug_id"] not in allowed_ids:
                    row["suggested_bug_id"] = ""
                    row["match_type"] = "unmatched"
                    row["match_reason"] = "尚未关联，请为剩余 Bug 选择对应的用例。"
                row["candidate_bug_ids"] = [bug_id for bug_id in row["candidate_bug_ids"] if bug_id in allowed_ids]
                key = "exact" if row["match_type"] == "exact_id" else row["match_type"]
                summary[key] += 1
            # Only this successful write may rebase the remaining Bug snapshot.
            self._pending = {"plan_id": secrets.token_hex(16), "context_id": self._pending["context_id"],
                             "batch_key": self._pending["batch_key"], "rows": rows, "bugs": bugs,
                             "summary": summary, "review_scope": "bugs", "total_bugs": total_bugs,
                             "completed_bug_ids": completed_bug_ids,
                             "remaining_bugs": len(bugs), "remaining_cases": len(rows)}
        else:
            self._pending = None
        self._contexts.clear()
        return {**result, "state": self.app.state(), "remaining": len(bugs),
                "remaining_bugs": len(bugs), "remaining_cases": len(rows), "total_bugs": total_bugs,
                "completed_bug_ids": completed_bug_ids, "pending": copy.deepcopy(self._pending),
                "undo": self.app.workbench.undo_status()}
