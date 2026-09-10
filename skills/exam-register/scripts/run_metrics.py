"""Report observed coordinator timings, not estimates or model speed claims."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def metrics(data):
    events = data.get('events', [])
    durations = {'assignment_to_ready_seconds': [], 'ready_to_claim_seconds': [],
                 'claim_to_finish_seconds': []}
    starts = {}
    for event in events:
        key, action = event['item'], event['action']
        at = datetime.fromisoformat(event['at'])
        if action == 'return':
            starts.pop(key, None)
            continue
        prior = starts.setdefault(key, {})
        pair = {'ready': ('assign', 'assignment_to_ready_seconds'),
                'claim': ('ready', 'ready_to_claim_seconds'),
                'finish': ('claim', 'claim_to_finish_seconds')}.get(action)
        if pair and pair[0] in prior:
            durations[pair[1]].append({'item': key, 'seconds': (at-prior[pair[0]]).total_seconds()})
        prior[action] = at
    first = next((e['at'] for e in events if e['action'] == 'assign'), None)
    last = next((e['at'] for e in reversed(events) if e['action'] == 'finish'), None)
    completed = sum(i['state'] == 'completed' for i in data['items'].values())
    return {'scope': sorted(data['items']), 'items': len(data['items']), 'completed': completed,
            'complete': completed == len(data['items']),
            'first_assignment_to_last_finish_seconds':
                (datetime.fromisoformat(last)-datetime.fromisoformat(first)).total_seconds() if first and last else None,
            'returns': sum(e['action'] == 'return' for e in events), **durations,
            'interpretation': 'Includes coordinator/tool delays. Planning and empty-document creation excluded. Incomplete runs are not comparable completion times.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    print(json.dumps(metrics(json.loads(args.manifest.read_text(encoding='utf-8'))), indent=2, ensure_ascii=False))
