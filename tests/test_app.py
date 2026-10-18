"""End-to-end local HTTP and submission interruption checks; never use company services."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from app import Application, Handler, ThreadingHTTPServer
from zentao import ConnectorError


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(Path(self.temp.name) / "data")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.application = self.app
        self.app.server = self.server
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        base_headers = {"X-BugDesk-Token": self.app.token}
        base_headers.update(headers or {})
        content = None if data is None else json.dumps(data).encode()
        if content is not None:
            base_headers["Content-Type"] = "application/json"
        request = Request(self.url + path, data=content, headers=base_headers)
        return urlopen(request, timeout=5)

    def json(self, path, data=None, headers=None):
        with self.request(path, data, headers) as response:
            return json.load(response)

    def prepare_bug(self):
        folder = Path(self.temp.name) / "10.13" / "中文测试标题"
        folder.mkdir(parents=True)
        (folder / "录像.mp4").write_bytes(b"0123456789")
        state = self.json("/api/scan", {"path": str(folder.parent)})
        bug = state["bugs"][0]
        self.json("/api/save", {"settings": {"product": "1", "openedBuild": ["trunk"]}})
        state = self.json("/api/save", {"bugs": [{"id": bug["id"], "steps": "1. 打开页面", "actual": "按钮无响应", "expected": "按钮打开菜单"}]})
        state = self.json("/api/save", {"bugs": [{"id": bug["id"], "reviewed": True, "review_token": state["bugs"][0]["review_token"]}]})
        return state["bugs"][0]

    def wait_job(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not self.app.job_state()["running"]:
                return
            time.sleep(.01)
        self.fail("Job did not complete")

    def test_local_mutations_require_token_and_same_origin(self):
        for headers in ({"X-BugDesk-Token": "wrong"}, {"Origin": "https://evil.test"}, {"Host": "evil.test"}):
            with self.assertRaises(HTTPError) as result:
                self.request("/api/demo", {}, headers)
            self.assertEqual(result.exception.code, 403)
        self.assertTrue(self.json("/api/demo", {})["demo"])

    def test_scanning_saving_attachment_range_and_export(self):
        bug = self.prepare_bug()
        attachment = bug["attachments"][0]
        with self.request(f"/api/attachment?bug_id={bug['id']}&attachment_id={attachment['id']}", headers={"Range": "bytes=2-5"}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"2345")
        with self.assertRaises(HTTPError):
            self.request(f"/api/attachment?bug_id={bug['id']}&attachment_id=../../secret")
        exported = self.json("/api/export", {"format": "markdown"})
        with self.request(exported["url"]) as response:
            self.assertIn("按钮无响应", response.read().decode("utf-8"))
        restored = Application(Path(self.temp.name) / "data").state()
        self.assertEqual(restored["bugs"][0]["steps"], "1. 打开页面")

    def test_successful_remote_id_is_durable_and_cannot_submit_twice(self):
        bug = self.prepare_bug()
        calls = []
        class FakeClient:
            def create_bug(self, bug, settings, attachments):
                calls.append(bug["id"])
                return {"id": 123, "url": "https://company.test/bug-view-123.html", "upload_status": {attachments[0]["id"]: "uploaded"}}
        self.app.client = FakeClient()
        self.app.connection = {"connected": True, "first_verified": False, "url": "https://company.test"}
        self.json("/api/submit", {"ids": [bug["id"]]})
        self.wait_job()
        self.assertEqual(self.app.state()["bugs"][0]["remote_id"], 123)
        self.assertTrue(self.app.connection["first_verified"])
        with self.assertRaises(HTTPError):
            self.json("/api/submit", {"ids": [bug["id"]]})
        self.assertEqual(len(calls), 1)

    def test_unknown_result_blocks_retry_until_user_reconciles(self):
        bug = self.prepare_bug()
        class TimeoutClient:
            def create_bug(self, bug, settings, attachments):
                raise ConnectorError("结果未知", uncertain=True)
        self.app.client = TimeoutClient()
        self.app.connection = {"connected": True, "first_verified": False, "url": "https://company.test"}
        self.json("/api/submit", {"ids": [bug["id"]]})
        self.wait_job()
        self.assertEqual(self.app.state()["bugs"][0]["status"], "uncertain")
        with self.assertRaises(HTTPError):
            self.json("/api/submit", {"ids": [bug["id"]]})
        with self.assertRaises(HTTPError):
            self.json("/api/resolve-submission", {"id": bug["id"], "resolution": "not_created"})
        state = self.json("/api/resolve-submission", {"id": bug["id"], "resolution": "not_created", "confirmed": True})
        self.assertFalse(state["bugs"][0]["reviewed"])

    def test_context_menus_survive_reload_and_clear_when_context_changes(self):
        class MenuClient:
            def options(self, product, project, execution):
                if product == "2":
                    return {"projects": [], "executions": [], "modules": [], "builds": [], "probabilities": []}
                return {"products": [{"value": "1", "label": "产品一"}],
                        "users": [{"value": "tester", "label": "测试人员"}],
                        "builds": [{"value": "62", "label": "62 需求版本"}],
                        "probabilities": [{"value": "always", "label": "必现"}],
                        "probability_field": "recurRate"}
        self.app.client = MenuClient()
        self.app.connection = {"connected": True, "first_verified": False}
        expected = self.json("/api/options", {"product": "1", "project": "10", "execution": "20"})
        reloaded = self.json("/api/state")
        self.assertEqual(reloaded["options"], expected)
        self.assertEqual(reloaded["options_context"], {"product": "1", "project": "10", "execution": "20"})
        detached = self.app.state()
        detached["options"]["probabilities"][0]["label"] = "修改副本"
        self.assertEqual(self.app.state()["options"]["probabilities"][0]["label"], "必现")
        self.json("/api/options", {"product": "2"})
        changed = self.json("/api/state")
        self.assertEqual(changed["options"]["builds"], [])
        self.assertNotIn("probability_field", changed["options"])
        restarted = Application(Path(self.temp.name) / "data").state()
        self.assertFalse(restarted["connection"]["connected"])
        self.assertEqual(restarted["options"], {})
        self.json("/api/disconnect", {})
        disconnected = self.json("/api/state")
        self.assertEqual(disconnected["options"], {})
        self.assertEqual(disconnected["options_context"], {})

    def test_reconnect_replaces_old_company_menus(self):
        from unittest.mock import patch
        class NewClient:
            base_url = "https://new-company.test/"
            def __init__(self, *args):
                pass
            def connect(self):
                return {"connected": True, "message": "connected", "options": {"products": [{"value": "2", "label": "新产品"}], "users": []}}
        self.app.connection_options = {"builds": [{"value": "62", "label": "旧版本"}], "probabilities": [{"value": "1", "label": "必现"}]}
        self.app.options_context = {"product": "1", "project": "10", "execution": "20"}
        with patch("app.ZenTaoClient", NewClient):
            self.json("/api/connect", {"url": NewClient.base_url, "account": "tester", "password": "fake-password"})
        state = self.json("/api/state")
        self.assertEqual(state["options"], {"products": [{"value": "2", "label": "新产品"}], "users": []})
        self.assertEqual(state["options_context"], {"product": "", "project": "", "execution": ""})

    def test_probability_preflight_failure_can_be_corrected_and_reviewed_without_duplicate(self):
        bug = self.prepare_bug()
        writes = []
        class PreflightClient:
            def create_bug(self, bug, settings, attachments):
                if settings.get("probability") != "always":
                    raise ConnectorError("无法确认公司概率选项，本条未发送。")
                writes.append(bug["id"])
                return {"id": 155, "url": "https://company.test/bug-view-155.html", "upload_status": {attachments[0]["id"]: "uploaded"}}
        self.app.client = PreflightClient()
        self.app.connection = {"connected": True, "first_verified": False, "url": "https://company.test"}
        self.json("/api/submit", {"ids": [bug["id"]]})
        self.wait_job()
        failed = self.json("/api/state")["bugs"][0]
        self.assertEqual(failed["status"], "failed")
        self.assertFalse(failed["remote_id"])
        self.assertEqual(writes, [])
        corrected = self.json("/api/save", {"settings": {"probability": "always"}})
        self.assertFalse(corrected["bugs"][0]["reviewed"])
        self.json("/api/save", {"bugs": [{"id": bug["id"], "reviewed": True, "review_token": corrected["bugs"][0]["review_token"]}]})
        self.json("/api/submit", {"ids": [bug["id"]]})
        self.wait_job()
        self.assertEqual(self.json("/api/state")["bugs"][0]["remote_id"], 155)
        self.assertEqual(writes, [bug["id"]])

    def test_demo_submission_refused_even_if_connected(self):
        state = self.json("/api/demo", {})
        self.app.client = object()
        self.app.connection = {"connected": True, "first_verified": True}
        with self.assertRaises(HTTPError) as result:
            self.json("/api/submit", {"ids": [state["bugs"][0]["id"]]})
        self.assertEqual(result.exception.code, 400)

    def test_no_attachment_submission_does_not_verify_upload_integration(self):
        bug = self.prepare_bug()
        state = self.json("/api/save", {"bugs": [{"id": bug["id"], "excluded_attachments": [a["id"] for a in bug["attachments"]]}]})
        self.json("/api/save", {"bugs": [{"id": bug["id"], "reviewed": True, "review_token": state["bugs"][0]["review_token"]}]})
        class NoFilesClient:
            def create_bug(self, bug, settings, attachments):
                return {"id": 124, "url": "https://company.test/bug/124", "upload_status": {}}
        self.app.client = NoFilesClient()
        self.app.connection = {"connected": True, "first_verified": False, "url": "https://company.test"}
        self.json("/api/submit", {"ids": [bug["id"]]})
        self.wait_job()
        self.assertEqual(self.app.state()["bugs"][0]["status"], "submitted")
        self.assertFalse(self.app.connection["first_verified"])

    def test_queued_changed_attachment_has_error_and_is_not_sent(self):
        from unittest.mock import patch
        bug = self.prepare_bug()
        class NeverCalled:
            def create_bug(self, *args):
                raise AssertionError("Should not send when preflight fails")
        self.app.client = NeverCalled()
        self.app.connection = {"connected": True, "first_verified": False, "url": "https://company.test"}
        original = self.app.workbench.set_submission
        def preflight(bug_id, **fields):
            if fields.get("status") == "submitting":
                raise ValueError("附件已改变，请重新扫描。")
            return original(bug_id, **fields)
        with patch.object(self.app.workbench, "set_submission", side_effect=preflight):
            self.json("/api/submit", {"ids": [bug["id"]]})
            self.wait_job()
        self.assertEqual(self.app.job_state()["done"], 1)
        self.assertIn("附件已改变", self.app.job_state()["results"][0]["error"])
        self.assertEqual(self.app.state()["bugs"][0]["status"], "failed")

    def test_stale_review_in_another_window_is_rejected(self):
        bug = self.prepare_bug()
        token = bug["review_token"]
        self.json("/api/save", {"bugs": [{"id": bug["id"], "actual": "另一个窗口改过的实际结果"}]})
        with self.assertRaises(HTTPError) as result:
            self.json("/api/save", {"bugs": [{"id": bug["id"], "reviewed": True, "review_token": token}]})
        self.assertEqual(result.exception.code, 400)
        self.assertFalse(self.app.state()["bugs"][0]["reviewed"])

    def test_connect_cannot_replace_target_during_an_active_submission(self):
        from unittest.mock import patch
        self.prepare_bug()
        entered = threading.Event()
        release = threading.Event()
        errors = []
        class NewClient:
            base_url = "https://new-target.test/"
            def __init__(self, *args):
                pass
            def connect(self):
                entered.set()
                release.wait(3)
                return {"message": "connected", "options": {}}
        old_client = object()
        self.app.client = old_client
        self.app.connection = {"connected": True, "first_verified": True, "url": "https://old-target.test"}
        def attempt_connect():
            try:
                self.app.connect({"url": "https://new-target.test", "account": "tester", "password": "not-a-real-password"})
            except ValueError as exc:
                errors.append(str(exc))
        with patch("app.ZenTaoClient", NewClient):
            thread = threading.Thread(target=attempt_connect)
            thread.start()
            self.assertTrue(entered.wait(2))
            with self.app.job_lock:
                self.app.job["running"] = True
            release.set()
            thread.join(3)
        self.assertIs(self.app.client, old_client)
        self.assertEqual(self.app.connection["url"], "https://old-target.test")
        self.assertTrue(errors)
        self.app.job["running"] = False


if __name__ == "__main__":
    unittest.main()
