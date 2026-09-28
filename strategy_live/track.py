"""
Continuous tracker: recompute the frozen strategy on a schedule and keep the
snapshot history growing.

    py -m strategy_live.track                 # every 6 hours, forever
    py -m strategy_live.track --once          # single run
    py -m strategy_live.track --every 1800    # every 30 minutes

Run it beside the server; the dashboard reads whatever the tracker last wrote.

The point of the history is the drift log below: each run is compared with the
previous snapshot, and any change in the target book is recorded with the reason.
That is what turns a backtest into something you can actually audit later -
"why did it want to sell RPTECH on the 23rd" has an answer on disk.
"""
import sys
import io
import os
import json
import time
import argparse
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if __name__ == '__main__':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    except Exception:
        pass

SNAP_DIR = os.path.join(ROOT, 'strategy_live', 'snapshots')
DRIFT = os.path.join(ROOT, 'strategy_live', 'drift_log.jsonl')


def _target(snap):
    """The book the strategy wants after this snapshot's actions."""
    a = snap.get('actions', {})
    return sorted({x['symbol'] for x in a.get('hold', [])} |
                  {x['symbol'] for x in a.get('buy', [])})


def _prev_snapshot(exclude):
    xs = sorted(f for f in os.listdir(SNAP_DIR)
                if f.endswith('.json') and f not in ('latest.json', exclude))
    if not xs:
        return None
    with open(os.path.join(SNAP_DIR, xs[-1]), encoding='utf-8') as f:
        return json.load(f)


def run_once(verbose=True):
    from strategy_live.compute import build
    snap, path = build(with_backtest=True)

    prev = _prev_snapshot(os.path.basename(path))
    now_t = _target(snap)
    entry = {
        'at': datetime.now().isoformat(timespec='seconds'),
        'asof': snap['asof'],
        'param_hash': snap['param_hash'],
        'target': now_t,
        'cagr': (snap.get('performance') or {}).get('cagr'),
    }
    if prev:
        old_t = _target(prev)
        entry['added'] = sorted(set(now_t) - set(old_t))
        entry['removed'] = sorted(set(old_t) - set(now_t))
        entry['prev_asof'] = prev['asof']
        if prev['param_hash'] != snap['param_hash']:
            entry['PARAM_CHANGE'] = f"{prev['param_hash']} -> {snap['param_hash']}"
        # carry the stated reason for each drop, so it is auditable later
        reasons = {x['symbol']: x.get('reason')
                   for x in snap.get('actions', {}).get('sell', [])}
        if entry['removed']:
            entry['removal_reasons'] = {s: reasons.get(s) for s in entry['removed']}

    with open(DRIFT, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')

    if verbose:
        pf = snap.get('performance') or {}
        print(f"[{entry['at']}] asof {snap['asof']}  "
              f"CAGR {pf.get('cagr')}%  Sharpe {pf.get('sharpe')}  "
              f"({snap['compute_seconds']}s)")
        if entry.get('PARAM_CHANGE'):
            print(f"  !! PARAMETERS CHANGED: {entry['PARAM_CHANGE']}")
            print('     the validated holdout result no longer describes this run')
        if prev:
            if entry['added'] or entry['removed']:
                for s in entry['removed']:
                    print(f"  - {s:<14} {entry.get('removal_reasons', {}).get(s) or ''}")
                for s in entry['added']:
                    print(f"  + {s}")
            else:
                print('  book unchanged')
        print(f"  target ({len(now_t)}): {', '.join(now_t)}")
    return snap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--every', type=int, default=21600, help='seconds (default 6h)')
    a = ap.parse_args()

    if a.once:
        run_once()
        return

    print(f'tracking every {a.every}s  ({a.every/3600:.1f}h) - Ctrl+C to stop')
    print(f'drift log: {DRIFT}\n')
    while True:
        try:
            run_once()
        except Exception as e:
            print(f'[{datetime.now():%H:%M:%S}] run failed: {e}')
        try:
            time.sleep(a.every)
        except KeyboardInterrupt:
            print('\nstopped')
            return


if __name__ == '__main__':
    main()
