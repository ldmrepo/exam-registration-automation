"""Synthetic temporary-file coordinator tests; no real exam/editor validation."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/exam-register/scripts/parallel_run.py'
spec = importlib.util.spec_from_file_location('parallel_run', SCRIPT)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class ParallelRunTests(unittest.TestCase):
    def test_atomic_retries_transient_permission_error(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'state.json'
            replace = c.os.replace
            calls = []
            def transient(source, destination):
                calls.append(destination)
                if len(calls) == 1:
                    raise PermissionError('temporary file reader')
                return replace(source, destination)
            with patch.object(c.os, 'replace', side_effect=transient), patch.object(c.time, 'sleep'):
                c.atomic(target, {'revision': 2})
            self.assertEqual(json.loads(target.read_text()), {'revision': 2})
            self.assertEqual(len(calls), 2)

    def test_atomic_persistent_permission_error_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'state.json'
            target.write_text('{"revision": 1}')
            with patch.object(c.os, 'replace', side_effect=PermissionError('denied')) as replace, patch.object(c.time, 'sleep'):
                with self.assertRaises(PermissionError):
                    c.atomic(target, {'revision': 2})
            self.assertEqual(replace.call_count, 4)
            self.assertEqual(json.loads(target.read_text()), {'revision': 1})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'run'
        self.root.mkdir()
        (self.root / 'page.png').write_bytes(b'synthetic page placeholder')
        self.spec = {'exam': 'SYNTHETIC TEST ONLY', 'extractors': 2, 'items': [
            {'id': f'q{i}', 'order': i, 'type': 'choice', 'regions': [
                {'image': 'page.png', 'page': 1, 'image_size': [100, 200], 'bbox': [0, 0, 50, 80]}]}
            for i in (1, 2)]}
        self.run = c.Run(self.root)

    def init(self):
        self.run.init(self.spec)
        self.run.bind('q1', 'doc1')
        self.run.bind('q2', 'doc2')

    def data(self):
        return json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))

    def write(self, name, data):
        (self.root / name).write_text(json.dumps(data), encoding='utf-8')
        return name

    def draft(self, item, **overrides):
        data = {'id': item['id'], 'version': item['version'], 'document_id': item['document_id'], 'source_checked': True,
                'unresolved': [], 'html': '<p>Synthetic question</p>',
                'source_regions': item['regions'], 'answer': '1', 'answer_source': 'synthetic', 'assets': []}
        data.update(overrides)
        return self.write('extracted/' + item['id'] + '.json', data)

    def ready(self, key='q1', **overrides):
        item = self.run.assign(key, 'extractor-1')
        self.run.ready(key, item['assignment_token'], self.draft(item, **overrides))
        return item

    def evidence(self, item, **overrides):
        (self.root / 'verification/shot.png').write_bytes(b'synthetic screenshot placeholder')
        data = {'document_id': item['document_id'], 'version': item['version'], 'saved': True,
                'reopened': True, 'source_compared': True, 'content_matches': True,
                'answer_matches': True, 'screenshot': 'verification/shot.png'}
        data.update(overrides)
        return self.write('verification/result.json', data)

    def test_fifo_ready_order_and_single_editor(self):
        self.init()
        self.ready('q2')
        self.ready('q1')
        item = self.run.claim()
        self.assertEqual(item['id'], 'q2')
        with self.assertRaisesRegex(ValueError, 'Single editor'):
            self.run.claim()
        self.run.finish('q2', item['edit_token'], self.evidence(item))
        self.assertEqual(self.run.claim()['id'], 'q1')
        self.assertTrue((self.root / 'queue/completed/q2.json').exists())
        self.assertFalse((self.root / 'queue/ready/q2.json').exists())

    def test_claim_only_selects_oldest_allowed_and_leaves_other_ready(self):
        self.init()
        self.ready('q1')
        self.ready('q2')
        item = self.run.claim(['q2'])
        self.assertEqual(item['id'], 'q2')
        self.assertEqual(self.data()['items']['q1']['state'], 'ready')
        self.assertTrue((self.root / 'queue/ready/q1.json').exists())

    def test_claim_only_rejects_unknown_and_duplicate_ids(self):
        self.init()
        self.ready('q1')
        before = self.data()
        with self.assertRaisesRegex(ValueError, 'Unknown claim item'):
            self.run.claim(['q1', 'q99'])
        self.assertEqual(self.data(), before)
        with self.assertRaisesRegex(ValueError, 'Duplicate claim item'):
            self.run.claim(['q1', 'q1'])
        self.assertEqual(self.data(), before)

    def test_submit_releases_editor_while_review_is_pending(self):
        self.init()
        self.ready('q1')
        self.ready('q2')
        first = self.run.claim()
        evidence = self.evidence(first)
        self.run.submit('q1', first['edit_token'], evidence)
        self.assertEqual(self.data()['items']['q1']['state'], 'review_pending')
        self.assertTrue((self.root / 'queue/review_pending/q1.json').exists())
        self.assertFalse((self.root / 'queue/editing/q1.json').exists())
        self.assertEqual(self.run.claim()['id'], 'q2')
        self.run.finish('q1', first['edit_token'], evidence)
        self.assertEqual(self.data()['items']['q1']['state'], 'completed')

    def test_submit_and_claim_commits_once_and_preserves_review(self):
        self.init()
        self.ready('q1')
        self.ready('q2')
        first = self.run.claim()
        evidence = self.evidence(first)
        before = self.data()
        with patch.object(self.run, 'project', wraps=self.run.project) as project:
            result = self.run.submit_and_claim('q1', first['edit_token'], evidence, ['q1', 'q2'])
        self.assertEqual(project.call_count, 1)
        self.assertEqual(self.data()['revision'], before['revision'] + 1)
        self.assertEqual([e['action'] for e in self.data()['events'][-2:]], ['submit', 'claim'])
        self.assertEqual(result['submitted']['state'], 'review_pending')
        self.assertEqual(result['next']['id'], 'q2')
        self.assertEqual(result['next']['document_id'], 'doc2')
        self.assertEqual(result['next']['draft'], 'extracted/q2.json')
        self.assertEqual(result['next']['spec_version'], 1)
        self.assertNotEqual(result['next']['edit_token'], first['edit_token'])
        self.assertTrue((self.root / 'queue/review_pending/q1.json').exists())
        self.assertTrue((self.root / 'queue/editing/q2.json').exists())
        self.assertFalse((self.root / 'queue/editing/q1.json').exists())
        with self.assertRaisesRegex(ValueError, 'Single editor'):
            self.run.claim()
        with self.assertRaisesRegex(ValueError, 'Stale edit token'):
            self.run.submit_and_claim('q1', first['edit_token'], evidence)
        self.run.finish('q1', first['edit_token'], evidence)
        self.assertEqual(self.data()['items']['q2']['state'], 'editing')

    def test_submit_and_claim_no_scoped_ready_still_submits(self):
        self.init()
        self.ready('q1')
        self.ready('q2')
        first = self.run.claim()
        result = self.run.submit_and_claim('q1', first['edit_token'], self.evidence(first), ['q1'])
        self.assertIsNone(result['next'])
        self.assertEqual(self.data()['items']['q1']['state'], 'review_pending')
        self.assertEqual(self.data()['items']['q2']['state'], 'ready')

    def test_submit_and_claim_fifo_within_scope(self):
        self.spec['items'].append(dict(copy.deepcopy(self.spec['items'][0]), id='q3', order=3))
        self.init()
        self.run.bind('q3', 'doc3')
        self.ready('q1')
        first = self.run.claim()
        self.ready('q3')
        self.ready('q2')
        result = self.run.submit_and_claim('q1', first['edit_token'], self.evidence(first), ['q2', 'q3'])
        self.assertEqual(result['next']['id'], 'q3')
        self.assertEqual(self.data()['items']['q2']['state'], 'ready')

    def test_submit_and_claim_invalid_evidence_scope_or_token_rolls_back(self):
        self.init()
        self.ready('q1')
        self.ready('q2')
        first = self.run.claim()
        for token, changes, only in [('stale', {}, None), (first['edit_token'], {'reopened': False}, None),
                                     (first['edit_token'], {}, ['q2', 'q99']),
                                     (first['edit_token'], {}, ['q2', 'q2'])]:
            with self.subTest(token=token, changes=changes, only=only):
                before = self.data()
                evidence = self.evidence(first, **changes)
                with self.assertRaises(ValueError):
                    self.run.submit_and_claim('q1', token, evidence, only)
                self.assertEqual(self.data(), before)
                self.assertTrue((self.root / 'queue/editing/q1.json').exists())
                self.assertFalse((self.root / 'queue/review_pending/q1.json').exists())
                self.assertFalse((self.root / '.coordinator.lock').exists())

    def test_submit_and_claim_changed_next_input_rolls_back_both(self):
        self.init()
        self.ready('q1')
        (self.root / 'figure.png').write_bytes(b'original')
        self.ready('q2', assets=['figure.png'])
        first = self.run.claim()
        evidence = self.evidence(first)
        for name in ('extracted/q2.json', 'figure.png'):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(b'changed')
                before = self.data()
                with self.assertRaisesRegex(ValueError, 'changed after ready'):
                    self.run.submit_and_claim('q1', first['edit_token'], evidence)
                self.assertEqual(self.data(), before)
                path.write_bytes(original)

    def test_submit_and_claim_projection_failure_recovers_existing_tokens(self):
        self.init()
        self.ready('q1')
        self.ready('q2')
        first = self.run.claim()
        evidence = self.evidence(first)
        with patch.object(self.run, 'project', side_effect=PermissionError('projection busy')):
            with self.assertRaises(PermissionError):
                self.run.submit_and_claim('q1', first['edit_token'], evidence)
        committed = self.data()
        self.assertEqual(committed['items']['q1']['state'], 'review_pending')
        next_item = committed['items']['q2']
        self.assertEqual(next_item['state'], 'editing')
        self.assertEqual(self.run.rebuild()['editing'], [next_item])
        self.run.finish('q1', first['edit_token'], evidence)

    def test_preview_is_read_only_and_grants_no_tokens_even_for_revised_item(self):
        self.init()
        self.ready('q1')
        self.ready('q2')
        first = self.run.claim()
        self.run.return_item('q1', first['edit_token'], 'stopped', stopped=True)
        self.ready('q1')  # Retains a stale edit_token internally; preview must omit it.
        self.run.claim(['q2'])
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        preview = self.run.preview_next(['q1'])
        self.assertEqual(preview['id'], 'q1')
        self.assertTrue(preview['preview_only'])
        self.assertEqual(preview['version'], 2)
        self.assertNotIn('edit_token', preview)
        self.assertNotIn('assignment_token', preview)
        self.assertNotIn('owner', preview)
        self.assertIsNone(self.run.preview_next(['q2']))
        with self.assertRaisesRegex(ValueError, 'Unknown claim item'):
            self.run.preview_next(['q99'])
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_handoff_cli_json_contract(self):
        self.init()
        self.ready('q1')
        self.ready('q2')
        first = self.run.claim()
        evidence = self.evidence(first)
        prefix = [sys.executable, str(SCRIPT), '--run', str(self.root)]
        preview = subprocess.run(prefix + ['preview-next', '--only', 'q2'], check=True, capture_output=True, text=True)
        self.assertTrue(json.loads(preview.stdout)['preview_only'])
        result = subprocess.run(prefix + ['submit-and-claim', 'q1', first['edit_token'], evidence,
                                         '--only', 'q2'], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['submitted']['state'], 'review_pending')
        self.assertEqual(payload['next']['id'], 'q2')
        self.assertEqual(payload['next']['edit_token'], self.data()['items']['q2']['edit_token'])

    def test_review_rejects_stale_token_and_changed_evidence_hashes(self):
        self.init()
        self.ready('q1')
        item = self.run.claim()
        evidence = self.evidence(item)
        self.run.submit('q1', item['edit_token'], evidence)
        with self.assertRaisesRegex(ValueError, 'Stale edit token'):
            self.run.finish('q1', 'stale', evidence)
        self.evidence(item, observations='changed after submit')
        with self.assertRaisesRegex(ValueError, 'Submitted evidence changed'):
            self.run.finish('q1', item['edit_token'], evidence)
        self.evidence(item)
        (self.root / 'verification/shot.png').write_bytes(b'changed after submit')
        with self.assertRaisesRegex(ValueError, 'Submitted screenshot changed'):
            self.run.finish('q1', item['edit_token'], evidence)
        (self.root / 'verification/shot.png').write_bytes(b'synthetic screenshot placeholder')
        (self.root / 'page.png').write_bytes(b'changed after submit')
        with self.assertRaisesRegex(ValueError, 'Source changed while editing'):
            self.run.finish('q1', item['edit_token'], evidence)
        self.assertEqual(self.data()['items']['q1']['state'], 'review_pending')

    def test_review_return_uses_edit_token_without_editor_stop(self):
        self.init()
        self.ready('q1')
        item = self.run.claim()
        self.run.submit('q1', item['edit_token'], self.evidence(item))
        with self.assertRaisesRegex(ValueError, 'Stale token'):
            self.run.return_item('q1', 'stale', 'review failed')
        self.run.return_item('q1', item['edit_token'], 'review failed')
        self.assertEqual(self.data()['items']['q1']['state'], 'needs_revision')

    def test_legacy_finish_from_editing_is_preserved(self):
        self.init()
        self.ready('q1')
        item = self.run.claim()
        self.run.finish('q1', item['edit_token'], self.evidence(item))
        self.assertEqual(self.data()['items']['q1']['state'], 'completed')

    def test_source_change_after_ready_and_during_edit(self):
        self.init()
        self.ready('q1')
        page = self.root / 'page.png'
        original = page.read_bytes()
        page.write_bytes(b'changed original')
        with self.assertRaisesRegex(ValueError, 'Source changed after ready'):
            self.run.claim()
        page.write_bytes(original)
        item = self.run.claim()
        page.write_bytes(b'changed original again')
        with self.assertRaisesRegex(ValueError, 'Source changed while editing'):
            self.run.finish('q1', item['edit_token'], self.evidence(item))
        self.assertEqual(self.data()['items']['q1']['state'], 'editing')

    def test_resume_requires_observed_stop_and_rejects_old_token(self):
        self.init()
        self.ready()
        item = self.run.claim()
        observation = self.write('verification/stop.json', {'document_id': 'doc1', 'version': 1,
                                 'stopped': False, 'last_state': 'saved'})
        with self.assertRaisesRegex(ValueError, 'Actual stopped'):
            self.run.resume('q1', item['edit_token'], observation)
        self.write(observation, {'document_id': 'doc1', 'version': 1, 'stopped': True,
                                'last_state': 'saved; owned test tab closed'})
        renewed = self.run.resume('q1', item['edit_token'], observation)
        self.assertEqual(renewed['version'], item['version'])
        self.assertNotEqual(renewed['edit_token'], item['edit_token'])
        with self.assertRaisesRegex(ValueError, 'Stale edit token'):
            self.run.finish('q1', item['edit_token'], self.evidence(item))
        self.run.finish('q1', renewed['edit_token'], self.evidence(renewed))

    def test_bind_all_before_assignment_and_duplicate_ids(self):
        self.run.init(self.spec)
        self.run.bind('q1', 'doc1')
        with self.assertRaisesRegex(ValueError, 'duplicate document'):
            self.run.bind('q2', 'doc1')
        with self.assertRaisesRegex(ValueError, 'Bind every'):
            self.run.assign('q1', 'extractor-1')
        with self.assertRaisesRegex(ValueError, 'already bound'):
            self.run.bind('q1', 'other')

    def test_invalid_region_and_path_traversal(self):
        (Path(self.tmp.name) / 'outside.png').write_bytes(b'outside')
        for updates in ({'bbox': [-1, 0, 5, 5]}, {'bbox': [90, 0, 20, 5]},
                        {'bbox': [0, 0, 0, 5]}, {'page': 0}, {'image': '../outside.png'}):
            with self.subTest(updates=updates):
                s = copy.deepcopy(self.spec)
                s['items'][0]['regions'][0].update(updates)
                with self.assertRaises(ValueError):
                    self.run.init(s)
                self.assertFalse((self.root / 'manifest.json').exists())

    def test_wrong_version_token_and_unresolved_rejected_without_commit(self):
        self.init()
        item = self.run.assign('q1', 'extractor-1')
        for token, changes in [('wrong', {}), (item['assignment_token'], {'version': 0}),
                               (item['assignment_token'], {'unresolved': ['unclear']}),
                               (item['assignment_token'], {'answer': None})]:
            with self.subTest(changes=changes, token=token):
                before = self.data()
                with self.assertRaises(ValueError):
                    self.run.ready('q1', token, self.draft(item, **changes))
                self.assertEqual(self.data(), before)
                self.assertFalse((self.root / '.coordinator.lock').exists())

    def test_modified_draft_blocks_claim(self):
        self.init()
        self.ready()
        (self.root / 'extracted/q1.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Draft changed'):
            self.run.claim()
        self.assertEqual(self.data()['items']['q1']['state'], 'ready')

    def test_modified_asset_blocks_claim(self):
        self.init()
        (self.root / 'figure.png').write_bytes(b'original')
        self.ready(assets=['figure.png'])
        (self.root / 'figure.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Asset changed'):
            self.run.claim()

    def test_modified_asset_blocks_finish(self):
        self.init()
        (self.root / 'figure.png').write_bytes(b'original')
        self.ready(assets=['figure.png'])
        item = self.run.claim()
        (self.root / 'figure.png').write_bytes(b'changed during editing')
        with self.assertRaisesRegex(ValueError, 'Asset changed'):
            self.run.finish('q1', item['edit_token'], self.evidence(item))
        self.assertEqual(self.data()['items']['q1']['state'], 'editing')

    def test_recovery_requires_stopped_and_invalidates_old_tokens(self):
        self.init()
        original = self.ready()
        item = self.run.claim()
        with self.assertRaisesRegex(ValueError, 'Confirm editor stopped'):
            self.run.return_item('q1', item['edit_token'], 'synthetic failure')
        self.run.return_item('q1', item['edit_token'], 'verified stopped', stopped=True)
        revised = self.run.assign('q1', 'extractor-2')
        self.assertEqual(revised['version'], 2)
        self.assertEqual(revised['document_id'], 'doc1')
        with self.assertRaisesRegex(ValueError, 'Stale assignment'):
            self.run.ready('q1', original['assignment_token'], self.draft(revised))
        with self.assertRaisesRegex(ValueError, 'Stale edit token'):
            self.run.finish('q1', item['edit_token'], self.evidence(item))

    def test_finish_rejects_wrong_target_failed_checks_and_changed_draft(self):
        self.init()
        self.ready()
        item = self.run.claim()
        for changes in ({'document_id': 'wrong'}, {'version': 99}, {'reopened': False},
                        {'answer_matches': False}, {'screenshot': '../outside.png'}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.run.finish('q1', item['edit_token'], self.evidence(item, **changes))
                self.assertEqual(self.data()['items']['q1']['state'], 'editing')
        (self.root / 'extracted/q1.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Draft changed while editing'):
            self.run.finish('q1', item['edit_token'], self.evidence(item))

    def test_source_image_change_rejected_at_ready(self):
        self.init()
        item = self.run.assign('q1', 'extractor-1')
        original_hash = item['source_hashes']['page.png']
        (self.root / 'page.png').write_bytes(b'changed synthetic source')
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            self.run.ready('q1', item['assignment_token'], self.draft(item))
        self.assertEqual(self.data()['items']['q1']['source_hashes']['page.png'], original_hash)
        self.assertEqual(self.data()['items']['q1']['state'], 'extracting')

    def test_draft_must_reference_exact_assigned_regions(self):
        self.init()
        item = self.run.assign('q1', 'extractor-1')
        wrong = copy.deepcopy(item['regions'])
        wrong[0]['bbox'] = [10, 10, 20, 20]
        with self.assertRaisesRegex(ValueError, 'source differs'):
            self.run.ready('q1', item['assignment_token'], self.draft(item, source_regions=wrong))
        self.assertEqual(self.data()['items']['q1']['state'], 'extracting')

    def test_active_scope_amend_refused_then_return_reassign_versions(self):
        self.init()
        item = self.run.assign('q1', 'extractor-1')
        regions = copy.deepcopy(item['regions'])
        regions[0]['bbox'] = [10, 10, 60, 90]
        patch = self.write('correction.json', {'regions': regions, 'reason': 'synthetic boundary correction'})
        with self.assertRaisesRegex(ValueError, 'Return active work'):
            self.run.amend('q1', patch)
        self.run.ready('q1', item['assignment_token'], self.draft(item))
        with self.assertRaisesRegex(ValueError, 'Return active work'):
            self.run.amend('q1', patch)
        editing = self.run.claim()
        with self.assertRaisesRegex(ValueError, 'Return active work'):
            self.run.amend('q1', patch)
        self.run.return_item('q1', editing['edit_token'], 'stopped and inspected synthetic document', stopped=True)
        self.run.amend('q1', patch)
        amended = self.data()['items']['q1']
        self.assertEqual(amended['spec_version'], 2)
        self.assertEqual(amended['regions'], regions)
        self.assertEqual(amended['document_id'], 'doc1')
        reassigned = self.run.assign('q1', 'extractor-2')
        self.assertEqual(reassigned['version'], item['version'] + 1)
        self.assertEqual(reassigned['spec_version'], 2)
        with self.assertRaisesRegex(ValueError, 'Stale assignment'):
            self.run.ready('q1', item['assignment_token'], self.draft(item))
        self.run.ready('q1', reassigned['assignment_token'], self.draft(reassigned))

    def test_amend_rejects_empty_bad_bounds_type_mutation_and_path(self):
        self.init()
        for update in ({'regions': []}, {'type': 'short'}, {'regions': [
                {'image': 'page.png', 'page': 1, 'image_size': [100, 200], 'bbox': [99, 0, 10, 10]}]},
                {'regions': [{'image': '../outside.png', 'page': 1, 'image_size': [100, 200], 'bbox': [0, 0, 10, 10]}]}):
            with self.subTest(update=update):
                before = self.data()
                patch = self.write('correction.json', dict(update, reason='synthetic invalid patch'))
                with self.assertRaises(ValueError):
                    self.run.amend('q1', patch)
                self.assertEqual(self.data(), before)

    def test_existing_lock_refuses_mutation(self):
        self.init()
        (self.root / '.coordinator.lock').write_text('synthetic owner', encoding='utf-8')
        before = self.data()
        with self.assertRaisesRegex(ValueError, 'Coordinator lock exists'):
            self.run.assign('q1', 'extractor-1')
        self.assertEqual(self.data(), before)
        self.assertTrue((self.root / '.coordinator.lock').exists())

    def test_projection_rebuilt_from_authoritative_manifest(self):
        self.init()
        self.ready()
        (self.root / 'queue/ready/q1.json').unlink()
        self.write('queue/completed/stale.json', {})
        self.run.project(self.data())
        self.assertTrue((self.root / 'queue/ready/q1.json').exists())
        self.assertFalse((self.root / 'queue/completed/stale.json').exists())

    def test_rebuild_after_committed_claim_keeps_token_and_single_owner(self):
        self.init()
        self.ready('q1')
        self.ready('q2')
        with patch.object(self.run, 'project', side_effect=PermissionError('projection busy')):
            with self.assertRaises(PermissionError):
                self.run.claim()
        committed = self.data()['items']['q1']
        self.assertEqual(committed['state'], 'editing')
        result = self.run.rebuild()
        self.assertEqual(result['editing'], [committed])
        self.assertEqual(self.data()['items']['q1'], committed)
        projected = json.loads((self.root / 'queue/editing/q1.json').read_text())
        self.assertEqual(projected, committed)
        self.assertFalse((self.root / 'queue/ready/q1.json').exists())
        with self.assertRaisesRegex(ValueError, 'Single editor'):
            self.run.claim()

    def test_remap_requires_return_and_reissues_draft_for_new_target(self):
        self.init()
        assigned = self.ready()
        observation = self.write('verification/remap.json', {
            'previous_document_id': 'doc1', 'document_id': 'corrected-doc',
            'type': 'short', 'target_verified': True, 'reason': 'Wrong blank type observed'})
        with self.assertRaisesRegex(ValueError, 'Return active'):
            self.run.remap('q1', observation)
        self.run.return_item('q1', assigned['assignment_token'], 'Wrong blank type')
        corrected = self.run.remap('q1', observation)
        self.assertEqual(corrected['spec_version'], 2)
        self.assertEqual(corrected['type'], 'short')
        self.assertEqual(corrected['document_id'], 'corrected-doc')
        with self.assertRaises(ValueError):
            self.run.ready('q1', assigned['assignment_token'], 'extracted/q1.json')
        updated = self.run.assign('q1', 'extractor-1')
        self.assertEqual(updated['version'], assigned['version'] + 1)
        self.assertNotEqual(updated['assignment_token'], assigned['assignment_token'])
        event = next(e for e in self.data()['events'] if e['action'] == 'remap')
        self.assertEqual(event['details']['previous']['document_id'], 'doc1')

    def test_remap_rejects_duplicate_unverified_and_wrong_previous(self):
        self.init()
        base = {'previous_document_id': 'doc1', 'document_id': 'new-doc',
                'type': 'short', 'target_verified': True, 'reason': 'Observed mismatch'}
        for change in ({'document_id': 'doc2'}, {'target_verified': False},
                       {'previous_document_id': 'wrong'}, {'type': 'unknown'}):
            before = self.data()
            observation = self.write('verification/remap.json', {**base, **change})
            with self.assertRaises(ValueError):
                self.run.remap('q1', observation)
            self.assertEqual(self.data(), before)

    def test_ready_rejects_wrong_document_despite_valid_version(self):
        self.init()
        item = self.run.assign('q1', 'extractor-1')
        draft = self.draft(item, document_id='other-document')
        before = self.data()
        with self.assertRaisesRegex(ValueError, 'Wrong draft document'):
            self.run.ready('q1', item['assignment_token'], draft)
        self.assertEqual(self.data(), before)


if __name__ == '__main__':
    unittest.main()
