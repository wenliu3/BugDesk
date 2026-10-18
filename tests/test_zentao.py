"""Local-only protocol tests; never contact a real ZenTao instance."""
from email import policy
from email.parser import BytesParser
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zentao import ConnectorError, ZenTaoClient, _FormParser


class MockZenTao(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def route(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if parsed.path.endswith("index.php"):
            module = query.get("m", [""])[0]
            method = query.get("f", [""])[0]
            view = query.get("t", ["html"])[0]
            params = {key: value[0] for key, value in query.items() if key not in ("m", "f", "t")}
            if self.server.path_route:
                return "wrong", "wrong", view, params
            return module, method, view, params
        filename = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
        stem, view = filename.rsplit(".", 1)
        module, method, *values = stem.split("-")
        params = {"productID": values[0]} if values else {}
        if module == "bug" and method == "view":
            params = {"bugID": values[0]}
        return module, method, view, params

    def send(self, value, status=200, cookie=False):
        if isinstance(value, (dict, list)):
            data = json.dumps(value, ensure_ascii=False).encode()
            content_type = "application/json; charset=utf-8"
        else:
            data = value.encode()
            content_type = "text/html; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", "zentaosid=local-test-cookie; Path=/zentao/; HttpOnly")
        self.end_headers()
        self.wfile.write(data)

    def view(self, data):
        return {"status": "success", "data": json.dumps(data, ensure_ascii=False), "md5": "unused"}

    def do_GET(self):
        module, method, view, params = self.route()
        if (module, method) == ("user", "refreshRandom"):
            return self.send("12345", cookie=True)
        if module == "wrong":
            return self.send("<html>禅道登录</html>")
        authenticated = "zentaosid=local-test-cookie" in self.headers.get("Cookie", "") and self.server.auth
        if not authenticated:
            return self.send("<html><form>登录</form></html>")
        if (module, method) == ("user", "login"):
            if self.server.mode == "lost_session":
                return self.send({"status": "failed", "reason": "expired"})
            return self.send({"status": "success", "user": {"account": "tester", "token": "local-test-cookie"}})
        if module == "product" and method == "index":
            return self.send(self.view({"products": {"1": "【产品化】示例设备应用"}}))
        if module == "bug" and method == "create":
            if view == "json":
                data = {"products": {"1": "示例设备应用"}, "users": {"developer": "Demo:示例成员"},
                        "projects": {"10": "中屏项目"}, "executions": {"20": "基线软件"},
                        "moduleOptionMenu": {"0": "/", "3": "/播放器"},
                        "builds": {"62": "1.0需求版本8寸", "trunk": "主干"}}
                return self.send(self.view(data))
            probability = ""
            if self.server.probability:
                probability = '<label for="chance">概率</label><select name="chance" id="chance"><option value="1">必现</option><option value="2">偶现</option></select>'
            if self.server.probability_html is not None:
                probability = self.server.probability_html
            priority = getattr(self.server, "priority_html", "") or ""
            return self.send('<form><select name="product"><option value="1">示例设备应用</option></select>'
                             '<select name="openedBuild[]" multiple><option value="62">1.0版本</option></select>'
                             '<input type="hidden" name="csrf_token" value="local-csrf">'
                             '<input type="hidden" name="account" value="evil-field">' + probability + priority + '</form>')
        if module == "bug" and method == "view":
            if self.server.mode == "view_error":
                return self.send("<html>请登录</html>")
            detail = dict(self.server.created)
            if self.server.mode == "wrong_detail":
                detail["title"] = "别人的 Bug"
            return self.send(self.view({"bug": detail}))
        return self.send({"result": "fail"}, status=404)

    def do_POST(self):
        module, method, view, params = self.route()
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.posts.append((module, method, body, dict(self.headers)))
        if not self.headers.get("Referer", "").startswith(self.server.base_url):
            return self.send({"result": "fail", "message": "CSRF"}, status=403)
        if module == "user" and method == "login":
            fields = urllib.parse.parse_qs(body.decode())
            expected = hashlib.md5((hashlib.md5("测试密码abc123".encode()).hexdigest() + "12345").encode()).hexdigest()
            if (fields.get("account") != ["tester"] or fields.get("password") != [expected]
                    or fields.get("verifyRand") != ["12345"]
                    or "zentaosid=local-test-cookie" not in self.headers.get("Cookie", "")):
                return self.send({"status": "failed", "reason": "wrong protocol"})
            if self.server.mode == "fake_login":
                return self.send({"result": "success"})
            if self.server.mode == "wrong_user":
                return self.send({"status": "success", "user": {"account": "guest"}})
            self.server.auth = True
            return self.send({"status": "success", "user": {"account": "tester", "token": "local-test-cookie"}})
        if module != "bug" or method != "create":
            return self.send({"result": "fail"}, status=404)
        multipart = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
        fields, files = {}, []
        for part in multipart.iter_parts():
            key = part.get_param("name", header="content-disposition")
            data = part.get_payload(decode=True)
            filename = part.get_filename()
            if filename is None:
                fields.setdefault(key, []).append(data.decode())
            else:
                files.append((key, filename, data))
        self.server.submitted_fields = fields
        self.server.submitted_files = files
        remote_files = {str(index): {"id": index, "title": filename, "size": len(data)}
                        for index, (_, filename, data) in enumerate(files, 1)}
        if self.server.mode == "partial" and remote_files:
            remote_files.pop(next(iter(remote_files)))
        if self.server.mode == "zero_remote" and remote_files:
            remote_files[next(iter(remote_files))]["size"] = "0"
        self.server.created = {"id": 88, "product": 1, "title": fields["title"][0],
                               "steps": fields["steps"][0], "files": remote_files}
        for key in ("project", "execution", "module", "assignedTo", "feedbackBy", "type", "severity", "pri", "os", "chance"):
            self.server.created[key] = fields.get(key, [""])[0]
        for key, values in fields.items():
            self.server.created.setdefault(key.removesuffix("[]"), ",".join(values))
        self.server.created["openedBuild"] = ",".join(fields["openedBuild[]"])
        if self.server.mode == "ignored_field":
            self.server.created["execution"] = "0"
        if self.server.mode == "ignored_feedback":
            self.server.created.pop("feedbackBy", None)
        if self.server.mode == "ignored_probability":
            self.server.created.pop(self.server.custom_probability_name, None)
        if self.server.mode == "ignored_description":
            self.server.created["steps"] = "<p>[步骤]</p><p>默认模板</p>"
        mode = self.server.mode
        if mode == "drop_response":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if mode == "redirect_post":
            self.send_response(302)
            self.send_header("Location", "/zentao/user-login.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mode == "missing_id":
            return self.send({"result": "success"})
        if mode == "non_json":
            return self.send("<script>parent.location='/zentao/'</script>")
        if mode == "validation":
            return self.send({"result": "fail", "message": {"openedBuild": ["请选择影响版本"]}})
        if mode == "feedback_validation":
            return self.send({"result": "fail", "message": {"feedbackBy": ["请填写反馈者"]}})
        if mode == "probability_validation":
            return self.send({"result": "fail", "message": {self.server.custom_probability_name: ["请填写概率"]}})
        if mode == "after_insert_failure":
            return self.send({"result": "fail", "message": "SQL error 测试密码abc123"})
        if mode == "duplicate":
            return self.send({"result": "success", "id": 88, "locate": "bug-view-88.html", "message": "重复 Bug"})
        return self.send({"result": "success", "id": 88})


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockZenTao)
        self.server.base_url = f"http://127.0.0.1:{self.server.server_port}/zentao/"
        self.server.auth = False
        self.server.path_route = False
        self.server.probability = False
        self.server.probability_html = None
        self.server.custom_probability_name = "frequency"
        self.server.mode = "success"
        self.server.posts = []
        self.server.created = {}
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.client = ZenTaoClient(self.server.base_url, "tester", "测试密码abc123", timeout=3)
        self.bug = {"title": "【示例播放器】语音“别再说了”返回上一界面", "steps": "1. 打开示例播放器\n2. 说 <别再说了>",
                    "actual": "返回上一界面", "expected": "暂停播放", "preconditions": "网络正常"}
        self.settings = {"product": "1", "project": "10", "execution": "20", "module": "3",
                         "openedBuild": ["62", "trunk"], "assignedTo": "developer", "severity": "3", "pri": "4"}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)
        self.temp.cleanup()

    def attachments(self, names=("界面截图.png", "语音复现.mp4")):
        result = []
        for index, name in enumerate(names):
            path = Path(self.temp.name) / str(index) / name
            path.parent.mkdir()
            path.write_bytes(b"\x00binary\xff\r\n--not-the-boundary\x01" + bytes([index]))
            result.append({"id": f"file{index}", "name": name, "path": str(path), "size": path.stat().st_size})
        return result

    def connected(self):
        result = self.client.connect()
        self.assertTrue(result["connected"])
        self.assertEqual(result["options"]["products"][0]["value"], "1")
        return result

    def test_login_hash_cookie_referer_and_identity(self):
        self.connected()
        posts = self.server.posts
        self.assertEqual(len(posts), 1)
        body = posts[0][2]
        self.assertNotIn("测试密码abc123".encode(), body)
        self.assertNotIn(urllib.parse.quote("测试密码abc123").encode(), body)
        self.assertIn("zentaosid=local-test-cookie", posts[0][3]["Cookie"])
        self.assertEqual(posts[0][3]["Referer"], self.server.base_url)

    def test_http_200_or_bare_success_does_not_mean_login(self):
        for mode in ("fake_login", "wrong_user", "lost_session"):
            with self.subTest(mode=mode):
                self.server.mode = mode
                self.server.auth = False
                client = ZenTaoClient(self.server.base_url, "tester", "测试密码abc123")
                with self.assertRaises(ConnectorError) as error:
                    client.connect()
                self.assertFalse(client.connected)
                self.assertFalse(error.exception.uncertain)

    def test_options_and_observed_company_probability(self):
        self.server.probability = True
        self.connected()
        options = self.client.options("1", "10", "20")
        self.assertEqual(options["builds"][1], {"value": "trunk", "label": "主干"})
        self.assertEqual(options["probabilities"], [{"value": "1", "label": "必现"}, {"value": "2", "label": "偶现"}])
        self.settings["probability"] = "1"
        result = self.client.create_bug(self.bug, self.settings, [])
        self.assertEqual(result["id"], 88)
        self.assertEqual(self.server.submitted_fields["chance"], ["1"])

    def test_priority_uses_observed_company_labels_and_values(self):
        self.server.priority_html = ('<select name="pri"><option value="">请选择</option>'
            '<option value="P10">高</option><option value="P20">中</option>'
            '<option value="P30">低</option><option value="P40">极低</option>'
            '<option disabled value="old">旧选项</option></select>')
        self.connected()
        options = self.client.options("1", "10", "20")
        self.assertEqual(options["priorities"], [{"value": "P10", "label": "高"},
            {"value": "P20", "label": "中"}, {"value": "P30", "label": "低"}, {"value": "P40", "label": "极低"}])
        self.settings["pri"] = "P30"
        result = self.client.create_bug(self.bug, self.settings, [])
        self.assertEqual(result["id"], 88)
        self.assertEqual(self.server.submitted_fields["pri"], ["P30"])
        self.assertEqual(self.server.created["pri"], "P30")

    def test_priority_removed_from_company_menu_stops_before_create(self):
        self.server.priority_html = '<select name="pri"><option value="P10">高</option></select>'
        self.connected()
        self.settings["pri"] = "4"
        before = len(self.server.posts)
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, [])
        self.assertIn("优先级", str(error.exception))
        self.assertFalse(error.exception.uncertain)
        self.assertEqual(len(self.server.posts), before)

    def test_unverified_probability_stops_before_write(self):
        self.connected()
        self.settings["probability"] = "必现"
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, [])
        self.assertIn("概率", str(error.exception))
        self.assertFalse(error.exception.uncertain)
        self.assertEqual(len(self.server.posts), 1)

    def test_company_table_probability_saved_label_maps_to_observed_code(self):
        self.server.probability_html = ('<table><tr><th>概率 <span>*</span></th><td>'
            '<select name="frequency" id="customPicker"><option value="">请选择</option>'
            '<option value="always">必现</option><option value="H">高</option>'
            '<option value="M">中</option><option value="L">低</option></select></td></tr></table>')
        self.connected()
        options = self.client.options("1", "10", "20")
        self.assertEqual(options["probability_field"], "frequency")
        self.assertEqual([item["label"] for item in options["probabilities"]], ["必现", "高", "中", "低"])
        for label, code in (("必现", "always"), ("高", "H"), ("中", "M"), ("低", "L")):
            with self.subTest(label=label):
                before = len(self.server.posts)
                self.settings["probability"] = label
                result = self.client.create_bug(self.bug, self.settings, [])
                self.assertEqual(result["id"], 88)
                self.assertEqual(self.server.submitted_fields["frequency"], [code])
                self.assertEqual(len(self.server.posts), before + 1)

    def test_unavailable_or_ambiguous_probability_never_posts(self):
        self.connected()
        for markup, value, message in (
            ('<span class="input-group-addon">概率</span><select name="customFrequency"><option value="">请选择</option></select>', "必现", "没有可用选项"),
            ('<label for="customID">概率</label><select name="customFrequency" id="customID"><option value="A">必现</option><option value="B">必现</option></select>', "必现", "不唯一"),
            ('<label for="chance">概率</label><select name="chance"><option value="1">必现</option></select>', "old-value", "已不在公司菜单"),
            ('<label for="chance">概率</label><select name="chance"><option disabled value="1">必现</option></select>', "1", "没有可用选项"),
        ):
            with self.subTest(markup=markup):
                self.server.probability_html = markup
                self.settings["probability"] = value
                before = len(self.server.posts)
                with self.assertRaises(ConnectorError) as error:
                    self.client.create_bug(self.bug, self.settings, [])
                self.assertIn(message, str(error.exception))
                self.assertFalse(error.exception.uncertain)
                self.assertEqual(len(self.server.posts), before)

    def test_probability_post_detail_and_company_validation_use_actual_name(self):
        self.server.probability_html = ('<div class="input-group"><span class="input-group-addon">概率</span>'
            '<select name="companyCustomRate"><option value="C4">必现</option></select></div>')
        self.server.custom_probability_name = "companyCustomRate"
        self.settings["probability"] = "必现"
        self.connected()
        self.server.mode = "probability_validation"
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, [])
        self.assertIn("发生概率", str(error.exception))
        self.assertFalse(error.exception.uncertain)
        self.server.mode = "ignored_probability"
        before = len(self.server.posts)
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, [])
        self.assertTrue(error.exception.partial)
        self.assertEqual(error.exception.remote_id, 88)
        self.assertEqual(len(self.server.posts), before + 1)

    def test_unfilled_custom_probability_requirement_is_validation(self):
        self.server.probability_html = ('<div class="input-group"><span class="input-group-addon">概率</span>'
            '<select name="frequency"><option value="">请选择</option><option value="A1">必现</option></select></div>')
        self.server.mode = "probability_validation"
        self.connected()
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, [])
        self.assertIn("发生概率", str(error.exception))
        self.assertFalse(error.exception.uncertain)
        self.assertNotIn("frequency", self.server.submitted_fields)

    def test_probability_discovery_absence_returns_actionable_warning(self):
        self.connected()
        options = self.client.options("1", "10", "20")
        self.assertEqual(options["probabilities"], [])
        self.assertIn("概率", options["warnings"][0])
        self.assertEqual(options["probability_diagnostic"]["form_read"], "parsed")
        self.assertEqual(options["probability_diagnostic"]["fields"], [])

    def test_company_reuses_browser_array_for_probability(self):
        # The classic browser slot follows OS in the Bug type row. Company
        # customization can replace its caption and list while retaining its key.
        self.server.probability_html = (
            '<table><tr><th>Bug 类型</th><td><div class="table-col">'
            '<div class="input-group"><span class="input-group-addon">操作系统</span>'
            '<select name="os[]"><option value="android">Android</option></select></div></div>'
            '<div class="table-col"><div class="input-group">'
            '<span class="input-group-addon fix-border">概率</span>'
            '<select name="browser[]" id="browser" class="form-control chosen" multiple>'
            '<option value="">请选择</option><option value="always">必现</option>'
            '<option value="H">高</option><option value="M">中</option><option value="L">低</option>'
            '</select></div></div></td></tr></table>')
        self.server.custom_probability_name = "browser"
        self.connected()
        options = self.client.options("1", "10", "20")
        self.assertEqual(options["probability_field"], "browser[]")
        self.assertEqual([choice["label"] for choice in options["probabilities"]], ["必现", "高", "中", "低"])
        self.assertNotIn("warnings", options)
        self.assertIsNone(options["probability_diagnostic"])
        attachments = self.attachments()
        for label, code in (("必现", "always"), ("高", "H"), ("中", "M"), ("低", "L")):
            with self.subTest(label=label):
                self.settings["probability"] = label
                result = self.client.create_bug(self.bug, self.settings, attachments)
                self.assertEqual(result["id"], 88)
                self.assertEqual(self.server.submitted_fields["browser[]"], [code])
                self.assertNotIn("browser", self.server.submitted_fields)
                self.assertNotIn("probability", self.server.submitted_fields)
                self.assertEqual(self.server.created["browser"], code)
        self.server.mode = "ignored_probability"
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, [])
        self.assertTrue(error.exception.partial)
        self.assertEqual(error.exception.remote_id, 88)
        self.server.mode = "probability_validation"
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, [])
        self.assertFalse(error.exception.uncertain)
        self.assertIn("发生概率", str(error.exception))

    def test_multiple_chinese_files_exact_bytes_and_fields(self):
        self.connected()
        attachments = self.attachments()
        result = self.client.create_bug(self.bug, self.settings, attachments)
        self.assertEqual(result["upload_status"], {"file0": "uploaded", "file1": "uploaded"})
        self.assertEqual(result["id"], 88)
        self.assertIn("bugID=88", result["url"])
        for actual, attachment in zip(self.server.submitted_files, attachments):
            self.assertEqual(actual[0], "files[]")
            self.assertEqual(actual[1], attachment["name"])
            self.assertEqual(actual[2], Path(attachment["path"]).read_bytes())
        fields = self.server.submitted_fields
        self.assertEqual(fields["openedBuild[]"], ["62", "trunk"])
        self.assertEqual(fields["csrf_token"], ["local-csrf"])
        self.assertNotIn("account", fields)
        self.assertIn("&lt;别再说了&gt;", fields["steps"][0])
        self.assertEqual(fields["title"], [self.bug["title"]])

    def test_same_filename_requires_two_confirmed_records(self):
        self.connected()
        attachments = self.attachments(("同名.png", "同名.png"))
        self.server.mode = "partial"
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, attachments)
        self.assertTrue(error.exception.partial)
        self.assertEqual(list(error.exception.upload_status.values()).count("uploaded"), 1)

    def test_feedback_name_is_submitted_as_text_separate_from_creator(self):
        self.connected()
        self.settings["feedbackBy"] = "甲, 乙 & QA"
        result = self.client.create_bug(self.bug, self.settings, [])
        self.assertEqual(result["id"], 88)
        self.assertEqual(self.server.submitted_fields["feedbackBy"], ["甲, 乙 & QA"])
        self.assertNotIn("openedBy", self.server.submitted_fields)

    def test_discarded_feedback_does_not_claim_success_or_create_again(self):
        self.connected()
        self.settings["feedbackBy"] = "测试反馈者"
        self.server.mode = "ignored_feedback"
        before = len(self.server.posts)
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, [])
        self.assertTrue(error.exception.partial)
        self.assertEqual(error.exception.remote_id, 88)
        self.assertEqual(len(self.server.posts), before + 1)

    def test_feedback_too_long_stops_before_create(self):
        self.connected()
        self.settings["feedbackBy"] = "测" * 101
        before = len(self.server.posts)
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, [])
        self.assertIn("反馈者", str(error.exception))
        self.assertFalse(error.exception.uncertain)
        self.assertEqual(len(self.server.posts), before)

    def test_company_feedback_requirement_has_actionable_validation(self):
        self.connected()
        self.server.mode = "feedback_validation"
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, [])
        self.assertIn("反馈者", str(error.exception))
        self.assertFalse(error.exception.uncertain)
        self.assertFalse(error.exception.partial)

    def test_nested_same_basename_has_distinct_deterministic_upload_names(self):
        self.connected()
        attachments = self.attachments(("界面.png", "界面.png"))
        attachments[0]["name"] = "第一组/界面.png"
        attachments[1]["name"] = "第二组\\界面.png"
        result = self.client.create_bug(self.bug, self.settings, attachments)
        self.assertEqual(result["upload_status"], {"file0": "uploaded", "file1": "uploaded"})
        names = [file[1] for file in self.server.submitted_files]
        self.assertNotEqual(names[0], names[1])
        for name, attachment in zip(names, attachments):
            self.assertNotIn("/", name)
            self.assertNotIn("\\", name)
            self.assertTrue(name.endswith(".png"))
            self.assertEqual(name, self.client._upload_name(attachment))

    def test_created_but_ignored_fields_or_description_is_partial(self):
        self.connected()
        for mode in ("ignored_field", "ignored_description"):
            with self.subTest(mode=mode):
                self.server.mode = mode
                with self.assertRaises(ConnectorError) as error:
                    self.client.create_bug(self.bug, self.settings, [])
                self.assertTrue(error.exception.partial)
                self.assertEqual(error.exception.remote_id, 88)

    def test_partial_upload_zero_size_and_unreadable_detail_never_success(self):
        self.connected()
        attachments = self.attachments()
        for mode in ("partial", "zero_remote", "view_error", "wrong_detail", "duplicate"):
            with self.subTest(mode=mode):
                self.server.mode = mode
                with self.assertRaises(ConnectorError) as error:
                    self.client.create_bug(self.bug, self.settings, attachments)
                self.assertTrue(error.exception.partial)
                self.assertEqual(error.exception.remote_id, 88)
                self.assertIn("88", error.exception.remote_url)

    def test_unknown_write_outcomes_are_not_retried(self):
        self.connected()
        for mode in ("drop_response", "redirect_post", "missing_id", "non_json", "after_insert_failure"):
            with self.subTest(mode=mode):
                self.server.mode = mode
                before = len(self.server.posts)
                with self.assertRaises(ConnectorError) as error:
                    self.client.create_bug(self.bug, self.settings, [])
                self.assertTrue(error.exception.uncertain)
                self.assertFalse(error.exception.partial)
                self.assertNotIn("测试密码abc123", str(error.exception))
                self.assertEqual(len(self.server.posts), before + 1)

    def test_validation_failure_can_be_corrected(self):
        self.connected()
        self.server.mode = "validation"
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, [])
        self.assertFalse(error.exception.uncertain)
        self.assertFalse(error.exception.partial)
        self.assertIn("影响版本", str(error.exception))

    def test_local_preflight_failure_makes_no_creation_request(self):
        self.connected()
        attachments = self.attachments()
        Path(attachments[0]["path"]).write_bytes(b"")
        with self.assertRaises(ConnectorError) as error:
            self.client.create_bug(self.bug, self.settings, attachments)
        self.assertFalse(error.exception.uncertain)
        self.assertEqual(len(self.server.posts), 1)

    def test_classic_path_route_read_discovery_and_single_write(self):
        self.server.path_route = True
        self.connected()
        result = self.client.create_bug(self.bug, self.settings, self.attachments())
        self.assertEqual(result["id"], 88)
        self.assertIn("bug-view-88.html", result["url"])
        self.assertEqual(len(self.server.posts), 2)

    def test_invalid_url_and_missing_required_content(self):
        for url in ("localhost/zentao", "file:///zentao", "http://user:pass@example.test/zentao/", "https://host:bad"):
            with self.subTest(url=url), self.assertRaises(ConnectorError):
                ZenTaoClient(url, "u", "p")
        self.connected()
        for field in ("title", "steps", "actual", "expected"):
            bug = {**self.bug, field: ""}
            with self.subTest(field=field), self.assertRaises(ConnectorError):
                self.client.create_bug(bug, self.settings, [])
        self.assertEqual(len(self.server.posts), 1)


class ProbabilityCaptionTests(unittest.TestCase):
    @staticmethod
    def parse(markup):
        parser = _FormParser()
        parser.feed(markup)
        return ZenTaoClient._probability_field(parser)

    def test_name_and_id_can_differ(self):
        name, choices = self.parse('<label for="ratePicker">发生概率</label><select name="extension12" id="ratePicker">'
                                   '<option value="99">必现</option></select>')
        self.assertEqual(name, "extension12")
        self.assertEqual(choices, [{"value": "99", "label": "必现"}])

    def test_repurposed_browser_requires_its_exact_local_caption(self):
        for name in ("browser", "browser[]"):
            with self.subTest(name=name):
                self.assertEqual(self.parse('<div class="input-group">'
                    '<span class="input-group-addon">概率<span>*</span></span>'
                    f'<select name="{name}"><option value="observed">必现</option></select></div>'),
                    (name, [{"value": "observed", "label": "必现"}]))
        for markup in (
            '<span class="input-group-addon">浏览器</span><select name="browser[]"><option value="chrome">Chrome</option></select>',
            '<select name="browser"><option value="always">必现</option><option value="H">高</option></select>',
            '<span class="input-group-addon">概率说明</span><select name="browser[]"><option value="1">必现</option></select>',
            '<table><tr><th>概率</th><td><select name="browser[]"><option value="1">必现</option></select><select name="os"><option value="linux">Linux</option></select></td></tr></table>',
            '<div class="input-group"><span class="input-group-addon">概率</span><select name="chance"><option value="1">必现</option></select><select name="browser"><option value="chrome">Chrome</option></select></div>',
        ):
            with self.subTest(markup=markup):
                name, _ = self.parse(markup)
                self.assertNotIn(name, ("browser", "browser[]"))

    def test_input_group_caption_does_not_capture_type_os_or_priority(self):
        markup = ('<table><tr><th>Bug 类型</th><td><div class="input-group">'
                  '<select name="type"><option value="codeerror">代码错误</option></select>'
                  '<span class="input-group-addon">操作系统</span>'
                  '<select name="os"><option value="android">Android</option></select>'
                  '<span class="input-group-addon fix-border">概率<span class="required">*</span></span>'
                  '<div class="picker-wrapper"><select name="customFrequency"><option value="P1">必现</option>'
                  '<option value="P2">高</option><option value="P3">中</option><option value="P4">低</option></select></div>'
                  '<span class="input-group-addon">优先级</span><select name="pri"><option value="4">低</option></select>'
                  '</div></td></tr></table>')
        name, choices = self.parse(markup)
        self.assertEqual(name, "customFrequency")
        self.assertEqual([item["value"] for item in choices], ["P1", "P2", "P3", "P4"])

    def test_table_caption_and_wrapping_label_are_supported(self):
        for markup in (
            '<table><tr><th>发生概率</th><td><div><select name="xRate"><option value="R1">必现</option></select></div></td></tr></table>',
            '<label>发生概率<select name="xRate"><option value="R1">必现</option></select></label>',
        ):
            with self.subTest(markup=markup):
                self.assertEqual(self.parse(markup), ("xRate", [{"value": "R1", "label": "必现"}]))

    def test_frequency_name_and_lookalike_labels_do_not_prove_probability(self):
        for markup in (
            '<label for="frequency">采样频率</label><select name="frequency"><option value="1">高</option></select>',
            '<select name="frequency"><option value="1">必现</option><option value="2">高</option></select>',
            '<div><span>此处不是概率字段说明</span><select name="other"><option value="1">必现</option></select></div>',
            '<table><tr><th>概率</th><td><select name="unrelatedA"><option value="1">必现</option></select><select name="unrelatedB"><option value="2">高</option></select></td></tr></table>',
        ):
            with self.subTest(markup=markup):
                self.assertEqual(self.parse(markup), ("", []))

    def test_multiple_matching_fields_are_rejected(self):
        with self.assertRaises(ConnectorError):
            self.parse('<label for="first">概率</label><select id="first" name="first"><option value="1">必现</option></select>'
                       '<label for="second">发生概率</label><select id="second" name="second"><option value="2">必现</option></select>')

    def test_disabled_control_and_placeholder_values_are_not_usable(self):
        self.assertEqual(self.parse('<select disabled name="chance"><option value="1">必现</option></select>'), ("", []))
        self.assertEqual(self.parse('<select name="chance"><option value="">请选择</option><option value="1" disabled>必现</option></select>'), ("chance", []))
        self.assertEqual(self.parse('<select name="chance"><optgroup disabled><option value="1">必现</option></optgroup><option value="2">高</option></select>'),
                         ("chance", [{"value": "2", "label": "高"}]))

    def test_implicit_html_option_values_use_actual_browser_text(self):
        self.assertEqual(self.parse('<label for="custom">概率</label><select name="custom"><option>必现</option><option>高</option></select>'),
                         ("custom", [{"value": "必现", "label": "必现"}, {"value": "高", "label": "高"}]))


if __name__ == "__main__":
    unittest.main()
