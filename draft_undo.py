"""One local WorkBuddy import transaction, committed with the draft store.

Only the four facts and bounded testcase provenance are reversible.  The
remaining draft content is hashed for conflict detection, never snapshotted.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path


STORE_KEY = "last_workbuddy_import"
FACT_FIELDS = ("preconditions", "steps", "actual", "expected")
SOURCE_LIMITS = {"case_id": 200, "case_title": 1000, "group": 2000, "tester": 200, "date": 100}
MAX_TARGETS = 300
MAX_FACT = 100000
_HEX_32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")


def _text(value, limit):
    return isinstance(value, str) and len(value) <= limit and "\x00" not in value


def _source(value):
    return (isinstance(value, dict) and not set(value) - SOURCE_LIMITS.keys()
            and all(_text(text, SOURCE_LIMITS[key]) and "\x00" not in text
                    for key, text in value.items()))


def validate_record(value):
    """Discard a malformed optional journal without losing otherwise valid drafts.

    Return the original validated object; neither callers nor this function
    expose it in public state.  Existing stores need no migration.
    """
    if (not isinstance(value, dict) or set(value) != {"schema", "transaction_id", "batch_key", "items"}
            or type(value.get("schema")) is not int or value["schema"] != 1
            or not isinstance(value.get("transaction_id"), str)
            or not _HEX_32.fullmatch(value["transaction_id"])
            or not _text(value.get("batch_key"), 200) or not value["batch_key"]
            or "\x00" in value["batch_key"]
            or not isinstance(value.get("items"), list) or not 1 <= len(value["items"]) <= MAX_TARGETS):
        return None
    seen = set()
    for item in value["items"]:
        if (not isinstance(item, dict)
                or set(item) != {"bug_id", "title", "before", "review_token", "guard"}
                or not _text(item.get("bug_id"), 200) or not item["bug_id"]
                or "\x00" in item["bug_id"] or item["bug_id"] in seen
                or not _text(item.get("title"), MAX_FACT)
                or any(not isinstance(item.get(key), str) or not _HEX_64.fullmatch(item[key])
                       for key in ("review_token", "guard"))):
            return None
        seen.add(item["bug_id"])
        before = item.get("before")
        if (not isinstance(before, dict)
                or set(before) != {*FACT_FIELDS, "case_source", "case_sources"}
                or any(not _text(before.get(key), MAX_FACT) for key in FACT_FIELDS)
                or not _source(before.get("case_source"))
                or not isinstance(before.get("case_sources"), list)
                or len(before["case_sources"]) > MAX_TARGETS
                or any(not _source(source) for source in before["case_sources"])):
            return None
        sources = before["case_sources"]
        if before["case_source"] != (sources[0] if sources else {}):
            return None
    return value


def _evidence_state(bug, batch):
    """Stat only scanned evidence paths and their already-authorized parents.

    Never read evidence contents or enumerate a directory.  Check directory
    parents before their children so replacement links cannot redirect a stat.
    """
    root, folder = Path(batch["root_dir"]), Path(bug["folder"])
    if not root.is_absolute() or not folder.is_absolute():
        raise ValueError("证据目录不再是已扫描的本机目录。")
    relative_folder = folder.relative_to(root)
    if ".." in relative_folder.parts:
        raise ValueError("证据目录已超出本批扫描范围。")
    directories = {}

    def directory(path):
        if path not in directories:
            info = path.lstat()
            if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                    or not stat.S_ISDIR(info.st_mode)):
                raise ValueError("证据目录缺失或已变成链接。")
            directories[path] = info

    def metadata(info):
        return [info.st_mode, info.st_size, info.st_mtime_ns, info.st_ino, info.st_dev]

    directory(root)
    parent = root
    for name in relative_folder.parts:
        parent /= name
        directory(parent)
    evidence = []
    for attachment in bug.get("attachments", []):
        path = Path(attachment["path"])
        relative = path.relative_to(folder)
        if not path.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("附件路径已超出已扫描的证据目录。")
        parent = folder
        for name in relative.parts[:-1]:
            parent /= name
            directory(parent)
        info = path.lstat()
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                or not stat.S_ISREG(info.st_mode)):
            raise ValueError("附件缺失或已变成链接。")
        evidence.append([relative.as_posix(), *metadata(info)])
    # The batch root is validated but its timestamp is not included: another
    # independent Bug folder should not invalidate this target's transaction.
    return {"directories": sorted([[path.relative_to(folder).as_posix(), *metadata(info)]
                                   for path, info in directories.items() if path == folder or folder in path.parents]),
            "attachments": sorted(evidence)}


def _guard(bug, store, batch_key):
    # Selection and review may change after import.  Everything else, including
    # excluded evidence metadata and failed submission attempts, blocks undo.
    content = {key: value for key, value in bug.items()
               if key not in {"selected", "reviewed", "updated_at", "review_token"}}
    lifecycle = [item for item in store.get("history", [])
                 if item.get("batch_key") == batch_key and item.get("bug_id") == bug["id"]]
    evidence = _evidence_state(bug, store["batches"][batch_key])
    encoded = json.dumps({"draft": content, "submission_history": lifecycle, "evidence": evidence}, ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def record_import(workbench, replacement, batch_key, changed_ids):
    """Record only changed targets before the caller's single atomic persist."""
    if not changed_ids:
        return
    previous = {bug["id"]: bug for bug in workbench._store["batches"][batch_key]["bugs"]}
    batch = replacement["batches"][batch_key]
    current = {bug["id"]: bug for bug in batch["bugs"]}
    items = []
    for bug_id in changed_ids:
        old, new = previous[bug_id], current[bug_id]
        before = {field: old.get(field, "") for field in FACT_FIELDS}
        before["case_sources"] = copy.deepcopy(old.get("case_sources", [old["case_source"]]
                                                       if old.get("case_source") else []))
        before["case_source"] = copy.deepcopy(before["case_sources"][0]) if before["case_sources"] else {}
        try:
            guard = _guard(new, replacement, batch_key)
        except (OSError, ValueError) as error:
            raise ValueError("证据文件夹或附件已变化、缺失或无法读取，请重新扫描后再导入。") from error
        items.append({"bug_id": bug_id, "title": new["title"], "before": before,
                      "review_token": workbench._review_token(new, batch["settings"]), "guard": guard})
    record = {"schema": 1, "transaction_id": secrets.token_hex(16), "batch_key": batch_key, "items": items}
    if validate_record(record) is None:
        raise ValueError("这次导入的原草稿超出可撤销范围，请先检查本地草稿。")
    replacement[STORE_KEY] = record


def _unavailable_reason(workbench, record):
    batch = workbench._batch()
    if not batch or batch["batch_key"] != record["batch_key"]:
        return "当前 Bug 目录已切换，请回到最近导入的目录后再撤销。"
    if batch.get("requires_rescan"):
        return "当前草稿需要重新扫描，不能撤销最近导入。"
    active = set(batch["active_ids"])
    targets = {item["bug_id"] for item in record["items"]}
    bugs = {bug["id"]: bug for bug in batch["bugs"] if bug["id"] in targets and bug["id"] in active}
    for item in record["items"]:
        bug = bugs.get(item["bug_id"])
        if bug is None:
            return "最近导入的 Bug 清单已变化，不能撤销。"
        if workbench._case_locked(bug):
            return "最近导入的 Bug 已提交、正在提交或等待核对，不能撤销。"
        try:
            guard = _guard(bug, workbench._store, record["batch_key"])
        except (OSError, ValueError):
            return "最近导入的证据文件夹或附件已变化、缺失或无法读取，不能撤销。"
        if (workbench._review_token(bug, batch["settings"]) != item["review_token"]
                or guard != item["guard"]):
            return "最近导入后，Bug 内容、公共信息、附件或提交状态已变化，不能撤销。"
    return ""


def undo_status(workbench):
    """Public summary only; never expose original facts to the AI capability."""
    with workbench._lock:
        record = validate_record(workbench._store.get(STORE_KEY))
        if record is None:
            return None
        reason = _unavailable_reason(workbench, record)
        return {"transaction_id": record["transaction_id"], "count": len(record["items"]),
                "titles": [item["title"] for item in record["items"]],
                "available": not reason, "reason": reason}


def undo_last_import(workbench, transaction_id):
    with workbench._lock:
        record = validate_record(workbench._store.get(STORE_KEY))
        if (not isinstance(transaction_id, str) or not _HEX_32.fullmatch(transaction_id)
                or record is None or transaction_id != record["transaction_id"]):
            raise ValueError("最近导入记录已变化或已撤销，请刷新后再确认。")
        reason = _unavailable_reason(workbench, record)
        if reason:
            raise ValueError(reason)
        replacement = copy.deepcopy(workbench._store)
        batch = replacement["batches"][record["batch_key"]]
        bugs = {bug["id"]: bug for bug in batch["bugs"]}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for item in record["items"]:
            bug = bugs[item["bug_id"]]
            bug.update(copy.deepcopy(item["before"]))
            bug["reviewed"] = False
            bug["updated_at"] = now
        replacement.pop(STORE_KEY, None)
        original = workbench._store
        workbench._store = replacement
        try:
            workbench._persist()
        except BaseException:
            workbench._store = original
            raise
        return {"state": workbench.state(), "undone": len(record["items"]), "undo": None}
