import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/exam-register/scripts/connector.py'
spec = importlib.util.spec_from_file_location('connector', SCRIPT)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith('/redirect'):
            self.send_response(302)
            self.send_header('Location', '/leak')
            self.end_headers()
            return
        if self.path == '/leak':
            self.server.leaked = True
        if self.headers.get('Authorization') != 'Bearer twk_test':
            self.send_response(401)
            result = {'message': 'INVALID_TOKEN'}
        else:
            self.send_response(200)
            result = {'data': [], 'error': None, 'traceId': 'test'}
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def do_POST(self):
        if self.path != '/auth/handoff':
            self.send_error(404)
            return
        self.send_response(201)
        self.end_headers()
        self.wfile.write(json.dumps({'data': {'code': 'one-time-code', 'expiresIn': 30}, 'error': None}).encode())


class ConnectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.leaked = False
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def profile(self):
        return {'key': 'twk_test', 'api_url': self.url, 'web_url': 'https://editor.example'}

    def test_authenticated_read_and_safe_error(self):
        self.assertEqual(c.request(self.profile(), '/documents'), [])
        profile = self.profile()
        profile['key'] = 'twk_wrong_secret'
        with self.assertRaisesRegex(c.ConnectorError, '401: INVALID_TOKEN') as ctx:
            c.request(profile, '/documents')
        self.assertNotIn(profile['key'], str(ctx.exception))

    def test_redirect_does_not_forward_credential(self):
        with self.assertRaisesRegex(c.ConnectorError, '302'):
            c.request(self.profile(), '/redirect')
        self.assertFalse(self.server.leaked)

    def test_handoff_and_reject_external_redirect(self):
        url = c.handoff_url(self.profile(), '/documents/example/edit')
        self.assertTrue(url.startswith('https://editor.example/auth/handoff?'))
        self.assertIn('code=one-time-code', url)
        for redirect in ['//evil.example', '/documents/../admin', '/login?redirect=https://evil.example']:
            with self.assertRaises(c.ConnectorError):
                c.handoff_url(self.profile(), redirect)

    def test_invalid_destinations(self):
        for url in ['http://editor.example', 'https://user:pass@example.com',
                    'https://example.com?key=secret', 'file:///tmp', 'https://example.com\\evil',
                    'https://example.com:bad', 'https://example.com\n']:
            with self.assertRaises(c.ConnectorError):
                c.base_url(url)
        self.assertEqual(c.base_url('https://editor.example/api/v1/'), 'https://editor.example/api/v1')

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_encrypted_storage_and_tamper(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            profile = self.profile()
            c.save_profile(profile, directory)
            self.assertNotIn(b'twk_test', (directory / 'connection.dpapi').read_bytes())
            self.assertEqual(c.load_profile(directory), profile)
            (directory / 'connection.dpapi').write_bytes(b'corrupt')
            with self.assertRaises(c.ConnectorError):
                c.load_profile(directory)

    def test_install_relocation_and_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'skills'
            first = c.install(destination)
            (first / 'personal-marker').write_text('preserve me')
            second = c.install(destination)
            self.assertTrue((second / 'references/workflow.md').exists())
            self.assertFalse((second / 'personal-marker').exists())
            backups = list((Path(temp) / 'exam-register-backups').glob('*/personal-marker'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), 'preserve me')

    @unittest.skipUnless(os.name == 'nt', 'Windows installation flow')
    def test_installed_cli_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp:
            target = c.install(Path(temp) / 'codex' / 'skills')
            cli = target / 'scripts/connector.py'
            env = dict(os.environ, EXAM_REGISTER_HOME=str(Path(temp) / 'state'), PYTHONIOENCODING='utf-8')

            def run(*args, key=None):
                result = subprocess.run([sys.executable, str(cli), *args], input=key,
                                        text=True, encoding='utf-8', capture_output=True, env=env, cwd=temp)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('twk_test', result.stdout + result.stderr)
                return result.stdout

            run('configure', '--web-url', 'https://editor.example', '--api-url', self.url,
                '--key-stdin', key='twk_test\n')
            self.assertEqual(json.loads(run('status'))['api_url'], self.url)
            run('doctor')
            self.assertIn('code=one-time-code', run('open', '--print-url'))
            run('disconnect')
            self.assertFalse((Path(temp) / 'state/connection.dpapi').exists())


if __name__ == '__main__':
    unittest.main()
