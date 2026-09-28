"""
Point-in-time replay: pretend it is <ASOF>, build the three lists knowing
NOTHING after that date, then score them against what actually happened on the
next trading day.

This is the only test that catches look-ahead properly. Every panel is sliced
to <= ASOF *before* any rolling feature, band inference, model fit or
calibration runs - so the model cannot see the answer, not even indirectly
through a rolling window or a calibration bin.

Usage:  py replay_asof.py 2026-09-18
"""
import sys
import io
import os

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')

import numpy as np
import pandas as pd

import study_upper_circuit as S
from predict_upper_circuit import discretise, fit, score
from score_three_lists import LISTS, build, run_one, TOPN

OUT = 'results/upper_circuit'


def actual_outcomes(close_full, high_full, band_asof, nxt):
    """What really happened on `nxt` - computed from the FULL panels."""
    prev = close_full.index[close_full.index < nxt].max()
    ret = close_full.loc[nxt] / close_full.loc[prev] - 1
    at_high = close_full.loc[nxt] >= high_full.loc[nxt] * S.AT_HIGH_TOL
    band_asof = band_asof.reindex(ret.index)
    return pd.DataFrame({
        'ret': ret,
        'uc10': (ret >= 0.097) & (ret <= 0.103) & at_high & (band_asof == 10.0),
        'uc20': (ret >= 0.195) & (ret <= 0.205) & at_high & (band_asof == 20.0),
        'up5': ret >= 0.05,
    })


def main():
    asof = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else '2026-09-18')

    close_f, high_f, low_f, vol_f, turn_f = S.load()
    nxt = close_f.index[close_f.index > asof].min()
    if pd.isna(nxt):
        raise SystemExit(f'no trading day after {asof:%Y-%m-%d} in the data')

    # ---- hard cut: nothing after ASOF exists from here on ----
    close, high, low, vol, turn = [p.loc[:asof] for p in
                                   (close_f, high_f, low_f, vol_f, turn_f)]
    assert close.index.max() == asof, 'slice failed'
    ret = close.pct_change()
    band = S.infer_band(ret)

    print('=' * 92)
    print(f'  REPLAY  -  as of {asof:%Y-%m-%d %A}, predicting {nxt:%Y-%m-%d %A}')
    print(f'  data visible: {close.index.min():%Y-%m-%d} .. {close.index.max():%Y-%m-%d}'
          f'  ({len(close):,} days)   nothing after {asof:%Y-%m-%d} is used')
    print('=' * 92)

    # band as known at ASOF (a Series over symbols), not the whole panel
    act = actual_outcomes(close_f, high_f, band.loc[asof], nxt)
    print(f'\n  WHAT ACTUALLY HAPPENED ON {nxt:%Y-%m-%d}:')
    print(f'    stocks locking +10% UC : {int(act.uc10.sum()):4d}   '
          f'{list(act.index[act.uc10])[:8]}')
    print(f'    stocks locking +20% UC : {int(act.uc20.sum()):4d}   '
          f'{list(act.index[act.uc20])[:8]}')
    print(f'    stocks up >= +5%       : {int(act.up5.sum()):4d}')

    rows = []
    for tag, title, band_val, rng in LISTS:
        ev, live, last = build(close, high, low, vol, turn, ret, band,
                               band_val, rng)
        assert last == asof
        live, st = run_one(ev, live)
        top = live.head(TOPN).reset_index(drop=True)

        col = {'A': 'uc10', 'B': 'uc20', 'C': 'up5'}[tag]
        top['HIT'] = top['symbol'].map(act[col]).fillna(False)
        top['actual_ret'] = top['symbol'].map(act['ret'])

        print(f'\n{"="*92}\n  LIST {tag}  -  {title}\n{"="*92}')
        print(f'  {"#":<3}{"symbol":<13}{"P(pred)":>9}{"HIT?":>7}'
              f'{"actual ret":>12}{"turnover/day":>15}')
        print('  ' + '-' * 62)
        for i, r in top.iterrows():
            ar = f'{r.actual_ret*100:+.2f}%' if pd.notna(r.actual_ret) else 'n/a'
            p = f'{r.p*100:.1f}%' if pd.notna(r.p) else 'n/a'
            print(f'  {i+1:<3}{r.symbol:<13}{p:>9}'
                  f'{"  HIT" if r.HIT else "   -":>7}{ar:>12}'
                  f'{r.turn_med20/1e5:>13,.1f}L')

        hits = int(top['HIT'].sum())
        expd = top['p'].sum()
        mret = top['actual_ret'].mean()
        univ = act[col].mean()
        rows.append({
            'list': tag, 'predicted': round(expd, 2), 'actual_hits': hits,
            'top10_hit_rate': hits / TOPN,
            'universe_base_rate': univ,
            'lift': (hits / TOPN) / univ if univ else np.nan,
            'mean_ret': mret,
        })
        print(f'\n  predicted ~{expd:.2f} hits   ->   ACTUAL {hits} hits'
              f'   |  basket mean return {mret*100:+.2f}%')

    print(f'\n{"="*92}\n  SCORECARD\n{"="*92}')
    d = pd.DataFrame(rows)
    print(f'  {"list":<6}{"predicted":>11}{"actual":>8}{"top10 hit%":>12}'
          f'{"universe%":>11}{"lift":>8}{"mean ret":>11}')
    print('  ' + '-' * 68)
    for _, r in d.iterrows():
        print(f'  {r.list:<6}{r.predicted:>11.2f}{int(r.actual_hits):>8}'
              f'{r.top10_hit_rate*100:>11.1f}%{r.universe_base_rate*100:>10.2f}%'
              f'{r.lift:>8.1f}{r.mean_ret*100:>10.2f}%')
    d.to_csv(os.path.join(OUT, f'replay_{asof:%Y%m%d}.csv'), index=False)


if __name__ == '__main__':
    main()
