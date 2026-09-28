"""
Produce a dated snapshot of the frozen strategy: current ranks, the portfolio it
implies, the trades needed to get there, and performance to date.

Snapshots are append-only JSON under strategy_live/snapshots/. Keeping every run
is the point - it is what lets you check later whether the signal you acted on
was the signal the model actually produced that day, rather than a number
reconstructed after the fact.

    py -m strategy_live.compute            # snapshot from the latest bar
    py -m strategy_live.compute --backtest # also refresh performance history
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

import numpy as np
import pandas as pd

from strategy_live.frozen import FROZEN, BENCHMARKS, param_hash
import signals as S
from research_harness import load_panels, evaluate
from run_smallcap_universe import RankBandUniverseBuilder
from config import SystemConfig

SNAP_DIR = os.path.join(ROOT, 'strategy_live', 'snapshots')
STATE = os.path.join(ROOT, 'strategy_live', 'state.json')
CAPITAL = os.path.join(ROOT, 'strategy_live', 'capital.json')
os.makedirs(SNAP_DIR, exist_ok=True)


def _scorer(turn, c=FROZEN):
    return S.blend([
        (S.momentum(c['mom_formation'], c['mom_skip']), c['w_momentum']),
        (S.low_vol(c['vol_lookback']), c['w_lowvol']),
        (S.amihud(c['amihud_lookback'])(turn), c['w_amihud']),
    ])


def current_ranks(top=60):
    """Score the eligible universe as of the latest bar."""
    close, high, low, vol, turn = load_panels()
    cfg = SystemConfig()
    asof = close.index.max()

    ub = RankBandUniverseBuilder(close, high, low, vol, turn, cfg.universe,
                                 FROZEN['rank_band'][0], FROZEN['rank_band'][1])
    snap = ub.build_universe(asof)
    uni = snap.symbols

    scores = _scorer(turn)(close, asof, uni)
    if scores.empty:
        raise RuntimeError('scorer produced nothing - check data freshness')

    # component detail, so a rank can be explained rather than just asserted
    mom = S.momentum(FROZEN['mom_formation'], FROZEN['mom_skip'])(close, asof, uni)
    lv = S.low_vol(FROZEN['vol_lookback'])(close, asof, uni)
    am = S.amihud(FROZEN['amihud_lookback'])(turn)(close, asof, uni)
    px = close.loc[asof]
    t20 = turn.loc[:asof].tail(20).median()
    r20 = close.loc[:asof].pct_change(20).iloc[-1]

    rows = []
    for i, sym in enumerate(scores.index[:top], 1):
        rows.append({
            'rank': i, 'symbol': sym,
            'score': round(float(scores[sym]), 4),
            'price': round(float(px.get(sym, np.nan)), 2),
            'ret20d': round(float(r20.get(sym, np.nan)) * 100, 2)
            if pd.notna(r20.get(sym, np.nan)) else None,
            'mom_pct': round(float(mom.rank(pct=True).get(sym, np.nan)) * 100, 1)
            if sym in mom.index else None,
            'lowvol_pct': round(float(lv.rank(pct=True).get(sym, np.nan)) * 100, 1)
            if sym in lv.index else None,
            'amihud_pct': round(float(am.rank(pct=True).get(sym, np.nan)) * 100, 1)
            if sym in am.index else None,
            'turnover_lakh': round(float(t20.get(sym, 0)) / 1e5, 1),
        })
    # Full rank map for EVERY scored name, not just the displayed top slice.
    # A held stock that has fallen to rank 400 and one sitting at rank 21 both
    # get sold, but they mean very different things - so record the real rank.
    full = {sym: i for i, sym in enumerate(scores.index, 1)}
    return asof, rows, len(uni), full


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding='utf-8') as f:
            return json.load(f)
    return {'holdings': [], 'last_rebalance': None, 'history': []}


def save_state(st):
    with open(STATE, 'w', encoding='utf-8') as f:
        json.dump(st, f, indent=2)


def plan_actions(ranks, holdings, full_rank=None):
    """
    Apply the buffer rule to today's ranks.
      hold  : currently held and rank <= buffer
      sell  : currently held and rank > buffer (or gone from the universe)
      buy   : highest-ranked names not held, filling the remaining slots
    """
    n, buf = FROZEN['n_stocks'], FROZEN['buffer']
    rank_of = dict(full_rank) if full_rank else {r['symbol']: r['rank']
                                                 for r in ranks}

    keep = sorted([s for s in holdings if rank_of.get(s, 10 ** 9) <= buf],
                  key=lambda s: rank_of[s])[:n]
    sell = [s for s in holdings if s not in keep]
    slots = n - len(keep)
    buy = [r['symbol'] for r in ranks
           if r['symbol'] not in keep][:max(slots, 0)]

    return {
        'hold': [{'symbol': s, 'rank': rank_of[s]} for s in keep],
        'sell': [{'symbol': s,
                  'rank': rank_of.get(s),
                  'reason': ('left universe' if s not in rank_of
                             else f'rank {rank_of[s]} > buffer {buf}')}
                 for s in sell],
        'buy': [{'symbol': s, 'rank': rank_of[s]} for s in buy],
        'slots_open': slots,
    }


def read_capital():
    cap = {'starting_capital': 10_000_000, 'started_on': None,
           'is_real_money': False}
    if os.path.exists(CAPITAL):
        with open(CAPITAL, encoding='utf-8') as f:
            cap.update({k: v for k, v in json.load(f).items()
                        if not k.startswith('_')})
    return cap


def performance(capital=None):
    """
    Backtest the frozen strategy over the clean out-of-sample window, AT THE
    CAPITAL BEING TRACKED.

    This must be a real run at that size, never a scaled version of a bigger
    one: at small books the Rs 20-per-order brokerage and whole-share rounding
    are a genuine drag, not a proportional one. Measured here, Rs 1 lakh earns
    24.34% against Rs 1 crore's 29.26% - a 4.9pp/yr gap that pure scaling would
    have hidden completely.
    """
    close, high, low, vol, turn = load_panels()
    cap = float(capital if capital is not None
                else read_capital()['starting_capital'])
    m = evaluate(_scorer(turn), close, high, low, vol, turn, split='live',
                 capital=cap, n_stocks=FROZEN['n_stocks'],
                 rebalance=FROZEN['rebalance'], buffer=FROZEN['buffer'],
                 rank_band=FROZEN['rank_band'], label='frozen')
    eq = m['equity']
    q = eq.resample('QE').last().pct_change().mul(100).dropna()
    mo = eq.resample('ME').last().pct_change().mul(100).dropna()
    return {
        'capital': cap,
        'cagr': round(m['cagr'] * 100, 2),
        'sharpe': round(m['sharpe'], 2),
        'maxdd': round(m['maxdd'] * 100, 2),
        'start': str(eq.index[0].date()), 'end': str(eq.index[-1].date()),
        'final': round(float(m['final'])),
        'n_trades': len(m['trades']),
        'turnover': round(m.get('avg_turnover', 0) * 100, 1),
        'equity': [{'d': str(d.date()), 'v': round(float(v))}
                   for d, v in eq.resample('W').last().dropna().items()],
        'quarters': [{'q': str(p), 'r': round(float(v), 2)}
                     for p, v in q.to_period('Q').items()],
        'months': [{'m': str(p), 'r': round(float(v), 2)}
                   for p, v in mo.to_period('M').items()][-18:],
        'holdings_now': sorted({t['symbol'] for t in m['trades']
                                if t['side'] == 'BUY'} &
                               set(_latest_book(m['trades']))),
    }


def _latest_book(trades):
    pos = {}
    for t in sorted(trades, key=lambda x: x['date']):
        if t['side'] == 'BUY':
            pos[t['symbol']] = pos.get(t['symbol'], 0) + t['shares']
        else:
            pos[t['symbol']] = pos.get(t['symbol'], 0) - t['shares']
            if pos[t['symbol']] <= 0:
                pos.pop(t['symbol'], None)
    return list(pos)


def money(perf):
    """
    Translate the equity curve into plain rupees: what was put in, what it is
    worth now, and what that is per year. Scaled to whatever capital.json says,
    so the figures match the book the user is actually tracking.
    """
    if not perf:
        return None
    cap = {'starting_capital': 10_000_000, 'started_on': None,
           'is_real_money': False}
    if os.path.exists(CAPITAL):
        with open(CAPITAL, encoding='utf-8') as f:
            cap.update({k: v for k, v in json.load(f).items()
                        if not k.startswith('_')})

    start_amt = float(perf.get('capital') or cap['starting_capital'])
    eq = perf['equity']
    if not eq:
        return None
    # No rescaling: perf was produced by a real backtest at start_amt, so the
    # rupee figures already include the cost drag that size actually incurs.
    curve = [{'d': p['d'], 'v': round(p['v'])} for p in eq]
    now = curve[-1]['v']
    profit = now - start_amt

    # calendar-year money: value at each year end, scaled the same way
    by_year, seen = [], {}
    for p in curve:
        seen[p['d'][:4]] = p['v']
    prev = start_amt
    for y in sorted(seen):
        v = seen[y]
        by_year.append({'year': y, 'value': v, 'gain': round(v - prev),
                        'pct': round((v / prev - 1) * 100, 1) if prev else None})
        prev = v

    peak, dd = 0, 0
    for p in curve:
        peak = max(peak, p['v'])
        dd = min(dd, p['v'] / peak - 1)

    return {
        'is_real_money': bool(cap.get('is_real_money')),
        'invested': round(start_amt),
        'now': round(now),
        'profit': round(profit),
        'pct': round(profit / start_amt * 100, 1) if start_amt else None,
        'multiple': round(now / start_amt, 2) if start_amt else None,
        'start_date': curve[0]['d'], 'end_date': curve[-1]['d'],
        'years': round(len(curve) / 52.0, 1),
        'worst_dip': round(dd * 100, 1),
        'worst_dip_rupees': round(peak * dd),
        'per_year': by_year,
        'curve': curve,
    }


def ladder(levels=(100_000, 500_000, 1_000_000, 10_000_000, 50_000_000)):
    """CAGR at each book size - the honest answer to 'can I run this small?'."""
    out = []
    for c in levels:
        try:
            p = performance(capital=c)
            out.append({'capital': c, 'cagr': p['cagr'], 'sharpe': p['sharpe'],
                        'maxdd': p['maxdd'], 'final': p['final'],
                        'trades': p['n_trades']})
        except Exception:
            pass
    return out


def build(with_backtest=True):
    t0 = time.time()
    asof, ranks, n_uni, full_rank = current_ranks()
    st = load_state()

    # First run has no tracked book, so seed it from what the backtest holds.
    perf = performance() if with_backtest else None
    if not st['holdings'] and perf:
        st['holdings'] = perf['holdings_now']
        st['last_rebalance'] = str(asof.date())
        save_state(st)

    snap = {
        'generated': datetime.now().isoformat(timespec='seconds'),
        'asof': str(asof.date()),
        'strategy': FROZEN['name'],
        'version': FROZEN['version'],
        'param_hash': param_hash(),
        'universe_size': n_uni,
        'params': {k: (list(v) if isinstance(v, tuple) else v)
                   for k, v in FROZEN.items()},
        'benchmarks': BENCHMARKS,
        'ranks': ranks,
        'holdings': st['holdings'],
        'actions': plan_actions(ranks, st['holdings'], full_rank),
        'performance': perf,
        'money': money(perf),
        'ladder': ladder() if with_backtest else None,
        'compute_seconds': round(time.time() - t0, 1),
    }

    path = os.path.join(SNAP_DIR, f'{asof:%Y-%m-%d}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(snap, f, indent=2)
    with open(os.path.join(SNAP_DIR, 'latest.json'), 'w', encoding='utf-8') as f:
        json.dump(snap, f, indent=2)
    return snap, path


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-backtest', action='store_true')
    a = ap.parse_args()
    s, p = build(with_backtest=not a.no_backtest)
    print(f"snapshot {s['asof']}  ({s['compute_seconds']}s)  -> {p}")
    print(f"  universe {s['universe_size']}  hash {s['param_hash']}")
    if s['performance']:
        pf = s['performance']
        print(f"  CAGR {pf['cagr']}%  Sharpe {pf['sharpe']}  MaxDD {pf['maxdd']}%")
    act = s['actions']
    print(f"  HOLD {len(act['hold'])}  BUY {len(act['buy'])}  SELL {len(act['sell'])}")
    for b in act['buy']:
        print(f"    BUY  {b['symbol']:<14} rank {b['rank']}")
    for x in act['sell']:
        print(f"    SELL {x['symbol']:<14} {x['reason']}")
