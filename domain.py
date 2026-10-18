"""Local, offline BugDesk workbench. User evidence folders are read-only inputs."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import stat
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


MAX_ATTACHMENT_SIZE = 500 * 1024 * 1024
DEFAULT_SETTINGS = {
    "product": "", "product_name": "", "project": "", "project_name": "",
    "execution": "", "execution_name": "", "module": "0", "module_name": "",
    "openedBuild": [], "build_name": "", "assignedTo": "", "assignee_name": "",
    "feedbackBy": "",
    "type": "codeerror", "severity": "3", "pri": "4", "probability": "", "os": "",
    "title_prefix": "", "preconditions": "", "steps_template": "", "zentao_url": "",
}
EDITABLE_FIELDS = {
    "title", "preconditions", "steps", "actual", "expected", "overrides",
    "excluded_attachments", "selected", "reviewed",
}
TEXT_FIELDS = {"title", "preconditions", "steps", "actual", "expected"}
LIFECYCLE_STATUSES = {"submitting", "submitted", "uncertain", "failed", "partial"}
TERMINAL_STATUSES = {"submitted", "uncertain", "partial"}
TEMP_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
TEMP_SUFFIXES = {".tmp", ".temp", ".crdownload", ".part", ".lock"}
CASE_FACT_FIELDS = ("preconditions", "steps", "actual", "expected")
CASE_SOURCE_LIMITS = {"case_id": 200, "case_title": 1000, "group": 2000, "tester": 200, "date": 100}
MAX_CASE_ROWS = 300


def _case_source(value):
    """Keep the bounded provenance that a user explicitly linked to a draft."""
    if not isinstance(value, dict) or set(value) - CASE_SOURCE_LIMITS.keys():
        raise ValueError("用例来源信息格式不正确。")
    cleaned = {}
    for key, text in value.items():
        if not isinstance(text, str) or len(text) > CASE_SOURCE_LIMITS[key] or "\x00" in text:
            raise ValueError("用例来源信息过长或格式不正确。")
        cleaned[key] = text
    return cleaned


def _case_rows(rows):
    if not isinstance(rows, list) or len(rows) > MAX_CASE_ROWS:
        raise ValueError("一次最多粘贴 300 条用例。")
    cleaned = copy.deepcopy(rows)
    seen = set()
    text_limits = {**{field: 20000 for field in CASE_FACT_FIELDS}, "case_id": 200,
                   "title": 1000, "group": 2000, "tester": 200, "date": 100, "result": 200}
    for row in cleaned:
        if not isinstance(row, dict):
            raise ValueError("粘贴的用例格式不正确。")
        identifier = row.get("row_id")
        if (not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 200
                or "\x00" in identifier or identifier in seen):
            raise ValueError("用例行编号缺失或重复，请重新解析粘贴内容。")
        seen.add(identifier)
        for key, limit in text_limits.items():
            value = row.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > limit or "\x00" in value):
                raise ValueError("用例内容过长或格式不正确，请缩小粘贴范围。")
    return cleaned


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _natural(value):
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r"(\d+)", str(value)))


def _identity(path):
    # Do not resolve imported paths or follow a junction during identity matching.
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _is_link(path, info=None):
    info = info or path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _is_temporary(path, info=None):
    name = path.name.casefold()
    return (name.startswith((".", "~$")) or name in TEMP_NAMES
            or path.suffix.casefold() in TEMP_SUFFIXES
            or bool(getattr(info, "st_file_attributes", 0) & 0x2))


def _settings(value, *, partial=False):
    if not isinstance(value, dict):
        raise ValueError("公共信息需要是一个对象。")
    result = {} if partial else copy.deepcopy(DEFAULT_SETTINGS)
    for key, field in value.items():
        if key not in DEFAULT_SETTINGS:
            continue
        if key == "openedBuild":
            if not isinstance(field, list) or any(not isinstance(item, (str, int)) for item in field):
                raise ValueError("影响版本需要是版本 ID 列表。")
            result[key] = list(dict.fromkeys(str(item).strip() for item in field if str(item).strip()))
        else:
            if not isinstance(field, (str, int)) or isinstance(field, bool):
                raise ValueError(f"公共字段 {key} 需要是文字。")
            if key == "feedbackBy" and len(str(field)) > 100:
                raise ValueError("反馈者最多填写 100 个字符，请缩短后保存。")
            if len(str(field)) > 20000:
                raise ValueError(f"公共字段 {key} 太长。")
            result[key] = str(field)
    return result


def _csv_safe(value):
    text = str(value or "")
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


class Workbench:
    """Thread-safe batches, drafts, submission journal, and portable exports.

    All public mutations return a detached view of the active state. Validation
    returns detached (bug, effective_settings) pairs, with title/preamble merged.
    JSON imports never authorize or open attachment paths; the user must rescan.
    """

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).absolute()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._state_path = self.data_dir / "state.json"
        self._backup_path = self.data_dir / "state.backup.json"
        self._load_warnings = []
        self._store = self._load()
        changed = False
        for batch in self._store["batches"].values():
            for bug in batch.get("bugs", []):
                if bug.get("status") == "submitting":
                    bug["status"] = "uncertain"
                    bug["reviewed"] = False
                    bug["error"] = "上次提交中断，是否已创建需要到禅道核对。请勿重复提交。"
                    bug["updated_at"] = _now()
                    self._history(batch, bug)
                    changed = True
        if changed or (self._load_warnings and not self._state_path.exists()):
            self._persist()

    @staticmethod
    def _empty_store():
        return {"version": 1, "active_batch": "", "batches": {}, "profiles": [],
                "active_profile": "", "default_settings": copy.deepcopy(DEFAULT_SETTINGS), "history": []}

    @staticmethod
    def _decode(raw):
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("不支持的数据文件版本")
        if not isinstance(value.get("batches"), dict):
            raise ValueError("数据文件缺少批次")
        if not isinstance(value.get("history", []), list) or not isinstance(value.get("profiles", []), list):
            raise ValueError("数据文件格式错误")
        for key, batch in value["batches"].items():
            if not isinstance(batch, dict) or not isinstance(batch.get("bugs"), list):
                raise ValueError("批次内容损坏")
            if not isinstance(batch.get("settings"), dict) or not isinstance(batch.get("active_ids"), list):
                raise ValueError("批次配置损坏")
            if any(not isinstance(bug, dict) or not isinstance(bug.get("id"), str) for bug in batch["bugs"]):
                raise ValueError("Bug 数据损坏")
            if batch.get("batch_key") != key:
                raise ValueError("批次索引损坏")
            if not isinstance(batch.get("root_dir"), str) or not isinstance(batch.get("warnings"), list):
                raise ValueError("批次目录或警告损坏")
            batch["settings"] = _settings(batch["settings"])
            identifiers = set()
            for bug in batch["bugs"]:
                if bug["id"] in identifiers or not isinstance(bug.get("folder"), str) or not isinstance(bug.get("original_title"), str):
                    raise ValueError("Bug 索引或目录损坏")
                identifiers.add(bug["id"])
                if any(not isinstance(bug.get(field), str) for field in TEXT_FIELDS):
                    raise ValueError("Bug 描述损坏")
                if not isinstance(bug.get("attachments"), list) or not isinstance(bug.get("excluded_attachments"), list):
                    raise ValueError("Bug 附件列表损坏")
                if not isinstance(bug.get("selected"), bool) or not isinstance(bug.get("reviewed"), bool):
                    raise ValueError("Bug 复核状态损坏")
                _settings(bug.get("overrides", {}), partial=True)
                bug["case_source"] = _case_source(bug.get("case_source", {}))
                for item in bug["attachments"]:
                    if (not isinstance(item, dict) or any(not isinstance(item.get(field), str) for field in ("id", "name", "path", "mime"))
                            or not isinstance(item.get("size"), int) or item["size"] < 0):
                        raise ValueError("附件记录损坏")
            if any(not isinstance(item, str) or item not in identifiers for item in batch["active_ids"]):
                raise ValueError("当前批次清单损坏")
        value.setdefault("active_batch", "")
        value.setdefault("profiles", [])
        value.setdefault("active_profile", "")
        value["default_settings"] = _settings(value.get("default_settings", {}))
        for profile in value["profiles"]:
            if not isinstance(profile, dict):
                raise ValueError("配置内容损坏")
            profile["settings"] = _settings(profile.get("settings", {}))
        value.setdefault("history", [])
        return value

    def _load(self):
        failure = None
        if self._state_path.exists():
            try:
                return self._decode(self._state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError) as exc:
                failure = exc
                preserved = self.data_dir / f"state.corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
                try:
                    shutil.copy2(self._state_path, preserved)
                except OSError as copy_error:
                    raise ValueError("本地数据损坏，且无法保留原文件。请先备份数据目录。") from copy_error
                self._load_warnings.append(f"本地数据文件损坏，原文件已保留为 {preserved.name}。")
        if self._backup_path.exists():
            try:
                recovered = self._decode(self._backup_path.read_text(encoding="utf-8"))
                self._load_warnings.append("已从最近一次备份恢复。请检查最近修改与禅道提交记录。")
                # Keep the intact backup until the next successful atomic save.
                self._write_atomic(self._state_path, json.dumps(recovered, ensure_ascii=False, indent=2))
                return recovered
            except (OSError, ValueError, TypeError):
                self._load_warnings.append("备份也无法读取；已保留原始数据文件，当前打开的是空工作区。")
        elif failure:
            self._load_warnings.append("未找到可恢复的备份；已保留损坏原件，当前打开的是空工作区。")
        return self._empty_store()

    @staticmethod
    def _write_atomic(path, text):
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix=".bugdesk-", suffix=".tmp", dir=str(path.parent))
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def _persist(self):
        raw = json.dumps(self._store, ensure_ascii=False, indent=2)
        if self._state_path.exists():
            try:
                previous = self._state_path.read_text(encoding="utf-8")
                self._decode(previous)
            except (OSError, ValueError, TypeError):
                previous = None
            if previous is not None:
                self._write_atomic(self._backup_path, previous)
        self._write_atomic(self._state_path, raw)

    def _batch(self):
        return self._store["batches"].get(self._store["active_batch"])

    def _ensure_not_submitting(self):
        if any(bug.get("status") == "submitting" for batch in self._store["batches"].values() for bug in batch["bugs"]):
            raise ValueError("正在提交 Bug，请等当前提交结束后切换目录或导入草稿。")

    @staticmethod
    def _status(bug):
        if bug.get("status") in LIFECYCLE_STATUSES:
            return bug["status"]
        if any(not str(bug.get(key, "")).strip() for key in ("title", "steps", "actual", "expected")):
            return "draft"
        return "ready" if bug.get("reviewed") else "needs_review"

    def state(self):
        with self._lock:
            batch = self._batch()
            if batch:
                result = {key: copy.deepcopy(batch.get(key)) for key in
                          ("root_dir", "batch_key", "scanned_at", "demo", "settings", "warnings")}
                active = set(batch.get("active_ids", []))
                result["bugs"] = [copy.deepcopy(bug) for bug in batch["bugs"] if bug["id"] in active]
                result["requires_rescan"] = bool(batch.get("requires_rescan"))
            else:
                result = {"root_dir": "", "batch_key": "", "scanned_at": "", "demo": False,
                          "settings": copy.deepcopy(self._store["default_settings"]), "bugs": [],
                          "warnings": [], "requires_rescan": False}
            for bug in result["bugs"]:
                bug["status"] = self._status(bug)
                bug["review_token"] = self._review_token(bug, result["settings"])
            result["warnings"] = list(dict.fromkeys(self._load_warnings + (result["warnings"] or [])))
            result.update(version=1, profiles=copy.deepcopy(self._store["profiles"]),
                          active_profile=self._store["active_profile"], history=copy.deepcopy(self._store["history"][-200:]))
            return result

    def batch_context(self):
        """Read batch identity for polling without copying drafts or hashing facts."""
        with self._lock:
            batch = self._batch()
            return {"batch_key": batch["batch_key"] if batch else "",
                    "requires_rescan": bool(batch and batch.get("requires_rescan"))}

    def get_settings(self):
        with self._lock:
            return copy.deepcopy(self._batch()["settings"] if self._batch() else self._store["default_settings"])

    def get_bug(self, bug_id):
        with self._lock:
            batch = self._batch()
            if batch and bug_id in batch["active_ids"]:
                for bug in batch["bugs"]:
                    if bug["id"] == bug_id:
                        result = copy.deepcopy(bug)
                        result["status"] = self._status(bug)
                        result["review_token"] = self._review_token(bug, batch["settings"])
                        return result
            raise ValueError("未找到这条 Bug，请重新选择。")

    @staticmethod
    def _new_bug(folder):
        return {"id": _hash(_identity(folder)), "folder": str(folder), "original_title": folder.name,
                "title": folder.name, "preconditions": "", "steps": "", "actual": "", "expected": "",
                "case_source": {},
                "overrides": {}, "attachments": [], "excluded_attachments": [], "selected": True,
                "reviewed": False, "status": "draft", "remote_id": None, "remote_url": "", "error": "",
                "upload_status": {}, "updated_at": _now()}

    def _attachments(self, folder, warnings):
        attachments = []
        pending = [folder]
        while pending:
            directory = pending.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda item: _natural(item.name))
            except OSError:
                warnings.append(f"无法读取附件目录：{directory}")
                continue
            for path in children:
                try:
                    info = path.lstat()
                    if _is_link(path, info):
                        warnings.append(f"已跳过链接或映射目录：{path}")
                        continue
                    if _is_temporary(path, info):
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path)
                    elif stat.S_ISREG(info.st_mode):
                        relative = path.relative_to(folder).as_posix()
                        attachment = {"id": _hash(relative.casefold()), "name": relative,
                                      "path": str(path.absolute()), "size": info.st_size,
                                      "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                                      "mtime_ns": info.st_mtime_ns}
                        attachments.append(attachment)
                        if info.st_size > MAX_ATTACHMENT_SIZE:
                            warnings.append(f"附件超过 500 MB，请取消勾选或压缩后重扫：{folder.name} / {relative}")
                except OSError:
                    warnings.append(f"无法读取附件：{path}")
        return sorted(attachments, key=lambda item: _natural(item["name"]))

    def scan(self, path, demo=False):
        if not isinstance(path, str) or not path.strip():
            raise ValueError("请先选择一个日期目录。")
        root = Path(path).absolute()
        with self._lock:
            self._ensure_not_submitting()
            try:
                root_info = root.lstat()
                if _is_link(root, root_info):
                    raise ValueError("请选择普通文件夹；链接或映射目录无法作为扫描目录。")
                if not stat.S_ISDIR(root_info.st_mode):
                    raise ValueError("选择的路径不是文件夹。")
                children = sorted(root.iterdir(), key=lambda item: _natural(item.name))
            except OSError as exc:
                raise ValueError("无法读取这个目录，请检查路径、磁盘和访问权限。") from exc
            key = _hash(_identity(root))
            demo_root = _identity(self.data_dir / "demo")
            inferred_demo = _identity(root) == demo_root or _identity(root).startswith(demo_root + os.sep)
            batch = self._store["batches"].get(key)
            if batch is None:
                batch = {"root_dir": str(root), "batch_key": key, "scanned_at": "", "demo": bool(demo or inferred_demo),
                         "settings": copy.deepcopy(self._store["default_settings"]), "bugs": [],
                         "active_ids": [], "warnings": [], "requires_rescan": False}
            # A imported or previously marked demonstration cannot be made real by rescanning.
            batch["demo"] = bool(batch.get("demo") or demo or inferred_demo)
            old_bugs = {_identity(bug["folder"]): bug for bug in batch["bugs"]}
            active_ids = []
            warnings = []
            for folder in children:
                try:
                    info = folder.lstat()
                    if _is_link(folder, info):
                        warnings.append(f"已跳过链接或映射目录：{folder.name}")
                        continue
                    if _is_temporary(folder, info) or not stat.S_ISDIR(info.st_mode):
                        continue
                    identity = _identity(folder)
                    bug = old_bugs.get(identity)
                    if bug is None:
                        bug = self._new_bug(folder)
                        batch["bugs"].append(bug)
                    previous = {item["id"]: item for item in bug.get("attachments", [])}
                    attachments = self._attachments(folder, warnings)
                    current = {item["id"]: item for item in attachments}
                    lost = set(previous) - set(current)
                    for missing in sorted(lost):
                        warnings.append(f"原附件已不存在：{folder.name} / {previous[missing]['name']}")
                    old_fingerprint = [(item["id"], item["size"], item.get("mtime_ns")) for item in bug.get("attachments", [])]
                    new_fingerprint = [(item["id"], item["size"], item.get("mtime_ns")) for item in attachments]
                    if old_fingerprint != new_fingerprint:
                        bug["reviewed"] = False
                        if bug.get("status") not in LIFECYCLE_STATUSES:
                            bug["status"] = "draft"
                    bug["attachments"] = attachments
                    bug["folder"] = str(folder)
                    bug["excluded_attachments"] = [item for item in bug.get("excluded_attachments", []) if item in current]
                    active_ids.append(bug["id"])
                except OSError:
                    warnings.append(f"无法读取 Bug 文件夹：{folder.name}")
            for bug in batch["bugs"]:
                if bug["id"] not in active_ids:
                    warnings.append(f"Bug 文件夹已不在当前目录中，草稿仍保留：{bug['original_title']}")
            if not active_ids:
                warnings.append("没有找到 Bug 子文件夹。请选日期目录，每个 Bug 使用一个子文件夹。")
            batch.update(root_dir=str(root), scanned_at=_now(), active_ids=active_ids,
                         warnings=warnings, requires_rescan=False)
            self._store["batches"][key] = batch
            self._store["active_batch"] = key
            self._persist()
            return self.state()

    @staticmethod
    def _case_locked(bug):
        return (bug.get("status") in {"locked", "submitting", "submitted", "uncertain", "partial"}
                or bug.get("remote_id") not in (None, "") or bool(bug.get("locked")))

    def preview_case_links(self, rows):
        """Suggest only an unambiguous exact ID link to a current editable draft."""
        cleaned = _case_rows(rows)
        with self._lock:
            batch = self._batch()
            active = set(batch["active_ids"]) if batch else set()
            candidates = [bug for bug in batch["bugs"] if bug["id"] in active and not self._case_locked(bug)] if batch else []
            counts = {}
            for row in cleaned:
                case_id = (row.get("case_id") or "").strip()
                if case_id:
                    counts[case_id] = counts.get(case_id, 0) + 1
            for row in cleaned:
                row["suggested_bug_id"] = ""
                case_id = (row.get("case_id") or "").strip()
                if not batch or batch.get("requires_rescan"):
                    row["match_reason"] = "请先扫描当前 Bug 文件夹。"
                elif not case_id:
                    row["match_reason"] = "没有用例 ID，请手动关联 Bug。"
                elif counts[case_id] > 1:
                    row["match_reason"] = "粘贴内容中用例 ID 重复，请手动关联 Bug。"
                else:
                    token = re.compile(r"(?<![A-Za-z0-9])" + re.escape(case_id) + r"(?![A-Za-z0-9])")
                    matches = []
                    for bug in candidates:
                        remembered = bug.get("case_source", {}).get("case_id", "").strip()
                        if remembered:
                            if remembered == case_id:
                                matches.append((bug, "按已关联的用例 ID 匹配。"))
                        elif any(token.search(bug.get(field, "")) for field in ("original_title", "title")):
                            matches.append((bug, "按 Bug 标题中的完整用例 ID 匹配。"))
                    if len(matches) == 1:
                        row["suggested_bug_id"] = matches[0][0]["id"]
                        row["match_reason"] = matches[0][1]
                    elif len(matches) > 1:
                        row["match_reason"] = "多条 Bug 使用同一个用例 ID，请手动关联 Bug。"
                    else:
                        row["match_reason"] = "没有匹配到完整用例 ID，请手动关联 Bug。"
            return cleaned

    def apply_cases(self, rows, assignments, *, batch_key):
        """Apply explicitly reviewed testcase facts, without changing evidence or titles."""
        cleaned = _case_rows(rows)
        if not isinstance(assignments, list) or not assignments or len(assignments) > MAX_CASE_ROWS:
            raise ValueError("请选择需要填入的用例，一次最多关联 300 条 Bug。")
        indexed_rows = {row["row_id"]: row for row in cleaned}
        with self._lock:
            batch = self._batch()
            if not batch or not isinstance(batch_key, str) or batch_key != batch["batch_key"]:
                raise ValueError("当前 Bug 批次已经切换，请重新打开粘贴预览。")
            if batch.get("requires_rescan"):
                raise ValueError("导入的草稿需要先扫描本机 Bug 文件夹后再关联用例。")
            replacement = copy.deepcopy(self._store)
            edited_batch = replacement["batches"][batch_key]
            active = set(edited_batch["active_ids"])
            bugs = {bug["id"]: bug for bug in edited_batch["bugs"] if bug["id"] in active}
            seen = set()
            applied = unchanged = skipped_fields = 0
            for assignment in assignments:
                if not isinstance(assignment, dict):
                    raise ValueError("用例关联格式不正确。")
                row_id, bug_id = assignment.get("row_id"), assignment.get("bug_id")
                if not isinstance(row_id, str) or row_id not in indexed_rows:
                    raise ValueError("用例行已经变化，请重新解析粘贴内容。")
                if not isinstance(bug_id, str) or bug_id not in bugs:
                    raise ValueError("关联的 Bug 不在当前批次中，请重新打开粘贴预览。")
                if bug_id in seen:
                    raise ValueError("一条 Bug 只能填入一条用例，请检查重复关联。")
                seen.add(bug_id)
                bug = bugs[bug_id]
                if self._case_locked(bug):
                    raise ValueError("这条 Bug 已提交、正在提交或等待核对，不能填入用例。")
                if assignment.get("review_token") != self._review_token(bug, edited_batch["settings"]):
                    raise ValueError("这条 Bug 的内容已变化，请重新打开粘贴预览，确认后再填入。")
                mode = assignment.get("mode", "fill")
                if not isinstance(mode, str) or mode not in {"fill", "replace"}:
                    raise ValueError("请选择仅补空白或替换描述。")
                row = indexed_rows[row_id]
                changed = False
                for field in CASE_FACT_FIELDS:
                    value = row.get(field)
                    if value is None or not value.strip():
                        continue
                    current = bug.get(field, "")
                    if mode == "fill" and current.strip():
                        if value != current:
                            skipped_fields += 1
                        continue
                    if value != current:
                        bug[field] = value
                        changed = True
                source = _case_source({"case_id": row.get("case_id") or "", "case_title": row.get("title") or "",
                                       "group": row.get("group") or "", "tester": row.get("tester") or "",
                                       "date": row.get("date") or ""})
                if source != bug.get("case_source", {}):
                    bug["case_source"] = source
                    changed = True
                if changed:
                    bug["reviewed"] = False
                    # Preserve a prior failed attempt and its journal; importing
                    # testcase facts cannot rewrite a submission record.
                    bug["updated_at"] = _now()
                    applied += 1
                else:
                    unchanged += 1
            if applied:
                original = self._store
                self._store = replacement
                try:
                    self._persist()
                except BaseException:
                    self._store = original
                    raise
            return {"state": self.state(), "applied": applied, "unchanged": unchanged,
                    "skipped_fields": skipped_fields}

    def save(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("保存内容格式不正确。")
        with self._lock:
            # Validate the complete mutation on a copy so an invalid later field
            # cannot leave half of a draft changed in memory.
            replacement = copy.deepcopy(self._store)
            batch = replacement["batches"].get(replacement["active_batch"])
            settings = batch["settings"] if batch else replacement["default_settings"]
            settings_changed = False
            if "settings" in payload:
                new_settings = copy.deepcopy(settings)
                new_settings.update(_settings(payload["settings"], partial=True))
                if new_settings != settings:
                    settings_changed = True
                    if batch and any(bug.get("status") == "submitting" for bug in batch["bugs"]):
                        raise ValueError("有 Bug 正在提交，请等提交结束后修改公共信息。")
                    settings.clear()
                    settings.update(new_settings)
                    if not batch or not batch.get("demo"):
                        replacement["default_settings"] = copy.deepcopy(new_settings)
                    if batch:
                        for bug in batch["bugs"]:
                            bug["reviewed"] = False
                            bug["updated_at"] = _now()
            if "profiles" in payload:
                profiles = payload["profiles"]
                if not isinstance(profiles, list) or len(profiles) > 100:
                    raise ValueError("配置列表格式不正确，最多保存 100 套配置。")
                cleaned = []
                seen = set()
                for profile in profiles:
                    if not isinstance(profile, dict):
                        raise ValueError("配置内容格式不正确。")
                    identifier = str(profile.get("id", "")).strip()
                    name = str(profile.get("name", "")).strip()
                    if not identifier or not name or identifier in seen:
                        raise ValueError("每套配置需要唯一 ID 和名称。")
                    seen.add(identifier)
                    cleaned.append({"id": identifier, "name": name, "settings": _settings(profile.get("settings", {}))})
                replacement["profiles"] = cleaned
                if replacement["active_profile"] not in seen:
                    replacement["active_profile"] = ""
            if "active_profile" in payload:
                identifier = payload["active_profile"]
                if not isinstance(identifier, str):
                    raise ValueError("配置选择格式不正确。")
                if identifier and identifier not in {item["id"] for item in replacement["profiles"]}:
                    raise ValueError("这套配置不存在，请重新选择。")
                replacement["active_profile"] = identifier
            if "bugs" in payload:
                if not isinstance(payload["bugs"], list):
                    raise ValueError("Bug 编辑列表格式不正确。")
                if not batch:
                    raise ValueError("请先扫描 Bug 文件夹。")
                indexed = {bug["id"]: bug for bug in batch["bugs"] if bug["id"] in batch["active_ids"]}
                seen = set()
                for patch in payload["bugs"]:
                    if not isinstance(patch, dict) or patch.get("id") not in indexed:
                        raise ValueError("保存的 Bug 已不在当前批次，请重新扫描。")
                    if patch["id"] in seen:
                        raise ValueError("同一条 Bug 不应重复出现在保存列表中。")
                    seen.add(patch["id"])
                    bug = indexed[patch["id"]]
                    if bug.get("status") == "submitting":
                        raise ValueError("这条 Bug 正在提交，请等提交结束后编辑。")
                    if self._case_locked(bug) and any(field in patch for field in EDITABLE_FIELDS - {"selected"}):
                        raise ValueError("这条 Bug 已提交、等待核对或已锁定，不能修改描述、单独设置、附件或审核状态。请刷新查看最新记录。")
                    changed = False
                    for field in EDITABLE_FIELDS - {"reviewed"}:
                        if field not in patch:
                            continue
                        value = patch[field]
                        if field in TEXT_FIELDS:
                            if not isinstance(value, str) or len(value) > 100000:
                                raise ValueError("Bug 描述必须是文字，且不能超过 100,000 字符。")
                        elif field == "overrides":
                            value = _settings(value, partial=True)
                        elif field == "excluded_attachments":
                            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                                raise ValueError("附件选择格式不正确。")
                            available = {item["id"] for item in bug["attachments"]}
                            if any(item not in available for item in value):
                                raise ValueError("附件已变化，请重新扫描后选择。")
                            value = list(dict.fromkeys(value))
                        elif field == "selected" and not isinstance(value, bool):
                            raise ValueError("Bug 选择状态格式不正确。")
                        if bug.get(field) != value:
                            bug[field] = copy.deepcopy(value)
                            if field != "selected":
                                changed = True
                    if changed:
                        bug["reviewed"] = False
                        if bug.get("status") == "failed":
                            bug["status"] = "draft"
                            bug["error"] = ""
                    if "reviewed" in patch:
                        if not isinstance(patch["reviewed"], bool):
                            raise ValueError("复核状态格式不正确。")
                        if patch["reviewed"]:
                            if ("review_token" in patch
                                    and patch["review_token"] != self._review_token(bug, batch["settings"])):
                                raise ValueError("这条 Bug 的描述、公共信息或附件已变化，请重新打开复核预览后确认。")
                            if any(not str(bug.get(field, "")).strip() for field in ("title", "steps", "actual", "expected")):
                                raise ValueError(f"「{bug['title']}」需要补齐标题、步骤、实际结果和预期结果后再复核。")
                            if batch.get("requires_rescan"):
                                raise ValueError("导入的草稿需要先重新扫描本机目录后再复核。")
                        # Full editor patches may still carry the old review flag.
                        # Review the saved final draft in a separate confirmation.
                        bug["reviewed"] = patch["reviewed"] and not changed and not settings_changed
                    bug["updated_at"] = _now()
            self._store = replacement
            self._persist()
            return self.state()

    def _effective(self, bug, shared_settings=None):
        settings = copy.deepcopy(self._batch()["settings"] if shared_settings is None else shared_settings)
        settings.update(copy.deepcopy(bug.get("overrides", {})))
        result = copy.deepcopy(bug)
        prefix = settings.get("title_prefix", "").strip()
        if prefix and not result["title"].startswith(prefix):
            result["title"] = prefix + result["title"]
        parts = [value.strip() for value in (settings.get("preconditions", ""), bug.get("preconditions", "")) if value.strip()]
        result["preconditions"] = "\n\n".join(dict.fromkeys(parts))
        result["status"] = self._status(bug)
        return result, settings

    def _review_token(self, bug, shared_settings):
        effective_bug, settings = self._effective(bug, shared_settings)
        excluded = set(bug.get("excluded_attachments", []))
        attachments = [{field: item.get(field) for field in ("id", "name", "size", "mtime_ns")}
                       for item in bug.get("attachments", []) if item["id"] not in excluded]
        attachments.sort(key=lambda item: (item["id"], item["name"]))
        material = {"id": bug["id"], "settings": settings, "attachments": attachments}
        material["case_source"] = copy.deepcopy(bug.get("case_source", {}))
        material.update({field: effective_bug.get(field, "") for field in TEXT_FIELDS})
        encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def validate_submission(self, ids):
        with self._lock:
            batch = self._batch()
            if not batch:
                raise ValueError("请先扫描 Bug 文件夹。")
            if batch.get("demo"):
                raise ValueError("演示数据只能体验和导出，请扫描自己的 Bug 目录后提交。")
            if batch.get("requires_rescan"):
                raise ValueError("导入的草稿需要先重新扫描本机目录，确认附件后再提交。")
            if (not isinstance(ids, list) or not ids or any(not isinstance(item, str) for item in ids)
                    or len(ids) != len(set(ids))):
                raise ValueError("请选择至少一条 Bug，且不要重复选择。")
            results = []
            for identifier in ids:
                bug = self.get_bug(identifier)
                title = bug["title"] or bug["original_title"]
                if bug.get("remote_id") or bug.get("status") in {"submitted", "partial"}:
                    raise ValueError(f"「{title}」已在禅道创建，不能重复提交。")
                if bug.get("status") in {"uncertain", "submitting"}:
                    raise ValueError(f"「{title}」提交结果尚未确认，请先到禅道核对，不能重复提交。")
                missing = [label for key, label in (("title", "标题"), ("steps", "复现步骤"), ("actual", "实际结果"), ("expected", "预期结果"))
                           if not str(bug.get(key, "")).strip()]
                if missing:
                    raise ValueError(f"「{title}」还缺少：{'、'.join(missing)}。")
                if not bug.get("reviewed"):
                    raise ValueError(f"「{title}」尚未复核，请先确认描述和附件。")
                effective_bug, settings = self._effective(bug)
                if not settings.get("product", "").strip():
                    raise ValueError("请先在公共信息中选择所属产品。")
                if not settings.get("openedBuild"):
                    raise ValueError("请先在公共信息中选择影响版本。")
                try:
                    folder = Path(bug["folder"])
                    folder_info = folder.lstat()
                    root_info = Path(batch["root_dir"]).lstat()
                    if (not stat.S_ISDIR(folder_info.st_mode) or _is_link(folder, folder_info)
                            or not stat.S_ISDIR(root_info.st_mode) or _is_link(Path(batch["root_dir"]), root_info)):
                        raise OSError("Bug 目录已变化")
                except OSError as exc:
                    raise ValueError(f"「{title}」的文件夹已不存在或变成链接，请重新扫描。") from exc
                excluded = set(bug.get("excluded_attachments", []))
                for attachment in bug["attachments"]:
                    if attachment["id"] in excluded:
                        continue
                    evidence = Path(attachment["path"])
                    try:
                        info = evidence.lstat()
                        parent = evidence.parent
                        trusted_folder = _identity(bug["folder"])
                        while _identity(parent) != trusted_folder:
                            if _is_link(parent):
                                raise OSError("附件父目录已变成链接")
                            next_parent = parent.parent
                            if next_parent == parent:
                                raise OSError("附件已超出 Bug 目录")
                            parent = next_parent
                        if _is_link(parent) or _is_link(evidence, info) or not stat.S_ISREG(info.st_mode):
                            raise OSError("附件不再是普通文件")
                    except OSError as exc:
                        raise ValueError(f"「{title}」的附件已不存在或无法读取，请重新扫描：{attachment['name']}") from exc
                    if info.st_size != attachment["size"] or info.st_mtime_ns != attachment.get("mtime_ns", info.st_mtime_ns):
                        raise ValueError(f"「{title}」的附件已经变化，请重新扫描并复核：{attachment['name']}")
                    if info.st_size > MAX_ATTACHMENT_SIZE:
                        raise ValueError(f"附件超过 500 MB，请取消勾选或压缩：{attachment['name']}")
                results.append((effective_bug, settings))
            return results

    def _history(self, batch, bug):
        self._store["history"].append({"time": _now(), "batch_key": batch["batch_key"], "root_dir": batch["root_dir"],
                                       "bug_id": bug["id"], "title": bug["title"], "status": bug["status"],
                                       "remote_id": bug.get("remote_id"), "remote_url": bug.get("remote_url", ""),
                                       "error": bug.get("error", ""), "upload_status": copy.deepcopy(bug.get("upload_status", {}))})
        self._store["history"] = self._store["history"][-2000:]

    def set_submission(self, bug_id, **fields):
        allowed = {"status", "remote_id", "remote_url", "error", "upload_status"}
        if set(fields) - allowed:
            raise ValueError("提交结果包含不支持的字段。")
        with self._lock:
            snapshot = self.get_bug(bug_id)
            batch = self._batch()
            bug = next(item for item in batch["bugs"] if item["id"] == bug_id)
            status = fields.get("status", snapshot["status"])
            if status not in LIFECYCLE_STATUSES:
                raise ValueError("提交状态不正确。")
            if status == "submitting":
                self.validate_submission([bug_id])
            if snapshot.get("remote_id") and fields.get("remote_id", snapshot["remote_id"]) != snapshot["remote_id"]:
                raise ValueError("已创建的 Bug 编号不能被清除或替换。")
            if snapshot.get("status") in TERMINAL_STATUSES and status == "failed":
                raise ValueError("已创建或结果不明确的 Bug 不能被标记为可重试失败。")
            remote_id = fields.get("remote_id", snapshot.get("remote_id"))
            if status in {"submitted", "partial"} and not remote_id:
                raise ValueError("提交成功需要确认禅道返回的 Bug 编号。")
            if remote_id is not None and (not isinstance(remote_id, (str, int)) or isinstance(remote_id, bool)):
                raise ValueError("禅道 Bug 编号格式不正确。")
            if any(not isinstance(fields[key], str) for key in ("remote_url", "error") if key in fields):
                raise ValueError("提交信息格式不正确。")
            if "upload_status" in fields and not isinstance(fields["upload_status"], dict):
                raise ValueError("附件上传状态格式不正确。")
            bug.update(copy.deepcopy(fields))
            bug["status"] = status
            bug["updated_at"] = _now()
            self._history(batch, bug)
            self._persist()
            return self.state()

    def reconcile_submission(self, bug_id, resolution, remote_id=None, remote_url=""):
        """Record the user's explicit verification of an ambiguous company result.

        This does not perform a network request. A known created ID is immutable;
        only an ambiguous result without an ID may be confirmed as not created.
        """
        with self._lock:
            snapshot = self.get_bug(bug_id)
            if snapshot["status"] not in {"uncertain", "partial"}:
                raise ValueError("只有待核对或附件待处理的 Bug 可以记录核对结果。")
            if resolution not in {"created", "not_created"}:
                raise ValueError("请选择已创建或确认未创建。")
            if not isinstance(remote_url, str):
                raise ValueError("禅道链接格式不正确。")
            batch = self._batch()
            bug = next(item for item in batch["bugs"] if item["id"] == bug_id)
            if resolution == "not_created":
                if snapshot.get("remote_id"):
                    raise ValueError("这条 Bug 已有禅道编号，不能记录为未创建。请处理现有 Bug。")
                bug.update(status="failed", reviewed=False,
                           error="已由用户到禅道核对并确认未创建。重新复核后可再次提交。")
            else:
                identifier = remote_id if remote_id is not None else snapshot.get("remote_id")
                if isinstance(identifier, bool) or not str(identifier or "").isdigit() or int(identifier) <= 0:
                    raise ValueError("请填写禅道页面上的正整数 Bug 编号。")
                if snapshot.get("remote_id") and str(identifier) != str(snapshot["remote_id"]):
                    raise ValueError("核对编号与本地已确认的禅道编号不同，不能替换。")
                bug.update(status="submitted", remote_id=identifier,
                           remote_url=remote_url or snapshot.get("remote_url", ""), error="")
            bug["updated_at"] = _now()
            self._history(batch, bug)
            self._persist()
            return self.state()

    def create_demo(self):
        with self._lock:
            root = self.data_dir / "demo"
            examples = [
                ("1. 搜索无结果时未显示空状态", "打开搜索页面，输入“示例不存在的关键词”，点击搜索。", "结果区域空白，未显示任何提示。", "显示“未找到相关内容”，并提供重新搜索入口。"),
                ("2. 表单保存失败后丢失已填内容", "进入示例资料表单，填写姓名和备注；在断网状态下点击保存。", "出现保存失败提示，同时已填的姓名和备注被清空。", "提示保存失败并保留填写内容，方便恢复网络后重试。"),
                ("10. 视频暂停后进度条仍在前进", "播放示例视频，等待 5 秒后点击暂停，观察进度条。", "画面暂停，但进度条继续前进。", "暂停时画面和进度条同时停止。"),
            ]
            for index, (title, _, _, _) in enumerate(examples, start=1):
                folder = root / title
                folder.mkdir(parents=True, exist_ok=True)
                screenshot = folder / "示例截图.svg"
                if not screenshot.exists():
                    content = f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="560" viewBox="0 0 960 560"><rect width="960" height="560" fill="#edf5f5"/><rect x="40" y="40" width="880" height="480" rx="24" fill="white"/><rect x="40" y="40" width="880" height="76" rx="24" fill="#17334d"/><text x="76" y="90" font-family="Microsoft YaHei, sans-serif" font-size="26" fill="white">BugDesk 示例截图 · {index}</text><text x="76" y="176" font-family="Microsoft YaHei, sans-serif" font-size="25" fill="#17334d">{title}</text><rect x="76" y="210" width="808" height="180" rx="12" fill="#f2f6fa"/><text x="110" y="282" font-family="Microsoft YaHei, sans-serif" font-size="22" fill="#4e6578">这是演示附件，用于体验预览和批量复核。</text><text x="110" y="325" font-family="Microsoft YaHei, sans-serif" font-size="20" fill="#4e6578">示例内容与任何真实产品无关。</text><text x="76" y="464" font-family="Microsoft YaHei, sans-serif" font-size="20" fill="#0a877a">请扫描自己的日期目录，开始整理真实 Bug。</text></svg>'''
                    screenshot.write_text(content, encoding="utf-8")
            result = self.scan(str(root), demo=True)
            batch = self._batch()
            for bug in batch["bugs"]:
                example = next((item for item in examples if item[0] == bug["original_title"]), None)
                if example and not bug["steps"]:
                    bug.update(preconditions="【演示事实】以下内容是工具自带示例，请勿提交到公司禅道。",
                               steps=example[1], actual=example[2], expected=example[3], reviewed=False)
            if not batch["settings"].get("product_name"):
                batch["settings"].update(product_name="示例产品", project_name="示例项目", execution_name="示例测试", build_name="示例版本")
            self._persist()
            return self.state()

    @staticmethod
    def _description(bug):
        blocks = []
        if bug.get("preconditions", "").strip():
            blocks.append("[前置条件]\n" + bug["preconditions"].strip())
        for field, label in (("steps", "步骤"), ("actual", "结果"), ("expected", "期望")):
            blocks.append(f"[{label}]\n{bug.get(field, '').strip()}")
        return "\n\n".join(blocks)

    def export(self, format):
        if format not in {"markdown", "json", "csv"}:
            raise ValueError("请选择 Markdown、JSON 或 CSV 导出格式。")
        with self._lock:
            state = self.state()
            if not state["bugs"]:
                raise ValueError("当前没有可导出的 Bug，请先扫描目录。")
            directory = self.data_dir / "exports"
            directory.mkdir(parents=True, exist_ok=True)
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(state["root_dir"]).name)[:60] or "Bug"
            extension = {"markdown": "md", "json": "json", "csv": "csv"}[format]
            path = directory / f"BugDesk-{stem}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.{extension}"
            if format == "json":
                content = json.dumps({"format": "bugdesk-backup", "version": 1, "exported_at": _now(), "state": state}, ensure_ascii=False, indent=2)
            elif format == "markdown":
                lines = ["# BugDesk · Bug 清单", "", f"日期目录：{state['root_dir']}", f"导出时间：{_now()}", ""]
                if state["demo"]:
                    lines.extend(["> 演示数据：以下问题和附件均为工具示例。", ""])
                for source in state["bugs"]:
                    bug, settings = self._effective(source)
                    lines.extend([f"## {bug['title']}", "", f"状态：{bug['status']}",
                                  f"产品：{settings.get('product_name') or settings.get('product', '')}",
                                  f"反馈者：{settings.get('feedbackBy', '')}",
                                  f"影响版本：{settings.get('build_name') or ', '.join(settings.get('openedBuild', []))}", "",
                                  self._description(bug), "", "附件："])
                    excluded = set(bug["excluded_attachments"])
                    lines.extend([f"- {item['name']}（{item['size']} 字节{'，已排除' if item['id'] in excluded else ''}）" for item in bug["attachments"]] or ["- 无"])
                    if bug.get("remote_id"):
                        lines.extend(["", f"禅道 Bug：{bug['remote_id']}", f"禅道链接：{bug.get('remote_url', '')}"])
                    lines.append("")
                content = "\n".join(lines)
            else:
                buffer = io.StringIO(newline="")
                writer = csv.writer(buffer)
                writer.writerow(["标题", "前置条件", "复现步骤", "实际结果", "预期结果", "产品", "项目", "执行", "影响版本", "指派人", "反馈者", "严重程度", "优先级", "概率", "状态", "附件", "禅道编号", "禅道链接"])
                for source in state["bugs"]:
                    bug, settings = self._effective(source)
                    excluded = set(bug["excluded_attachments"])
                    values = [bug["title"], bug.get("preconditions", ""), bug["steps"], bug["actual"], bug["expected"],
                              settings.get("product_name") or settings["product"], settings.get("project_name") or settings["project"],
                              settings.get("execution_name") or settings["execution"], settings.get("build_name") or ", ".join(settings["openedBuild"]),
                              settings.get("assignee_name") or settings["assignedTo"], settings.get("feedbackBy", ""), settings["severity"], settings["pri"], settings["probability"],
                              bug["status"], "\n".join(item["name"] for item in bug["attachments"] if item["id"] not in excluded),
                              bug.get("remote_id"), bug.get("remote_url", "")]
                    writer.writerow([_csv_safe(item) for item in values])
                content = "\ufeff" + buffer.getvalue()
            self._write_atomic(path, content)
            return str(path.absolute())

    def import_backup(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("请选择 BugDesk 导出的 JSON 文件。")
        source = payload.get("state", payload)
        if payload.get("format") not in (None, "bugdesk-backup") or not isinstance(source, dict) or source.get("version") != 1:
            raise ValueError("这不是支持的 BugDesk 备份文件。")
        root_text = source.get("root_dir")
        if not isinstance(root_text, str) or not root_text.strip() or "\x00" in root_text:
            raise ValueError("备份缺少日期目录。")
        source_bugs = source.get("bugs")
        if not isinstance(source_bugs, list) or len(source_bugs) > 10000:
            raise ValueError("备份的 Bug 列表格式不正确。")
        with self._lock:
            self._ensure_not_submitting()
            imported_profiles = copy.deepcopy(self._store["profiles"])
            if "profiles" in source:
                profiles = source["profiles"]
                if not isinstance(profiles, list) or len(profiles) > 100:
                    raise ValueError("备份中的配置列表格式不正确。")
                profile_map = {item["id"]: item for item in imported_profiles}
                seen_profile_ids = set()
                for profile in profiles:
                    if not isinstance(profile, dict):
                        raise ValueError("备份中的配置格式不正确。")
                    identifier = profile.get("id")
                    name = profile.get("name")
                    if (not isinstance(identifier, str) or not identifier.strip() or not isinstance(name, str)
                            or not name.strip() or identifier in seen_profile_ids):
                        raise ValueError("备份中的配置需要唯一 ID 和名称。")
                    seen_profile_ids.add(identifier)
                    profile_map[identifier] = {"id": identifier, "name": name, "settings": _settings(profile.get("settings", {}))}
                imported_profiles = list(profile_map.values())
            imported_history = copy.deepcopy(self._store["history"])
            if "history" in source:
                history = source["history"]
                if not isinstance(history, list) or len(history) > 2000:
                    raise ValueError("备份中的提交历史格式不正确。")
                known_entries = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in imported_history}
                for item in history:
                    if not isinstance(item, dict) or any(not isinstance(item.get(field), str) for field in ("time", "batch_key", "bug_id", "title", "status")):
                        raise ValueError("备份中的提交历史记录损坏。")
                    encoded = json.dumps(item, sort_keys=True, ensure_ascii=False)
                    if encoded not in known_entries:
                        imported_history.append(copy.deepcopy(item))
                        known_entries.add(encoded)
            root = Path(root_text).absolute()
            key = _hash(_identity(root))
            batch = copy.deepcopy(self._store["batches"].get(key))
            if batch is None:
                batch = {"root_dir": str(root), "batch_key": key, "scanned_at": "", "demo": bool(source.get("demo")),
                         "settings": _settings(source.get("settings", {})), "bugs": [], "active_ids": [], "warnings": []}
            else:
                batch["settings"] = _settings(source.get("settings", {}))
            existing = {_identity(bug["folder"]): bug for bug in batch["bugs"]}
            active = []
            seen = set()
            for item in source_bugs:
                if not isinstance(item, dict):
                    raise ValueError("备份包含损坏的 Bug。")
                name = item.get("original_title")
                if (not isinstance(name, str) or not name or name in {".", ".."}
                        or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)):
                    raise ValueError("备份包含不安全的 Bug 文件夹名称。")
                folder = root / name
                identity = _identity(folder)
                if identity in seen:
                    raise ValueError("备份包含重复的 Bug 文件夹。")
                seen.add(identity)
                bug = self._new_bug(folder)
                for field in TEXT_FIELDS:
                    text = item.get(field, "")
                    if not isinstance(text, str) or len(text) > 100000:
                        raise ValueError("备份中的 Bug 描述格式不正确。")
                    bug[field] = text
                bug["overrides"] = _settings(item.get("overrides", {}), partial=True)
                bug["case_source"] = _case_source(item.get("case_source", {}))
                bug["selected"] = item.get("selected", True) is not False
                exclusions = item.get("excluded_attachments", [])
                if not isinstance(exclusions, list) or any(not isinstance(entry, str) for entry in exclusions):
                    raise ValueError("备份中的附件选择格式不正确。")
                bug["excluded_attachments"] = list(dict.fromkeys(exclusions))
                status = item.get("status", "draft")
                if status in LIFECYCLE_STATUSES:
                    bug["status"] = "uncertain" if status == "submitting" else status
                remote_id = item.get("remote_id")
                if remote_id is not None and (not isinstance(remote_id, (str, int)) or isinstance(remote_id, bool)):
                    raise ValueError("备份中的禅道编号格式不正确。")
                bug["remote_id"] = remote_id
                for field in ("remote_url", "error"):
                    if not isinstance(item.get(field, ""), str):
                        raise ValueError("备份中的提交记录格式不正确。")
                    bug[field] = item.get(field, "")
                if isinstance(item.get("upload_status"), dict):
                    bug["upload_status"] = copy.deepcopy(item["upload_status"])
                # Never downgrade a locally known submission by importing an old draft.
                known = existing.get(identity)
                if known and (known.get("remote_id") or known.get("status") in TERMINAL_STATUSES):
                    for field in ("status", "remote_id", "remote_url", "error", "upload_status", "case_source"):
                        bug[field] = copy.deepcopy(known.get(field))
                existing[identity] = bug
                active.append(bug["id"])
            batch.update(bugs=list(existing.values()), active_ids=active, requires_rescan=True,
                         demo=bool(batch.get("demo") or source.get("demo")),
                         warnings=["已导入草稿。附件路径未导入，请重新扫描对应的本机日期目录，再确认描述和附件。"])
            self._store["batches"][key] = batch
            self._store["active_batch"] = key
            if not batch.get("demo"):
                self._store["default_settings"] = copy.deepcopy(batch["settings"])
            self._store["profiles"] = imported_profiles
            self._store["history"] = imported_history[-2000:]
            if source.get("active_profile") in {item["id"] for item in imported_profiles}:
                self._store["active_profile"] = source["active_profile"]
            self._persist()
            return self.state()
