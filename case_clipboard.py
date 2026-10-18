"""Read copied test-case tables without executing or persisting their contents."""

import csv
import hashlib
import io
import json
import re
from html.parser import HTMLParser


MAX_CLIPBOARD_BYTES = 1024 * 1024
MAX_ROWS = 300
MAX_COLUMNS = 80
MAX_FIELD_CHARS = 20000
FIELDS = (
    "case_id", "title", "group", "preconditions", "steps", "expected",
    "actual", "tester", "date", "result",
)
FIELD_LABELS = {
    "case_id": "用例 ID", "title": "用例名称", "group": "用例分组",
    "preconditions": "前置条件", "steps": "步骤描述", "expected": "预期结果",
    "actual": "实际结果", "tester": "测试人员", "date": "测试时间", "result": "测试结果",
}
ALIASES = {
    "case_id": ("用例id", "用例编号", "测试用例id", "测试用例编号", "caseid"),
    "title": ("用例名称", "用例标题", "测试用例名称", "casename"),
    "group": ("用例分组", "用例目录", "所属模块", "模块名称"),
    "preconditions": ("前置条件", "前提条件", "预置条件", "preconditions"),
    "steps": ("步骤描述", "测试步骤", "操作步骤", "复现步骤", "步骤", "steps"),
    "expected": ("预期结果", "期望结果", "预期输出", "expectedresult", "expected"),
    "actual": ("实际结果", "实际现象", "实际输出", "备注", "actualresult", "actual"),
    "tester": ("测试人员", "测试人", "执行人", "tester"),
    "date": ("测试时间", "测试日期", "执行日期", "date"),
    "result": ("测试结果", "执行结果", "测试状态", "result"),
}
PROFILE = {
    "case_id": 0, "title": 3, "group": 7, "preconditions": 9, "steps": 10,
    "expected": 11, "actual": 15, "tester": 12, "date": 13, "result": 14,
}
PROFILE_LABELS = (
    "用例 ID", "共享文档", "用例类别", "用例名称", "测试类型", "用例优先级",
    "用例评审状态", "用例分组", "关联需求", "前置条件", "步骤描述", "预期结果",
    "测试人员", "测试时间", "测试结果", "备注 / 实际结果",
)
CASE_ID = re.compile(r"PD\d+-CA\d+", re.IGNORECASE)
ROW_ANCHOR = re.compile(r"^[ \t]*PD\d+-CA\d+\t", re.IGNORECASE)


def _normal_header(value):
    value = re.sub(r"[（(][^）)]*[）)]", "", value)
    return re.sub(r"[\s_\-：:*＊]+", "", value).lower()


def _header_mapping(cells):
    mapping = {key: None for key in FIELDS}
    ambiguous = []
    for key, aliases in ALIASES.items():
        hits = [index for index, value in enumerate(cells)
                if _normal_header(value) in aliases]
        if len(hits) == 1:
            mapping[key] = hits[0]
        elif len(hits) > 1:
            ambiguous.append(FIELD_LABELS[key])
    return mapping, ambiguous


def _blank(cells):
    return all(not cell.strip() for cell in cells)


def _text_rows(text):
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ValueError("请先粘贴共享表格里的用例。")
    try:
        parsed = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t", strict=True))
    except csv.Error as error:
        raise ValueError("粘贴内容的引号不完整，请重新复制完整的表格区域。") from error
    nonblank = [(index + 1, [cell.strip() for cell in cells])
                for index, cells in enumerate(parsed) if not _blank(cells)]
    # Some shared-sheet copies append an empty right-edge column to only some
    # rows. Remove only that proven empty padding; never discard a nonempty cell.
    if nonblank:
        minimum_width = min(len(cells) for _, cells in nonblank)
        if all(not cell for _, cells in nonblank for cell in cells[minimum_width:]):
            nonblank = [(index, cells[:minimum_width]) for index, cells in nonblank]
    widths = {len(cells) for _, cells in nonblank}
    if len(widths) == 1 and widths and next(iter(widths)) >= 2:
        return nonblank, "tsv", []

    # Shared sheets may emit unquoted line breaks inside cells. Only the explicit
    # case-ID-at-line-start boundary makes these records safe to reconstruct.
    lines = text.split("\n")
    anchors = [index for index, line in enumerate(lines) if ROW_ANCHOR.match(line)]
    if anchors:
        prefix = "\n".join(lines[:anchors[0]]).strip("\n")
        logical = []
        if prefix.strip():
            header_cells = [cell.strip() for cell in prefix.split("\t")]
            if len(header_cells) > 16 and all(not cell for cell in header_cells[16:]):
                header_cells = header_cells[:16]
            inferred, _ = _header_mapping(header_cells)
            if (len(header_cells) != 16 or inferred["case_id"] != 0
                    or inferred["steps"] is None or inferred["expected"] is None):
                raise ValueError("表头或多行单元格边界不清楚，请复制带表头的完整区域。")
            logical.append((1, header_cells))
        has_prefix = bool(logical)
        for position, start in enumerate(anchors):
            stop = anchors[position + 1] if position + 1 < len(anchors) else len(lines)
            cells = [cell.strip() for cell in "\n".join(lines[start:stop]).strip("\n").split("\t")]
            if len(cells) > 16 and all(not cell for cell in cells[16:]):
                cells = cells[:16]
            if len(cells) != 16:
                raise ValueError("这段多行用例无法确定列边界，请完整复制每条用例的 16 列。")
            logical.append((position + 1 + has_prefix, cells))
        return logical, "anchored-tsv", []
    raise ValueError("无法确定多行单元格的边界。请复制带表头的表格区域，或同时复制用例 ID 列。")


class _TableParser(HTMLParser):
    """Collect only the first table; embedded markup is plain, inert cell text."""

    BLOCKS = {"p", "div", "li", "section", "article", "pre", "h1", "h2", "h3"}
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                 "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = False
        self.done = False
        self.depth = 0
        self.ignored = 0
        self.row = None
        self.cell = None
        self.rows = []
        self.white_spaces = []

    def _break(self):
        if self.cell is not None and self.cell["parts"] and not self.cell["parts"][-1].endswith("\n"):
            self.cell["parts"].append("\n")

    @staticmethod
    def _span(attributes, key, limit):
        value = attributes.get(key, "1")
        if not re.fullmatch(r"[0-9]+", value or "") or not 1 <= int(value) <= limit:
            raise ValueError("表格合并单元格范围无效或过大。")
        return int(value)

    @staticmethod
    def _inline_white_space(attributes):
        # Inspect one inert inline property only. Never load style sheets, URLs,
        # or evaluate any CSS or event handlers from clipboard HTML.
        style = re.sub(r"/\*.*?\*/", "", attributes.get("style") or "", flags=re.DOTALL)
        selected = None
        important = False
        for declaration in style.split(";"):
            property_name, separator, value = declaration.partition(":")
            if not separator or property_name.strip().lower() != "white-space":
                continue
            value = value.strip().lower()
            priority = bool(re.search(r"\s*!\s*important\s*$", value))
            value = re.sub(r"\s*!\s*important\s*$", "", value).strip()
            if value not in {"normal", "nowrap", "pre", "pre-wrap", "pre-line", "break-spaces",
                             "inherit", "initial", "unset"}:
                continue
            if selected is None or priority or not important:
                selected, important = value, priority
        return selected

    def _push_white_space(self, tag, attrs):
        inherited = self.white_spaces[-1][1] if self.white_spaces else "normal"
        mode = self._inline_white_space(dict(attrs))
        if mode in {"inherit", "unset"}:
            mode = inherited
        elif mode == "initial":
            mode = "normal"
        elif mode is None:
            mode = "pre" if tag == "pre" else inherited
        self.white_spaces.append((tag, mode))

    def _pop_white_space(self, tag):
        for index in range(len(self.white_spaces) - 1, -1, -1):
            if self.white_spaces[index][0] == tag:
                del self.white_spaces[index:]
                break

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if tag == "table":
            if not self.found:
                self.found = True
                self._push_white_space(tag, attrs)
            self.depth += 1
            return
        if self.depth > 1:
            return
        if tag in ("script", "style"):
            self.ignored += 1
            return
        if self.ignored:
            return
        if self.depth == 0:
            # Inline whitespace modes can be inherited from the clipboard's
            # wrapper as well as table/tbody/tr. No style sheets are loaded.
            if tag not in self.VOID_TAGS:
                self._push_white_space(tag, attrs)
            return
        if tag == "tr":
            if self.row is not None:
                raise ValueError("复制的表格行结构不完整，请重新复制。")
            self.row = []
        elif tag in ("td", "th"):
            if self.row is None or self.cell is not None:
                raise ValueError("复制的表格单元格结构不完整，请重新复制。")
            attributes = dict(attrs)
            self.cell = {"parts": [], "rowspan": self._span(attributes, "rowspan", MAX_ROWS + 1),
                         "colspan": self._span(attributes, "colspan", MAX_COLUMNS)}
        elif self.cell is not None:
            if tag == "br":
                self.cell["parts"].append("\n")
            elif tag in self.BLOCKS:
                self._break()
        if tag not in self.VOID_TAGS:
            self._push_white_space(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.done:
            return
        if tag == "table" and self.depth:
            self.depth -= 1
            if self.depth == 0:
                if self.row is not None or self.cell is not None:
                    raise ValueError("复制的表格结构不完整，请重新复制。")
                self._pop_white_space(tag)
                self.done = True
            return
        if self.depth > 1:
            return
        if tag in ("script", "style") and self.ignored:
            self.ignored -= 1
            return
        if self.ignored:
            return
        if self.depth == 0:
            self._pop_white_space(tag)
            return
        if tag in ("td", "th") and self.cell is not None:
            self.cell["text"] = "".join(self.cell.pop("parts")).strip()
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.cell is not None:
                raise ValueError("复制的表格单元格结构不完整，请重新复制。")
            self.rows.append(self.row)
            self.row = None
            if len(self.rows) > MAX_ROWS + 1:
                raise ValueError(f"一次最多粘贴 {MAX_ROWS} 条用例，请分批导入。")
        elif self.cell is not None:
            if tag in self.BLOCKS:
                self._break()
        self._pop_white_space(tag)

    def handle_data(self, data):
        if self.depth == 1 and not self.ignored and self.cell is not None:
            mode = self.white_spaces[-1][1] if self.white_spaces else "normal"
            data = data.replace("\r\n", "\n").replace("\r", "\n")
            if mode == "pre-line":
                data = re.sub(r"[\t\f ]+", " ", data)
                data = re.sub(r" *\n *", "\n", data)
            elif mode not in {"pre", "pre-wrap", "break-spaces"}:
                data = re.sub(r"[\t\r\n\f ]+", " ", data)
            self.cell["parts"].append(data)

    def grid(self):
        if not self.found:
            return None
        if not self.done:
            raise ValueError("复制的表格结构不完整，请重新复制。")
        cells = {}
        spans = []
        width = 0
        for row_index, row in enumerate(self.rows):
            column = 0
            for cell in row:
                while (row_index, column) in cells:
                    column += 1
                right = column + cell["colspan"]
                bottom = row_index + cell["rowspan"]
                if right > MAX_COLUMNS:
                    raise ValueError(f"一次最多支持 {MAX_COLUMNS} 列。")
                if bottom > len(self.rows):
                    raise ValueError("合并单元格超出了复制范围，请完整复制相关行。")
                for y in range(row_index, bottom):
                    for x in range(column, right):
                        if (y, x) in cells:
                            raise ValueError("合并单元格重叠，无法可靠对齐用例字段。")
                        cells[y, x] = cell["text"]
                if cell["colspan"] > 1 and cell["text"]:
                    spans.append((row_index + 1, bottom, column, right))
                width = max(width, right)
                column = right
        rows = [(index + 1, [cells.get((index, column), "") for column in range(width)])
                for index in range(len(self.rows))]
        return [(index, row) for index, row in rows if not _blank(row)], spans


def parse_cases(text, html="", mapping=None, has_header=None):
    """Return an editable preview of copied test cases; never infer Bug priority."""
    if not isinstance(text, str) or not isinstance(html, str):
        raise ValueError("粘贴内容必须是文本。")
    if len(text.encode("utf-8")) + len(html.encode("utf-8")) > MAX_CLIPBOARD_BYTES:
        raise ValueError("粘贴内容超过 1 MB，请分批复制用例。")
    if has_header is not None and not isinstance(has_header, bool):
        raise ValueError("表头选项无效。")
    parsed_html = None
    if html.strip():
        parser = _TableParser()
        parser.feed(html)
        parser.close()
        parsed_html = parser.grid()
    if parsed_html is not None:
        source_rows, spans = parsed_html
        format_name = "html"
    else:
        source_rows, format_name, spans = _text_rows(text)
    if not source_rows:
        raise ValueError("粘贴区域没有可导入的用例。")
    width = max(len(cells) for _, cells in source_rows)
    if width > MAX_COLUMNS:
        raise ValueError(f"一次最多支持 {MAX_COLUMNS} 列。")
    for _, cells in source_rows:
        if len(cells) != width:
            raise ValueError("用例行的列数不一致，请完整复制表格区域。")
        if any(len(cell) > MAX_FIELD_CHARS for cell in cells):
            raise ValueError(f"单个单元格超过 {MAX_FIELD_CHARS} 字，请缩小复制范围。")

    inferred, ambiguous = _header_mapping(source_rows[0][1])
    if has_header is None:
        has_header = (not CASE_ID.fullmatch(source_rows[0][1][0])
                      and sum(value is not None for value in inferred.values()) >= 3
                      and (inferred["steps"] is not None or inferred["expected"] is not None))
    headers = source_rows[0][1] if has_header else None
    data_rows = source_rows[1:] if has_header else source_rows
    if not data_rows:
        raise ValueError("只有表头，没有用例数据。")
    if len(data_rows) > MAX_ROWS:
        raise ValueError(f"一次最多粘贴 {MAX_ROWS} 条用例，请分批导入。")
    is_profile = not has_header and width == 16 and all(
        CASE_ID.fullmatch(cells[0]) for _, cells in data_rows)
    active_mapping = inferred if has_header else dict(PROFILE) if is_profile else {key: None for key in FIELDS}
    if mapping is not None:
        if not isinstance(mapping, dict) or any(key not in FIELDS for key in mapping):
            raise ValueError("列对应设置包含无效字段。")
        for key, index in mapping.items():
            if index is not None and (isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < width):
                raise ValueError(f"{FIELD_LABELS[key]}的列编号无效。")
        active_mapping.update(mapping)

    data_numbers = {index for index, _ in data_rows}
    mapped_columns = {index for index in active_mapping.values() if index is not None}
    for start, bottom, left, right in spans:
        if any(number in data_numbers for number in range(start, bottom + 1)) and mapped_columns.intersection(range(left, right)):
            raise ValueError("用例数据有跨列合并单元格，无法确定字段对应，请取消合并或重新复制。")

    warnings = []
    if is_profile:
        warnings.append("无表头内容按示例的 16 列顺序推定，请核对列对应；其他用例表的列顺序可能不同。")
    if has_header and ambiguous:
        warnings.append("表头有重复字段，请手动选择列对应：" + "、".join(ambiguous) + "。")
    if active_mapping["steps"] is None or active_mapping["expected"] is None:
        warnings.append("请确认步骤描述和预期结果的列对应后再导入。")
    columns = []
    for index in range(width):
        label = headers[index] if headers else PROFILE_LABELS[index] if is_profile else f"第 {index + 1} 列"
        sample = next((cells[index] for _, cells in data_rows if cells[index]), "")
        columns.append({"index": index, "label": label or f"第 {index + 1} 列", "sample": sample})
    rows = []
    counts = {}
    for source_index, cells in data_rows:
        row = {key: cells[index] if index is not None else "" for key, index in active_mapping.items()}
        row["row_id"] = hashlib.sha256(json.dumps([source_index, cells], ensure_ascii=False).encode("utf-8")).hexdigest()[:24]
        row["source_row"] = source_index
        row["warnings"] = []
        if not row["case_id"]:
            row["warnings"].append("缺少用例 ID，请手动关联附件文件夹。")
        if not row["actual"]:
            row["warnings"].append("实际结果为空，导入后需补充。")
        if not row["steps"] or not row["expected"]:
            row["warnings"].append("复现步骤或预期结果为空。")
        if row["case_id"]:
            counts[row["case_id"]] = counts.get(row["case_id"], 0) + 1
        rows.append(row)
    for row in rows:
        if counts.get(row["case_id"], 0) > 1:
            row["warnings"].append("用例 ID 重复，请逐条确认；不会自动合并。")
    if any(count > 1 for count in counts.values()):
        warnings.append("包含重复用例 ID，请确认每条对应关系。")
    return {"format": format_name, "has_header": has_header, "columns": columns,
            "mapping": active_mapping, "rows": rows, "warnings": warnings}
