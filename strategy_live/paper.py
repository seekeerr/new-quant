"""
Paper-trading ledger for the frozen strategy.

Purpose, stated plainly: this is NOT a test of whether the strategy makes money.
Three months cannot answer that. At ~25% annual volatility, a 3-month window has
a standard deviation of roughly 12%, so a perfectly good strategy shows anything
from -12% to +20% and a broken one shows the same range. Judging on P&L here is
judging noise.

What three months CAN answer, and what the gates below actually test:
  1. Can you get filled near the price the model assumed?  (slippage)
  2. Do the real costs match the modelled costs?
  3. Does the signal compute on time, every month, without manual rescue?
  4. Does the live book match the model's book?               (tracking)
  5. Can you actually sit through a drawdown without overriding it?

Those are operational questions, and they are exactly what breaks when a
backtest meets a broker. Returns appear only as a crash guardrail, never as a
pass condition.

    py -m strategy_live.paper start              begin the run
    py -m strategy_live.paper fill SYM 1234.50 8 log an actual fill
    py -m strategy_live.paper mark               mark to market today
    py -m strategy_live.paper status             ledger + gate progress
    py -m strategy_live.paper verdict            the Jan-1 go / no-go
"""
import sys
import io
import os
import json
import argparse
from datetime import datetime, date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if __name__ == '__main__':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    except Exception:
        pass

import pandas as pd

LEDGER = os.path.join(ROOT, 'strategy_live', 'paper_ledger.json')
SNAP = os.path.join(ROOT, 'strategy_live', 'snapshots', 'latest.json')

# Pre-registered before the run starts. Writing these down in advance is the
# whole point - decided afterwards, any outcome can be argued into a pass.
GATES = {
    'slippage': {
        'label': 'Fills within 0.5% of the modelled close',
        'test': 'median |fill - model close| / close <= 0.5%',
        'why': 'The backtest fills at the close. If real fills drift further '
               'than this, the 24% CAGR is not reachable and every other '
               'number is fiction.',
        'threshold': 0.5,
    },
    'costs': {
        'label': 'Real costs within 1.3x of modelled',
        'test': 'actual cost / modelled cost <= 1.3',
        'why': 'At Rs 1 lakh the model already assumes 0.2% per round trip. '
               'Much above that and the edge is eaten.',
        'threshold': 1.3,
    },
    'operations': {
        'label': 'All 3 monthly rebalances executed on time',
        'test': '3 rebalances, each within 2 trading days of the 1st',
        'why': 'A strategy you forget to run is not a strategy. This also '
               'proves the data pipeline stays fresh without babysitting.',
        'threshold': 3,
    },
    'tracking': {
        'label': 'Live book matches the model book',
        'test': '>= 90% name overlap at each rebalance',
        'why': 'Catches silent divergence - a stock you could not buy, a '
               'symbol change, a missed order.',
        'threshold': 90.0,
    },
    'discipline': {
        'label': 'No manual overrides',
        'test': 'zero positions opened or closed outside the model',
        'why': 'The most common way a systematic strategy dies. If you '
               'override it on paper, you will override it with money.',
        'threshold': 0,
    },
}

# Return is NOT a pass condition. It is only a stop-loss on the experiment.
CRASH_GUARD = -25.0   # percent; below this, stop and re-examine


def _load():
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding='utf-8') as f:
            return json.load(f)
    return None


def _save(d):
    with open(LEDGER, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2)


def _prices():
    from research_harness import load_panels
    close, *_ = load_panels()
    return close


def cmd_start(args):
    if _load() and not args.force:
        print('ledger already exists - use --force to restart (it is wiped)')
        return
    cap = float(args.capital)
    d = {
        'started': datetime.now().isoformat(timespec='seconds'),
        'start_date': args.start or str(date.today()),
        'review_date': args.review,
        'capital': cap, 'cash': cap,
        'is_real_money': False,
        'positions': {},        # symbol -> {shares, entry_px, entry_date, model_px}
        'fills': [],            # every logged fill
        'rebalances': [],       # dated record of each monthly run
        'marks': [],            # mark-to-market history
        'overrides': [],        # anything done outside the model
        'gates': GATES,
        'crash_guard': CRASH_GUARD,
    }
    _save(d)
    print(f'paper run started  capital Rs {cap:,.0f}')
    print(f'  start  {d["start_date"]}')
    print(f'  review {d["review_date"]}')
    print('\nPre-registered gates (decided NOW, not after the result):')
    for k, g in GATES.items():
        print(f'  [{k:<11}] {g["label"]}')
    print(f'\n  crash guard: stop if the book is below {CRASH_GUARD}%')
    print('\n  Return is deliberately NOT a gate. Three months of P&L is noise.')


def cmd_fill(args):
    d = _load()
    if not d:
        return print('no ledger - run: py -m strategy_live.paper start')
    sym, px, sh = args.symbol.upper(), float(args.price), int(args.shares)
    side = args.side.upper()

    snap = json.load(open(SNAP, encoding='utf-8')) if os.path.exists(SNAP) else {}
    model_px = None
    for r in snap.get('ranks', []):
        if r['symbol'] == sym:
            model_px = r['price']
            break

    val = px * sh
    rec = {'date': args.date or str(date.today()), 'symbol': sym, 'side': side,
           'shares': sh, 'price': px, 'value': round(val, 2),
           'model_price': model_px,
           'slip_pct': (round((px - model_px) / model_px * 100, 3)
                        if model_px else None),
           'cost': float(args.cost or 0)}
    d['fills'].append(rec)

    if side == 'BUY':
        d['cash'] -= val + rec['cost']
        p = d['positions'].setdefault(sym, {'shares': 0, 'entry_px': px,
                                            'entry_date': rec['date'],
                                            'model_px': model_px})
        tot = p['shares'] + sh
        p['entry_px'] = (p['entry_px'] * p['shares'] + px * sh) / tot if tot else px
        p['shares'] = tot
    else:
        d['cash'] += val - rec['cost']
        p = d['positions'].get(sym)
        if p:
            p['shares'] -= sh
            if p['shares'] <= 0:
                d['positions'].pop(sym)

    _save(d)
    s = f"  slip {rec['slip_pct']:+.2f}% vs model" if rec['slip_pct'] is not None else ''
    print(f"{side} {sh} {sym} @ {px}  = Rs {val:,.0f}{s}")
    print(f"  cash Rs {d['cash']:,.0f}  positions {len(d['positions'])}")


def cmd_mark(args):
    d = _load()
    if not d:
        return print('no ledger')
    if not d['positions']:
        print('no open positions')
    close = _prices()
    asof = close.index.max()
    total, rows = d['cash'], []
    for sym, p in d['positions'].items():
        px = float(close[sym].loc[:asof].iloc[-1]) if sym in close.columns else p['entry_px']
        v = px * p['shares']
        total += v
        rows.append((sym, p['shares'], p['entry_px'], px, v,
                     (px / p['entry_px'] - 1) * 100))
    pnl = total - d['capital']
    d['marks'].append({'date': str(asof.date()), 'value': round(total, 2),
                       'pnl': round(pnl, 2),
                       'pct': round(pnl / d['capital'] * 100, 2)})
    _save(d)

    print(f'mark to market  {asof:%Y-%m-%d}')
    print(f"  {'symbol':<13}{'sh':>6}{'entry':>10}{'now':>10}{'value':>12}{'P&L':>9}")
    for s_, sh, e, n, v, r in sorted(rows, key=lambda x: -x[4]):
        print(f'  {s_:<13}{sh:>6}{e:>10.2f}{n:>10.2f}{v:>12,.0f}{r:>8.1f}%')
    print(f"  {'cash':<13}{'':>6}{'':>10}{'':>10}{d['cash']:>12,.0f}")
    print(f"\n  total Rs {total:,.0f}   P&L Rs {pnl:+,.0f}  "
          f"({pnl/d['capital']*100:+.2f}%)")
    if pnl / d['capital'] * 100 < d['crash_guard']:
        print(f"\n  !! below the {d['crash_guard']}% crash guard - stop and review")


def _gate_results(d):
    out = {}

    slips = [abs(f['slip_pct']) for f in d['fills'] if f.get('slip_pct') is not None]
    out['slippage'] = {
        'value': round(pd.Series(slips).median(), 3) if slips else None,
        'pass': (pd.Series(slips).median() <= GATES['slippage']['threshold'])
        if slips else None,
        'detail': f'{len(slips)} fills measured',
    }

    # Modelled cost must come from the SAME cost model the backtest used, per
    # trade at its real size. A flat 0.1% baseline was wrong here: on a Rs 1
    # lakh book each position is ~Rs 10,000, where the flat Rs 20 brokerage
    # alone is 0.2% - so that baseline failed the gate on arithmetic rather
    # than on execution quality.
    act = sum(f.get('cost', 0) for f in d['fills'])
    modelled = 0.0
    try:
        from costs.cost_model import CostModel
        cm = CostModel()
        for f in d['fills']:
            tc = cm.calculate_trade_cost(f['symbol'], f['side'], f['shares'],
                                         f['price'], liquidity_tier=2)
            modelled += tc.total_cost
    except Exception:
        modelled = sum(f['value'] for f in d['fills']) * 0.002
    out['costs'] = {
        'value': round(act / modelled, 2) if modelled else None,
        'pass': (act / modelled <= GATES['costs']['threshold'])
        if modelled and act else None,
        'detail': f'actual Rs {act:,.0f} vs modelled Rs {modelled:,.0f}',
    }

    n = len(d['rebalances'])
    out['operations'] = {
        'value': n, 'pass': n >= GATES['operations']['threshold'],
        'detail': f'{n} of 3 rebalances logged',
    }

    ov = [r.get('overlap_pct') for r in d['rebalances'] if r.get('overlap_pct')]
    out['tracking'] = {
        'value': round(min(ov), 1) if ov else None,
        'pass': (min(ov) >= GATES['tracking']['threshold']) if ov else None,
        'detail': f'{len(ov)} rebalances checked',
    }

    out['discipline'] = {
        'value': len(d['overrides']),
        'pass': len(d['overrides']) == 0,
        'detail': f"{len(d['overrides'])} overrides",
    }
    return out


def cmd_status(args):
    d = _load()
    if not d:
        return print('no ledger - run: py -m strategy_live.paper start')
    last = d['marks'][-1] if d['marks'] else None
    print(f"paper run   Rs {d['capital']:,.0f}   "
          f"{d['start_date']} -> review {d['review_date']}")
    if last:
        print(f"  value Rs {last['value']:,.0f}   P&L {last['pct']:+.2f}%   "
              f"(marked {last['date']})")
    print(f"  positions {len(d['positions'])}   fills {len(d['fills'])}   "
          f"rebalances {len(d['rebalances'])}")

    print('\n  GATES (pre-registered)')
    res = _gate_results(d)
    for k, g in GATES.items():
        r = res[k]
        mark = '?' if r['pass'] is None else ('PASS' if r['pass'] else 'FAIL')
        v = '—' if r['value'] is None else r['value']
        print(f"    [{mark:^4}] {g['label']:<44} {v}   ({r['detail']})")


def cmd_verdict(args):
    d = _load()
    if not d:
        return print('no ledger')
    res = _gate_results(d)
    done = [k for k, r in res.items() if r['pass'] is not None]
    passed = [k for k in done if res[k]['pass']]
    last = d['marks'][-1] if d['marks'] else None

    print('=' * 72)
    print(f"  GO / NO-GO for real money   (review {d['review_date']})")
    print('=' * 72)
    for k, g in GATES.items():
        r = res[k]
        mark = 'not measured' if r['pass'] is None else (
            'PASS' if r['pass'] else 'FAIL')
        print(f"\n  {g['label']}")
        print(f"    result : {r['value']}  -> {mark}")
        print(f"    why    : {g['why']}")

    print('\n' + '-' * 72)
    if last:
        print(f"  P&L over the run: {last['pct']:+.2f}%  "
              f"(context only - NOT a gate)")
        if last['pct'] < d['crash_guard']:
            print(f"  CRASH GUARD BREACHED ({d['crash_guard']}%) - do not go live")
    if len(done) < len(GATES):
        print(f"  {len(GATES)-len(done)} gate(s) not yet measurable - run longer")
    elif len(passed) == len(GATES):
        print('  ALL GATES PASS - the execution side is sound.')
        print('  Note this says nothing about future returns. Start small.')
    else:
        print(f"  {len(GATES)-len(passed)} gate(s) FAILED: "
              f"{', '.join(k for k in done if not res[k]['pass'])}")
        print('  Fix the cause before committing money.')


def cmd_rebalance(args):
    """Log a monthly rebalance and check the live book against the model."""
    d = _load()
    if not d:
        return print('no ledger')
    snap = json.load(open(SNAP, encoding='utf-8'))
    a = snap.get('actions', {})
    model = {x['symbol'] for x in a.get('hold', [])} | {x['symbol'] for x in a.get('buy', [])}
    live = set(d['positions'])
    overlap = (len(model & live) / len(model) * 100) if model else None
    d['rebalances'].append({
        'date': args.date or str(date.today()),
        'asof': snap.get('asof'),
        'model_book': sorted(model), 'live_book': sorted(live),
        'overlap_pct': round(overlap, 1) if overlap is not None else None,
        'missing': sorted(model - live), 'extra': sorted(live - model),
    })
    _save(d)
    print(f'rebalance #{len(d["rebalances"])} logged  overlap {overlap:.0f}%')
    if model - live:
        print(f'  model wants, you lack : {", ".join(sorted(model-live))}')
    if live - model:
        print(f'  you hold, model drops : {", ".join(sorted(live-model))}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('start'); s.set_defaults(f=cmd_start)
    s.add_argument('--capital', default=100000)
    s.add_argument('--start'); s.add_argument('--review', default='2027-01-01')
    s.add_argument('--force', action='store_true')

    s = sub.add_parser('fill'); s.set_defaults(f=cmd_fill)
    s.add_argument('symbol'); s.add_argument('price'); s.add_argument('shares')
    s.add_argument('--side', default='BUY'); s.add_argument('--cost', default=0)
    s.add_argument('--date')

    s = sub.add_parser('mark'); s.set_defaults(f=cmd_mark)
    s = sub.add_parser('status'); s.set_defaults(f=cmd_status)
    s = sub.add_parser('verdict'); s.set_defaults(f=cmd_verdict)
    s = sub.add_parser('rebalance'); s.set_defaults(f=cmd_rebalance)
    s.add_argument('--date')

    a = ap.parse_args()
    a.f(a)


if __name__ == '__main__':
    main()
