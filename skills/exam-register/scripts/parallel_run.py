"""Local coordinator journal. Only the master invokes mutations; no editor API calls.

The manifest is authoritative; queue directories are disposable projections rebuilt
on every transaction. A filesystem lock prevents concurrent master writes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


def require(ok, message):
    if not ok:
        raise ValueError(message)


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(4):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == 3:
                raise
            time.sleep(0.05 * (attempt + 1))


def local_file(root, name):
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), 'File must stay inside run directory')
    require(path.is_file(), 'Evidence file does not exist: ' + name)
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Run:
    def __init__(self, root):
        self.root = Path(root).resolve()

    @contextmanager
    def transaction(self):
        lock = self.root / '.coordinator.lock'
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ValueError('Coordinator lock exists; inspect its owner before recovery')
        try:
            os.write(fd, str(os.getpid()).encode())
            data = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
            yield data
            data['revision'] += 1
            atomic(self.root / 'manifest.json', data)
            self.project(data)
        finally:
            os.close(fd)
            lock.unlink()

    def project(self, data):
        for state in ('ready', 'editing', 'review_pending', 'completed'):
            folder = self.root / 'queue' / state
            folder.mkdir(parents=True, exist_ok=True)
            expected = {k: v for k, v in data['items'].items() if v['state'] == state}
            for old in folder.glob('*.json'):
                if old.stem not in expected:
                    old.unlink()
            for key, item in expected.items():
                atomic(folder / (key + '.json'), item)

    def rebuild(self):
        """Repair projections under the master lock without repeating an action."""
        with self.transaction() as data:
            self.event(data, 'rebuild', None)
            return {'revision_before': data['revision'], 'editing': [
                dict(item) for item in data['items'].values() if item['state'] == 'editing']}

    def init(self, spec):
        require(not (self.root / 'manifest.json').exists(), 'Run already exists')
        require(spec.get('extractors') in (1, 2), 'Current runtime supports 1 or 2 extractors')
        require(bool(spec.get('exam')), 'Exam scope required')
        items = {}
        orders = set()
        for entry in spec['items']:
            key = entry['id']
            require(re.fullmatch(r'[A-Za-z0-9_-]+', key), 'Invalid item id')
            require(key not in items, 'Duplicate item id')
            require(entry['type'] in ('choice', 'short', 'passage'), 'Invalid item type')
            require(entry['order'] not in orders, 'Duplicate order')
            orders.add(entry['order'])
            require(bool(entry.get('regions')), 'Regions required')
            for region in entry['regions']:
                local_file(self.root, region['image'])
                x, y, w, h = region['bbox']
                iw, ih = region['image_size']
                require(region['page'] >= 1 and x >= 0 and y >= 0 and w > 0 and h > 0
                        and x + w <= iw and y + h <= ih, 'Invalid region bounds')
            items[key] = dict(entry, state='planned', version=0, document_id=None)
            items[key]['source_hashes'] = {r['image']: digest(local_file(self.root, r['image'])) for r in entry['regions']}
        require(bool(items), 'Empty scope')
        for folder in ('source', 'pages', 'assignments', 'extracted', 'verification', 'queue'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        data = {'schema_version': 2, 'revision': 0, 'exam': spec['exam'],
                'extractors': spec['extractors'], 'items': items, 'events': []}
        atomic(self.root / 'manifest.json', data)
        self.project(data)

    def event(self, data, action, key, details=None):
        data['events'].append({'at': datetime.now(timezone.utc).isoformat(),
                               'action': action, 'item': key, 'details': details})

    def bind(self, key, document_id):
        with self.transaction() as data:
            item = data['items'][key]
            require(item['state'] == 'planned', 'Document already bound')
            require(document_id and all(i['document_id'] != document_id for i in data['items'].values()),
                    'Empty or duplicate document id')
            item.update(document_id=document_id, state='empty')
            self.event(data, 'bind', key)

    def remap(self, key, observation_file):
        """Correct a stopped item's target after the master inspects the editor."""
        with self.transaction() as data:
            item = data['items'][key]
            require(item['state'] in ('empty', 'needs_revision'), 'Return active work before remapping')
            path = local_file(self.root, observation_file)
            observation = json.loads(path.read_text(encoding='utf-8'))
            require(observation.get('previous_document_id') == item['document_id'], 'Wrong previous target')
            require(observation.get('target_verified') is True and bool(observation.get('reason')),
                    'Target inspection and reason required')
            target = observation.get('document_id')
            kind = observation.get('type')
            require(kind in ('choice', 'short', 'passage'), 'Invalid target type')
            require(target and all(k == key or i['document_id'] != target for k, i in data['items'].items()),
                    'Empty or duplicate document id')
            previous = {'document_id': item['document_id'], 'type': item['type']}
            require(previous != {'document_id': target, 'type': kind}, 'Mapping unchanged')
            item.update(document_id=target, type=kind, state='needs_revision',
                        spec_version=item.get('spec_version', 1) + 1)
            self.event(data, 'remap', key, {'previous': previous, 'observation': observation_file,
                                           'hash': digest(path)})
            return dict(item)

    def assign(self, key, owner):
        with self.transaction() as data:
            require(all(i['document_id'] for i in data['items'].values()), 'Bind every empty document first')
            require(owner in ['extractor-' + str(n) for n in range(1, data['extractors'] + 1)], 'Unknown extractor')
            item = data['items'][key]
            require(item['state'] in ('empty', 'needs_revision'), 'Not assignable')
            item.update(state='extracting', owner=owner, version=item['version'] + 1,
                        assignment_token=uuid.uuid4().hex)
            self.event(data, 'assign', key, owner)
            atomic(self.root / 'assignments' / (key + '.json'), item)
            return dict(item)

    def amend(self, key, spec_file):
        """Correct a returned item's source regions; never silently change document type."""
        with self.transaction() as data:
            item = data['items'][key]
            require(item['state'] in ('empty', 'needs_revision'), 'Return active work before correcting scope')
            patch = json.loads(local_file(self.root, spec_file).read_text(encoding='utf-8'))
            require(set(patch) <= {'regions', 'related', 'reason'} and bool(patch.get('reason')), 'Only source corrections with reason supported')
            for region in patch.get('regions', []):
                local_file(self.root, region['image'])
                x, y, w, h = region['bbox']
                iw, ih = region['image_size']
                require(region['page'] >= 1 and x >= 0 and y >= 0 and w > 0 and h > 0
                        and x + w <= iw and y + h <= ih, 'Invalid region bounds')
            require('regions' not in patch or bool(patch['regions']), 'Empty regions')
            item.update(patch)
            item['source_hashes'] = {r['image']: digest(local_file(self.root, r['image'])) for r in item['regions']}
            item['spec_version'] = item.get('spec_version', 1) + 1
            self.event(data, 'amend', key, patch['reason'])

    def ready(self, key, token, draft_file):
        with self.transaction() as data:
            item = data['items'][key]
            require(item['state'] == 'extracting' and item['assignment_token'] == token, 'Stale assignment')
            path = local_file(self.root, draft_file)
            draft = json.loads(path.read_text(encoding='utf-8'))
            require(draft.get('id') == key and draft.get('version') == item['version'], 'Wrong draft version')
            require(draft.get('document_id') == item['document_id'], 'Wrong draft document target')
            require(draft.get('source_checked') is True and draft.get('unresolved') == [], 'Unresolved extraction')
            require(bool(draft.get('html')) and bool(draft.get('source_regions')), 'Content and source required')
            require(draft['source_regions'] == item['regions'], 'Draft source differs from assignment')
            for name, hash_value in item['source_hashes'].items():
                require(digest(local_file(self.root, name)) == hash_value, 'Source changed after assignment')
            if item['type'] != 'passage':
                require(draft.get('answer') is not None and bool(draft.get('answer_source')), 'Official answer required')
            assets = {name: digest(local_file(self.root, name)) for name in draft.get('assets', [])}
            item.update(state='ready', draft=draft_file, draft_hash=digest(path), asset_hashes=assets,
                        ready_order=data['revision'] + 1)
            self.event(data, 'ready', key)

    def claim(self, only=None):
        with self.transaction() as data:
            return self._claim(data, only)

    def _next_ready(self, data, only):
        allowed = None
        if only is not None:
            require(len(only) == len(set(only)), 'Duplicate claim item id')
            unknown = [key for key in only if key not in data['items']]
            require(not unknown, 'Unknown claim item id: ' + ', '.join(unknown))
            allowed = set(only)
        ready = sorted((i for i in data['items'].values()
                        if i['state'] == 'ready' and (allowed is None or i['id'] in allowed)),
                       key=lambda i: i['ready_order'])
        if not ready:
            return None
        item = ready[0]
        for name, hash_value in item['source_hashes'].items():
            require(digest(local_file(self.root, name)) == hash_value, 'Source changed after ready')
        require(digest(local_file(self.root, item['draft'])) == item['draft_hash'], 'Draft changed after ready')
        for name, hash_value in item['asset_hashes'].items():
            require(digest(local_file(self.root, name)) == hash_value, 'Asset changed after ready')
        return item

    def _claim(self, data, only):
        item = self._next_ready(data, only)
        require(not any(i['state'] == 'editing' for i in data['items'].values()), 'Single editor already busy')
        if item is None:
            return None
        item.update(state='editing', edit_token=uuid.uuid4().hex)
        self.event(data, 'claim', item['id'])
        return dict(item, spec_version=item.get('spec_version', 1))

    def preview_next(self, only=None):
        """Advisory snapshot for file prefetch; never grants editor ownership."""
        data = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
        item = self._next_ready(data, only)
        if item is None:
            return None
        fields = ('id', 'document_id', 'type', 'version', 'regions', 'draft',
                  'source_hashes', 'draft_hash', 'asset_hashes')
        return {**{key: item[key] for key in fields},
                'spec_version': item.get('spec_version', 1),
                'revision': data['revision'], 'preview_only': True}

    def validate_evidence(self, item, evidence_file):
        evidence_path = local_file(self.root, evidence_file)
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        require(evidence.get('document_id') == item['document_id'] and evidence.get('version') == item['version'], 'Wrong evidence target')
        checks = ('saved', 'reopened', 'source_compared', 'content_matches')
        require(all(evidence.get(c) is True for c in checks), 'Incomplete verification')
        if item['type'] != 'passage':
            require(evidence.get('answer_matches') is True, 'Answer not verified')
        require(bool(evidence.get('screenshot')), 'Reopen screenshot required')
        shot = local_file(self.root, evidence['screenshot'])
        for name, hash_value in item['source_hashes'].items():
            require(digest(local_file(self.root, name)) == hash_value, 'Source changed while editing')
        require(digest(local_file(self.root, item['draft'])) == item['draft_hash'], 'Draft changed while editing')
        for name, hash_value in item['asset_hashes'].items():
            require(digest(local_file(self.root, name)) == hash_value, 'Asset changed while editing')
        return evidence_path, shot

    def submit(self, key, token, evidence_file):
        with self.transaction() as data:
            self._submit(data, key, token, evidence_file)

    def _submit(self, data, key, token, evidence_file):
        item = data['items'][key]
        require(item['state'] == 'editing' and item['edit_token'] == token, 'Stale edit token')
        evidence_path, shot = self.validate_evidence(item, evidence_file)
        item.update(state='review_pending', evidence=evidence_file,
                    evidence_hash=digest(evidence_path), screenshot_hash=digest(shot))
        self.event(data, 'submit', key)
        return dict(item)

    def submit_and_claim(self, key, token, evidence_file, only=None):
        """Submit and grant the next scoped FIFO item in one manifest commit."""
        with self.transaction() as data:
            submitted = self._submit(data, key, token, evidence_file)
            next_item = self._claim(data, only)
            return {'submitted': submitted, 'next': next_item}

    def finish(self, key, token, evidence_file):
        with self.transaction() as data:
            item = data['items'][key]
            require(item['state'] in ('editing', 'review_pending') and item['edit_token'] == token,
                    'Stale edit token')
            evidence_path, shot = self.validate_evidence(item, evidence_file)
            if item['state'] == 'review_pending':
                require(evidence_file == item['evidence'], 'Submitted evidence changed')
                require(digest(evidence_path) == item['evidence_hash'], 'Submitted evidence changed')
                require(digest(shot) == item['screenshot_hash'], 'Submitted screenshot changed')
            item.update(state='completed', evidence=evidence_file,
                        evidence_hash=digest(evidence_path), screenshot_hash=digest(shot))
            self.event(data, 'finish', key)

    def return_item(self, key, token, reason, stopped=False):
        with self.transaction() as data:
            item = data['items'][key]
            require(bool(reason), 'Reason required')
            require(item['state'] in ('extracting', 'ready', 'editing', 'review_pending'), 'Not active')
            expected = item.get('edit_token') if item['state'] in ('editing', 'review_pending') else item['assignment_token']
            require(token == expected, 'Stale token')
            require(item['state'] != 'editing' or stopped, 'Confirm editor stopped and inspect saved document before recovery')
            item.update(state='needs_revision', reason=reason)
            self.event(data, 'return', key, reason)

    def resume(self, key, token, observation_file):
        """Renew editor ownership after confirmed stop, retaining the fixed draft."""
        with self.transaction() as data:
            item = data['items'][key]
            require(item['state'] == 'editing' and item['edit_token'] == token, 'Stale edit token')
            path = local_file(self.root, observation_file)
            observation = json.loads(path.read_text(encoding='utf-8'))
            require(observation.get('document_id') == item['document_id']
                    and observation.get('version') == item['version'], 'Wrong recovery target')
            require(observation.get('stopped') is True and bool(observation.get('last_state')),
                    'Actual stopped editor and saved-state observation required')
            require(digest(local_file(self.root, item['draft'])) == item['draft_hash'], 'Draft changed before resume')
            for name, hash_value in {**item['source_hashes'], **item['asset_hashes']}.items():
                require(digest(local_file(self.root, name)) == hash_value, 'Source or asset changed before resume')
            item.update(edit_token=uuid.uuid4().hex, recovery_observation=observation_file)
            self.event(data, 'resume', key, {'observation': observation_file, 'hash': digest(path)})
            return dict(item)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('init'); p.add_argument('spec')
    p = sub.add_parser('bind'); p.add_argument('id'); p.add_argument('document_id')
    p = sub.add_parser('remap'); p.add_argument('id'); p.add_argument('observation')
    p = sub.add_parser('assign'); p.add_argument('id'); p.add_argument('owner')
    p = sub.add_parser('amend'); p.add_argument('id'); p.add_argument('spec')
    p = sub.add_parser('ready'); p.add_argument('id'); p.add_argument('token'); p.add_argument('draft')
    p = sub.add_parser('claim'); p.add_argument('--only', nargs='+')
    p = sub.add_parser('preview-next'); p.add_argument('--only', nargs='+')
    p = sub.add_parser('submit'); p.add_argument('id'); p.add_argument('token'); p.add_argument('evidence')
    p = sub.add_parser('submit-and-claim'); p.add_argument('id'); p.add_argument('token'); p.add_argument('evidence'); p.add_argument('--only', nargs='+')
    p = sub.add_parser('finish'); p.add_argument('id'); p.add_argument('token'); p.add_argument('evidence')
    p = sub.add_parser('return'); p.add_argument('id'); p.add_argument('token'); p.add_argument('reason'); p.add_argument('--editor-stopped', action='store_true')
    p = sub.add_parser('resume'); p.add_argument('id'); p.add_argument('token'); p.add_argument('observation')
    sub.add_parser('status')
    sub.add_parser('rebuild')
    args = parser.parse_args()
    run = Run(args.run)
    if args.action == 'init':
        result = run.init(json.loads(Path(args.spec).read_text(encoding='utf-8')))
    elif args.action == 'bind': result = run.bind(args.id, args.document_id)
    elif args.action == 'remap': result = run.remap(args.id, args.observation)
    elif args.action == 'assign': result = run.assign(args.id, args.owner)
    elif args.action == 'amend': result = run.amend(args.id, args.spec)
    elif args.action == 'ready': result = run.ready(args.id, args.token, args.draft)
    elif args.action == 'claim': result = run.claim(args.only)
    elif args.action == 'preview-next': result = run.preview_next(args.only)
    elif args.action == 'submit': result = run.submit(args.id, args.token, args.evidence)
    elif args.action == 'submit-and-claim': result = run.submit_and_claim(args.id, args.token, args.evidence, args.only)
    elif args.action == 'finish': result = run.finish(args.id, args.token, args.evidence)
    elif args.action == 'return': result = run.return_item(args.id, args.token, args.reason, args.editor_stopped)
    elif args.action == 'resume': result = run.resume(args.id, args.token, args.observation)
    elif args.action == 'rebuild': result = run.rebuild()
    else: result = json.loads((run.root / 'manifest.json').read_text(encoding='utf-8'))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
