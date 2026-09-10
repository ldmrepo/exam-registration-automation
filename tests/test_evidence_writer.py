"""Synthetic editor evidence tests; no browser or real run writes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'skills/exam-register/scripts/evidence_writer.py'
spec = importlib.util.spec_from_file_location('evidence_writer', SCRIPT)
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)


class EvidenceWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {'items': {f'q{i}': {'state': 'editing' if i == 2 else 'completed',
                         'document_id': f'doc{i}', 'version': 1, 'edit_token': f'token{i}'} for i in (1, 2)}}
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        for item in ('q1', 'q2'):
            folder = self.root / 'verification' / item
            folder.mkdir(parents=True)
            (folder / 'shot.png').write_bytes(b'synthetic screenshot')
        self.payload = {'document_id': 'doc2', 'version': 1, 'saved': True,
                        'reopened': True, 'source_compared': True, 'content_matches': True,
                        'answer_matches': True, 'screenshot': 'verification/q2/shot.png',
                        'input_checks': dict.fromkeys(('target_confirmed',
                            'main_editor_focus_confirmed', 'structure_before_save_confirmed',
                            'structure_after_reopen_confirmed'), True)}

    def test_focus_and_structure_gates_before_file_creation(self):
        for name in self.payload['input_checks']:
            bad = {**self.payload, 'input_checks': {**self.payload['input_checks'], name: False}}
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Input focus'):
                writer.write_evidence(self.root, 'q2', 'token2', bad)
        with self.assertRaisesRegex(ValueError, 'Input focus'):
            writer.write_evidence(self.root, 'q2', 'token2', {**self.payload, 'input_checks': {}})
        self.assertFalse((self.root / 'verification/q2/evidence.json').exists())

    def test_valid_write_preserves_manifest_and_other_item(self):
        manifest = (self.root / 'manifest.json').read_bytes()
        old = self.root / 'verification/q1/evidence.json'
        old.write_bytes(b'completed evidence must stay exact')
        result = writer.write_evidence(self.root, 'q2', 'token2', self.payload)
        self.assertEqual(result, {'item': 'q2', 'evidence': 'verification/q2/evidence.json'})
        self.assertEqual(json.loads((self.root / result['evidence']).read_text()), self.payload)
        self.assertEqual((self.root / 'manifest.json').read_bytes(), manifest)
        self.assertEqual(old.read_bytes(), b'completed evidence must stay exact')

    def test_rejects_stale_token_and_completed_item(self):
        for item, token in [('q2', 'token1'), ('q1', 'token1')]:
            with self.subTest(item=item), self.assertRaisesRegex(ValueError, 'Stale edit token'):
                writer.write_evidence(self.root, item, token, self.payload)
        self.assertFalse((self.root / 'verification/q2/evidence.json').exists())

    def test_rejects_wrong_payload_target_and_screenshot_scope(self):
        for change in ({'document_id': 'doc1'}, {'version': 2}, {'id': 'q1'}, {'edit_token': 'token1'},
                       {'screenshot': 'verification/q1/shot.png'}, {'screenshot': 'verification/q2/missing.png'},
                       {'screenshot': '../shot.png'}, {'screenshot': 'verification/q2/../q1/shot.png'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                writer.write_evidence(self.root, 'q2', 'token2', {**self.payload, **change})
        for item in ('../q2', 'unknown'):
            with self.subTest(item=item), self.assertRaises(ValueError):
                writer.write_evidence(self.root, item, 'token2', self.payload)
        self.assertFalse((self.root / 'verification/q2/evidence.json').exists())

    def test_existing_evidence_never_overwritten(self):
        target = self.root / 'verification/q2/evidence.json'
        target.write_bytes(b'previous evidence exact bytes')
        with self.assertRaises(FileExistsError):
            writer.write_evidence(self.root, 'q2', 'token2', self.payload)
        self.assertEqual(target.read_bytes(), b'previous evidence exact bytes')

    def test_cli_stdin_and_file(self):
        prefix = [sys.executable, str(SCRIPT), '--run', str(self.root), '--item', 'q2', '--token', 'token2']
        result = subprocess.run(prefix + ['--payload', '-'], input=json.dumps(self.payload),
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['evidence'], 'verification/q2/evidence.json')
        draft = self.root / 'payload.json'
        draft.write_text(json.dumps(self.payload), encoding='utf-8')
        again = subprocess.run(prefix + ['--payload', str(draft)], capture_output=True, text=True)
        self.assertNotEqual(again.returncode, 0)
        self.assertEqual(json.loads((self.root / 'verification/q2/evidence.json').read_text()), self.payload)


if __name__ == '__main__':
    unittest.main()
