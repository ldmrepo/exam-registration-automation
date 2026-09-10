"""Synthetic handoff protocol tests; no live exam/browser writes."""
import importlib.util
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_parallel_run as fixtures

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/exam-register/scripts/handoff_relay.py'
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location('handoff_relay', SCRIPT)
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


class HandoffRelayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ParallelRunTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.init()
        self.fixture.ready('q1')
        self.fixture.ready('q2')
        self.root = self.fixture.root
        self.item = self.fixture.run.claim(['q1'])
        self.token = self.item['edit_token']
        self.evidence = self.fixture.evidence(self.item)
        self.server = relay.Relay(self.root, ['q1', 'q2'])

    def send(self):
        relay.request(self.root, 'q1', self.token, self.evidence)
        return relay.location(self.root, 'inbox', self.token)

    def test_handoff_and_duplicate_never_finish_or_regrant(self):
        path = self.send()
        result = self.server.process(path)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['submitted']['state'], 'review_pending')
        self.assertEqual(result['next']['id'], 'q2')
        before = (self.root / 'manifest.json').read_bytes()
        response = relay.location(self.root, 'responses', self.token).read_bytes()
        self.assertIsNone(self.server.process(path))
        self.assertEqual(before, (self.root / 'manifest.json').read_bytes())
        self.assertEqual(response, relay.location(self.root, 'responses', self.token).read_bytes())
        self.assertEqual(relay.wait(self.root, self.token, .01), result)

    def test_next_null_and_outside_scope_unchanged(self):
        other = self.fixture.data()['items']['q2']
        result = relay.Relay(self.root, ['q1']).process(self.send())
        self.assertIsNone(result['next'])
        self.assertIsNone(relay.compact_response(result)['next'])
        self.assertEqual(self.fixture.data()['items']['q2'], other)

    def test_compact_handoff_preserves_ownership_cache_and_durable_response(self):
        full = self.server.process(self.send())
        original = copy.deepcopy(full)
        response_path = relay.location(self.root, 'responses', self.token)
        before = response_path.read_bytes()
        compact = relay.compact_response(full)
        submitted_keys = {'id', 'version', 'edit_token', 'evidence'}
        next_keys = {'id', 'document_id', 'type', 'version', 'spec_version',
                     'edit_token', 'draft', 'draft_hash', 'source_hashes', 'asset_hashes'}
        self.assertEqual(compact['submitted'], {key: full['submitted'][key] for key in submitted_keys})
        self.assertEqual(compact['next'], {key: full['next'][key] for key in next_keys})
        self.assertEqual(compact['status'], 'ok')
        self.assertEqual(compact['token'], self.token)
        self.assertEqual(full, original)
        self.assertEqual(response_path.read_bytes(), before)
        self.assertEqual(relay.wait(self.root, self.token, .01), full)
        self.assertIn('regions', full['next'])
        self.assertNotIn('regions', compact['next'])

    def test_compact_errors_timeout_and_ack_preserve_all_information(self):
        values = [
            {'status': 'recoverable_error', 'token': self.token, 'next': None,
             'error': 'commit uncertain', 'recovery': 'inspect manifest and attempts'},
            {'status': 'recoverable_error', 'request': 'bad.json', 'error': 'output failed',
             'recovery': 'Stopped. Never blind retry.'},
            {'status': 'rejected', 'token': self.token, 'next': None, 'error': 'outside scope'},
            {'status': 'timeout', 'token': self.token, 'next': None},
            {'status': 'requested', 'item': 'q1', 'token': self.token},
        ]
        for value in values:
            with self.subTest(status=value['status']):
                self.assertEqual(relay.compact_response(value), value)
        # Displaying a partial record must not invent ownership or cache fields.
        self.assertEqual(relay.compact_response({'status': 'ok', 'submitted': {'id': 'q1'}, 'next': None}),
                         {'status': 'ok', 'submitted': {'id': 'q1'}, 'next': None})

    def test_cli_wait_compact_verbose_and_timeout_are_read_only(self):
        full = self.server.process(self.send())
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for verbose in (False, True):
            command = [sys.executable, str(SCRIPT), '--run', str(self.root), 'wait',
                       '--token', self.token, '--max-seconds', '.01']
            if verbose:
                command.append('--verbose')
            result = subprocess.run(command, capture_output=True, text=True, timeout=4)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), full if verbose else relay.compact_response(full))
        result = subprocess.run([sys.executable, str(SCRIPT), '--run', str(self.root), 'wait',
            '--token', 'missing-token', '--max-seconds', '.01'], capture_output=True, text=True, timeout=4)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'status': 'timeout', 'token': 'missing-token', 'next': None})
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_cli_request_and_serve_verbose_use_full_records(self):
        full = self.server.process(self.send())
        for action in ('request', 'serve'):
            with self.subTest(action=action), patch.object(sys, 'stdout', new_callable=io.StringIO) as output:
                command = [str(SCRIPT), '--run', str(self.root), action, '--verbose']
                if action == 'request':
                    command += ['--item', 'q1', '--token', self.token, '--evidence', self.evidence, '--wait-seconds', '1']
                    with patch.object(sys, 'argv', command), patch.object(relay, 'request_and_wait', return_value=full):
                        relay.main()
                else:
                    command += ['--only', 'q1', '--max-seconds', '1']
                    with patch.object(sys, 'argv', command), patch.object(relay.Relay, 'serve',
                            side_effect=lambda seconds, emit, drained: emit(full)):
                        relay.main()
                self.assertEqual(json.loads(output.getvalue()), full)

    def test_wrong_scope_and_malformed_request_no_manifest_mutation(self):
        for payload in ({'item': 'q2', 'edit_token': self.token, 'evidence': self.evidence},
                        {'garbage': True}, [],
                        {'item': 'q1', 'edit_token': self.token, 'evidence': '../outside.json'}):
            with self.subTest(payload=payload):
                path = relay.location(self.root, 'inbox', self.token)
                path.write_text(json.dumps(payload), encoding='utf-8')
                before = (self.root / 'manifest.json').read_bytes()
                result = relay.Relay(self.root, ['q1']).process(path)
                self.assertEqual(result['status'], 'rejected')
                self.assertEqual(before, (self.root / 'manifest.json').read_bytes())
                relay.location(self.root, 'responses', self.token).unlink()

    def test_stale_token_refuses_grant(self):
        token = 'stale-token'
        path = relay.location(self.root, 'inbox', token)
        relay.publish(path, {'item': 'q1', 'edit_token': token, 'evidence': self.evidence})
        before = (self.root / 'manifest.json').read_bytes()
        self.assertEqual(self.server.process(path)['status'], 'recoverable_error')
        self.assertEqual(before, (self.root / 'manifest.json').read_bytes())
        with self.assertRaisesRegex(ValueError, 'Stale'):
            relay.request(self.root, 'q1', token, self.evidence)

    def test_readonly_wait_timeout_and_bounds(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(relay.wait(self.root, self.token, .02)['status'], 'timeout')
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        for seconds in (0, -1, 46, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                relay.wait(self.root, self.token, seconds)
        with self.assertRaises(ValueError):
            relay.wait(self.root, '../bad', .01)

    def test_bounded_stop_and_global_lock(self):
        events = []
        start = time.monotonic()
        self.server.serve(.03, events.append)
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(events[-1]['reason'], 'bounded_timeout')
        lock = self.root / '.handoff-relay.lock'
        self.assertFalse(lock.exists())
        lock.write_text('other master')
        with self.assertRaises(FileExistsError):
            self.server.serve(.03, events.append)
        self.assertEqual(lock.read_text(), 'other master')

    def test_committed_output_failure_never_retries(self):
        path = self.send()
        publish = relay.publish
        def fail_response(target, value):
            if target.parent.name == 'responses':
                raise OSError('simulated response disk failure')
            publish(target, value)
        with patch.object(relay, 'publish', side_effect=fail_response):
            with self.assertRaises(OSError):
                self.server.process(path)
        before = (self.root / 'manifest.json').read_bytes()
        self.assertEqual(self.fixture.data()['items']['q1']['state'], 'review_pending')
        self.assertEqual(self.server.process(path)['status'], 'recoverable_error')
        self.assertEqual(before, (self.root / 'manifest.json').read_bytes())

    def test_projection_failure_is_recoverable_not_retried(self):
        path = self.send()
        with patch.object(self.server.run, 'project', side_effect=OSError('projection failure')):
            result = self.server.process(path)
        self.assertEqual(result['status'], 'recoverable_error')
        self.assertEqual(self.fixture.data()['items']['q1']['state'], 'review_pending')
        self.assertEqual(self.fixture.data()['items']['q2']['state'], 'editing')
        self.assertIsNone(self.server.process(path))

    def test_transient_pretransaction_lock_retries_only_acquisition(self):
        path = self.send()
        original = self.server.run.submit_and_claim
        calls = []
        def locked_once(*args, **kwargs):
            calls.append(True)
            if len(calls) == 1:
                raise ValueError('Coordinator lock exists; inspect its owner before recovery')
            return original(*args, **kwargs)
        with patch.object(self.server.run, 'submit_and_claim', side_effect=locked_once):
            self.assertEqual(self.server.process(path)['status'], 'ok')
        self.assertEqual(len(calls), 2)

    def test_persistent_lock_respects_deadline(self):
        path = self.send()
        (self.root / '.coordinator.lock').write_text('other master')
        start = time.monotonic()
        self.assertEqual(self.server.process(path, start + .03)['status'], 'recoverable_error')
        self.assertLess(time.monotonic() - start, .5)
        self.assertEqual(self.fixture.data()['items']['q1']['state'], 'editing')

    def test_stop_when_drained(self):
        self.send()
        events = []
        relay.Relay(self.root, ['q1']).serve(2, events.append, stop_when_drained=True)
        self.assertEqual(events[-1], {'status': 'stopped', 'reason': 'scope_drained'})
        self.assertEqual(self.fixture.data()['items']['q1']['state'], 'review_pending')

    def test_single_client_payload_request_wait(self):
        folder = self.root / 'verification/q1'
        folder.mkdir()
        (folder / 'shot.png').write_bytes(b'synthetic')
        payload = json.loads((self.root / self.evidence).read_text())
        payload['screenshot'] = 'verification/q1/shot.png'
        payload['input_checks'] = dict.fromkeys(('target_confirmed', 'main_editor_focus_confirmed',
            'structure_before_save_confirmed', 'structure_after_reopen_confirmed'), True)
        # This checks a successful subprocess handoff, not a 1-second latency SLA.
        # Windows process startup and fsync may exceed that under host load.
        proc = subprocess.Popen([sys.executable, str(SCRIPT), '--run', str(self.root),
            'serve', '--only', 'q1', 'q2', '--max-seconds', '10'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.assertEqual(json.loads(proc.stdout.readline())['status'], 'started')
        client = subprocess.run([sys.executable, str(SCRIPT), '--run', str(self.root), 'request',
            '--item', 'q1', '--token', self.token, '--payload', '-', '--wait-seconds', '5'],
            input=json.dumps(payload), capture_output=True, text=True, timeout=15)
        self.assertEqual(client.returncode, 0, client.stderr)
        compact = json.loads(client.stdout)
        self.assertEqual(compact['status'], 'ok', compact)
        self.assertEqual(compact['next']['id'], 'q2')
        full = relay.wait(self.root, self.token, .01)
        self.assertEqual(compact, relay.compact_response(full))
        output, error = proc.communicate(timeout=15)
        self.assertEqual(proc.returncode, 0, error)
        events = [json.loads(line) for line in output.splitlines()]
        self.assertEqual(next(event for event in events if event['status'] == 'ok'), compact)
        self.assertEqual(full['submitted']['state'], 'review_pending')


if __name__ == '__main__':
    unittest.main()
