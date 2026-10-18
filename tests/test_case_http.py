"""Clipboard parsing and draft updates through the protected local HTTP API."""
import unittest
from urllib.error import HTTPError
from pathlib import Path

import test_app


SAMPLE = (
    'PD10000-CA10001\t示例设备测试（公开演示）\t示例设备测试\t示例学习学习中，唤醒语音助手\t功能性\tP1\t通过\t示例用例/1.0版本/示例学习\t\t1、已绑定智屏\t'
    '1.打开示例学习\n2.进行视频识字学习\n3.语音语音助手\n4.没有说话，聆听结束\t'
    '3.识字视频暂停，语音助手聆听中\n4.视频继续播放\t示例测试员\t10月11日\t失败\t示例学习播放视频识字后唤醒语音助手不会暂停视频\n'
    'PD10000-CA10002\t示例设备测试（公开演示）\t示例设备测试\t全程语音控制\t功能性\tP1\t通过\t示例用例/1.0版本/示例播放器\t\t视频播放过程中\t1.语音：先别播了\t1.播放暂停\t示例测试员\t10月13日\t失败\t会返回到上一界面'
)


class ClipboardHTTPTests(unittest.TestCase):
    setUp = test_app.HTTPTests.setUp
    tearDown = test_app.HTTPTests.tearDown
    request = test_app.HTTPTests.request
    json = test_app.HTTPTests.json
    prepare_bug = test_app.HTTPTests.prepare_bug

    def prepare_folders(self):
        root = Path(self.temp.name) / '10.14'
        for name in ('PD10000-CA10001_示例学习不会暂停视频', 'PD10000-CA10002_语音先别播了返回上一界面'):
            folder = root / name
            folder.mkdir(parents=True)
            (folder / '截图.png').write_bytes(b'evidence')
        self.json('/api/scan', {'path': str(root)})
        return root

    @staticmethod
    def assignments(preview, mode='fill'):
        targets = {bug['id']: bug for bug in preview['bugs']}
        return [{'row_id': row['row_id'], 'bug_id': row['suggested_bug_id'],
                 'review_token': targets[row['suggested_bug_id']]['review_token'], 'mode': mode}
                for row in preview['rows']]

    def test_bulk_multiline_paste_is_previewed_then_applied_without_touching_evidence(self):
        root = self.prepare_folders()
        preview = self.json('/api/cases/preview', {'text': SAMPLE})
        self.assertEqual(len(preview['rows']), 2)
        self.assertEqual(preview['rows'][0]['steps'].splitlines(), [
            '1.打开示例学习', '2.进行视频识字学习', '3.语音语音助手', '4.没有说话，聆听结束'])
        self.assertEqual(preview['rows'][0]['expected'].count('\n'), 1)
        self.assertTrue(all(row['suggested_bug_id'] for row in preview['rows']))
        self.assertTrue(all(not bug['steps'] for bug in self.json('/api/state')['bugs']))
        reply = self.json('/api/cases/apply', {'text': SAMPLE, 'batch_key': preview['batch_key'],
            'mapping': preview['mapping'], 'has_header': preview['has_header'],
            'assignments': self.assignments(preview)})
        self.assertEqual(reply['applied'], 2)
        self.assertFalse(reply['state']['connection']['connected'])
        self.assertTrue(all(not bug['reviewed'] for bug in reply['state']['bugs']))
        imported = {bug['case_source']['case_id']: bug for bug in reply['state']['bugs']}
        self.assertIn('PD10000-CA10001_', imported['PD10000-CA10001']['title'])
        self.assertEqual(len(list(root.rglob('*'))), 4)
        self.assertTrue(all(path.read_bytes() == b'evidence' for path in root.rglob('*.png')))
        preview_again = self.json('/api/cases/preview', {'text': SAMPLE})
        repeated = self.json('/api/cases/apply', {'text': SAMPLE, 'batch_key': preview_again['batch_key'],
            'assignments': self.assignments(preview_again)})
        self.assertEqual(repeated['unchanged'], 2)

    def test_stale_preview_cannot_overwrite_another_edit(self):
        self.prepare_folders()
        preview = self.json('/api/cases/preview', {'text': SAMPLE})
        target = preview['rows'][0]['suggested_bug_id']
        self.json('/api/save', {'bugs': [{'id': target, 'steps': '更新后的人工步骤'}]})
        with self.assertRaises(HTTPError) as error:
            self.json('/api/cases/apply', {'text': SAMPLE, 'batch_key': preview['batch_key'],
                'assignments': self.assignments(preview, 'replace')})
        self.assertEqual(error.exception.code, 400)
        bugs = {bug['id']: bug for bug in self.json('/api/state')['bugs']}
        self.assertEqual(bugs[target]['steps'], '更新后的人工步骤')
        other = preview['rows'][1]['suggested_bug_id']
        self.assertEqual(bugs[other]['steps'], '')

    def test_no_required_column_or_wrong_batch_cannot_import(self):
        self.prepare_folders()
        preview = self.json('/api/cases/preview', {'text': SAMPLE})
        for extra in ({'mapping': {'steps': None}}, {'batch_key': 'wrong-batch'}):
            with self.subTest(extra=extra), self.assertRaises(HTTPError) as error:
                self.json('/api/cases/apply', {'text': SAMPLE, 'batch_key': preview['batch_key'],
                    'assignments': self.assignments(preview), **extra})
            self.assertEqual(error.exception.code, 400)
        self.assertTrue(all(not bug['steps'] for bug in self.json('/api/state')['bugs']))

    def test_clipboard_actions_keep_token_and_job_guards(self):
        self.prepare_folders()
        with self.assertRaises(HTTPError) as error:
            self.json('/api/cases/preview', {'text': SAMPLE}, {'X-BugDesk-Token': 'wrong'})
        self.assertEqual(error.exception.code, 403)
        self.app.job['running'] = True
        try:
            with self.assertRaises(HTTPError) as error:
                self.json('/api/cases/preview', {'text': SAMPLE})
            self.assertEqual(error.exception.code, 400)
        finally:
            self.app.job['running'] = False
        with self.request('/case_import.js') as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b'installCaseImport', response.read())


if __name__ == '__main__':
    unittest.main()
