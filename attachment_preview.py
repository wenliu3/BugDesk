"""Bounded, read-only attachment previews using only the Python standard library.

All returned strings are data for text-only UI nodes.  This module never renders
HTML, follows Office relationships outside the archive, evaluates formulas or
extracts files.  Callers remain responsible for attachment ownership/path checks.
"""

import codecs
import csv
import io
import os
import posixpath
import re
import stat
import struct
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET


MAX_TEXT_BYTES = 512 * 1024
MAX_OUTPUT_CHARS = 512 * 1024
MAX_CELL_CHARS = 4096
MAX_TABLE_COLUMNS = 80
MAX_CSV_ROWS = 500
MAX_SHEET_ROWS = 300
MAX_SHEETS = 10
MAX_ZIP_ENTRIES = 5000
MAX_ARCHIVE_ROWS = 500
MAX_CENTRAL_BYTES = 2 * 1024 * 1024
MAX_XML_PART_BYTES = 10 * 1024 * 1024
MAX_XML_TOTAL_BYTES = 20 * 1024 * 1024
MAX_XML_ELEMENTS = 100000
MAX_XML_DEPTH = 64
MAX_SHARED_STRINGS = 50000

TEXT_SUFFIXES = frozenset({
    ".txt", ".log", ".json", ".jsonl", ".ndjson", ".har", ".xml", ".html", ".htm",
    ".md", ".markdown", ".ini", ".cfg", ".conf", ".config", ".yaml", ".yml",
    ".properties", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".css", ".scss", ".less", ".sql", ".bat", ".cmd", ".ps1", ".sh",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".java", ".go", ".rs", ".rb",
    ".toml", ".env", ".rst", ".out", ".err", ".trace", ".asc", ".svg",
})
OFFICE_SUFFIXES = frozenset({".docx", ".xlsx", ".pptx"})
LEGACY_SUFFIXES = frozenset({".doc", ".xls", ".ppt", ".wps", ".et", ".dps"})
_BINARY_SIGNATURES = (b"MZ", b"PK\x03\x04", b"\x7fELF", b"\x89PNG", b"GIF8",
                      b"\xff\xd8\xff", b"%PDF-", b"\x1f\x8b", b"Rar!", b"7z\xbc\xaf")


class _PreviewError(ValueError):
    pass


class _Budget:
    def __init__(self):
        self.remaining = MAX_OUTPUT_CHARS
        self.truncated = False

    def take(self, value, limit=None):
        value = str(value)
        allowed = self.remaining if limit is None else min(self.remaining, limit)
        if len(value) > allowed:
            self.truncated = True
            value = value[:allowed]
        self.remaining -= len(value)
        return value


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _notice(parts):
    return " ".join(dict.fromkeys(part for part in parts if part))


def _decode_text(raw, truncated=False, utf8_only=False):
    if raw.startswith(_BINARY_SIGNATURES):
        raise _PreviewError("文件内容是二进制数据，无法作为文本预览。")
    if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        candidates = [("utf-32", "UTF-32")]
    elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        candidates = [("utf-16", "UTF-16")]
    else:
        candidates = [("utf-8-sig", "UTF-8")]
        if not utf8_only:
            candidates.append(("gb18030", "GB18030"))
    for encoding, label in candidates:
        try:
            decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
            text = decoder.decode(raw, final=not truncated)
        except UnicodeError:
            continue
        controls = sum(ord(char) < 32 and char not in "\t\n\r\f\b" for char in text)
        if "\x00" in text or controls > max(1, len(text) // 100):
            continue
        return text, label
    raise _PreviewError("无法识别为可预览的文本编码，或文件包含二进制内容。")


def _read_text(stream, size, utf8_only=False):
    raw = stream.read(MAX_TEXT_BYTES + 1)
    truncated = len(raw) > MAX_TEXT_BYTES or size > MAX_TEXT_BYTES
    text, encoding = _decode_text(raw[:MAX_TEXT_BYTES], truncated, utf8_only)
    return text, encoding, truncated


def _text_preview(stream, size, utf8_only=False):
    text, encoding, truncated = _read_text(stream, size, utf8_only)
    result = {"kind": "text", "text": text, "encoding": encoding, "truncated": truncated}
    if truncated:
        result["notice"] = "文件较大，仅预览前 512 KiB；原文件保持完整。"
    return result


def _csv_preview(stream, size, name, delimiter):
    text, encoding, truncated = _read_text(stream, size)
    budget = _Budget()
    rows = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=not truncated)
        for row in reader:
            if len(rows) >= MAX_CSV_ROWS or budget.remaining == 0:
                truncated = True
                break
            if len(row) > MAX_TABLE_COLUMNS:
                truncated = True
            rows.append([budget.take(cell, MAX_CELL_CHARS) for cell in row[:MAX_TABLE_COLUMNS]])
    except csv.Error as exc:
        raise _PreviewError("表格文本格式不完整或单元格过大，无法生成表格预览。") from exc
    truncated = truncated or budget.truncated
    result = {"kind": "table", "encoding": encoding,
              "sheets": [{"name": name, "rows": rows, "truncated": truncated}],
              "truncated": truncated}
    if truncated:
        result["notice"] = "预览已截取：最多读取 512 KiB、500 行、80 列，每格最多 4096 字符；原文件保持完整。"
    return result


def _check_zip_directory(stream, size):
    # ZipFile otherwise allocates the entire central directory before we can
    # inspect infolist().  Reject oversized/ZIP64 directories before construction.
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or len(tail) - position < 22:
        raise _PreviewError("压缩文件不完整或格式不正确，无法预览。")
    fields = struct.unpack_from("<4s4H2LH", tail, position)
    _, disk, central_disk, disk_entries, entries, central_size, offset, comment_size = fields
    if position + 22 + comment_size != len(tail):
        raise _PreviewError("压缩文件目录格式不正确，无法预览。")
    end_position = size - len(tail) + position
    # Python's ZipFile honors this locator even when every ordinary EOCD field
    # is small rather than a ZIP64 sentinel. Check the exact preceding record
    # before construction; with a 65535-byte comment it lies outside ``tail``.
    if end_position >= 20:
        stream.seek(end_position - 20)
        if stream.read(20).startswith(b"PK\x06\x07"):
            raise _PreviewError("压缩文件使用 ZIP64 格式，目录过大时请在本机打开查看。")
    if disk or central_disk or disk_entries != entries:
        raise _PreviewError("暂不支持分卷压缩文件预览。")
    if entries == 65535 or central_size == 0xFFFFFFFF or offset == 0xFFFFFFFF:
        raise _PreviewError("压缩文件使用 ZIP64 格式，目录过大时请在本机打开查看。")
    if entries > MAX_ZIP_ENTRIES or central_size > MAX_CENTRAL_BYTES:
        raise _PreviewError("压缩文件目录过大，预览最多支持 5000 个条目和 2 MiB 目录。")
    if offset + central_size > end_position:
        raise _PreviewError("压缩文件目录越界或已经损坏，无法预览。")
    stream.seek(0)


class _OfficeArchive:
    def __init__(self, archive):
        self.archive = archive
        self.total = 0
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES or len({item.filename for item in infos}) != len(infos):
            raise _PreviewError("文档压缩目录过大或包含重名文件，无法安全预览。")

    def xml(self, name):
        try:
            info = self.archive.getinfo(name)
        except KeyError as exc:
            raise _PreviewError("文档缺少必要内容，可能已经损坏或不是标准 Office 文件。") from exc
        if info.flag_bits & 1:
            raise _PreviewError("文件已加密，请在本机应用中输入密码后查看。")
        if info.file_size > MAX_XML_PART_BYTES or self.total + info.file_size > MAX_XML_TOTAL_BYTES:
            raise _PreviewError("文档内容过大，预览限制为单个部分 10 MiB、累计 20 MiB。")
        with self.archive.open(info) as member:
            raw = member.read(MAX_XML_PART_BYTES + 1)
        if len(raw) > MAX_XML_PART_BYTES or self.total + len(raw) > MAX_XML_TOTAL_BYTES:
            raise _PreviewError("文档内容超出预览大小限制，请在本机应用中查看。")
        self.total += len(raw)
        # XML syntax uses ASCII punctuation even for UTF-16/32. Removing NULs
        # detects declarations in those encodings before Expat sees them.
        declaration_check = raw.replace(b"\x00", b"").upper()
        if b"<!DOCTYPE" in declaration_check or b"<!ENTITY" in declaration_check:
            raise _PreviewError("文档含有不支持的 XML 声明，无法安全预览。")
        count = depth = 0
        parser = ET.iterparse(io.BytesIO(raw), events=("start", "end"))
        for event, _ in parser:
            if event == "start":
                depth += 1
                count += 1
                if count > MAX_XML_ELEMENTS or depth > MAX_XML_DEPTH:
                    raise _PreviewError("文档结构过于复杂，无法生成预览。")
            else:
                depth -= 1
        return parser.root


def _paragraphs(root, budget):
    parts = []
    for paragraph in root.iter():
        if _local(paragraph.tag) != "p":
            continue
        if budget.remaining == 0:
            budget.truncated = True
            break
        line = []
        for node in paragraph.iter():
            tag = _local(node.tag)
            if tag == "t":
                line.append(budget.take(node.text or ""))
            elif tag in {"br", "cr"}:
                line.append(budget.take("\n"))
            elif tag == "tab":
                line.append(budget.take("\t"))
        parts.append("".join(line))
        budget.take("\n")
    return "\n".join(parts)


def _docx_preview(office):
    root = office.xml("word/document.xml")
    if _local(root.tag) != "document":
        raise _PreviewError("文件不是可识别的 Word 文档。")
    budget = _Budget()
    text = _paragraphs(root, budget)
    return {"kind": "document", "text": text, "truncated": budget.truncated,
            "notice": _notice(["仅预览文档正文文字，不展示排版、图片、批注或嵌入附件。",
                               "内容较多，文字预览已截取。" if budget.truncated else ""])}


def _part_target(base, target):
    if not target or "\\" in target or "\x00" in target or ":" in target:
        return None
    normalized = posixpath.normpath(target.lstrip("/") if target.startswith("/")
                                     else posixpath.join(base, target))
    if not normalized.startswith(base + "/") or normalized.startswith("../"):
        return None
    return normalized


def _relationships(office, name, base):
    root = office.xml(name)
    result = {}
    for node in root:
        if _local(node.tag) != "Relationship" or node.get("TargetMode", "").lower() == "external":
            continue
        target = _part_target(base, node.get("Target", ""))
        if target:
            result[node.get("Id", "")] = target
    return result


def _relationship_id(node):
    # PowerPoint also has an unqualified numeric ``id`` on the same element.
    return next((value for key, value in node.attrib.items() if key.endswith("}id")), "")


def _text_nodes(node):
    return "".join(item.text or "" for item in node.iter() if _local(item.tag) == "t")


def _cell_position(reference):
    match = re.fullmatch(r"([A-Za-z]{1,3})([1-9][0-9]{0,6})", reference or "")
    if not match:
        return None
    column = 0
    for char in match[1].upper():
        column = column * 26 + ord(char) - ord("A") + 1
    return int(match[2]), column


def _xlsx_preview(office):
    workbook = office.xml("xl/workbook.xml")
    if _local(workbook.tag) != "workbook":
        raise _PreviewError("文件不是可识别的 Excel 工作簿。")
    relationships = _relationships(office, "xl/_rels/workbook.xml.rels", "xl")
    shared = []
    truncated = False
    if "xl/sharedStrings.xml" in office.archive.namelist():
        for node in office.xml("xl/sharedStrings.xml"):
            if _local(node.tag) != "si":
                continue
            if len(shared) == MAX_SHARED_STRINGS:
                truncated = True
                break
            value = _text_nodes(node)
            if len(value) > MAX_CELL_CHARS:
                truncated = True
            shared.append(value[:MAX_CELL_CHARS])
    budget = _Budget()
    sheets = []
    for node in workbook.iter():
        if _local(node.tag) != "sheet":
            continue
        if len(sheets) == MAX_SHEETS or budget.remaining == 0:
            truncated = True
            break
        name = budget.take(node.get("name", "工作表"), 200)
        target = relationships.get(_relationship_id(node))
        if not target:
            sheets.append({"name": name, "rows": [], "truncated": True})
            truncated = True
            continue
        root = office.xml(target)
        if _local(root.tag) != "worksheet":
            raise _PreviewError("工作表内容格式不正确，无法预览。")
        sheet_truncated = False
        rows = []
        inferred_row = 0
        for row in root.iter():
            if _local(row.tag) != "row":
                continue
            inferred_row += 1
            row_value = row.get("r", str(inferred_row))
            if not re.fullmatch(r"[1-9][0-9]{0,6}", row_value):
                sheet_truncated = True
                continue
            row_number = int(row_value)
            inferred_row = row_number
            if row_number > MAX_SHEET_ROWS or budget.remaining == 0:
                sheet_truncated = True
                continue
            cells = {}
            inferred_column = 0
            for cell in row:
                if _local(cell.tag) != "c":
                    continue
                inferred_column += 1
                position = _cell_position(cell.get("r", "")) if cell.get("r") else (row_number, inferred_column)
                if not position or position[0] != row_number or position[1] > MAX_TABLE_COLUMNS:
                    sheet_truncated = True
                    continue
                column = inferred_column = position[1]
                kind = cell.get("t", "")
                values = {_local(item.tag): item for item in cell}
                value = (values["v"].text or "") if "v" in values else ""
                if kind == "s":
                    if value.isascii() and value.isdigit() and len(value) <= 7 and int(value) < len(shared):
                        value = shared[int(value)]
                    else:
                        value = "[共享文字超出预览范围]"
                        sheet_truncated = True
                elif kind == "inlineStr":
                    value = _text_nodes(cell)
                elif kind == "b":
                    value = "TRUE" if value == "1" else "FALSE"
                elif "v" not in values and "f" in values:
                    value = "=" + (values["f"].text or "")
                old_truncated = budget.truncated
                cells[column] = budget.take(value, MAX_CELL_CHARS)
                sheet_truncated |= budget.truncated and not old_truncated
            if cells:
                while len(rows) < row_number:
                    rows.append([])
                width = max(cells)
                rows[row_number - 1] = [cells.get(index, "") for index in range(1, width + 1)]
        sheets.append({"name": name, "rows": rows, "truncated": sheet_truncated})
        truncated |= sheet_truncated
    truncated |= budget.truncated
    return {"kind": "table", "sheets": sheets, "truncated": truncated,
            "notice": _notice(["仅预览单元格文字和值，不展示格式、图片；公式不执行，仅显示已保存的值或公式文本，日期可能显示为原始数值。",
                               "预览已截取：最多 10 个工作表，每表前 300 行、80 列，每格 4096 字符。" if truncated else ""])}


def _pptx_preview(office):
    presentation = office.xml("ppt/presentation.xml")
    if _local(presentation.tag) != "presentation":
        raise _PreviewError("文件不是可识别的 PowerPoint 演示文稿。")
    relationships = _relationships(office, "ppt/_rels/presentation.xml.rels", "ppt")
    budget = _Budget()
    parts = []
    count = 0
    for node in presentation.iter():
        if _local(node.tag) != "sldId":
            continue
        count += 1
        if count > 100 or budget.remaining == 0:
            budget.truncated = True
            break
        target = relationships.get(_relationship_id(node))
        if not target:
            raise _PreviewError("演示文稿包含无法读取的幻灯片关系，无法预览。")
        root = office.xml(target)
        if _local(root.tag) != "sld":
            raise _PreviewError("幻灯片内容格式不正确，无法预览。")
        parts.append(budget.take(f"第 {count} 页\n") + _paragraphs(root, budget))
        budget.take("\n\n")
    return {"kind": "document", "text": "\n\n".join(parts), "truncated": budget.truncated,
            "notice": _notice(["仅按幻灯片顺序预览文字，不展示排版、图片、动画或演讲者备注。",
                               "文字预览已截取，最多预览前 100 页。" if budget.truncated else ""])}


def _zip_preview(stream, size, suffix):
    _check_zip_directory(stream, size)
    with zipfile.ZipFile(stream) as archive:
        if suffix in OFFICE_SUFFIXES:
            office = _OfficeArchive(archive)
            return {".docx": _docx_preview, ".xlsx": _xlsx_preview,
                    ".pptx": _pptx_preview}[suffix](office)
        budget = _Budget()
        entries = []
        encrypted = False
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise _PreviewError("压缩文件目录过大，无法预览。")
        for info in infos[:MAX_ARCHIVE_ROWS]:
            entries.append({"name": budget.take(info.filename, 1000), "size": info.file_size,
                            "directory": info.is_dir()})
            encrypted |= bool(info.flag_bits & 1)
        truncated = len(infos) > MAX_ARCHIVE_ROWS or budget.truncated
        return {"kind": "archive", "entries": entries, "truncated": truncated,
                "notice": _notice(["仅显示 ZIP 文件目录，不解压或打开其中的文件。",
                                   "最多显示前 500 个条目，目录预览已截取。" if truncated else "",
                                   "部分内容已加密。" if encrypted else ""])}


def preview_attachment(path: Path) -> dict:
    """Return a bounded preview; all unsupported/malformed files have a message.

    The caller must first resolve a known attachment and enforce its filesystem
    boundary.  No file contents are modified, extracted, executed or requested
    from the network.  Unsupported suffixes are not opened.
    """
    path = Path(path)
    result = {"name": path.name}
    suffix = path.suffix.lower()
    if suffix in LEGACY_SUFFIXES:
        return dict(result, kind="unsupported", message="旧版 Office/WPS 格式暂不支持内嵌预览，请在本机打开原文件，或另存为 DOCX、XLSX、PPTX。")
    if suffix in {".rar", ".7z"}:
        return dict(result, kind="unsupported", message="此压缩格式暂不支持目录预览，请在原始文件夹中用本机解压工具查看。")
    is_text = suffix in TEXT_SUFFIXES or bool(re.search(r"\.log\.\d+$", path.name, re.I))
    if not is_text and suffix not in OFFICE_SUFFIXES | {".zip", ".csv", ".tsv", ""}:
        return dict(result, kind="unsupported", message="此文件格式暂不支持内嵌预览，请在本机打开原文件查看。")
    try:
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise _PreviewError("此附件不是普通文件，无法预览。")
            result["size"] = info.st_size
            if suffix in OFFICE_SUFFIXES | {".zip"}:
                content = _zip_preview(stream, info.st_size, suffix)
            elif suffix in {".csv", ".tsv"}:
                content = _csv_preview(stream, info.st_size, path.stem, "\t" if suffix == ".tsv" else ",")
            else:
                content = _text_preview(stream, info.st_size, utf8_only=not suffix)
            return dict(result, **content)
    except _PreviewError as exc:
        return dict(result, kind="unsupported", message=str(exc))
    except (OSError, UnicodeError, ValueError, RuntimeError, OverflowError, EOFError,
            zipfile.BadZipFile, NotImplementedError, ET.ParseError, zlib.error, struct.error):
        # Do not echo parser error text: it may contain sensitive file contents
        # or machine-specific paths.  Detailed failures remain local to callers.
        return dict(result, kind="unsupported", message="文件无法读取、已加密、损坏或使用了暂不支持的格式，请在本机打开原文件查看。")
