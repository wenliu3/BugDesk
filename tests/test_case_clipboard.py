import csv
import io
import unittest
from pathlib import Path

from case_clipboard import MAX_CLIPBOARD_BYTES, MAX_COLUMNS, MAX_FIELD_CHARS, MAX_ROWS, parse_cases


SAMPLE = (
    "PD10000-CA10001\t示例设备测试（公开演示）\t示例设备测试\t示例学习学习中，唤醒语音助手\t功能性\tP1\t通过\t示例用例/1.0版本/示例学习\t\t1、已绑定智屏\t1.打开示例学习\n"
    "2.进行视频识字学习\n3.语音语音助手\n4.没有说话，聆听结束\t3.识字视频暂停，语音助手聆听中\n"
    "4.视频继续播放\t示例测试员\t10月11日\t失败\t示例学习播放视频识字后唤醒语音助手不会暂停视频\n"
    "PD10000-CA10002\t示例设备测试（公开演示）\t示例设备测试\t全程语音控制\t功能性\tP1\t通过\t示例用例/1.0版本/示例播放器\t\t视频播放过程中\t1.语音：先别播了\t1.播放暂停\t示例测试员\t10月13日\t失败\t会返回到上一界面\n"
    "PD10000-CA10003\t示例设备测试（公开演示）\t示例设备测试\t全程语音控制\t功能性\tP1\t通过\t示例用例/1.0版本/示例播放器\t\t视频播放过程中\t1.语音：先别放了\t1.播放暂停\t示例测试员\t10月13日\t失败\t会返回到上一界面\n"
    "PD10000-CA10004\t示例设备测试（公开演示）\t示例设备测试\t全程语音控制\t功能性\tP1\t通过\t示例用例/1.0版本/示例播放器\t\t视频播放过程中\t1.语音：别放了\t1.播放暂停\t示例测试员\t10月13日\t失败\t会返回到上一界面\n"
    "PD10000-CA10005\t示例设备测试（公开演示）\t示例设备测试\t全程语音控制\t功能性\tP1\t通过\t示例用例/1.0版本/示例播放器\t\t视频播放过程中\t1.语音：别播了\t1.播放暂停\t示例测试员\t10月13日\t失败\t会返回到上一界面\n"
    "PD10000-CA10006\t示例设备测试（公开演示）\t示例设备测试\t全程语音控制\t功能性\tP1\t通过\t示例用例/1.0版本/示例播放器\t\t视频播放过程中\t1.语音：别说了\t1.播放暂停\t示例测试员\t10月13日\t失败\t会返回到上一界面\n"
    "PD10000-CA10007\t示例设备测试（公开演示）\t示例设备测试\t全程语音控制\t功能性\tP1\t通过\t示例用例/1.0版本/示例播放器\t\t视频播放过程中\t1.语音：别播放了\t1.播放暂停\t示例测试员\t10月13日\t失败\t会返回到上一界面"
)


class ClipboardCaseTests(unittest.TestCase):
    def test_actual_seven_record_unquoted_multiline_sample(self):
        parsed = parse_cases(SAMPLE)
        self.assertEqual(parsed["format"], "anchored-tsv")
        self.assertFalse(parsed["has_header"])
        self.assertEqual(len(parsed["rows"]), 7)
        first = parsed["rows"][0]
        self.assertEqual(first["steps"], "1.打开示例学习\n2.进行视频识字学习\n3.语音语音助手\n4.没有说话，聆听结束")
        self.assertEqual(first["expected"], "3.识字视频暂停，语音助手聆听中\n4.视频继续播放")
        self.assertEqual(first["preconditions"], "1、已绑定智屏")
        self.assertEqual(first["actual"], "示例学习播放视频识字后唤醒语音助手不会暂停视频")
        self.assertEqual(first["result"], "失败")
        self.assertEqual(first["tester"], "示例测试员")
        self.assertEqual(first["date"], "10月11日")
        self.assertEqual(first["title"], "示例学习学习中，唤醒语音助手")
        self.assertEqual(parsed["mapping"]["result"], 14)
        self.assertEqual(parsed["mapping"]["actual"], 15)
        self.assertEqual(parsed["rows"][1]["steps"], "1.语音：先别播了")
        self.assertEqual(parsed["rows"][-1]["source_row"], 7)
        self.assertEqual(parsed, parse_cases(SAMPLE))
        self.assertTrue(any("无表头" in warning and "核对列对应" in warning for warning in parsed["warnings"]))

    def test_actual_multiline_header_with_inconsistent_empty_right_edge(self):
        raw = (Path(__file__).parent / "fixtures" / "shared_sheet_multiline_header.tsv").read_text(encoding="utf-8")
        parsed = parse_cases(raw)
        self.assertEqual(parsed["format"], "anchored-tsv")
        self.assertTrue(parsed["has_header"])
        self.assertEqual(len(parsed["columns"]), 16)
        self.assertEqual(len(parsed["rows"]), 2)
        self.assertIn("\n（选填，不填将新建", parsed["columns"][0]["label"])
        self.assertEqual(parsed["mapping"], {"case_id": 0, "title": 3, "group": 7, "preconditions": 9,
                                             "steps": 10, "expected": 11, "actual": 15, "tester": 12,
                                             "date": 13, "result": 14})
        first, second = parsed["rows"]
        self.assertEqual(first["source_row"], 2)
        self.assertEqual(first["case_id"], "PD10000-CA10001")
        self.assertEqual(first["preconditions"], "1、已绑定智屏")
        self.assertEqual(first["steps"], "1.打开示例学习\n2.进行视频识字学习\n3.语音语音助手\n4.没有说话，聆听结束")
        self.assertEqual(first["expected"], "3.识字视频暂停，语音助手聆听中\n4.视频继续播放")
        self.assertEqual(first["actual"], "示例学习播放视频识字后唤醒语音助手不会暂停视频")
        self.assertEqual(second["case_id"], "PD10000-CA10002")
        self.assertEqual(second["preconditions"], "视频播放过程中")
        self.assertEqual(second["steps"], "1.语音：先别播了")
        self.assertEqual(second["expected"], "1.播放暂停")
        self.assertEqual(second["actual"], "会返回到上一界面")
        self.assertTrue(all(row["result"] == "失败" for row in parsed["rows"]))

    def test_multiline_header_still_rejects_unknown_boundary_and_nonempty_extra_column(self):
        raw = (Path(__file__).parent / "fixtures" / "shared_sheet_multiline_header.tsv").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "边界"):
            parse_cases(raw.replace("用例ID", "无法确定的文字", 1))
        with self.assertRaisesRegex(ValueError, "16 列"):
            parse_cases(raw.replace("不会暂停视频\t\n", "不会暂停视频\t不能丢弃的额外内容\n", 1))

    def test_quoted_tsv_ignores_only_empty_extra_right_edge_cells(self):
        cells = SAMPLE.splitlines()[-1].split("\t")
        cells[10] = "1.打开\n2.等待\t响应"
        cells[11] = "1.暂停\n2.恢复"
        output = io.StringIO(newline="")
        csv.writer(output, delimiter="\t").writerows([cells + [""], cells])
        parsed = parse_cases(output.getvalue())
        self.assertEqual(parsed["format"], "tsv")
        self.assertEqual(len(parsed["columns"]), 16)
        self.assertEqual(len(parsed["rows"]), 2)
        self.assertEqual(parsed["rows"][0]["steps"], cells[10])
        self.assertEqual(parsed["rows"][0]["expected"], cells[11])
        with self.assertRaises(ValueError):
            parse_cases("操作\t预期\t额外事实\n操作二\t预期二")

    def test_unquoted_multiline_record_preserves_empty_last_actual_cell(self):
        cells = SAMPLE.splitlines()[-1].split("\t")
        cells[10] = "1.打开\n2.等待"
        cells[11] = "1.暂停\n2.恢复"
        cells[15] = ""
        parsed = parse_cases("\t".join(cells) + "\n" + SAMPLE.splitlines()[-2])
        self.assertEqual(len(parsed["columns"]), 16)
        self.assertEqual(parsed["rows"][0]["actual"], "")
        self.assertEqual(parsed["rows"][0]["expected"], cells[11])

    def test_quoted_tsv_preserves_multiline_tabs_and_quotes(self):
        cells = ["PD10000-CA10001", "文档", "类别", "标题", "功能性", "P1", "通过", "分组", "",
                 "前置\n条件", '1.输入 "别播了"\n2.等待\t响应', "1.暂停\n2.显示按钮", "示例测试员", "10月11日", "失败", "实际"]
        output = io.StringIO(newline="")
        csv.writer(output, delimiter="\t").writerows([cells, cells])
        parsed = parse_cases(output.getvalue())
        self.assertEqual(parsed["format"], "tsv")
        self.assertEqual(parsed["rows"][0]["steps"], cells[10])
        self.assertEqual(parsed["rows"][0]["preconditions"], cells[9])
        self.assertNotEqual(parsed["rows"][0]["row_id"], parsed["rows"][1]["row_id"])
        self.assertTrue(parsed["rows"][0]["warnings"])

    def test_headers_with_instructions_and_multiline(self):
        headers = ["用例 ID（选填，不填将新建）", "用例名称（选填）", "前置条件（选填）",
                   "步骤描述（选填，多个步骤用数字加标点开始）", "预期结果（步骤间用双空行分隔）",
                   "备注", "测试人员", "测试时间", "测试结果"]
        parsed = parse_cases("\t".join(headers) + "\nPD1-CA2\t用例\t前提\t操作\t预期\t实际\t张三\t10月14日\t失败")
        self.assertTrue(parsed["has_header"])
        self.assertEqual(parsed["mapping"]["actual"], 5)
        self.assertEqual(parsed["rows"][0]["source_row"], 2)
        self.assertEqual(parsed["rows"][0]["actual"], "实际")

    def test_manual_mapping_for_other_headerless_layout(self):
        raw = "名字\t操作\t结果\t现象\n另一条\t另一步\t另一个结果\t另一个现象"
        unmapped = parse_cases(raw)
        self.assertTrue(unmapped["warnings"])
        self.assertTrue(all(value is None for value in unmapped["mapping"].values()))
        parsed = parse_cases(raw, mapping={"title": 0, "steps": 1, "expected": 2, "actual": 3}, has_header=False)
        self.assertEqual(parsed["rows"][1]["steps"], "另一步")
        self.assertEqual(len(parsed["rows"]), 2)

    def test_explicit_no_header_does_not_drop_headerlike_first_case(self):
        parsed = parse_cases("用例名称\t步骤描述\t预期结果\n另一个名字\t操作\t结果", has_header=False,
                             mapping={"title": 0, "steps": 1, "expected": 2})
        self.assertEqual(len(parsed["rows"]), 2)

    def test_case_id_prevents_header_inference_from_headerlike_case_facts(self):
        cells = SAMPLE.splitlines()[-1].split("\t")
        cells[3] = "用例名称显示错误"
        cells[9] = "前置条件已经满足"
        cells[10] = "步骤描述编辑后没有保存"
        cells[11] = "预期结果正常保存"
        parsed = parse_cases("\t".join(cells))
        self.assertFalse(parsed["has_header"])
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(parsed["rows"][0]["steps"], cells[10])
        self.assertEqual(parsed["rows"][0]["expected"], cells[11])
        raw = "PD1-CA2\t步骤描述一\t预期结果一\t前置条件一\nPD1-CA3\t步骤描述二\t预期结果二\t前置条件二"
        manual = parse_cases(raw, mapping={"case_id": 0, "steps": 1, "expected": 2, "preconditions": 3})
        self.assertFalse(manual["has_header"])
        self.assertEqual(len(manual["rows"]), 2)
        forced = parse_cases(raw, has_header=True,
                             mapping={"case_id": 0, "steps": 1, "expected": 2, "preconditions": 3})
        self.assertTrue(forced["has_header"])
        self.assertEqual(len(forced["rows"]), 1)

    def test_non_pd_ids_and_headerlike_facts_do_not_drop_first_case(self):
        raw = ("CASE-1\t前置条件：登录成功\t步骤描述为空时点击保存\t预期结果提示必填\t实际结果保存成功\n"
               "CASE-2\t已登录\t打开详情\t显示详情\t白屏")
        unmapped = parse_cases(raw)
        self.assertFalse(unmapped["has_header"])
        self.assertEqual([row["source_row"] for row in unmapped["rows"]], [1, 2])
        mapped = parse_cases(raw, mapping={"case_id": 0, "preconditions": 1, "steps": 2, "expected": 3, "actual": 4})
        self.assertFalse(mapped["has_header"])
        self.assertEqual([row["case_id"] for row in mapped["rows"]], ["CASE-1", "CASE-2"])
        self.assertEqual(mapped["rows"][0]["steps"], "步骤描述为空时点击保存")
        self.assertEqual(mapped["rows"][0]["actual"], "实际结果保存成功")
        single = parse_cases(raw.split("\n")[0])
        self.assertFalse(single["has_header"])
        self.assertEqual(len(single["rows"]), 1)

    def test_duplicate_ids_are_warned_without_merging(self):
        cells = SAMPLE.splitlines()[-1]
        parsed = parse_cases(cells + "\n" + cells)
        self.assertEqual(len(parsed["rows"]), 2)
        self.assertNotEqual(parsed["rows"][0]["row_id"], parsed["rows"][1]["row_id"])
        self.assertTrue(any("重复" in warning for warning in parsed["warnings"]))

    def test_result_is_not_derived_from_review_status(self):
        cells = SAMPLE.splitlines()[-1].split("\t")
        cells[14] = "通过"
        parsed = parse_cases("\t".join(cells))
        self.assertEqual(parsed["rows"][0]["result"], "通过")
        self.assertEqual(len(parsed["rows"]), 1)

    def test_html_takes_priority_preserving_breaks_entities_and_plain_text(self):
        html = '<table><tr><th>用例 ID</th><th>步骤描述</th><th>预期结果</th><th>备注</th></tr><tr><td>PD1-CA2</td><td>1.打开<br>2.输入 &lt;script&gt; &amp; "语音"<script>secret()</script><style>secret</style><table><tr><td>忽略嵌套内容</td></tr></table></td><td><div>1.暂停</div><div>2.恢复</div></td><td><img src="x" onerror="secret()">实际现象</td></tr></table><table><tr><td>不要读取</td></tr></table>'
        parsed = parse_cases("错误文本", html=html)
        self.assertEqual(parsed["format"], "html")
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(parsed["rows"][0]["steps"], '1.打开\n2.输入 <script> & "语音"')
        self.assertEqual(parsed["rows"][0]["expected"], "1.暂停\n2.恢复")
        self.assertEqual(parsed["rows"][0]["actual"], "实际现象")

    def test_html_rowspan_keeps_columns_aligned(self):
        html = '<table><tr><th>用例 ID</th><th>步骤描述</th><th>预期结果</th></tr><tr><td rowspan="2">PD1-CA2</td><td>步骤一</td><td>结果一</td></tr><tr><td>步骤二</td><td>结果二</td></tr></table>'
        parsed = parse_cases("", html)
        self.assertEqual(len(parsed["rows"]), 2)
        self.assertEqual(parsed["rows"][1]["case_id"], "PD1-CA2")
        self.assertEqual(parsed["rows"][1]["steps"], "步骤二")
        self.assertEqual(parsed["rows"][1]["expected"], "结果二")
        self.assertTrue(parsed["warnings"])

    def test_html_inline_preserving_modes_keep_literal_multiline_cells(self):
        for mode in ("pre", "pre-wrap", "break-spaces"):
            with self.subTest(mode=mode):
                html = ('<table><tr><td style="white-space:' + mode + '">1.Open\n2.  Wait\tresponse</td>'
                        '<td style="WHITE-SPACE: ' + mode + ' !important">1.Pause\r\n2.Continue</td></tr></table>')
                parsed = parse_cases("1.Open\n2.  Wait\tresponse\t1.Pause\n2.Continue", html,
                                     mapping={"steps": 0, "expected": 1}, has_header=False)
                self.assertEqual(parsed["format"], "html")
                self.assertEqual(parsed["rows"][0]["steps"], "1.Open\n2.  Wait\tresponse")
                self.assertEqual(parsed["rows"][0]["expected"], "1.Pause\n2.Continue")

    def test_html_inherits_ancestor_whitespace_when_plaintext_also_available(self):
        output = io.StringIO(newline="")
        csv.writer(output, delimiter="\t").writerows([
            ["用例ID", "步骤描述", "预期结果", "实际结果"],
            ["PD1-CA2", "1.Open\n2.Wait", "1.Pause\n2.Continue", "Returned"],
        ])
        plain = output.getvalue()
        header = "<tr><th>用例ID</th><th>步骤描述</th><th>预期结果</th><th>实际结果</th></tr>"
        record = "<td>PD1-CA2</td><td>1.Open\n2.Wait</td><td>1.Pause\n2.Continue</td><td>Returned</td>"
        variants = [
            '<table style="white-space:pre-wrap">' + header + "<tr>" + record + "</tr></table>",
            "<table>" + header + '<tr style="white-space:pre-wrap">' + record + "</tr></table>",
            "<table>" + header + '<tbody style="white-space:pre-wrap"><tr>' + record + "</tr></tbody></table>",
            '<div style="white-space:pre-wrap"><table>' + header + "<tr>" + record + "</tr></table></div>",
        ]
        for html in variants:
            with self.subTest(html=html):
                parsed = parse_cases(plain, html)
                self.assertEqual(parsed["format"], "html")
                self.assertEqual(parsed["rows"][0]["steps"], parse_cases(plain)["rows"][0]["steps"])
                self.assertEqual(parsed["rows"][0]["expected"], "1.Pause\n2.Continue")

    def test_html_ancestor_modes_reset_at_sibling_boundaries(self):
        html = ('<table><tr style="white-space:pre-wrap"><td>1.Open\n2.Wait</td><td>1.Pause\n2.Continue</td></tr>'
                '<tr><td>3.Open\n4.Wait</td><td>3.Pause\n4.Continue</td></tr></table>')
        parsed = parse_cases("", html, mapping={"steps": 0, "expected": 1}, has_header=False)
        self.assertEqual(parsed["rows"][0]["steps"], "1.Open\n2.Wait")
        self.assertEqual(parsed["rows"][1]["steps"], "3.Open 4.Wait")
        override = ('<table style="white-space:pre-wrap"><tr><td style="white-space:normal">A\nB</td>'
                    '<td>C\nD</td></tr></table>')
        result = parse_cases("", override, mapping={"steps": 0, "expected": 1}, has_header=False)
        self.assertEqual(result["rows"][0]["steps"], "A B")
        self.assertEqual(result["rows"][0]["expected"], "C\nD")

    def test_html_nested_tables_and_scripts_cannot_change_ancestor_mode(self):
        html = ('<script>notExecuted()</script><style>td{white-space:normal}</style>'
                '<table style="white-space:pre-wrap"><tr><td>1.Open\n'
                '<table style="white-space:normal"><tr><td>ignored\nnested</td></tr></table>'
                '<script>ignored()</script><style>ignored style</style>2.Wait</td>'
                '<td>1.Pause\n2.Continue</td></tr></table>')
        parsed = parse_cases("", html, mapping={"steps": 0, "expected": 1}, has_header=False)
        self.assertEqual(parsed["rows"][0]["steps"], "1.Open\n2.Wait")
        self.assertEqual(parsed["rows"][0]["expected"], "1.Pause\n2.Continue")

    def test_html_pre_line_from_ancestor_preserves_linebreaks(self):
        html = ('<table style="white-space:pre-line"><tr><td>1.  Open \n 2.\t Wait</td>'
                '<td>1. Pause\n2. Continue</td></tr></table>')
        parsed = parse_cases("", html, mapping={"steps": 0, "expected": 1}, has_header=False)
        self.assertEqual(parsed["rows"][0]["steps"], "1. Open\n2. Wait")

    def test_html_pre_line_preserves_linebreaks_while_collapsing_spacing(self):
        html = '<table><tr><td style="white-space:pre-line">1.  Open \n 2.\t Wait\n\n3. Continue</td><td>预期</td></tr></table>'
        parsed = parse_cases("", html, mapping={"steps": 0, "expected": 1}, has_header=False)
        self.assertEqual(parsed["rows"][0]["steps"], "1. Open\n2. Wait\n\n3. Continue")

    def test_html_descendant_preservation_inheritance_and_sibling_reset(self):
        html = ('<table><tr><td><span style="white-space:pre-wrap">1.Open\n<b>2.  Wait</b>'
                '<img style="white-space:normal" src="inert">\n3.Done</span><span> next\nnormal</span></td>'
                '<td style="white-space:pre-wrap"><span style="white-space:normal">A\nB</span>\nC\nD</td></tr></table>')
        parsed = parse_cases("", html, mapping={"steps": 0, "expected": 1}, has_header=False)
        self.assertEqual(parsed["rows"][0]["steps"], "1.Open\n2.  Wait\n3.Done next normal")
        self.assertEqual(parsed["rows"][0]["expected"], "A B\nC\nD")

    def test_html_pre_tag_and_important_style_preserve_only_scoped_text(self):
        html = ('<table><tr><td><pre>1.Open\n2.Wait</pre><span>3. Normal\n4. Normal</span></td>'
                '<td style="white-space:pre-wrap!important;white-space:normal">A\nB</td></tr></table>')
        parsed = parse_cases("", html, mapping={"steps": 0, "expected": 1}, has_header=False)
        self.assertEqual(parsed["rows"][0]["steps"], "1.Open\n2.Wait\n3. Normal 4. Normal")
        self.assertEqual(parsed["rows"][0]["expected"], "A\nB")

    def test_html_ordinary_indentation_and_explicit_breaks_still_work(self):
        html = ('<table>\n<tr>\n<td>\n  1.Open\n  <span>2.Wait</span>\n</td>\n'
                '<td><div>1.Pause<br>2.Continue</div><div>3.Done</div></td>\n</tr>\n</table>')
        parsed = parse_cases("", html, mapping={"steps": 0, "expected": 1}, has_header=False)
        self.assertEqual(parsed["rows"][0]["steps"], "1.Open 2.Wait")
        self.assertEqual(parsed["rows"][0]["expected"], "1.Pause\n2.Continue\n3.Done")

    def test_html_blank_colspan_is_safe_and_preserves_offsets(self):
        html = '<table><tr><td colspan="2"></td><td>操作</td><td>预期</td></tr></table>'
        parsed = parse_cases("", html, mapping={"steps": 2, "expected": 3}, has_header=False)
        self.assertEqual(len(parsed["columns"]), 4)
        self.assertEqual(parsed["rows"][0]["steps"], "操作")

    def test_html_merged_header_can_be_manually_mapped(self):
        html = '<table><tr><th colspan="2">标题</th><th>步骤描述</th><th>预期结果</th></tr><tr><td>ID</td><td>名字</td><td>操作</td><td>预期</td></tr></table>'
        parsed = parse_cases("", html, mapping={"case_id": 0, "title": 1}, has_header=True)
        self.assertEqual(parsed["rows"][0]["title"], "名字")
        self.assertEqual(parsed["rows"][0]["steps"], "操作")

    def test_reject_merged_core_data_and_out_of_range_span(self):
        with self.assertRaisesRegex(ValueError, "跨列合并"):
            parse_cases("", '<table><tr><td colspan="2">一个单元格</td></tr></table>',
                        mapping={"steps": 0, "expected": 1}, has_header=False)
        with self.assertRaisesRegex(ValueError, "超出了复制范围"):
            parse_cases("", '<table><tr><td rowspan="2">操作</td><td>预期</td></tr></table>')

    def test_falls_back_to_text_when_html_has_no_table(self):
        parsed = parse_cases("操作\t预期", html="<p>nothing</p>", mapping={"steps": 0, "expected": 1})
        self.assertEqual(parsed["format"], "tsv")

    def test_ragged_unquoted_multiline_without_anchor_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "边界"):
            parse_cases("标题\t1.打开\n2.等待\t预期\t实际")
        with self.assertRaisesRegex(ValueError, "16 列"):
            parse_cases("PD1-CA2\t步骤\n后续步骤\t预期\t实际")

    def test_malformed_quoted_cell_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "引号"):
            parse_cases('ID\t"未关闭\n步骤\t预期')

    def test_blank_outer_rows_and_cell_whitespace_are_safe(self):
        parsed = parse_cases("\n \t \n  操作  \t  预期  \n\n", mapping={"steps": 0, "expected": 1})
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(parsed["rows"][0]["steps"], "操作")
        self.assertEqual(parsed["rows"][0]["source_row"], 3)

    def test_bad_mappings_and_option_types_rejected(self):
        for mapping in ({"unknown": 0}, {"steps": True}, {"steps": -1}, {"steps": 2}, {"steps": "0"}, []):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                parse_cases("操作\t预期", mapping=mapping)
        with self.assertRaises(ValueError):
            parse_cases("操作\t预期", has_header="true")

    def test_limits_are_errors_not_truncation(self):
        for raw in ("x" * (MAX_CLIPBOARD_BYTES + 1), "x" * (MAX_FIELD_CHARS + 1) + "\t预期",
                    "\t".join(["x"] * (MAX_COLUMNS + 1)), "\n".join(["操作\t预期"] * (MAX_ROWS + 1))):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                parse_cases(raw)
        with self.assertRaisesRegex(ValueError, "1 MB"):
            parse_cases("x" * (MAX_CLIPBOARD_BYTES // 2 + 1), "x" * (MAX_CLIPBOARD_BYTES // 2 + 1))

    def test_formula_text_is_inert_and_unchanged(self):
        parsed = parse_cases('=HYPERLINK("secret")\t+cmd|x\t@input',
                             mapping={"steps": 0, "expected": 1, "actual": 2}, has_header=False)
        self.assertEqual(parsed["rows"][0]["steps"], '=HYPERLINK("secret")')
        self.assertEqual(parsed["rows"][0]["expected"], "+cmd|x")


if __name__ == "__main__":
    unittest.main()
