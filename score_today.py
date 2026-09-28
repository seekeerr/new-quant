"""
Score the live universe for "locks +10% UC on the NEXT trading day".

Separate from predict_upper_circuit.py because the study frame drops the final
date (no T+1 target exists yet) - that is exactly the row we need to trade on.

Model coefficients are refit on the FULL history here (more data for the live
call); the honest performance numbers come from the held-out test in
predict_upper_circuit.py and must be read from there, not from this file.
"""
import sys
import io
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd

import study_upper_circuit as S
from predict_upper_circuit import (SPECS, discretise, fit, score,
                                   TRAIN_END, TEST_START)

OUT = 'results/upper_circuit'
NTOP = 25


def main():
    close, high, low, vol, turn = S.load()
    uc_raw, ret = S.detect_uc(close, high)
    band = S.infer_band(ret)
    uc = uc_raw & (band == 10.0)
    f = S.build_features(close, high, low, vol, turn, ret, uc, band)

    last = close.index.max()
    print(f'signal date (last close) = {last:%Y-%m-%d %A}')

    # ---- fit on everything that HAS a target ----
    ev = S.stack_events(f, uc, close, turn, band)
    ev = ev.dropna(subset=['uc_next', 'vol_ratio', 'turn_med20'])
    ev['date'] = pd.to_datetime(ev['date'])
    d = discretise(ev)
    w, b_lo = fit(d, ev['uc_next'])

    # ---- build the live row set for `last` (no target needed) ----
    elig = ((band.loc[last] == 10.0) & (close.loc[last] >= S.MIN_PRICE) &
            f['turn_med20'].loc[last].notna())
    syms = elig[elig].index
    live = pd.DataFrame({k: v.loc[last, syms] for k, v in f.items()})
    live.index.name = 'symbol'
    live = live.reset_index()
    live = live.dropna(subset=['vol_ratio', 'turn_med20'])
    print(f'eligible 10%-band names today: {len(live):,}')

    live['score'] = score(discretise(live), w, b_lo)

    # ---- calibrate: raw naive-Bayes p is overconfident by up to 40x because
    # the features are strongly correlated. Map score -> EMPIRICAL hit rate
    # measured on the held-out 2024+ block, which is the only honest number.
    cal_tr = ev['date'] <= TRAIN_END
    w_c, b_c = fit(discretise(ev[cal_tr]), ev.loc[cal_tr, 'uc_next'])
    ev_te = ev[ev['date'] >= TEST_START].copy()
    ev_te['score'] = score(discretise(ev_te), w_c, b_c)
    cuts = [-99, -8, -6, -5, -4, -3, -2, -1, 0, 1, 2, 99]
    ev_te['sb'] = pd.cut(ev_te['score'], cuts)
    cal = ev_te.groupby('sb', observed=True)['uc_next'].agg(['mean', 'count'])
    cal = cal[cal['count'] >= 20]['mean']
    live['p_cal'] = pd.cut(live['score'], cuts).map(cal).astype(float)
    live['tier'] = live['turn_med20'].apply(S.liq_tier)
    live = live.sort_values('score', ascending=False).head(NTOP)

    cols = ['symbol', 'p_cal', 'score', 'price', 'ret_1d', 'ret_5d', 'ret_20d',
            'vol_ratio', 'uc_today', 'uc_20d', 'pct_52wh', 'turn_med20', 'tier']
    out = live[cols].reset_index(drop=True)
    out.to_csv(os.path.join(OUT, 'candidates_today.csv'), index=False)

    print(f'\n{"#":<4}{"symbol":<14}{"p_est":>8}{"px":>9}{"1d":>8}{"5d":>8}'
          f'{"20d":>8}{"vol x":>7}{"UC20":>6}{"%52wH":>7}{"turnover":>12}')
    print('-' * 95)
    for i, r in out.iterrows():
        print(f'{i+1:<4}{r.symbol:<14}{r.p_cal*100:>7.1f}%{r.price:>9,.1f}'
              f'{r.ret_1d*100:>7.1f}%{r.ret_5d*100:>7.1f}%{r.ret_20d*100:>7.1f}%'
              f'{r.vol_ratio:>7.1f}{int(r.uc_20d):>6}{r.pct_52wh*100:>6.0f}%'
              f'{r.turn_med20/1e5:>10,.0f}L')
    print(f'\nsaved -> {OUT}/candidates_today.csv')


if __name__ == '__main__':
    main()
