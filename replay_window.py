"""
Multi-day replay. One day proves nothing at a 0.1% base rate - this runs the
same three lists over EVERY trading day in a held-out window and scores them.

Strict time separation (nothing overlaps):
    FIT       <= 2023-12-31          model coefficients
    CALIBRATE 2024-01-01..2026-06-30 rank -> probability map
    REPLAY    2026-07-01..end        never used for anything until scored

Why features may be computed on the full panel: every feature is strictly
backward-looking (rolling(...).max/median/std, pct_change, no negative shift),
so the value at day T is identical whether the panel was truncated at T or not.
Only the FIT and the CALIBRATION can leak, and both are hard-gated above.
The single-date replay_asof.py truncates panels physically and is the check
that this assumption holds - the two agree.

Usage:  py replay_window.py [replay_start]
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
from score_three_lists import LISTS, build, TOPN

OUT = 'results/upper_circuit'
FIT_END = '2023-12-31'
CAL_END = '2026-06-30'


def main():
    rep_start = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else '2026-07-01')

    close, high, low, vol, turn = S.load()
    ret = close.pct_change()
    band = S.infer_band(ret)

    print('=' * 96)
    print(f'  MULTI-DAY REPLAY   fit<={FIT_END} | calib {FIT_END[:4]}+..{CAL_END}'
          f' | replay {rep_start:%Y-%m-%d}..{close.index.max():%Y-%m-%d}')
    print('=' * 96)

    summary = []
    for tag, title, band_val, rng in LISTS:
        ev, _, _ = build(close, high, low, vol, turn, ret, band, band_val, rng)

        fit_m = ev['date'] <= FIT_END
        cal_m = (ev['date'] > FIT_END) & (ev['date'] <= CAL_END)
        rep_m = ev['date'] >= rep_start
        if not rep_m.any():
            continue

        w, b = fit(discretise(ev[fit_m]), ev.loc[fit_m, 'uc_next'])
        ev = ev.copy()
        ev['score'] = score(discretise(ev), w, b)
        ev['rk'] = ev.groupby('date')['score'].rank(ascending=False,
                                                    method='first')

        # rank -> probability, learned on the calibration block only
        c = ev[cal_m]
        rp = c.groupby('rk')['uc_next'].agg(['mean', 'count'])
        rp = rp[rp['count'] >= 30]['mean'].sort_index()
        rp = pd.Series(np.minimum.accumulate(rp.values), index=rp.index)

        r = ev[rep_m].copy()
        r['p'] = r['rk'].map(rp)
        top = r[r['rk'] <= TOPN]
        ndays = r['date'].nunique()

        base = r['uc_next'].mean()
        hit = top['uc_next'].mean()
        pred = top['p'].mean()
        # per-day: predicted vs actual number of hits in the basket
        per_day = top.groupby('date')['uc_next'].sum()

        print(f'\n  LIST {tag}  -  {title}')
        print(f'  {"-"*88}')
        print(f'    replay days              : {ndays}')
        print(f'    universe base rate       : {base*100:.3f}%')
        print(f'    top-10 PREDICTED hit rate: {pred*100:.2f}%')
        print(f'    top-10 ACTUAL    hit rate: {hit*100:.2f}%'
              f'   ({int(top["uc_next"].sum())} hits / {len(top):,} picks)')
        print(f'    lift vs universe         : {hit/base:.1f}x'
              if base else '    lift: n/a')
        print(f'    calibration error        : '
              f'{(hit-pred)*100:+.2f} pp  '
              f'({"over" if pred>hit else "under"}-confident)')
        print(f'    days with >=1 hit        : {(per_day>0).sum()}/{ndays}'
              f'  ({(per_day>0).mean()*100:.0f}%)')
        print(f'    total hits               : {int(per_day.sum())}'
              f'   (expected {pred*TOPN*ndays:.1f})')

        summary.append({
            'list': tag, 'days': ndays, 'base_rate': base,
            'pred_hit': pred, 'actual_hit': hit,
            'lift': hit / base if base else np.nan,
            'hits': int(per_day.sum()),
            'pct_days_with_hit': (per_day > 0).mean(),
        })

    d = pd.DataFrame(summary)
    d.to_csv(os.path.join(OUT, 'replay_window.csv'), index=False)
    print(f'\n{"="*96}\n  SCORECARD  ({d.days.iloc[0]} trading days, '
          f'10 picks/day/list)\n{"="*96}')
    print(f'  {"list":<6}{"base%":>9}{"pred%":>9}{"actual%":>10}{"lift":>8}'
          f'{"hits":>8}{"days w/ hit":>14}')
    print('  ' + '-' * 64)
    for _, r in d.iterrows():
        print(f'  {r.list:<6}{r.base_rate*100:>8.3f}%{r.pred_hit*100:>8.2f}%'
              f'{r.actual_hit*100:>9.2f}%{r.lift:>8.1f}{r.hits:>8}'
              f'{r.pct_days_with_hit*100:>13.0f}%')


if __name__ == '__main__':
    main()
