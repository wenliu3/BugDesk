"""Synthetic attachment formats must remain bounded, read-only and text-only."""

import codecs
import hashlib
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import attachment_preview as preview


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"


class AttachmentPreviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def file(self, name, data):
        path = self.base / name
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    def archive(self, name, parts):
        path = self.base / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for part, data in parts.items():
                archive.writestr(part, data)
        return path

    def docx(self, body, encoding="utf-8"):
        text = f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
        return self.archive("证据.docx", {"word/document.xml": text.encode(encoding)})

    def xlsx(self, rows, extra=None, sheet_count=1, target="worksheets/sheet1.xml", mode=""):
        sheets = "".join(f'<sheet name="工作表 {index}" sheetId="{index}" r:id="rId{index}"/>'
                         for index in range(1, sheet_count + 1))
        relationships = "".join(f'<Relationship Id="rId{index}" Target="{target}" {mode}/>'
                                for index in range(1, sheet_count + 1))
        parts = {
            "xl/workbook.xml": f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets>{sheets}</sheets></workbook>',
            "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{REL}">{relationships}</Relationships>',
            "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{S}"><sheetData>{rows}</sheetData></worksheet>',
        }
        parts.update(extra or {})
        return self.archive("测试表.xlsx", parts)

    def test_utf8_html_markdown_and_xml_remain_original_plain_text(self):
        for suffix in (".txt", ".log", ".html", ".md", ".xml", ".svg", ".js"):
            with self.subTest(suffix=suffix):
                content = '<script>alert("测试")</script>\n**原文** &amp;'
                result = preview.preview_attachment(self.file("日志" + suffix, content))
                self.assertEqual(result["kind"], "text")
                self.assertEqual(result["text"], content)
                self.assertEqual(result["encoding"], "UTF-8")
                self.assertFalse(result["truncated"])
                self.assertEqual(result["name"], "日志" + suffix)

    def test_bom_utf8_utf16_and_gb18030(self):
        for encoding, expected in (("utf-8-sig", "UTF-8"), ("utf-16", "UTF-16"), ("gb18030", "GB18030")):
            with self.subTest(encoding=encoding):
                content = "设备异常：中文𠀀\n下一行"
                result = preview.preview_attachment(self.file("编码.log", content.encode(encoding)))
                self.assertEqual(result["text"], content)
                self.assertEqual(result["encoding"], expected)

    def test_plain_xml_declarations_remain_text_and_are_never_parsed(self):
        content = '<!DOCTYPE evidence [<!ENTITY x "text">]><evidence>&x;</evidence>'
        result = preview.preview_attachment(self.file("证据.xml", content))
        self.assertEqual(result["kind"], "text")
        self.assertEqual(result["text"], content)

    def test_text_truncates_at_multibyte_boundary_without_replacement_characters(self):
        path = self.file("很长.log", "中" * (preview.MAX_TEXT_BYTES // 3 + 10))
        result = preview.preview_attachment(path)
        self.assertEqual(result["kind"], "text")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["text"], "中" * (preview.MAX_TEXT_BYTES // 3))
        self.assertIn("原文件", result["notice"])
        self.assertLessEqual(len(result["text"].encode("utf-8")), preview.MAX_TEXT_BYTES)

    def test_utf16_truncation_ignores_partial_surrogate_pair(self):
        with patch.object(preview, "MAX_TEXT_BYTES", 9):
            result = preview.preview_attachment(self.file("编码.txt", "A😀B😀".encode("utf-16")))
        self.assertEqual(result["text"], "A😀")
        self.assertTrue(result["truncated"])

    def test_binary_disguised_as_text_is_not_displayed(self):
        for content in (b"hello\x00world", b"\x89PNG\r\n\x1a\n", bytes(range(1, 32)) * 10,
                        b"MZ\x00binary payload"):
            with self.subTest(content=content[:5]):
                result = preview.preview_attachment(self.file("证据.txt", content))
                self.assertEqual(result["kind"], "unsupported")
                self.assertNotIn("text", result)

    def test_extensionless_utf8_and_rotated_log_are_supported(self):
        for name in ("README", ".env", "device.log.1"):
            with self.subTest(name=name):
                result = preview.preview_attachment(self.file(name, "文字\nnext"))
                self.assertEqual(result["kind"], "text")

    def test_extensionless_non_utf8_is_not_guessed(self):
        result = preview.preview_attachment(self.file("binary", "中文".encode("gb18030")))
        self.assertEqual(result["kind"], "unsupported")

    def test_executables_unknown_and_legacy_formats_are_never_opened(self):
        for name in ("a.exe", "a.dll", "a.unknown", "a.doc", "a.xls", "a.ppt", "a.rar", "a.7z"):
            with self.subTest(name=name), patch.object(Path, "open", side_effect=AssertionError("must not open")):
                result = preview.preview_attachment(self.base / name)
                self.assertEqual(result["kind"], "unsupported")
                self.assertTrue(result["message"])

    def test_empty_text_is_valid(self):
        result = preview.preview_attachment(self.file("empty.log", b""))
        self.assertEqual(result["text"], "")
        self.assertEqual(result["size"], 0)

    def test_csv_quoted_newlines_and_formulas_are_data(self):
        content = '名称,备注\r\n设备,"两行\n文字"\r\n=HYPERLINK(""),<script>\r\n'
        result = preview.preview_attachment(self.file("测试.csv", codecs.BOM_UTF8 + content.encode("utf-8")))
        self.assertEqual(result["kind"], "table")
        self.assertEqual(result["sheets"][0]["rows"],
                         [["名称", "备注"], ["设备", "两行\n文字"], ['=HYPERLINK("")', "<script>"]])
        self.assertFalse(result["truncated"])

    def test_tsv_gb18030(self):
        result = preview.preview_attachment(self.file("表.tsv", "用例\t结果\n甲\t失败".encode("gb18030")))
        self.assertEqual(result["sheets"][0]["rows"][1], ["甲", "失败"])
        self.assertEqual(result["encoding"], "GB18030")

    def test_csv_row_column_and_cell_limits(self):
        path = self.file("large.csv", ",".join(["x" * 12] * 5) + "\n" + "a,b\n" * 5)
        with patch.object(preview, "MAX_CSV_ROWS", 3), patch.object(preview, "MAX_TABLE_COLUMNS", 2), \
                patch.object(preview, "MAX_CELL_CHARS", 8):
            result = preview.preview_attachment(path)
        rows = result["sheets"][0]["rows"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], ["x" * 8, "x" * 8])
        self.assertTrue(result["truncated"])
        self.assertTrue(result["sheets"][0]["truncated"])

    def test_malformed_csv_falls_back_without_echoing_contents(self):
        result = preview.preview_attachment(self.file("broken.csv", 'private,"unterminated'))
        self.assertEqual(result["kind"], "unsupported")
        self.assertNotIn("private", result["message"])

    def test_docx_paragraphs_tabs_and_breaks(self):
        path = self.docx('<w:p><w:r><w:t>前置</w:t><w:tab/><w:t>条件</w:t><w:br/><w:t>下一行</w:t>'
                         '</w:r></w:p><w:p><w:r><w:t>步骤 &amp; 结果</w:t></w:r></w:p>')
        result = preview.preview_attachment(path)
        self.assertEqual(result["kind"], "document")
        self.assertEqual(result["text"], "前置\t条件\n下一行\n步骤 & 结果")
        self.assertFalse(result["truncated"])
        self.assertIn("正文", result["notice"])

    def test_docx_text_output_is_bounded(self):
        path = self.docx('<w:p><w:r><w:t>' + "x" * 200 + '</w:t></w:r></w:p>')
        with patch.object(preview, "MAX_OUTPUT_CHARS", 80):
            result = preview.preview_attachment(path)
        self.assertEqual(result["text"], "x" * 80)
        self.assertTrue(result["truncated"])

    def test_xlsx_multiple_sheets_rich_text_and_cached_formulas(self):
        rows = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr">'
                '<is><r><t>设备</t></r><r><t>异常</t></r></is></c><c r="C1"><f>1+2</f><v>3</v></c>'
                '<c r="D1" t="b"><v>1</v></c><c r="E1"><f>HYPERLINK("https://example.invalid")</f></c></row>')
        path = self.xlsx(rows, {"xl/sharedStrings.xml": f'<sst xmlns="{S}"><si><t>用例 A</t></si></sst>'}, sheet_count=2)
        result = preview.preview_attachment(path)
        self.assertEqual(len(result["sheets"]), 2)
        self.assertEqual(result["sheets"][0]["name"], "工作表 1")
        self.assertEqual(result["sheets"][1]["rows"][0],
                         ["用例 A", "设备异常", "3", "TRUE", '=HYPERLINK("https://example.invalid")'])
        self.assertIn("公式不执行", result["notice"])
        self.assertFalse(result["truncated"])

    def test_xlsx_sparse_coordinates_do_not_allocate_huge_arrays(self):
        rows = ('<row r="2"><c r="D2"><v>42</v></c><c r="XFD2"><v>discard</v></c></row>'
                '<row r="9999999"><c r="A9999999"><v>discard</v></c></row>'
                '<row r="3"><c r="A999999999999999999999"><v>discard</v></c></row>')
        result = preview.preview_attachment(self.xlsx(rows))
        self.assertEqual(result["sheets"][0]["rows"], [[], ["", "", "", "42"]])
        self.assertTrue(result["sheets"][0]["truncated"])
        self.assertTrue(result["truncated"])

    def test_xlsx_out_of_range_shared_string_index_does_not_allocate(self):
        result = preview.preview_attachment(self.xlsx('<row><c t="s"><v>9999999999999999999999</v></c></row>'))
        self.assertTrue(result["truncated"])
        self.assertIn("超出", result["sheets"][0]["rows"][0][0])

    def test_xlsx_sheet_and_global_output_limits(self):
        path = self.xlsx('<row><c t="inlineStr"><is><t>' + "x" * 100 + '</t></is></c></row>', sheet_count=3)
        with patch.object(preview, "MAX_SHEETS", 2), patch.object(preview, "MAX_OUTPUT_CHARS", 50):
            result = preview.preview_attachment(path)
        self.assertEqual(len(result["sheets"]), 1)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(sum(len(cell) for sheet in result["sheets"] for row in sheet["rows"] for cell in row), 50)

    def test_office_external_relationship_is_not_opened(self):
        result = preview.preview_attachment(self.xlsx('<row/>', target="https://example.invalid/private", mode='TargetMode="External"'))
        self.assertEqual(result["kind"], "table")
        self.assertEqual(result["sheets"][0]["rows"], [])
        self.assertTrue(result["truncated"])

    def test_office_relationship_cannot_escape_its_namespace(self):
        result = preview.preview_attachment(self.xlsx('<row/>', target="../../word/document.xml"))
        self.assertEqual(result["sheets"][0]["rows"], [])
        self.assertTrue(result["truncated"])

    def test_pptx_uses_slide_order_and_namespace_relationship_id(self):
        parts = {
            "ppt/presentation.xml": f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst>'
                                    '<p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId1"/>'
                                    '</p:sldIdLst></p:presentation>',
            "ppt/_rels/presentation.xml.rels": f'<Relationships xmlns="{REL}">'
                                                '<Relationship Id="rId1" Target="slides/slide1.xml"/>'
                                                '<Relationship Id="rId2" Target="slides/slide2.xml"/></Relationships>',
            "ppt/slides/slide1.xml": f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><a:p><a:r><a:t>第二项</a:t></a:r></a:p></p:sld>',
            "ppt/slides/slide2.xml": f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><a:p><a:r><a:t>第一项</a:t></a:r></a:p></p:sld>',
        }
        result = preview.preview_attachment(self.archive("证据.pptx", parts))
        self.assertEqual(result["kind"], "document")
        self.assertEqual(result["text"], "第 1 页\n第一项\n\n第 2 页\n第二项")
        self.assertFalse(result["truncated"])

    def test_zip_directory_lists_without_opening_or_extracting_members(self):
        path = self.archive("压缩.zip", {"目录/": b"", "目录/日志.txt": "内容", "../outside.exe": b"MZ"})
        with patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("members must remain closed")), \
                patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("must not extract")), \
                patch.object(zipfile.ZipFile, "extractall", side_effect=AssertionError("must not extract")):
            result = preview.preview_attachment(path)
        self.assertEqual(result["kind"], "archive")
        self.assertEqual(result["entries"][0], {"name": "目录/", "size": 0, "directory": True})
        self.assertEqual(result["entries"][1]["size"], len("内容".encode("utf-8")))
        self.assertEqual(result["entries"][2]["name"], "../outside.exe")
        self.assertFalse((self.base.parent / "outside.exe").exists())

    def test_zip_listing_is_truncated_to_visible_limit(self):
        path = self.archive("many.zip", {f"{index}.txt": "ok" for index in range(6)})
        with patch.object(preview, "MAX_ARCHIVE_ROWS", 3):
            result = preview.preview_attachment(path)
        self.assertEqual(len(result["entries"]), 3)
        self.assertTrue(result["truncated"])

    def test_zip_entry_count_and_central_size_rejected_before_zipfile_construction(self):
        for count, size in ((5001, 40), (1, preview.MAX_CENTRAL_BYTES + 1)):
            with self.subTest(count=count, size=size):
                raw = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, count, count, size, 0, 0)
                path = self.file("bomb.zip", raw)
                with patch.object(zipfile, "ZipFile", side_effect=AssertionError("central directory must not load")):
                    result = preview.preview_attachment(path)
                self.assertEqual(result["kind"], "unsupported")
                self.assertIn("目录", result["message"])

    def test_zip64_and_multidisk_are_graceful(self):
        for fields in ((0, 0, 65535, 65535, 0, 0), (1, 1, 1, 1, 0, 0)):
            with self.subTest(fields=fields):
                path = self.file("unsupported.zip", struct.pack("<4s4H2LH", b"PK\x05\x06", *fields, 0))
                self.assertEqual(preview.preview_attachment(path)["kind"], "unsupported")

    def test_zip64_locator_cannot_override_small_eocd_fields_before_preflight(self):
        for comment_length in (0, 65535):
            with self.subTest(comment_length=comment_length):
                path = self.archive("locator.zip", {"evidence.txt": "original"})
                original = path.read_bytes()
                end_position = len(original) - 22
                fields = struct.unpack_from("<4s4H2LH", original, end_position)
                central_size, central_offset = fields[5:7]
                self.assertGreater(central_size, 32)
                record = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45,
                                     0, 0, 1, 1, central_size, central_offset)
                locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, end_position, 1)
                # The normal EOCD conceals the central directory's real size.
                ordinary = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, 1, 0, comment_length)
                path.write_bytes(original[:end_position] + record + locator + ordinary + b"x" * comment_length)
                # Prove this is a valid ZipFile input: its ZIP64 locator replaces
                # the small ordinary fields, including the central size of 1.
                with zipfile.ZipFile(path) as archive:
                    self.assertEqual(archive.namelist(), ["evidence.txt"])
                with patch.object(preview, "MAX_CENTRAL_BYTES", 32), \
                        patch.object(zipfile, "ZipFile", side_effect=AssertionError("ZIP64 must be rejected before construction")):
                    result = preview.preview_attachment(path)
                self.assertEqual(result["kind"], "unsupported")
                self.assertIn("ZIP64", result["message"])

    def test_xml_entity_declarations_are_rejected_for_utf8_and_utf16(self):
        for encoding in ("utf-8", "utf-16"):
            with self.subTest(encoding=encoding):
                content = '<?xml version="1.0"?><!DOCTYPE document [<!ENTITY sample "private">]>' \
                          f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&sample;</w:t>' \
                          '</w:r></w:p></w:body></w:document>'
                result = preview.preview_attachment(self.archive("entities.docx", {"word/document.xml": content.encode(encoding)}))
                self.assertEqual(result["kind"], "unsupported")
                self.assertIn("XML", result["message"])
                self.assertNotIn("private", result["message"])

    def test_xml_depth_and_element_limits(self):
        for body, attribute, limit in (("<w:p>" * 20 + "</w:p>" * 20, "MAX_XML_DEPTH", 10),
                                       ("<w:p/>" * 20, "MAX_XML_ELEMENTS", 10)):
            with self.subTest(attribute=attribute), patch.object(preview, attribute, limit):
                result = preview.preview_attachment(self.docx(body))
                self.assertEqual(result["kind"], "unsupported")
                self.assertIn("复杂", result["message"])

    def test_xml_part_and_aggregate_uncompressed_limits(self):
        docx = self.docx('<w:p><w:r><w:t>' + "x" * 500 + '</w:t></w:r></w:p>')
        with patch.object(preview, "MAX_XML_PART_BYTES", 100):
            self.assertEqual(preview.preview_attachment(docx)["kind"], "unsupported")
        xlsx = self.xlsx("<row/>")
        with patch.object(preview, "MAX_XML_TOTAL_BYTES", 300):
            self.assertEqual(preview.preview_attachment(xlsx)["kind"], "unsupported")

    def test_compressed_xml_bomb_is_rejected_from_declared_size(self):
        path = self.archive("compressed.docx", {"word/document.xml": b"x" * (preview.MAX_XML_PART_BYTES + 1)})
        self.assertLess(path.stat().st_size, 20000)
        with patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("oversized part must not decompress")):
            result = preview.preview_attachment(path)
        self.assertEqual(result["kind"], "unsupported")
        self.assertIn("过大", result["message"])

    def test_duplicate_office_parts_are_rejected(self):
        path = self.base / "duplicate.docx"
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", "<document/>")
                archive.writestr("word/document.xml", "<document/>")
        self.assertEqual(preview.preview_attachment(path)["kind"], "unsupported")

    def test_encrypted_office_member_is_graceful(self):
        path = self.docx("<w:p/>")
        raw = bytearray(path.read_bytes())
        central = raw.index(b"PK\x01\x02")
        flags = struct.unpack_from("<H", raw, central + 8)[0]
        struct.pack_into("<H", raw, central + 8, flags | 1)
        path.write_bytes(raw)
        result = preview.preview_attachment(path)
        self.assertEqual(result["kind"], "unsupported")
        self.assertIn("加密", result["message"])

    def test_missing_parts_and_malformed_formats_do_not_expose_parser_details(self):
        for name, content in (("bad.zip", b"not a zip private content"),
                              ("bad.docx", b"not a document"), ("bad.xlsx", b"not a workbook")):
            with self.subTest(name=name):
                result = preview.preview_attachment(self.file(name, content))
                self.assertEqual(result["kind"], "unsupported")
                self.assertNotIn("private", result["message"])
        path = self.archive("missing.docx", {"unrelated.xml": "<data/>"})
        self.assertEqual(preview.preview_attachment(path)["kind"], "unsupported")
        path = self.archive("malformed.docx", {"word/document.xml": "<document><private>"})
        result = preview.preview_attachment(path)
        self.assertEqual(result["kind"], "unsupported")
        self.assertNotIn("private", result["message"])

    def test_missing_file_has_human_readable_message_without_absolute_path(self):
        result = preview.preview_attachment(self.base / "missing.log")
        self.assertEqual(result["kind"], "unsupported")
        self.assertNotIn(str(self.base), result["message"])

    def test_preview_does_not_modify_source_bytes_or_directory(self):
        paths = [self.file("日志.log", "原始证据"), self.file("表.csv", "a,b\n1,2"),
                 self.docx('<w:p><w:r><w:t>原始</w:t></w:r></w:p>'),
                 self.xlsx('<row><c><v>42</v></c></row>'), self.archive("证据.zip", {"nested/evidence.txt": "original"})]
        before = {path.name: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}
        names = {path.name for path in self.base.iterdir()}
        for path in paths:
            self.assertNotEqual(preview.preview_attachment(path)["kind"], "unsupported")
        after = {path.name: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}
        self.assertEqual(before, after)
        self.assertEqual(names, {path.name for path in self.base.iterdir()})
        json.dumps([preview.preview_attachment(path) for path in paths], ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
