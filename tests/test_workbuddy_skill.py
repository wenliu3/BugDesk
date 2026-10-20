"""Exercise the portable skill through real PowerShell and isolated loopback HTTP."""

import json
import shutil
import subprocess
import threading
import unittest
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import test_app


SCRIPT = Path(__file__).resolve().parents[1] / "integrations" / "bugdesk-workbuddy" / "scripts" / "bugdesk.ps1"
RUNTIMES = list(dict.fromkeys(path for command in ("powershell.exe", "pwsh.exe")
                              if (path := shutil.which(command))))


@unittest.skipUnless(RUNTIMES, "PowerShell runtime is not installed")
class WorkBuddySkillTests(unittest.TestCase):
    setUp = test_app.HTTPTests.setUp
    tearDown = test_app.HTTPTests.tearDown

    def invoke(self, runtime, connection_file, action="context", input_file=None):
        command = [runtime, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                   "-Action", action, "-ConnectionFile", str(connection_file)]
        if input_file is not None:
            command.extend(["-InputFile", str(input_file)])
        result = subprocess.run(command, capture_output=True, timeout=45)
        self.assertEqual(result.stderr, b"")
        output = result.stdout.decode("utf-8-sig")
        secret = json.loads(Path(connection_file).read_text(encoding="utf-8"))["token"]
        self.assertNotIn(secret, output)
        self.assertNotIn(str(connection_file), output)
        return result.returncode, json.loads(output)

    @contextmanager
    def accepting_stage_server(self):
        """Record requests without server validation, to test the helper's boundary."""
        instance = "isolated-grouped-script-instance"
        secret = "isolated_grouped_token_12345678901234567890"
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, value):
                data = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path != "/health":
                    self.send_error(404)
                    return
                self.respond({"app": "BugDesk", "instance": instance})

            def do_POST(self):
                if self.path != "/api/workbuddy/stage" or self.headers.get("X-BugDesk-WorkBuddy-Token") != secret:
                    self.send_error(403)
                    return
                value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append(value)
                count = len(value["rows"])
                self.respond({"plan_id": "isolated-stage-plan", "summary": {
                    "total": count, "exact": 0, "suggested": count, "unmatched": 0}})

        server = HTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            connection = Path(self.temp.name) / "isolated-grouped-script-session.json"
            connection.write_text(json.dumps({"schema": 1, "url": f"http://127.0.0.1:{server.server_port}/",
                "instance": instance, "token": secret,
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}), encoding="utf-8")
            yield connection, received
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    @staticmethod
    def grouped_row():
        source = {"case_id": "DEMO-CA1", "title": "来源用例一", "group": "演示/故事", "tester": "测试人员",
                  "date": "2026-10-19T12:34:56Z", "preconditions": "已启动\n处于首页",
                  "steps": "1.语音：讲个恐怖故事", "expected": "不播报恐怖故事",
                  "actual": "【示例版本】设备仍播报故事", "source_actual": "【示例版本】设备仍播报故事"}
        second = {**source, "case_id": "DEMO-CA2", "title": "来源用例二",
                  "steps": "1.语音：讲个鬼故事", "expected": "不播报鬼故事"}
        return {"case_id": "", "title": "两个故事请求场景", "group": "演示/故事", "tester": "", "date": "",
                "preconditions": source["preconditions"],
                "steps": "场景一：讲个恐怖故事\n场景二：讲个鬼故事",
                "expected": "场景一：不播报恐怖故事\n场景二：不播报鬼故事",
                "actual": "场景一、场景二：设备仍播报故事", "source_actual": source["source_actual"],
                "review_notes": [], "suggested_bug_id": "isolated-bug", "match_reason": "两个场景与草稿问题对应。",
                "candidate_bug_ids": [], "source_cases": [source, second]}

    def test_grouped_and_legacy_payloads_preserve_sources_through_helper(self):
        grouped = self.grouped_row()
        # Source remarks are optional, even when the parent has a common remark.
        del grouped["source_cases"][1]["source_actual"]
        legacy = {key: value for key, value in grouped.items() if key != "source_cases"}
        legacy["case_id"] = "DEMO-CA3"
        maximum = deepcopy(grouped)
        maximum["source_cases"] = [dict(grouped["source_cases"][0], case_id=f"DEMO-CA{index}")
                                   for index in range(300)]
        with self.accepting_stage_server() as (connection, received):
            for runtime in RUNTIMES:
                for rows in ([grouped, legacy], [maximum]):
                    with self.subTest(runtime=runtime, rows=len(rows), sources=len(rows[0]["source_cases"])):
                        payload = {"context_id": "grouped-script-context", "rows": rows}
                        source_file = Path(self.temp.name) / "组合建议.json"
                        source_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
                        code, result = self.invoke(runtime, connection, "stage", source_file)
                        self.assertEqual(code, 0, result)
                        self.assertEqual(result["summary"]["total"], len(rows))
                        self.assertEqual(received[-1], payload)

    def test_source_case_validation_stops_invalid_payloads_before_post(self):
        original = self.grouped_row()
        invalid = []
        for name, value in (("empty", []), ("object", original["source_cases"][0]),
                            ("null", None), ("too_many", [original["source_cases"][0]] * 301),
                            ("bad_item", ["not a case"])):
            invalid.append((name, [{**original, "source_cases": value}]))
        for name, field, value in (("unknown", "attachment_path", "private.png"),
                                   ("wrong_type", "steps", 123), ("nul", "case_id", "unsafe\u0000id"),
                                   ("long_fact", "actual", "x" * 20001),
                                   ("long_remark", "source_actual", "x" * 20001),
                                   ("long_title", "title", "x" * 1001)):
            row = deepcopy(original)
            row["source_cases"][0][field] = value
            invalid.append((name, [row]))
        missing = deepcopy(original)
        del missing["source_cases"][0]["case_id"]
        invalid.append(("missing_source_field", [missing]))
        full = {**original, "source_cases": [original["source_cases"][0]] * 300}
        legacy = {key: value for key, value in original.items() if key != "source_cases"}
        invalid.append(("mixed_total_over_300", [full, legacy]))
        with self.accepting_stage_server() as (connection, received):
            for runtime in RUNTIMES:
                for name, rows in invalid:
                    with self.subTest(runtime=runtime, invalid=name):
                        source_file = Path(self.temp.name) / "非法组合建议.json"
                        source_file.write_text(json.dumps({"context_id": "grouped-script-context", "rows": rows},
                                                         ensure_ascii=False), encoding="utf-8")
                        code, result = self.invoke(runtime, connection, "stage", source_file)
                        self.assertEqual(code, 1, result)
                        self.assertFalse(result["ok"])
                        self.assertEqual(received, [], "Invalid source cases must never reach the stage endpoint")

    def test_large_real_context_and_small_stage_preserve_all_facts(self):
        evidence = Path(self.temp.name) / "isolated-demo"
        for index in range(14):
            (evidence / f"PD1-CA{index}_测试问题").mkdir(parents=True)
        state = self.app.workbench.scan(str(evidence), demo=True)
        prefix = "1.打开\n2.等待\n"
        facts = prefix + "甲" * (20000 - len(prefix))
        self.app.workbench.save({"bugs": [{"id": bug["id"], **{
            field: facts for field in ("preconditions", "steps", "expected", "actual")
        }} for bug in state["bugs"]]})
        status = self.app.workbuddy.enable()
        connection = Path(status["connection_file"])
        before = self.app.workbench.state()
        for runtime in RUNTIMES:
            with self.subTest(runtime=runtime):
                code, context = self.invoke(runtime, connection)
                self.assertEqual(code, 0)
                self.assertTrue(context["demo"])
                encoded = json.dumps(context, ensure_ascii=False).encode("utf-8")
                self.assertGreater(len(encoded), 1024 * 1024)
                self.assertLess(len(encoded), 8 * 1024 * 1024)
                self.assertEqual(len(context["bugs"]), 14)
                for bug in context["bugs"]:
                    for field in ("preconditions", "steps", "expected", "actual"):
                        self.assertEqual(bug[field], facts)
                bug = context["bugs"][0]
                row = {"case_id": "", "title": "隔离用例", "group": "演示", "tester": "测试人员",
                       "date": "2026-10-15T12:34:56Z", "preconditions": "已启动",
                       "steps": "1.打开视频\n2.语音：别播了", "expected": "视频暂停\n保持当前页面",
                       "actual": "返回上一页", "suggested_bug_id": bug["id"],
                       "match_reason": "仅用于本机兼容性测试。", "candidate_bug_ids": [bug["id"]],
                       "source_actual": "【1.0需求版本】返回上一页", "review_notes": ["需要确认发生时间。"]}
                source = Path(self.temp.name) / "建议.json"
                source.write_text(json.dumps({"context_id": context["context_id"], "rows": [row]},
                                             ensure_ascii=False), encoding="utf-8-sig")
                code, staged = self.invoke(runtime, connection, "stage", source)
                self.assertEqual(code, 0)
                self.assertEqual(staged["summary"]["total"], 1)
                pending = self.app.workbuddy.status()["pending"]
                self.assertEqual(pending["rows"][0]["steps"], row["steps"])
                self.assertEqual(pending["rows"][0]["expected"], row["expected"])
                self.assertEqual(pending["rows"][0]["date"], row["date"])
                self.assertEqual(pending["rows"][0]["source_actual"], row["source_actual"])
                self.assertEqual(pending["rows"][0]["review_notes"], row["review_notes"])
                self.assertEqual(self.app.workbench.state(), before)

    def test_stage_input_over_one_mib_is_still_rejected(self):
        evidence = Path(self.temp.name) / "isolated-demo"
        (evidence / "测试问题").mkdir(parents=True)
        self.app.workbench.scan(str(evidence), demo=True)
        status = self.app.workbuddy.enable()
        connection = Path(status["connection_file"])
        source = Path(self.temp.name) / "过大的建议.json"
        # This is valid JSON whose size, rather than syntax, must stop the stage.
        source.write_text(json.dumps({"context_id": "unused", "rows": [], "padding": "x" * (1024 * 1024)}),
                          encoding="utf-8")
        before = self.app.workbench.state()
        for runtime in RUNTIMES:
            with self.subTest(runtime=runtime):
                code, result = self.invoke(runtime, connection, "stage", source)
                self.assertEqual(code, 1)
                self.assertIn("1 MiB", result["error"])
                self.assertIsNone(self.app.workbuddy.status()["pending"])
                self.assertEqual(self.app.workbench.state(), before)

    def test_network_context_over_eight_mib_is_rejected_without_partial_output(self):
        instance = "isolated-script-instance"
        secret = "isolated_script_token_12345678901234567890"
        body = json.dumps({"context_id": "large-context", "padding": "x" * (8 * 1024 * 1024)}).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/health":
                    data = json.dumps({"app": "BugDesk", "instance": instance}).encode("utf-8")
                elif self.path == "/api/workbuddy/context" and self.headers.get("X-BugDesk-WorkBuddy-Token") == secret:
                    data = body
                else:
                    self.send_error(403)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            connection = Path(self.temp.name) / "isolated-script-session.json"
            connection.write_text(json.dumps({"schema": 1, "url": f"http://127.0.0.1:{server.server_port}/",
                "instance": instance, "token": secret,
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}), encoding="utf-8")
            for runtime in RUNTIMES:
                with self.subTest(runtime=runtime):
                    code, result = self.invoke(runtime, connection)
                    self.assertEqual(code, 1)
                    self.assertFalse(result["ok"])
                    self.assertIn("8 MiB", result["error"])
                    self.assertEqual(set(result), {"ok", "error"})
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
