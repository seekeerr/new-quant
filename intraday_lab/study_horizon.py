"""
Does finer resolution help? Hold the signal fixed and vary only the holding
period.

The 15m battery's top 25 configs were ALL at the two longest horizons tested.
That is either a coincidence of the search grid or the actual shape of the
problem, so measure it: same signal, same universe, same entry - only h moves.

Cost is flat in h (one round trip is one round trip). Edge is not. Where the
two lines cross is the fastest you can trade this and still be paid.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from intraday_lab import harness_fine as H

COST = 21.0

for interval in ('5m', '15m'):
    d = H.load(interval)
    npd = H.bars_per_day(d)
    mins = {'5m': 5, '15m': 15}[interval]
    date = d['date']
    C = d['close']
    el = H.eligible(d)
    liq = H.liquidity(d)
    el = el & (liq.where(el).rank(axis=1, ascending=False, method='first') <= 100)

    # the family the battery surfaced: short the biggest losers of the last
    # ~3 hours. k is held at 3 hours' worth of bars for both intervals.
    k = int(round(180 / mins))
    r = C / C.shift(k) - 1
    score = -r.where(H.bcast(date.shift(k) == date, r))

    print(f'\n{"="*86}')
    print(f'  {interval}: short {k}-bar (3h) losers, top-10, top-100 liquidity')
    print(f'{"="*86}')
    print(f'  {"hold":>10}{"mins":>7}{"obs":>7}{"gross":>8}{"net":>8}'
          f'{"t":>7}{"bp/hour":>10}{"trades/day":>12}')
    print('  ' + '-' * 82)

    for h in (1, 2, 3, 4, 6, 8, 12, 16, 24, 36, 48, 72):
        if h >= npd:
            continue
        fwd = H.forward(d, h)
        res = H.evaluate(score, d, fwd, topn=10, long=False, cost_bp=COST,
                         el=el, label=f'h{h}')
        if not res:
            continue
        hold_min = h * mins
        per_hour = res['gross_bp'] / (hold_min / 60)
        print(f"  {str(h)+' bars':>10}{hold_min:>7}{res['obs']:>7}"
              f"{res['gross_bp']:>8.1f}{res['net_bp']:>8.1f}{res['tstat']:>7.2f}"
              f"{per_hour:>10.1f}{npd/h:>12.1f}")

    print(f'\n  cost floor {COST} bp is FLAT in holding period.')
