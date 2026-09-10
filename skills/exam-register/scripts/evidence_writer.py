"""Write editor-owned evidence once; never change the coordinator manifest."""
import argparse
import json
from pathlib import Path
import re
import sys


def require(ok, message):
    if not ok:
        raise ValueError(message)


def write_evidence(run, item_id, token, payload):
    root = Path(run).resolve()
    require(re.fullmatch(r'[A-Za-z0-9_-]+', item_id), 'Invalid item id')
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    require(item_id in manifest['items'], 'Unknown item id')
    item = manifest['items'][item_id]
    require(item['state'] == 'editing' and item.get('edit_token') == token, 'Stale edit token')
    require(isinstance(payload, dict), 'Evidence must be an object')
    require(payload.get('document_id') == item['document_id']
            and payload.get('version') == item['version'], 'Wrong evidence target')
    require(payload.get('id', item_id) == item_id, 'Wrong evidence item id')
    require(payload.get('edit_token', token) == token, 'Wrong evidence edit token')
    checks = payload.get('input_checks', {})
    require(isinstance(checks, dict) and all(checks.get(name) is True for name in (
        'target_confirmed', 'main_editor_focus_confirmed',
        'structure_before_save_confirmed', 'structure_after_reopen_confirmed')),
        'Input focus and structure checks required')
    folder = root / 'verification' / item_id
    require(folder.resolve() == folder, 'Evidence directory must not redirect to another path')
    screenshot = payload.get('screenshot')
    require(isinstance(screenshot, str) and bool(screenshot), 'Screenshot required')
    shot = (root / screenshot).resolve()
    require(shot.is_relative_to(folder) and shot.is_file(), 'Screenshot must exist inside this item verification directory')
    target = folder / 'evidence.json'
    require(shot != target, 'Screenshot cannot be the evidence file')
    # Serialize before creating the file. Exclusive create also refuses symlinks
    # and racing writers; a prior evidence record is never truncated.
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    with target.open('x', encoding='utf-8') as output:
        output.write(encoded)
    return {'item': item_id, 'evidence': f'verification/{item_id}/evidence.json'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--item', required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--payload', required=True, help='JSON file path, or - for stdin')
    args = parser.parse_args()
    raw = sys.stdin.read() if args.payload == '-' else Path(args.payload).read_text(encoding='utf-8-sig')
    print(json.dumps(write_evidence(args.run, args.item, args.token, json.loads(raw)), ensure_ascii=False))


if __name__ == '__main__':
    main()
