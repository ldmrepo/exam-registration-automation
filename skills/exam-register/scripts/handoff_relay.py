"""Bounded, master-started local handoff relay. Never completes an item."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import uuid

from parallel_run import Run, local_file, require
from evidence_writer import write_evidence


def compact_response(value):
    """Project successful handoffs for display; durable records stay complete."""
    if value.get('status') != 'ok':
        return value
    fields = {
        'submitted': ('id', 'version', 'edit_token', 'evidence'),
        'next': ('id', 'document_id', 'type', 'version', 'spec_version',
                 'edit_token', 'draft', 'draft_hash', 'source_hashes', 'asset_hashes'),
    }
    result = dict(value)
    for name, keys in fields.items():
        item = value.get(name)
        if isinstance(item, dict):
            result[name] = {key: item[key] for key in keys if key in item}
    return result


def token_name(token):
    require(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', token), 'Invalid token')
    return token + '.json'


def inside(root, relative):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    require(target.is_relative_to(root), 'Path must stay inside run')
    return target


def publish(path, value):
    """Flush then atomically publish without replacing an existing record."""
    temp = path.with_name('.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def location(root, kind, token):
    return inside(root, 'relay/' + kind + '/' + token_name(token))


def request(root, item, token, evidence):
    require(isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9_-]+', item), 'Invalid item')
    token_name(token)
    local_file(Path(root), evidence)
    data = json.loads(local_file(Path(root), 'manifest.json').read_text(encoding='utf-8'))
    current = data['items'].get(item, {})
    require(current.get('state') == 'editing' and current.get('edit_token') == token, 'Stale edit token')
    path = location(root, 'inbox', token)
    require(path.parent.is_dir(), 'Master relay must initialize inbox first')
    publish(path, {'item': item, 'edit_token': token, 'evidence': evidence})
    return {'status': 'requested', 'item': item, 'token': token}


def bounded(seconds, maximum):
    require(math.isfinite(seconds) and 0 < seconds <= maximum, f'Duration must be > 0 and <= {maximum}')


def wait(root, token, seconds=45):
    """Read only. A timeout conveys no editor ownership."""
    bounded(seconds, 45)
    path = location(root, 'responses', token)
    deadline = time.monotonic() + seconds
    while True:
        if path.is_file():
            return json.loads(path.read_text(encoding='utf-8'))
        if time.monotonic() >= deadline:
            return {'status': 'timeout', 'token': token, 'next': None}
        time.sleep(min(.1, max(0, deadline - time.monotonic())))


def request_and_wait(root, item, token, evidence=None, payload=None, seconds=None):
    require((evidence is None) != (payload is None), 'Provide evidence or payload, exclusively')
    if seconds is not None:
        bounded(seconds, 45)
    token_name(token)
    require(location(root, 'inbox', token).parent.is_dir(), 'Master relay must initialize inbox first')
    require(not location(root, 'inbox', token).exists(), 'Request already exists; use read-only wait')
    if payload is not None:
        evidence = write_evidence(root, item, token, payload)['evidence']
    result = request(root, item, token, evidence)
    return wait(root, token, seconds) if seconds is not None else result


class Relay:
    def __init__(self, root, only):
        self.root = Path(root).resolve()
        self.run = Run(self.root)
        self.only = list(only)
        data = json.loads(local_file(self.root, 'manifest.json').read_text(encoding='utf-8'))
        require(bool(self.only) and len(set(self.only)) == len(self.only), 'Explicit unique scope required')
        require(all(key in data['items'] for key in self.only), 'Unknown scope item')
        for kind in ('inbox', 'responses', 'attempts'):
            inside(self.root, 'relay/' + kind).mkdir(parents=True, exist_ok=True)

    def process(self, path, deadline=None):
        token = path.stem
        token_name(token)
        require(path.resolve() == location(self.root, 'inbox', token), 'Invalid request path')
        response = location(self.root, 'responses', token)
        attempt = location(self.root, 'attempts', token)
        if response.exists():
            return None
        if attempt.exists():
            result = {'status': 'recoverable_error', 'token': token, 'next': None,
                      'error': 'Prior attempt has no response. Master must inspect status and rebuild; never resubmit blindly.'}
            publish(response, result)
            return result
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            require(isinstance(payload, dict) and set(payload) == {'item', 'edit_token', 'evidence'}, 'Malformed request fields')
            require(payload['edit_token'] == token, 'Request token differs from filename')
            require(payload['item'] in self.only, 'Item outside master scope')
            require(isinstance(payload['evidence'], str), 'Evidence path required')
            local_file(self.root, payload['evidence'])
        except (ValueError, TypeError, OSError) as exc:
            result = {'status': 'rejected', 'token': token, 'next': None, 'error': str(exc)}
            publish(response, result)
            return result
        # A durable intent barrier prevents automatic retry after an uncertain commit.
        publish(attempt, {'request': payload, 'only': self.only, 'pid': os.getpid()})
        try:
            retry_until = min(time.monotonic() + 2, deadline if deadline is not None else float('inf'))
            while True:
                try:
                    result = {'status': 'ok', 'token': token, **self.run.submit_and_claim(
                        payload['item'], token, payload['evidence'], only=self.only)}
                    break
                except ValueError as exc:
                    # This exact core error occurs before transaction entry only.
                    if str(exc) != 'Coordinator lock exists; inspect its owner before recovery' or time.monotonic() >= retry_until:
                        raise
                    time.sleep(min(.05, max(0, retry_until - time.monotonic())))
        except Exception as exc:
            result = {'status': 'recoverable_error', 'token': token, 'next': None,
                      'error': str(exc), 'recovery': 'Master inspect manifest/status and rebuild before any retry.'}
        publish(response, result)
        return result

    def serve(self, seconds, emit, stop_when_drained=False):
        bounded(seconds, 3600)
        lock = inside(self.root, '.handoff-relay.lock')
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, json.dumps({'pid': os.getpid(), 'only': self.only, 'max_seconds': seconds}).encode())
            os.fsync(fd)
            deadline = time.monotonic() + seconds
            emit({'status': 'started', 'only': self.only, 'max_seconds': seconds})
            while time.monotonic() < deadline:
                for path in sorted(inside(self.root, 'relay/inbox').glob('*.json')):
                    if time.monotonic() >= deadline:
                        break
                    try:
                        result = self.process(path, deadline)
                        if result:
                            emit(result)
                            if result['status'] == 'recoverable_error':
                                return
                            if stop_when_drained and result['status'] == 'ok' and result['next'] is None:
                                data = json.loads(local_file(self.root, 'manifest.json').read_text(encoding='utf-8'))
                                if not any(data['items'][key]['state'] in ('ready', 'editing') for key in self.only):
                                    emit({'status': 'stopped', 'reason': 'scope_drained'})
                                    return
                    except Exception as exc:
                        # Includes publication/output failure after successful commit.
                        # Stop: persistent attempt marker is the recovery barrier.
                        emit({'status': 'recoverable_error', 'request': path.name, 'error': str(exc),
                              'recovery': 'Stopped. Inspect manifest, attempts and responses; never blind retry.'})
                        return
                time.sleep(min(.1, max(0, deadline - time.monotonic())))
            emit({'status': 'stopped', 'reason': 'bounded_timeout'})
        finally:
            os.close(fd)
            lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    sub = parser.add_subparsers(dest='action', required=True)
    server = sub.add_parser('serve')
    server.add_argument('--only', nargs='+', required=True)
    server.add_argument('--max-seconds', type=float, required=True)
    server.add_argument('--stop-when-drained', action='store_true')
    client = sub.add_parser('request')
    client.add_argument('--item', required=True)
    client.add_argument('--token', required=True)
    inputs = client.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--evidence')
    inputs.add_argument('--payload', help='JSON file inside run, or - for stdin')
    client.add_argument('--wait-seconds', type=float)
    reader = sub.add_parser('wait')
    reader.add_argument('--token', required=True)
    reader.add_argument('--max-seconds', type=float, default=45)
    for command in (server, client, reader):
        command.add_argument('--verbose', action='store_true', help='Print complete records instead of compact handoffs')
    args = parser.parse_args()
    def emit(value):
        print(json.dumps(value if args.verbose else compact_response(value), ensure_ascii=False), flush=True)
    if args.action == 'serve':
        Relay(args.run, args.only).serve(args.max_seconds, emit, args.stop_when_drained)
    elif args.action == 'request':
        payload = None
        if args.payload is not None:
            raw = sys.stdin.read() if args.payload == '-' else local_file(Path(args.run), args.payload).read_text(encoding='utf-8-sig')
            payload = json.loads(raw)
        emit(request_and_wait(args.run, args.item, args.token, args.evidence, payload, args.wait_seconds))
    else:
        emit(wait(args.run, args.token, args.max_seconds))


if __name__ == '__main__':
    main()
