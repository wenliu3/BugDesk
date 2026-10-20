"""Only the local UI capability can undo a committed WorkBuddy import."""

import unittest
from urllib.error import HTTPError

import test_app
import test_workbuddy_http


class DraftUndoHTTPTests(unittest.TestCase):
    setUp = test_app.HTTPTests.setUp
    tearDown = test_app.HTTPTests.tearDown
    request = test_app.HTTPTests.request
    json = test_app.HTTPTests.json
    prepare = test_workbuddy_http.WorkBuddyHTTPTests.prepare
    row = staticmethod(test_workbuddy_http.WorkBuddyHTTPTests.row)

    def apply_workbuddy(self):
        context = self.prepare()
        row = self.row(context)
        self.json('/api/workbuddy/stage', {'context_id': context['context_id'], 'rows': [row]}, self.wb_headers)
        pending = self.json('/api/workbuddy/status')['pending']
        result = self.json('/api/workbuddy/apply', {'plan_id': pending['plan_id'], 'review_scope': 'bugs',
                                                   'assignments': [{'row_id': pending['rows'][0]['row_id'],
                                                                    'bug_id': row['suggested_bug_id']}]})
        return row, result

    def test_undo_requires_ui_token_and_no_external_snapshot_can_be_supplied(self):
        row, result = self.apply_workbuddy()
        payload = {'transaction_id': result['undo']['transaction_id']}
        for headers in (self.wb_headers, {'X-BugDesk-Token': ''}):
            with self.subTest(headers=headers), self.assertRaises(HTTPError) as error:
                self.json('/api/workbuddy/undo', payload, headers)
            self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            self.json('/api/workbuddy/undo', {**payload, 'before': {'actual': '外部注入'}})
        self.assertEqual(error.exception.code, 400)
        bug = next(bug for bug in self.json('/api/state')['bugs'] if bug['id'] == row['suggested_bug_id'])
        self.assertEqual(bug['actual'], row['actual'])
        self.assertTrue(self.json('/api/workbuddy/status')['undo']['available'])

    def test_undo_endpoint_works_with_disabled_connection_and_is_single_use(self):
        row, result = self.apply_workbuddy()
        self.assertIsNotNone(result['pending'])
        payload = {'transaction_id': result['undo']['transaction_id']}
        self.json('/api/workbuddy/disable', {})
        reverted = self.json('/api/workbuddy/undo', payload)
        self.assertEqual(reverted['undone'], 1)
        self.assertIsNone(reverted['undo'])
        self.assertIsNone(reverted['pending'])
        bug = next(bug for bug in reverted['state']['bugs'] if bug['id'] == row['suggested_bug_id'])
        for field in ('preconditions', 'steps', 'actual', 'expected'):
            self.assertEqual(bug[field], '')
        self.assertFalse(bug['reviewed'])
        self.assertEqual(bug['case_sources'], [])
        self.assertIsNone(self.json('/api/workbuddy/status')['undo'])
        with self.assertRaises(HTTPError) as error:
            self.json('/api/workbuddy/undo', payload)
        self.assertEqual(error.exception.code, 400)

    def test_stale_undo_is_rejected_without_clearing_pending_plan(self):
        row, result = self.apply_workbuddy()
        payload = {'transaction_id': result['undo']['transaction_id']}
        self.json('/api/save', {'bugs': [{'id': row['suggested_bug_id'], 'actual': '之后人工修改'}]})
        before = self.json('/api/state')
        pending = self.json('/api/workbuddy/status')['pending']
        self.assertFalse(self.json('/api/workbuddy/status')['undo']['available'])
        with self.assertRaises(HTTPError) as error:
            self.json('/api/workbuddy/undo', payload)
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(self.json('/api/state'), before)
        self.assertEqual(self.json('/api/workbuddy/status')['pending'], pending)


if __name__ == '__main__':
    unittest.main()
