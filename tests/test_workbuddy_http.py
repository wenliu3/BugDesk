"""The WorkBuddy bridge uses its own capability and cannot review or submit drafts."""
import json
from pathlib import Path
import unittest
from urllib.error import HTTPError

import test_app


class WorkBuddyHTTPTests(unittest.TestCase):
    setUp = test_app.HTTPTests.setUp
    tearDown = test_app.HTTPTests.tearDown
    request = test_app.HTTPTests.request
    json = test_app.HTTPTests.json

    def prepare(self):
        root = Path(self.temp.name) / '10.14'
        for name in ('PD10000-CA10001_示例学习唤醒后视频未暂停', '表单保存失败后丢失内容'):
            folder = root / name
            folder.mkdir(parents=True)
            (folder / '截图.png').write_bytes(b'evidence')
        self.json('/api/scan', {'path': str(root)})
        status = self.json('/api/workbuddy/enable', {})
        connection = json.loads(Path(status['connection_file']).read_text(encoding='utf-8'))
        self.wb_headers = {'X-BugDesk-Token': '', 'X-BugDesk-WorkBuddy-Token': connection['token']}
        return self.json('/api/workbuddy/context', headers=self.wb_headers)

    @staticmethod
    def row(context):
        bug = next(item for item in context['bugs'] if 'CA10001' in item['title'])
        return {'case_id': 'PD10000-CA10001', 'title': '学习中唤醒管家', 'group': '示例学习',
                'tester': '测试人员', 'date': '10月11日', 'preconditions': '已绑定智屏',
                'steps': '1.打开示例学习\n2.语音唤醒管家', 'expected': '视频暂停',
                'actual': '视频仍继续播放', 'suggested_bug_id': bug['id'],
                'match_reason': 'Bug 标题和备注均说明唤醒后未暂停。'}

    def test_context_stage_and_ui_apply_keep_existing_review_workflow(self):
        context = self.prepare()
        encoded = json.dumps(context, ensure_ascii=False)
        self.assertNotIn(str(Path(self.temp.name)), encoded)
        self.assertNotIn('token', {key for key in context if key != 'context_id'})
        row = self.row(context)
        staged = self.json('/api/workbuddy/stage', {'context_id': context['context_id'], 'rows': [row]}, self.wb_headers)
        self.assertTrue(all(not bug['steps'] for bug in self.json('/api/state')['bugs']))
        pending = self.json('/api/workbuddy/status')['pending']
        self.assertEqual(pending['rows'][0]['match_type'], 'exact_id')
        result = self.json('/api/workbuddy/apply', {'plan_id': staged['plan_id'], 'assignments': [
            {'row_id': pending['rows'][0]['row_id'], 'bug_id': row['suggested_bug_id'], 'mode': 'fill'}]})
        bug = next(item for item in result['state']['bugs'] if item['id'] == row['suggested_bug_id'])
        self.assertEqual(bug['steps'], row['steps'])
        self.assertEqual(bug['case_source']['case_id'], row['case_id'])
        self.assertFalse(bug['reviewed'])
        self.assertFalse(bug['remote_id'])
        self.assertIsNone(self.json('/api/workbuddy/status')['pending'])

    def test_restricted_token_does_not_authorize_save_apply_or_submit(self):
        context = self.prepare()
        for path, payload in (('/api/save', {}), ('/api/workbuddy/apply', {}), ('/api/submit', {})):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                self.json(path, payload, self.wb_headers)
            self.assertEqual(error.exception.code, 403)
        for path, data, headers in (
            ('/api/workbuddy/context', None, {'X-BugDesk-WorkBuddy-Token': 'wrong'}),
            ('/api/workbuddy/stage', {'context_id': context['context_id'], 'rows': [self.row(context)]}, {}),
            ('/api/workbuddy/stage', {'context_id': context['context_id'], 'rows': [self.row(context)]},
             {**self.wb_headers, 'Origin': 'https://external.invalid'}),
        ):
            with self.subTest(path=path, headers=headers), self.assertRaises(HTTPError) as error:
                self.json(path, data, headers)
            self.assertEqual(error.exception.code, 403)
        self.json('/api/workbuddy/disable', {})
        with self.assertRaises(HTTPError) as error:
            self.json('/api/workbuddy/context', headers=self.wb_headers)
        self.assertEqual(error.exception.code, 403)

    def test_apply_rejects_changed_draft_and_stage_respects_submission_job(self):
        context = self.prepare()
        row = self.row(context)
        self.json('/api/workbuddy/stage', {'context_id': context['context_id'], 'rows': [row]}, self.wb_headers)
        pending = self.json('/api/workbuddy/status')['pending']
        self.json('/api/save', {'bugs': [{'id': row['suggested_bug_id'], 'steps': '人工修改后的步骤'}]})
        with self.assertRaises(HTTPError) as error:
            self.json('/api/workbuddy/apply', {'plan_id': pending['plan_id'], 'assignments': [
                {'row_id': pending['rows'][0]['row_id'], 'bug_id': row['suggested_bug_id'], 'mode': 'replace'}]})
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(next(bug for bug in self.json('/api/state')['bugs']
                              if bug['id'] == row['suggested_bug_id'])['steps'], '人工修改后的步骤')
        self.app.job['running'] = True
        try:
            with self.assertRaises(HTTPError):
                self.json('/api/workbuddy/stage', {'context_id': context['context_id'], 'rows': [row]}, self.wb_headers)
        finally:
            self.app.job['running'] = False

    def test_bundle_asset_and_connection_lifetime(self):
        self.prepare()
        status = self.json('/api/workbuddy/status')
        session_file = Path(status['connection_file'])
        with self.request('/workbuddy.js') as response:
            self.assertIn(b'installWorkBuddy', response.read())
        self.app.workbuddy.close()
        self.assertFalse(session_file.exists())

    def test_offline_guide_serves_scripts_and_all_screenshots_with_image_types(self):
        with self.request('/index.html') as response:
            self.assertIn(b'/workbuddy_help.js', response.read())
        with self.request('/workbuddy_help.js') as response:
            self.assertIn(b'installWorkBuddyGuide', response.read())
        with self.request('/workbuddy_help.css') as response:
            self.assertIn('text/css', response.headers['Content-Type'])
        for step, name in enumerate(('scan', 'send', 'preview', 'import'), 1):
            with self.request(f'/help/workbuddy-{step}-{name}.jpg') as response:
                self.assertEqual(response.headers['Content-Type'], 'image/jpeg')
                self.assertTrue(response.read().startswith(b'\xff\xd8'))
        with self.request('/help/workbuddy-3-workbuddy.png') as response:
            self.assertEqual(response.headers['Content-Type'], 'image/png')
            self.assertTrue(response.read().startswith(b'\x89PNG\r\n\x1a\n'))
        with self.assertRaises(HTTPError) as missing:
            self.request('/help/unknown.jpg')
        self.assertEqual(missing.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
