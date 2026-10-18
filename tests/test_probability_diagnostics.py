"""Bounded failure diagnostics must not disclose login or report content."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zentao import _FormParser, _probability_diagnostic


class ProbabilityDiagnosticTests(unittest.TestCase):
    @staticmethod
    def diagnose(markup):
        parser = _FormParser()
        parser.feed('<form>' + markup + '</form>')
        return _probability_diagnostic(parser)

    def test_only_picker_structure_and_filtered_choices_are_returned(self):
        diagnostic = self.diagnose(
            '<input name="password" value="private-password">'
            '<input type="hidden" name="csrf_token" value="private-csrf">'
            '<select name="assignedTo"><option value="private-account">私人人名</option></select>'
            '<select name="product"><option value="331">内部产品名称</option></select>'
            '<span class="input-group-addon">概率（内部说明）</span>'
            '<select name="browser[]" id="browser"><option value="always">必现</option>'
            '<option value="H">高</option><option value="private-account">低</option>'
            '<option value="999">私人人名</option></select>'
            '<label for="custom">内部标题含private-email@example.invalid</label>'
            '<select name="custom" id="custom"><option value="private-value">内部用例内容</option></select>')
        serialized = json.dumps(diagnostic, ensure_ascii=False)
        for private in ("private-password", "private-csrf", "private-account", "私人人名", "内部产品名称",
                        "内部说明", "内部标题", "private-email", "private-value", "内部用例内容"):
            self.assertNotIn(private, serialized)
        browser, custom = diagnostic["fields"]
        self.assertEqual(browser["name"], "browser[]")
        self.assertEqual(browser["captions"], ["概率"])
        self.assertEqual(browser["option_count"], 4)
        self.assertEqual(browser["choices"], [{"value": "always", "label": "必现"},
            {"value": "H", "label": "高"}, {"value": "[已隐藏]", "label": "低"}])
        self.assertEqual(browser["hidden_option_count"], 1)
        self.assertNotIn("choices", custom)

    def test_private_field_names_and_ids_are_excluded(self):
        diagnostic = self.diagnose('<select name="companyUserRate" id="accountName"><option value="H">高</option></select>'
            '<select name="chance" id="privateToken"><option value="1">必现</option></select>')
        self.assertEqual([field["name"] for field in diagnostic["fields"]], ["chance"])
        self.assertEqual(diagnostic["fields"][0]["ids"], [])

    def test_missing_form_and_empty_picker_have_distinct_status(self):
        unavailable = _probability_diagnostic()
        self.assertEqual(unavailable["form_read"], "unavailable")
        self.assertEqual(unavailable["fields"], [])
        parsed = self.diagnose('<span class="input-group-addon">概率</span><select name="browser[]"></select>')
        self.assertEqual(parsed["form_read"], "parsed")
        self.assertEqual(parsed["fields"][0]["option_count"], 0)

    def test_field_and_option_lists_are_bounded(self):
        diagnostic = self.diagnose(''.join(f'<select name="field{i}"></select>' for i in range(30)))
        self.assertEqual(len(diagnostic["fields"]), 20)
        self.assertTrue(diagnostic["fields_truncated"])
        diagnostic = self.diagnose('<select name="chance">' + ''.join(
            f'<option value="{i}">高</option>' for i in range(30)) + '</select>')
        self.assertEqual(len(diagnostic["fields"][0]["choices"]), 8)
        self.assertTrue(diagnostic["fields"][0]["choices_truncated"])


if __name__ == "__main__":
    unittest.main()
