"""
FINAL ADJUDICATION - the holdout is opened here, once.

Everything before this ran on DISCOVERY (2012-2021) only. This script takes the
handful of finalists and runs them on HOLDOUT (2022-01-01..2026-05-30), which no
search touched. Whatever the holdout says is the answer, including if it says
the discovery winners were luck.

Two kinds of finalist:
  * single scorer      - run directly on holdout
  * sleeve combination - each sleeve run on holdout, then returns blended with
                         the SAME fixed weights found in discovery (no refit)

Sleeve blends are reported with an explicit cost haircut, because blending
return series ignores (a) rebalancing between sleeves and (b) holding overlap.
"""
import sys
import io
import os

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')

import numpy as np
import pandas as pd

from research_harness import (load_panels, evaluate, champion_scorer,
                              rolling_3y_min, BENCH_CAGR)
from sweep2 import sleeve_defs, _stats
import signals as S

OUT = 'results/campaign'
N_TRIALS = 7350          # honest campaign-wide config count
SLEEVE_COST_HAIRCUT = 0.015   # 1.5pp/yr charged to cross-sleeve rebalancing


def single_finalists(close, high, low, vol, turn):
    ch = champion_scorer()
    mom = S.momentum(252, 21)
    lv = S.low_vol(252)
    base = dict(n_stocks=10, rebalance='monthly', rank_band=(0, 500))
    return [
        ('champ_buf40', ch, dict(buffer=40, **base)),
        ('mom+lv+amihud_.25',
         S.blend([(mom, .375), (lv, .375), (S.amihud(60)(turn), .25)]),
         dict(buffer=20, **base)),
        ('mom+lv+momcons_.5',
         S.blend([(mom, .25), (lv, .25), (S.momentum_consistency(252), .5)]),
         dict(buffer=20, **base)),
        ('mom_f126_s0', S.momentum(126, 0), dict(buffer=20, **base)),
    ]


COMBOS = {
    'eq3 champ+tail+mid': {'champ': 1/3, 'champ_tail': 1/3, 'champ_mid': 1/3},
    'champ.34+mid.50+momfast.16': {'champ': .34, 'champ_mid': .50,
                                   'mom_fast': .16},
    'champ.4+mid.6': {'champ': .4, 'champ_mid': .6},
}


def main():
    close, high, low, vol, turn = load_panels()
    rows = []

    # ---- reference: champion and index ----
    for sp in ('discovery', 'holdout'):
        m = evaluate(champion_scorer(), close, high, low, vol, turn, split=sp,
                     label='champion')
        rows.append(dict(strategy='champion (frozen)', kind='ref', split=sp,
                         cagr=m['cagr'], sharpe=m['sharpe'], maxdd=m['maxdd'],
                         roll3y=rolling_3y_min(m['returns'])))
        print(f"  champion {sp:<10} CAGR {m['cagr']*100:6.2f}%  "
              f"Sh {m['sharpe']:.2f}", flush=True)

    # ---- single-scorer finalists ----
    for label, sc, kw in single_finalists(close, high, low, vol, turn):
        for sp in ('discovery', 'holdout'):
            try:
                m = evaluate(sc, close, high, low, vol, turn, split=sp,
                             label=label, **kw)
                rows.append(dict(strategy=label, kind='single', split=sp,
                                 cagr=m['cagr'], sharpe=m['sharpe'],
                                 maxdd=m['maxdd'],
                                 roll3y=rolling_3y_min(m['returns'])))
                print(f"  {label:<26} {sp:<10} CAGR {m['cagr']*100:6.2f}%  "
                      f"Sh {m['sharpe']:.2f}", flush=True)
            except Exception as e:
                print(f'  {label} {sp}: ERROR {str(e)[:70]}', flush=True)

    # ---- sleeve combinations ----
    sl = {n: (s, k) for n, s, k in sleeve_defs(close, high, low, vol, turn)}
    needed = sorted({n for w in COMBOS.values() for n in w})
    sleeve_ret = {'discovery': {}, 'holdout': {}}
    for n in needed:
        sc, kw = sl[n]
        for sp in ('discovery', 'holdout'):
            try:
                m = evaluate(sc, close, high, low, vol, turn, split=sp,
                             label=n, **kw)
                sleeve_ret[sp][n] = m['returns']
            except Exception as e:
                print(f'  sleeve {n} {sp}: ERROR {str(e)[:60]}', flush=True)

    for cname, wts in COMBOS.items():
        for sp in ('discovery', 'holdout'):
            R = pd.DataFrame({n: sleeve_ret[sp][n] for n in wts
                              if n in sleeve_ret[sp]}).dropna(how='all').fillna(0)
            if R.empty:
                continue
            r = sum(R[n] * w for n, w in wts.items() if n in R.columns)
            st = _stats(r)
            # charge cross-sleeve rebalancing, which return-blending ignores
            net = st['cagr'] - SLEEVE_COST_HAIRCUT
            rows.append(dict(strategy=cname, kind='sleeve', split=sp,
                             cagr=net, cagr_gross=st['cagr'],
                             sharpe=st['sharpe'], maxdd=st['maxdd'],
                             roll3y=rolling_3y_min(r)))
            print(f"  {cname:<26} {sp:<10} CAGR {net*100:6.2f}% "
                  f"(gross {st['cagr']*100:.2f}%)  Sh {st['sharpe']:.2f}",
                  flush=True)

    d = pd.DataFrame(rows)
    d.to_csv(f'{OUT}/final_adjudication.csv', index=False)

    # ---- verdict table ----
    piv = d.pivot_table(index=['strategy', 'kind'], columns='split',
                        values=['cagr', 'sharpe', 'maxdd'])
    hold_hurdle = np.sqrt(2 * np.log(max(len(COMBOS) +
                                         len(single_finalists(close, high, low,
                                                              vol, turn)), 2))) / np.sqrt(4.4)
    champ_h = d[(d.strategy == 'champion (frozen)') &
                (d.split == 'holdout')]['cagr'].iloc[0]

    print('\n' + '=' * 100)
    print(f'  VERDICT   |  {N_TRIALS:,} configs searched on discovery  |  '
          f'holdout 2022-01..2026-05 opened once')
    print(f'  index {BENCH_CAGR*100:.2f}%   champion holdout {champ_h*100:.2f}%'
          f'   OOS Sharpe noise floor {hold_hurdle:.2f}')
    print('=' * 100)
    print(f'  {"strategy":<28}{"DISC cagr":>10}{"sh":>6}'
          f'{"HOLD cagr":>11}{"sh":>6}{"maxdd":>8}{"decay":>9}  verdict')
    print('  ' + '-' * 96)
    out = []
    for (name, kind), g in d[d.kind != 'ref'].groupby(['strategy', 'kind']):
        dd = g[g.split == 'discovery']
        hh = g[g.split == 'holdout']
        if dd.empty or hh.empty:
            continue
        dc, ds = dd.cagr.iloc[0], dd.sharpe.iloc[0]
        hc, hs, hm = hh.cagr.iloc[0], hh.sharpe.iloc[0], hh.maxdd.iloc[0]
        if hc <= BENCH_CAGR:
            v = 'REJECT (loses to index)'
        elif hs <= hold_hurdle:
            v = 'WEAK (within OOS noise)'
        elif hc > champ_h:
            v = 'PASS - beats champion'
        else:
            v = 'MARGINAL (beats index only)'
        out.append((hc, name, kind, dc, ds, hc, hs, hm, v))
    for hc, name, kind, dc, ds, _, hs, hm, v in sorted(out, reverse=True):
        print(f'  {name:<28}{dc*100:>9.2f}%{ds:>6.2f}{hc*100:>10.2f}%'
              f'{hs:>6.2f}{hm*100:>7.1f}%{(hc-dc)*100:>8.1f}pp  {v}')
    # champion row for reference
    cd = d[(d.strategy == 'champion (frozen)')]
    print('  ' + '-' * 96)
    print(f'  {"champion (frozen)":<28}'
          f'{cd[cd.split=="discovery"].cagr.iloc[0]*100:>9.2f}%'
          f'{cd[cd.split=="discovery"].sharpe.iloc[0]:>6.2f}'
          f'{champ_h*100:>10.2f}%{cd[cd.split=="holdout"].sharpe.iloc[0]:>6.2f}'
          f'{cd[cd.split=="holdout"].maxdd.iloc[0]*100:>7.1f}%'
          f'{(champ_h-cd[cd.split=="discovery"].cagr.iloc[0])*100:>8.1f}pp'
          f'  (reference)')
    print(f'\n  saved -> {OUT}/final_adjudication.csv')


if __name__ == '__main__':
    main()
