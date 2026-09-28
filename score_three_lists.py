"""
Three ranked lists for the next trading day, each its own model + calibration:

  LIST A  +10% upper-circuit lock   (universe: 10%-band stocks only)
  LIST B  +20% upper-circuit lock   (universe: 20%-band stocks only)
  LIST C  a meaningful up move >= +5%  (universe: ALL bands, any stock)

Why three models and not one: the three targets have different base rates,
different eligible universes and different drivers. A 20%-band name can never
produce a 10% lock, and List C is not a circuit question at all.

Every probability printed is CALIBRATED against out-of-sample hit rates
(train <=2023, test 2024+). Raw naive-Bayes numbers overstate by up to 40x
because the features are correlated - they are never shown.
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
from predict_upper_circuit import (SPECS, discretise, fit, score,
                                   TRAIN_END, TEST_START)

OUT = 'results/upper_circuit'
TOPN = 10
CUTS = [-99, -8, -6, -5, -4, -3, -2, -1, 0, 1, 2, 99]

LISTS = [
    ('A', '+10% UPPER CIRCUIT LOCK', 10.0, (0.097, 0.103)),
    ('B', '+20% UPPER CIRCUIT LOCK', 20.0, (0.195, 0.205)),
    ('C', 'UP MOVE >= +5% (any band)', None, None),
]


def target_panel(close, high, ret, band, band_val, rng):
    """Boolean panel of the event we are trying to predict, on day T."""
    if band_val is None:                       # List C: any stock, >= +5%
        return (ret >= 0.05) & close.notna()
    lo, hi = rng
    at_high = close >= high * S.AT_HIGH_TOL
    return (ret >= lo) & (ret <= hi) & at_high & (band == band_val)


def build(close, high, low, vol, turn, ret, band, band_val, rng):
    """Stack (date, symbol) rows with features at T and target at T+1."""
    evt = target_panel(close, high, ret, band, band_val, rng)
    f = S.build_features(close, high, low, vol, turn, ret, evt, band)

    tgt = evt.shift(-1)
    if band_val is None:
        elig = (close >= S.MIN_PRICE) & f['turn_med20'].notna() & band.notna()
    else:
        elig = ((band == band_val) & (close >= S.MIN_PRICE) &
                f['turn_med20'].notna())

    hist = elig & tgt.notna()
    r, c = np.where(hist.values)
    ev = {'date': hist.index.values[r], 'symbol': np.array(hist.columns)[c]}
    for k, v in f.items():
        ev[k] = v.values[r, c]
    ev['uc_next'] = tgt.values[r, c]
    ev = pd.DataFrame(ev).dropna(subset=['uc_next', 'vol_ratio', 'turn_med20'])
    ev['date'] = pd.to_datetime(ev['date'])

    # live rows for the final date (no target yet - that is what we predict)
    last = close.index.max()
    lm = elig.loc[last]
    syms = lm[lm].index
    live = pd.DataFrame({k: v.loc[last, syms] for k, v in f.items()})
    live.index.name = 'symbol'
    live = live.reset_index().dropna(subset=['vol_ratio', 'turn_med20'])
    return ev, live, last


def run_one(ev, live):
    """Fit, calibrate on held-out block, score live rows. Returns (live, stats)."""
    tr = ev['date'] <= TRAIN_END
    te = ev['date'] >= TEST_START

    # honest metrics: fit on train only, measure on test
    w_t, b_t = fit(discretise(ev[tr]), ev.loc[tr, 'uc_next'])
    t = ev[te].copy()
    t['score'] = score(discretise(t), w_t, b_t)
    t['rk'] = t.groupby('date')['score'].rank(ascending=False, method='first')
    base = t['uc_next'].mean()
    top = t[t['rk'] <= TOPN]
    stats = {
        'base': base,
        'hit': top['uc_next'].mean(),
        'lift': top['uc_next'].mean() / base if base else np.nan,
        'n_te': len(t),
        'n_ev': int(t['uc_next'].sum()),
    }

    # RANK-based calibration. Score->probability binning does not work here:
    # a single day's top-10 all sit in the extreme tail, so any score grid puts
    # them in one bin and they tie. What we actually want to know is "if I take
    # the #1 name of the day, how often does it hit?" - so calibrate on the
    # daily rank position itself, measured out-of-sample.
    rank_p = t.groupby('rk')['uc_next'].agg(['mean', 'count'])
    rank_p = rank_p[rank_p['count'] >= 30]['mean'].sort_index()
    # smooth: rank->hit is noisy and must be non-increasing in rank
    rank_p = pd.Series(np.minimum.accumulate(rank_p.values),
                       index=rank_p.index)

    # live scoring uses coefficients refit on ALL history
    w_a, b_a = fit(discretise(ev), ev['uc_next'])
    live = live.copy()
    live['score'] = score(discretise(live), w_a, b_a)
    live = live.sort_values('score', ascending=False).reset_index(drop=True)
    live['rk'] = np.arange(1, len(live) + 1)
    live['p'] = live['rk'].map(rank_p).astype(float)
    return live, stats


def main():
    close, high, low, vol, turn = S.load()
    ret = close.pct_change()
    band = S.infer_band(ret)

    R = []
    for tag, title, band_val, rng in LISTS:
        ev, live, last = build(close, high, low, vol, turn, ret, band,
                               band_val, rng)
        live, st = run_one(ev, live)
        top = live.head(TOPN).reset_index(drop=True)

        R.append('')
        R.append('=' * 92)
        R.append(f'  LIST {tag}  -  {title}')
        R.append(f'  for {last + pd.Timedelta(days=1):%Y-%m-%d} (next session)'
                 f'  |  eligible today: {len(live):,}')
        R.append(f'  out-of-sample: base {st["base"]*100:.3f}%  ->  '
                 f'top-10 {st["hit"]*100:.2f}%  ({st["lift"]:.0f}x lift, '
                 f'{st["n_ev"]:,} events in test)')
        R.append('=' * 92)
        R.append(f'  {"#":<3}{"symbol":<13}{"P(event)":>10}{"price":>10}'
                 f'{"1d":>8}{"5d":>8}{"20d":>8}{"vol x":>7}{"%52wH":>7}'
                 f'{"turnover/day":>15}')
        R.append('  ' + '-' * 88)
        for i, r in top.iterrows():
            p = f'{r.p*100:.1f}%' if pd.notna(r.p) else '  n/a'
            r20 = f'{r.ret_20d*100:.1f}%' if pd.notna(r.ret_20d) else '   n/a'
            R.append(f'  {i+1:<3}{r.symbol:<13}{p:>10}{r.price:>10,.1f}'
                     f'{r.ret_1d*100:>7.1f}%{r.ret_5d*100:>7.1f}%{r20:>8}'
                     f'{r.vol_ratio:>7.1f}{r.pct_52wh*100:>6.0f}%'
                     f'{r.turn_med20/1e5:>13,.1f}L')
        exp = top['p'].sum()
        R.append(f'  expected hits out of 10: {exp:.2f}')
        top.to_csv(os.path.join(OUT, f'list_{tag}.csv'), index=False)

    txt = '\n'.join(R)
    print(txt)
    with open(os.path.join(OUT, 'three_lists.txt'), 'w', encoding='utf-8') as f:
        f.write(txt)


if __name__ == '__main__':
    main()
