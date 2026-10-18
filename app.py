"""BugDesk: a dependency-free, loopback-only Windows bug workbench."""
from __future__ import annotations

import argparse
import atexit
import copy
import json
import mimetypes
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
import webbrowser

from domain import Workbench
from case_clipboard import parse_cases
from workbuddy import WorkBuddyBridge
from zentao import ZenTaoClient, ConnectorError

VERSION = "1.0.0"
ASSET_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "web"


def user_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        portable = Path(sys.executable).parent / "portable.flag"
        if portable.exists():
            return portable.parent / "BugDesk-data"
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BugDesk"


def open_browser(url: str) -> None:
    """Use a normal browser; no browser installation or runtime downloads."""
    webbrowser.open(url)


class Application:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workbench = Workbench(self.data_dir)
        self.token = secrets.token_urlsafe(32)
        self.instance = secrets.token_hex(16)
        self.client = None
        self.connection = {"connected": False, "message": "尚未连接公司禅道", "first_verified": False}
        self.job_lock = threading.RLock()
        self.remote_lock = threading.Lock()
        self.menu_revision = 0
        self.job = {"running": False, "total": 0, "done": 0, "current_title": "", "results": [], "cancel_requested": False}
        self.exports = {}
        self.last_activity = time.monotonic()
        self.server = None
        self.connection_options = {}
        self.options_context = {}
        self.stopping = False
        self.verified_target = ""
        self.verification_path = self.data_dir / "connection-verification.json"
        if self.verification_path.exists():
            try:
                self.verified_target = json.loads(self.verification_path.read_text(encoding="utf-8")).get("target", "")
            except (ValueError, OSError, AttributeError):
                pass
        self.workbuddy = WorkBuddyBridge(self)

    def state(self):
        state = self.workbench.state()
        with self.job_lock:
            state["connection"] = copy.deepcopy(self.connection)
            state["job"] = copy.deepcopy(self.job)
            state["options"] = copy.deepcopy(self.connection_options)
            state["options_context"] = copy.deepcopy(self.options_context)
        return state

    def job_state(self):
        with self.job_lock:
            return copy.deepcopy(self.job)

    def ensure_idle(self):
        with self.job_lock:
            if self.stopping:
                raise ValueError("工具正在关闭，请重新打开后操作。")
            if self.job["running"]:
                raise ValueError("正在提交，请等本次完成或停止后再修改批次。")

    @staticmethod
    def parse_case_request(data):
        return parse_cases(data.get("text", ""), data.get("html", ""),
                           mapping=data.get("mapping"), has_header=data.get("has_header"))

    def preview_cases(self, data):
        with self.job_lock:
            self.ensure_idle()
            parsed = self.parse_case_request(data)
            current = self.workbench.state()
            if not current["bugs"] or current.get("requires_rescan"):
                raise ValueError("请先扫描今天的 Bug 附件文件夹，再关联粘贴的用例。")
            parsed["rows"] = self.workbench.preview_case_links(parsed["rows"])
            fields = ("id", "title", "original_title", "status", "remote_id", "review_token",
                      "case_source", "preconditions", "steps", "actual", "expected")
            parsed.update(batch_key=current["batch_key"],
                          bugs=[{key: copy.deepcopy(bug.get(key)) for key in fields}
                                for bug in current["bugs"]])
            return parsed

    def apply_cases(self, data):
        with self.job_lock:
            self.ensure_idle()
            parsed = self.parse_case_request(data)
            if any(parsed["mapping"].get(key) is None for key in ("steps", "expected")):
                raise ValueError("请先在字段对应中选择步骤描述和预期结果所在的列。")
            result = self.workbench.apply_cases(parsed["rows"], data.get("assignments", []),
                                                batch_key=data.get("batch_key", ""))
            return {**result, "state": self.state()}

    def pick_folder(self):
        result_file = self.data_dir / ("folder-picker-" + secrets.token_hex(8) + ".txt")
        executable = sys.executable
        command = [executable]
        if not getattr(sys, "frozen", False):
            command.append(str(Path(__file__).resolve()))
        command += ["--pick-folder", "--result-file", str(result_file)]
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        try:
            proc = subprocess.run(command, timeout=600, check=False, **kwargs)
            if proc.returncode or not result_file.exists():
                raise ValueError("目录选择窗口未能打开，可以直接粘贴日期文件夹路径。")
            return {"path": result_file.read_text(encoding="utf-8")}
        finally:
            result_file.unlink(missing_ok=True)

    def connect(self, data):
        self.ensure_idle()
        url, account, password = (str(data.get(k, "")).strip() for k in ("url", "account", "password"))
        # Preserve whitespace in passwords; trim only the address and account.
        password = str(data.get("password", ""))
        if not url or not account or not password:
            raise ValueError("请填写公司禅道地址、账号和密码。")
        candidate = ZenTaoClient(url, account, password)
        info = candidate.connect()
        with self.job_lock:
            self.ensure_idle()
            self.workbench.save({"settings": {"zentao_url": url}})
            self.client = candidate
            self.menu_revision += 1
            target = getattr(candidate, "base_url", url).rstrip("/")
            first_verified = target == self.verified_target
            self.connection = {"connected": True, "message": info.get("message", "已登录；首次请用一条 Bug 验证"), "first_verified": first_verified, "url": target}
            self.connection_options = info.get("options", {})
            self.options_context = {"product": "", "project": "", "execution": ""}
        return {**self.connection, "options": self.connection_options}

    def read_options(self, data):
        """Keep only public menus in this session so a page reload can recover them."""
        with self.job_lock:
            self.ensure_idle()
            if not self.client:
                raise ValueError("请先连接公司禅道，或在公共配置中手动填写。")
            context = {key: str(data.get(key, "")) for key in ("product", "project", "execution")}
            client = self.client
            self.menu_revision += 1
            revision = self.menu_revision
        # Company I/O can take seconds. Keep local saves and disconnects free;
        # serialize connector calls separately so forms/cookies cannot race writes.
        with self.remote_lock:
            with self.job_lock:
                self.ensure_idle()
                if client is not self.client or revision != self.menu_revision:
                    raise ValueError("连接或菜单选择已变化，请重新加载当前菜单。")
            result = client.options(context["product"], context["project"], context["execution"])
        with self.job_lock:
            self.ensure_idle()
            if client is not self.client or revision != self.menu_revision:
                raise ValueError("连接或菜单选择已变化，已忽略旧菜单。")
            # Product-less reads omit global lists. Never retain old contextual lists.
            globals_only = {key: copy.deepcopy(self.connection_options[key])
                            for key in ("products", "users") if key in self.connection_options}
            self.connection_options = {**globals_only, **copy.deepcopy(result)}
            self.options_context = context
            return result

    def disconnect(self):
        with self.job_lock:
            self.ensure_idle()
            self.client = None
            self.menu_revision += 1
            self.connection_options = {}
            self.options_context = {}
            self.connection = {"connected": False, "message": "已断开连接", "first_verified": False}
        return self.connection

    def start_submit(self, data):
        with self.job_lock:
            self.ensure_idle()
            if not self.client or not self.connection["connected"]:
                raise ValueError("请先连接公司禅道。")
            state = self.workbench.state()
            if state.get("demo"):
                raise ValueError("示例批次仅用于体验，不会提交到公司禅道。请扫描自己的日期文件夹。")
            ids = data.get("ids", [])
            if not isinstance(ids, list) or not ids or any(not isinstance(v, str) for v in ids):
                raise ValueError("请选择需要提交的 Bug。")
            if len(ids) != len(set(ids)):
                raise ValueError("提交清单含重复条目，请重新选择。")
            if not self.connection.get("first_verified") and len(ids) != 1:
                raise ValueError("首次连接请只选择一条 Bug，验证填写和附件上传后再批量提交。")
            items = self.workbench.validate_submission(ids)
            self.menu_revision += 1
            job_id = secrets.token_hex(8)
            self.job = {"job_id": job_id, "running": True, "total": len(items), "done": 0, "current_title": "", "results": [], "cancel_requested": False}
            client = self.client
            target = self.connection.get("url", "")
            thread = threading.Thread(target=self._run_submit, args=(items, client, target), daemon=True)
            thread.start()
            return {"job_id": job_id}

    def _run_submit(self, items, client, target):
        try:
            for bug, settings in items:
                with self.job_lock:
                    if self.job["cancel_requested"]:
                        break
                    self.job["current_title"] = bug["title"]
                bug_id = bug["id"]
                try:
                    self.workbench.set_submission(bug_id, status="submitting", error="")
                except Exception as exc:
                    message = str(exc) if isinstance(exc, ValueError) else "本地提交记录无法保存，请检查数据目录空间与权限。本条没有发送到禅道。"
                    fields = {"status": "failed", "error": message}
                    try:
                        self.workbench.set_submission(bug_id, **fields)
                    except Exception:
                        pass
                    with self.job_lock:
                        self.job["done"] += 1
                        self.job["results"].append({"id": bug_id, **fields})
                        self.job["cancel_requested"] = True
                    break
                excluded = set(bug.get("excluded_attachments", []))
                attachments = [a for a in bug.get("attachments", []) if a["id"] not in excluded]
                try:
                    with self.remote_lock:
                        result = client.create_bug(bug, settings, attachments)
                    remote_id = result.get("id")
                    if not remote_id:
                        raise ConnectorError("禅道没有返回 Bug 编号，请到公司页面核对结果后再操作。", uncertain=True)
                    fields = {"status": "submitted", "remote_id": remote_id, "remote_url": result.get("url", ""), "error": "", "upload_status": result.get("upload_status", {})}
                    self.workbench.set_submission(bug_id, **fields)
                    uploads = result.get("upload_status", {})
                    upload_verified = bool(attachments) and all(uploads.get(a["id"]) == "uploaded" for a in attachments)
                    if upload_verified:
                        with self.job_lock:
                            if self.connection.get("url") == target:
                                self.connection["first_verified"] = True
                            self.verified_target = target
                        temp = self.verification_path.with_suffix(".tmp")
                        temp.write_text(json.dumps({"target": target}, ensure_ascii=False), encoding="utf-8")
                        temp.replace(self.verification_path)
                    elif not self.connection.get("first_verified"):
                        with self.job_lock:
                            self.connection["message"] = "本条 Bug 已创建。首次附件上传尚未验证，请选一条带附件的 Bug 试提交。"
                except ConnectorError as exc:
                    remote_id = getattr(exc, "remote_id", None)
                    status = "partial" if remote_id else "uncertain" if getattr(exc, "uncertain", False) or getattr(exc, "partial", False) else "failed"
                    fields = {"status": status, "remote_id": remote_id, "remote_url": getattr(exc, "remote_url", ""), "error": str(exc), "upload_status": getattr(exc, "upload_status", {})}
                    self.workbench.set_submission(bug_id, **fields)
                except Exception:
                    fields = {"status": "uncertain", "error": "连接中断，提交结果未确认。请到禅道核对，勿直接重提。"}
                    self.workbench.set_submission(bug_id, **fields)
                with self.job_lock:
                    self.job["done"] += 1
                    self.job["results"].append({"id": bug_id, **fields})
                    # Stop on partial/uncertain results: a human needs to inspect company behavior.
                    if fields["status"] in ("partial", "uncertain"):
                        self.job["cancel_requested"] = True
        finally:
            with self.job_lock:
                self.job["running"] = False
                self.job["current_title"] = ""

    def attachment(self, bug_id, attachment_id):
        bug = self.workbench.get_bug(bug_id)
        for entry in bug.get("attachments", []):
            if entry["id"] != attachment_id:
                continue
            path = Path(entry["path"])
            folder = Path(bug["folder"]).resolve()
            resolved = path.resolve()
            if path.is_symlink() or not resolved.is_relative_to(folder) or not resolved.is_file():
                raise ValueError("附件已移动或不在此 Bug 文件夹中，请重新扫描。")
            return resolved
        raise ValueError("找不到这个附件，请重新扫描。")

    def resolve_submission(self, data):
        with self.job_lock:
            self.ensure_idle()
            return self._resolve_submission(data)

    def _resolve_submission(self, data):
        self.ensure_idle()
        if data.get("confirmed") is not True:
            raise ValueError("请先到禅道核对，再确认记录结果。")
        bug = self.workbench.get_bug(str(data.get("id", "")))
        if bug.get("status") not in ("uncertain", "partial"):
            raise ValueError("这条 Bug 不需要核对提交结果。")
        resolution = data.get("resolution")
        if resolution == "not_created":
            if bug.get("remote_id"):
                raise ValueError("这条 Bug 已有禅道编号，请到禅道补齐附件，不能再次创建。")
            self.workbench.reconcile_submission(bug["id"], "not_created")
        elif resolution == "created":
            try:
                remote_id = int(data.get("remote_id") or bug.get("remote_id") or 0)
            except (ValueError, TypeError):
                remote_id = 0
            if remote_id <= 0:
                raise ValueError("请输入已在禅道核对的 Bug 编号。")
            if bug.get("remote_id") and int(bug["remote_id"]) != remote_id:
                raise ValueError("编号与已创建的 Bug 不一致，请再次核对。")
            remote_url = bug.get("remote_url", "")
            target = self.connection.get("url") or self.workbench.get_settings().get("zentao_url", "")
            if not remote_url and target:
                from urllib.parse import urlencode
                remote_url = target.rstrip("/") + "/index.php?" + urlencode({"m": "bug", "f": "view", "bugID": remote_id})
            self.workbench.reconcile_submission(bug["id"], "created", remote_id=remote_id, remote_url=remote_url)
        else:
            raise ValueError("请选择核对结果。")
        return self.state()


class Handler(BaseHTTPRequestHandler):
    server_version = "BugDesk"

    @property
    def application(self):
        return self.server.application

    def log_message(self, *args):
        pass

    def _valid_host(self):
        expected = f"127.0.0.1:{self.server.server_port}"
        return self.headers.get("Host", "") == expected

    def _headers(self, status=200, content_type="application/json; charset=utf-8", length=None, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if length is not None:
            self.send_header("Content-Length", str(length))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _json(self, value, status=200):
        content = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self._headers(status, length=len(content))
        self.wfile.write(content)

    def _guard(self, mutation=False, workbuddy=False):
        def reject(message):
            # Consume a bounded rejected POST before closing. On Windows, closing
            # with unread body bytes can reset TCP and hide the friendly error.
            if self.command == "POST":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if 0 < length <= 8 * 1024 * 1024:
                        previous_timeout = self.connection.gettimeout()
                        try:
                            self.connection.settimeout(2)
                            self.rfile.read(length)
                        finally:
                            self.connection.settimeout(previous_timeout)
                except (OSError, ValueError):
                    pass
            self._json({"error": message}, 403)
            return False
        if not self._valid_host():
            return reject("本工具只接受本机访问。")
        origin = self.headers.get("Origin")
        expected = f"http://127.0.0.1:{self.server.server_port}"
        if origin and origin != expected:
            return reject("访问来源不匹配，请重新打开 BugDesk。")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return reject("请从 BugDesk 窗口访问。")
        if workbuddy:
            try:
                self.application.workbuddy.validate(self.headers.get("X-BugDesk-WorkBuddy-Token", ""))
            except ValueError as exc:
                return reject(str(exc))
        elif mutation and not secrets.compare_digest(self.headers.get("X-BugDesk-Token", ""), self.application.token):
            return reject("页面已过期，请刷新后重试。")
        self.application.last_activity = time.monotonic()
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        if not self._guard(workbuddy=path == "/api/workbuddy/context"):
            return
        try:
            if path == "/health":
                return self._json({"app": "BugDesk", "version": VERSION, "instance": self.application.instance})
            if path == "/api/bootstrap":
                return self._json({"token": self.application.token, "version": VERSION, "data_dir": str(self.application.data_dir), "connection": self.application.connection})
            if path == "/api/state":
                return self._json(self.application.state())
            if path == "/api/workbuddy/status":
                return self._json(self.application.workbuddy.status(query.get("known_plan_id", [None])[0]))
            if path == "/api/workbuddy/context":
                return self._json(self.application.workbuddy.context(self.headers.get("X-BugDesk-WorkBuddy-Token", "")))
            if path == "/api/job":
                return self._json(self.application.job_state())
            if path == "/api/ping":
                return self._json({"ok": True})
            if path == "/api/attachment":
                attachment = self.application.attachment(query.get("bug_id", [""])[0], query.get("attachment_id", [""])[0])
                return self._file(attachment, media=True)
            if path == "/api/download":
                export_id = query.get("file", [""])[0]
                export_path = self.application.exports.get(export_id)
                if not export_path:
                    raise ValueError("导出链接已失效，请重新导出。")
                return self._file(Path(export_path), download=True)
            assets = {"/": "index.html", "/index.html": "index.html", "/app.css": "app.css", "/app.js": "app.js", "/case_import.js": "case_import.js", "/workbuddy.js": "workbuddy.js", "/workbuddy_help.js": "workbuddy_help.js", "/workbuddy_help.css": "workbuddy_help.css"}
            assets['/help/workbuddy-3-workbuddy.png'] = 'help/workbuddy-3-workbuddy.png'
            for step in range(1, 5):
                name = f'help/workbuddy-{step}-' + ('scan', 'send', 'preview', 'import')[step - 1] + '.jpg'
                assets['/' + name] = name
            if path in assets:
                file = ASSET_DIR / assets[path]
                body = file.read_bytes()
                content_type = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg"}[file.suffix]
                csp = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
                self._headers(content_type=content_type, length=len(body), extra={"Content-Security-Policy": csp})
                return self.wfile.write(body)
            return self._json({"error": "找不到这个页面。"}, 404)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            self._json({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._json({"error": "读取失败，请刷新页面或重新扫描文件夹。"}, 500)

    def _file(self, path: Path, media=False, download=False):
        size = path.stat().st_size
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        allowed_media = (mime.startswith("image/") or mime.startswith("video/") or mime.startswith("audio/"))
        if media and not allowed_media:
            mime, download = "application/octet-stream", True
        start, end, status = 0, size - 1, 200
        extra = {"Accept-Ranges": "bytes"}
        if mime == "image/svg+xml":
            extra["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
        if download:
            from urllib.parse import quote
            extra["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(path.name)
        requested = self.headers.get("Range")
        if requested:
            import re
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not match or size == 0:
                return self._headers(416, length=0, extra={"Content-Range": f"bytes */{size}"})
            left, right = match.groups()
            if left:
                start = int(left)
                end = min(int(right), size - 1) if right else size - 1
            elif right:
                start = max(0, size - int(right))
            else:
                return self._headers(416, length=0, extra={"Content-Range": f"bytes */{size}"})
            if start > end or start >= size:
                return self._headers(416, length=0, extra={"Content-Range": f"bytes */{size}"})
            status = 206
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        length = max(0, end - start + 1)
        self._headers(status, mime, length, extra)
        with path.open("rb") as stream:
            stream.seek(start)
            while length:
                block = stream.read(min(256 * 1024, length))
                if not block:
                    break
                self.wfile.write(block)
                length -= len(block)

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._guard(mutation=True, workbuddy=path == "/api/workbuddy/stage"):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 8 * 1024 * 1024:
                return self._json({"error": "请求太大，请选择较小的备份文件。"}, 413)
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("请求格式不正确。")
            path = urlparse(self.path).path
            app = self.application
            if path in ("/api/scan", "/api/demo", "/api/save", "/api/import"):
                with app.job_lock:
                    app.ensure_idle()
                    if path == "/api/scan":
                        app.workbench.scan(str(data.get("path", "")))
                    elif path == "/api/demo":
                        app.workbench.create_demo()
                    elif path == "/api/save":
                        patches = data.get("bugs", [])
                        if not isinstance(patches, list):
                            raise ValueError("Bug 编辑列表格式不正确。")
                        for patch in patches:
                            if isinstance(patch, dict) and patch.get("reviewed") is True and not patch.get("review_token"):
                                raise ValueError("审核内容已过期，请刷新并重新打开审核窗口。")
                        app.workbench.save(data)
                    else:
                        app.workbench.import_backup(data.get("data", {}))
                    return self._json(app.state())
            if path == "/api/pick-folder":
                return self._json(app.pick_folder())
            if path == "/api/export":
                exported = app.workbench.export(str(data.get("format", "markdown")))
                exported = Path(exported)
                export_id = secrets.token_urlsafe(18)
                app.exports[export_id] = str(exported)
                return self._json({"path": str(exported), "filename": exported.name, "url": "/api/download?file=" + export_id})
            if path == "/api/open-folder":
                if data.get("bug_id"):
                    target = app.workbench.get_bug(data["bug_id"])["folder"]
                else:
                    target = app.workbench.state().get("root_dir", "")
                if not target or not Path(target).is_dir():
                    raise ValueError("文件夹不存在，请重新选择。")
                if os.name == "nt":
                    os.startfile(target)
                else:
                    subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return self._json({"ok": True})
            if path == "/api/connect":
                return self._json(app.connect(data))
            if path == "/api/disconnect":
                return self._json(app.disconnect())
            if path == "/api/options":
                return self._json(app.read_options(data))
            if path == "/api/cases/preview":
                return self._json(app.preview_cases(data))
            if path == "/api/cases/apply":
                return self._json(app.apply_cases(data))
            if path == "/api/workbuddy/enable":
                return self._json(app.workbuddy.enable())
            if path == "/api/workbuddy/disable":
                return self._json(app.workbuddy.disable())
            if path == "/api/workbuddy/stage":
                return self._json(app.workbuddy.stage(data, self.headers.get("X-BugDesk-WorkBuddy-Token", "")))
            if path == "/api/workbuddy/apply":
                return self._json(app.workbuddy.apply(data))
            if path == "/api/submit":
                return self._json(app.start_submit(data))
            if path == "/api/resolve-submission":
                return self._json(app.resolve_submission(data))
            if path == "/api/cancel-submit":
                with app.job_lock:
                    app.job["cancel_requested"] = True
                return self._json({"ok": True, "message": "当前条目处理完成后停止。"})
            if path == "/api/shutdown":
                with app.job_lock:
                    app.ensure_idle()
                    app.stopping = True
                    self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self._json({"error": "找不到这个操作。"}, 404)
        except (ValueError, KeyError, FileNotFoundError, ConnectorError) as exc:
            self._json({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._json({"error": "操作未完成，请重试。草稿保存在本机。"}, 500)


def folder_dialog(result_file):
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(title="选择存放今天 Bug 的日期文件夹", mustexist=True, parent=root)
    Path(result_file).write_text(folder or "", encoding="utf-8")
    root.destroy()


def run(args):
    directory = Path(args.data_dir) if args.data_dir else user_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock_file = directory / "server-instance.json"
    if not args.isolated and lock_file.exists():
        try:
            existing = json.loads(lock_file.read_text(encoding="utf-8"))
            port = int(existing["port"])
            response = json.loads(urlopen(f"http://127.0.0.1:{port}/health", timeout=2).read())
            if response.get("app") == "BugDesk" and response.get("instance") == existing.get("instance"):
                if not args.no_browser:
                    open_browser(f"http://127.0.0.1:{port}/")
                return
        except Exception:
            pass
    app = Application(directory)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    server.application = app
    app.server = server
    port = server.server_port
    lock_file.write_text(json.dumps({"port": port, "instance": app.instance, "pid": os.getpid()}), encoding="utf-8")

    def cleanup():
        app.workbuddy.close()
        try:
            if json.loads(lock_file.read_text(encoding="utf-8")).get("instance") == app.instance:
                lock_file.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass

    atexit.register(cleanup)
    url = f"http://127.0.0.1:{port}/"
    if args.ready_file:
        Path(args.ready_file).write_text(json.dumps({"url": url, "port": port}, ensure_ascii=False), encoding="utf-8")
    if sys.stdout:
        print("BugDesk " + VERSION + " · " + url, flush=True)
    if args.idle_timeout > 0:
        def idle_monitor():
            while True:
                time.sleep(10)
                should_stop = False
                with app.job_lock:
                    if not app.job["running"] and time.monotonic() - app.last_activity > args.idle_timeout:
                        app.stopping = True
                        should_stop = True
                if should_stop:
                    server.shutdown()
                    break
        threading.Thread(target=idle_monitor, daemon=True).start()
    if not args.no_browser:
        threading.Timer(.4, lambda: open_browser(url)).start()
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        cleanup()


def main():
    parser = argparse.ArgumentParser(description="BugDesk 本地 Bug 提交助手")
    parser.add_argument("--data-dir")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("--ready-file")
    parser.add_argument("--idle-timeout", type=int, default=180)
    parser.add_argument("--pick-folder", action="store_true")
    parser.add_argument("--result-file")
    args = parser.parse_args()
    if args.pick_folder:
        return folder_dialog(args.result_file)
    try:
        run(args)
    except Exception as exc:
        if not args.no_browser:
            try:
                import tkinter
                from tkinter import messagebox
                root = tkinter.Tk()
                root.withdraw()
                messagebox.showerror("BugDesk 启动失败", "无法启动，请检查数据目录是否可写。\n\n" + str(exc), parent=root)
                root.destroy()
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()
