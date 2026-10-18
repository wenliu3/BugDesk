"""A slow company menu must not hold local draft editing or reconnect state."""
from pathlib import Path
import threading
import unittest

import test_app


class MenuResponsivenessTests(unittest.TestCase):
    setUp = test_app.HTTPTests.setUp
    tearDown = test_app.HTTPTests.tearDown
    request = test_app.HTTPTests.request
    json = test_app.HTTPTests.json
    prepare_bug = test_app.HTTPTests.prepare_bug
    wait_job = test_app.HTTPTests.wait_job

    def slow_menu(self):
        entered, release = threading.Event(), threading.Event()
        class Client:
            def options(self, product, project, execution):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('test did not release the simulated menu')
                return {'builds': [{'value': product, 'label': '版本' + product}]}
        self.app.client = Client()
        self.app.connection = {'connected': True, 'first_verified': False}
        results, errors = [], []
        def read():
            try:
                results.append(self.app.read_options({'product': '1'}))
            except Exception as error:
                errors.append(error)
        reader = threading.Thread(target=read)
        reader.start()
        self.assertTrue(entered.wait(2))
        return release, reader, results, errors

    def test_slow_menu_does_not_block_local_draft_save(self):
        folder = Path(self.temp.name) / '10.15' / '菜单打开后无响应'
        folder.mkdir(parents=True)
        bug = self.json('/api/scan', {'path': str(folder.parent)})['bugs'][0]
        release, reader, results, errors = self.slow_menu()
        saved, save_errors = threading.Event(), []
        def save():
            try:
                self.json('/api/save', {'bugs': [{'id': bug['id'], 'actual': '菜单未响应，步骤仍可编辑'}]})
                saved.set()
            except Exception as error:
                save_errors.append(error)
        writer = threading.Thread(target=save)
        writer.start()
        try:
            self.assertTrue(saved.wait(2), 'A company menu read blocked local draft saving')
        finally:
            release.set()
            reader.join(5)
            writer.join(5)
        self.assertFalse(errors or save_errors)
        self.assertEqual(self.json('/api/state')['bugs'][0]['actual'], '菜单未响应，步骤仍可编辑')
        self.assertEqual(results[0]['builds'][0]['value'], '1')

    def test_disconnect_during_menu_read_is_prompt_and_old_reply_is_not_cached(self):
        release, reader, _, errors = self.slow_menu()
        finished = threading.Event()
        def disconnect():
            self.app.disconnect()
            finished.set()
        disconnecter = threading.Thread(target=disconnect)
        disconnecter.start()
        try:
            self.assertTrue(finished.wait(2), 'Disconnect waited for an unrelated menu read')
        finally:
            release.set()
            reader.join(5)
            disconnecter.join(5)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)
        self.assertFalse(self.app.state()['connection']['connected'])
        self.assertEqual(self.app.state()['options'], {})
        self.assertEqual(self.app.state()['options_context'], {})

    def test_menu_requests_and_bug_creation_do_not_share_connector_state_concurrently(self):
        bug = self.prepare_bug()
        entered, release, created = threading.Event(), threading.Event(), threading.Event()
        in_menu = [False]
        class Client:
            def options(self, product, project, execution):
                in_menu[0] = True
                entered.set()
                try:
                    if not release.wait(5):
                        raise RuntimeError('test did not release the simulated menu')
                    return {'builds': []}
                finally:
                    in_menu[0] = False
            def create_bug(self, item, settings, attachments):
                if in_menu[0]:
                    raise AssertionError('A connector form read overlapped the create request')
                created.set()
                return {'id': 777, 'upload_status': {attachment['id']: 'uploaded' for attachment in attachments}}
        self.app.client = Client()
        self.app.connection = {'connected': True, 'first_verified': False, 'url': 'https://fixture.invalid/'}
        errors = []
        def read():
            try:
                self.app.read_options({'product': '1'})
            except ValueError as error:
                errors.append(error)
        reader = threading.Thread(target=read)
        reader.start()
        self.assertTrue(entered.wait(2))
        try:
            self.json('/api/submit', {'ids': [bug['id']]})
            self.assertFalse(created.wait(.1))
        finally:
            release.set()
            reader.join(5)
        self.wait_job()
        self.assertTrue(created.is_set())
        submitted = self.json('/api/state')['bugs'][0]
        self.assertEqual(submitted['status'], 'submitted')
        self.assertEqual(submitted['remote_id'], 777)
        self.assertEqual(self.app.state()['options'], {})


if __name__ == '__main__':
    unittest.main()
