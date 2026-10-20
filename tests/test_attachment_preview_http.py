"""Read-only attachment preview API checks using synthetic local evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app import Application, Handler, ThreadingHTTPServer


class AttachmentPreviewHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.folder = root / "evidence" / "synthetic bug"
        self.folder.mkdir(parents=True)
        self.app = Application(root / "data")
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

    def request(self, route, headers=None):
        return urlopen(Request(self.url + route, headers=headers or {}), timeout=5)

    def scan(self, files):
        for name, data in files.items():
            (self.folder / name).write_bytes(data)
        state = self.app.workbench.scan(str(self.folder.parent))
        bug = state["bugs"][0]
        urls = {entry["name"]: "/api/attachment?" + urlencode({
            "bug_id": bug["id"], "attachment_id": entry["id"]})
            for entry in bug["attachments"]}
        return bug, urls

    def preview(self, url):
        with self.request(url.replace("/api/attachment?", "/api/attachment-preview?")) as response:
            self.assertTrue(response.headers["Content-Type"].startswith("application/json"))
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            return json.load(response)

    def test_plain_text_preview_preserves_evidence_and_drafts(self):
        text = "中文日志\n<script>alert('synthetic')</script>"
        _, urls = self.scan({"日志.log": text.encode("gb18030")})
        before_state = self.app.state()
        before_hash = hashlib.sha256((self.folder / "日志.log").read_bytes()).hexdigest()
        result = self.preview(urls["日志.log"])
        self.assertEqual(result["kind"], "text")
        self.assertEqual(result["text"], text)
        self.assertEqual(self.app.state(), before_state)
        self.assertEqual(hashlib.sha256((self.folder / "日志.log").read_bytes()).hexdigest(), before_hash)

    def test_unknown_ids_and_external_origin_cannot_read_files(self):
        _, urls = self.scan({"log.txt": b"synthetic log"})
        with self.assertRaises(HTTPError) as failure:
            self.request("/api/attachment-preview?bug_id=unknown&attachment_id=../../secret")
        self.assertEqual(failure.exception.code, 400)
        with self.assertRaises(HTTPError) as failure:
            self.request(urls["log.txt"].replace("/api/attachment?", "/api/attachment-preview?"),
                         {"Origin": "https://external.invalid"})
        self.assertEqual(failure.exception.code, 403)

    def test_pdf_is_frameable_only_from_own_origin_and_range_still_works(self):
        pdf = b"%PDF-1.4\nsynthetic preview fixture\n%%EOF"
        _, urls = self.scan({"report.pdf": pdf, "fake.pdf": b"<html>synthetic</html>"})
        with self.request(urls["report.pdf"], {"Range": "bytes=0-7"}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), pdf[:8])
            self.assertEqual(response.headers["Content-Type"], "application/pdf")
            self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
            self.assertIn("frame-ancestors 'self'", response.headers["Content-Security-Policy"])
            self.assertIn("object-src 'self'", response.headers["Content-Security-Policy"])
            self.assertTrue(response.headers["Content-Disposition"].startswith("inline;"))
        for name, suffix in (("fake.pdf", ""), ("report.pdf", "&download=1")):
            with self.request(urls[name] + suffix) as response:
                self.assertTrue(response.headers["Content-Disposition"].startswith("attachment;"))
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")

    def test_html_attachment_is_text_preview_and_raw_download_never_html(self):
        source = b"<html><script>synthetic()</script><h1>evidence</h1></html>"
        _, urls = self.scan({"page.html": source})
        result = self.preview(urls["page.html"])
        self.assertEqual(result["kind"], "text")
        self.assertEqual(result["text"], source.decode())
        with self.request(urls["page.html"]) as response:
            self.assertEqual(response.headers["Content-Type"], "application/octet-stream")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertTrue(response.headers["Content-Disposition"].startswith("attachment;"))

    def test_media_preview_and_explicit_download(self):
        _, urls = self.scan({"recording.mp4": b"0123456789", "unknown.bin": b"\x00\x01\x02"})
        with self.request(urls["recording.mp4"], {"Range": "bytes=2-5"}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"2345")
            self.assertTrue(response.headers["Content-Type"].startswith("video/"))
        with self.request(urls["recording.mp4"] + "&download=1") as response:
            self.assertTrue(response.headers["Content-Disposition"].startswith("attachment;"))
        self.assertEqual(self.preview(urls["unknown.bin"])["kind"], "unsupported")

    def test_removed_evidence_is_rejected(self):
        _, urls = self.scan({"gone.log": b"synthetic log"})
        (self.folder / "gone.log").unlink()
        with self.assertRaises(HTTPError) as failure:
            self.preview(urls["gone.log"])
        self.assertEqual(failure.exception.code, 400)

    def test_viewer_assets_and_page_csp(self):
        for asset in ("/attachment_preview.js", "/attachment_preview.css"):
            with self.request(asset) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())
        with self.request("/") as response:
            csp = response.headers["Content-Security-Policy"]
            self.assertIn("frame-src 'self'", csp)
            self.assertIn("object-src 'none'", csp)
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")


if __name__ == "__main__":
    unittest.main()
