"""
Intraday research: buy at today's OPEN, sell at today's CLOSE. No overnight risk.

WHAT THE DATA CAN AND CANNOT SUPPORT
------------------------------------
This repo has daily OHLCV bhavcopy only - no minute bars, no ticks, no order
book. So the only honest "intraday" strategy shape is one whose entry and exit
are the day's official open and close prices. That is a real, tradeable shape.

What is NOT testable here, and is not attempted:
  * anything needing the intraday path (VWAP entry, intraday stops, scalping,
    breakout-of-the-first-30-minutes) - the path between open and close is
    simply not in the data
  * anything needing news timestamps - there is no historical news archive,
    so a news signal cannot be backtested at all, only asserted

SIGNAL TIMING RULE
------------------
A signal may use everything up to YESTERDAY's close, plus TODAY'S OPEN (which
is known at the moment you would enter). Nothing else. Using today's high, low
or close in a signal is look-ahead and invents the answer.

COST REALITY
------------
Intraday equity charges differ from delivery and the repo's delivery cost model
overstates them: intraday STT is 0.025% on the SELL side only (delivery is 0.1%
both sides), and stamp duty is 0.003% buy-side (delivery 0.015%). Those are
modelled properly below. Even so, trading ~250 times a year multiplies any
per-trade cost by 250, which is the central difficulty of this whole exercise.

    py -m intraday_lab.research
"""
import sys
import io
import os

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')

import numpy as np
import pandas as pd

# Isolated lab. This package is read-only with respect to everything else:
# it reads the shared price panels and writes ONLY under results/intraday_lab/.
# It imports nothing from strategy_live, research_harness or signals, so the
# frozen strategy and the paper-trading run cannot be disturbed by work here.
import os as _os
_HERE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
CACHE = _os.path.join(_HERE, 'data', 'cache_bhav')
OUT = _os.path.join(_HERE, 'results', 'intraday_lab')
os.makedirs(OUT, exist_ok=True)

TRAIN_END = '2023-12-31'      # search here
TEST_START = '2024-01-01'     # opened once, at the end

# Intraday equity cost, one round trip, as a fraction of turnover.
BROKERAGE_FLAT = 20.0         # Rs per order, discount broker
STT_SELL = 0.00025            # 0.025%, sell side only (intraday)
STAMP_BUY = 0.00003           # 0.003%, buy side only (intraday)
EXCH = 0.0000325              # per side
SEBI = 0.000001               # per side
GST = 0.18                    # on brokerage + exchange
SLIPPAGE = {1: 0.0005, 2: 0.0015, 3: 0.0035}   # per side, by liquidity tier


def round_trip_cost(order_value, tier=2):
    """Total intraday round-trip cost as a fraction of the order value."""
    brok = min(BROKERAGE_FLAT / order_value, 0.0003) * 2
    exch = EXCH * 2
    gst = (brok + exch) * GST
    slip = SLIPPAGE[tier] * 2
    return STT_SELL + STAMP_BUY + exch + SEBI * 2 + brok + gst + slip


def load():
    def rd(n):
        return pd.read_parquet(os.path.join(CACHE, n))
    c = rd('raw_close.parquet')
    o = rd('raw_open.parquet')
    h = rd('raw_high.parquet')
    l = rd('raw_low.parquet')
    v = rd('raw_volume.parquet')
    t = rd('raw_turnover.parquet')
    ac = rd('adj_close.parquet')

    cols = sorted(set(c.columns) & set(o.columns) & set(ac.columns))
    idx = c.index.intersection(o.index)
    idx = idx[idx >= pd.Timestamp('2017-01-01')]
    out = [x.reindex(index=idx, columns=cols) for x in (c, o, h, l, v, t, ac)]
    return out


def build_features(c, o, h, l, v, t, ac):
    """
    Everything here is knowable at today's OPEN:
      - panels shifted by 1 day  -> yesterday's close and earlier
      - today's open             -> known at entry
    """
    pc = c.shift(1)                      # yesterday's close
    f = {}
    f['gap'] = o / pc - 1                                    # overnight gap
    f['ret1'] = pc / c.shift(2) - 1                          # yesterday's move
    f['ret5'] = pc / c.shift(6) - 1
    f['ret20'] = pc / c.shift(21) - 1
    f['ret60'] = pc / c.shift(61) - 1

    rng = (h.shift(1) - l.shift(1)).replace(0, np.nan)
    f['clo_pos'] = (c.shift(1) - l.shift(1)) / rng           # yesterday's close in range
    f['range_y'] = rng / pc                                  # yesterday's range

    vol20 = v.shift(1).rolling(20, min_periods=10).median()
    f['vol_ratio'] = v.shift(1) / vol20.replace(0, np.nan)
    f['turn20'] = t.shift(1).rolling(20, min_periods=10).median()

    r = ac.pct_change()
    f['vol20d'] = r.shift(1).rolling(20, min_periods=10).std()
    f['atr'] = ((h - l) / c).shift(1).rolling(14, min_periods=7).mean()

    hi = c.shift(1).rolling(252, min_periods=60).max()
    f['pct52'] = pc / hi

    f['price'] = pc
    f['gap_x_vol'] = f['gap'] / f['vol20d'].replace(0, np.nan)   # gap in sigmas
    return f


SIGNALS = {
    # name: (feature, direction)  direction +1 = high value ranked first
    'gap_up_follow':      ('gap', +1),
    'gap_down_fade':      ('gap', -1),
    'gap_sigma_up':       ('gap_x_vol', +1),
    'gap_sigma_down':     ('gap_x_vol', -1),
    'prev_day_momentum':  ('ret1', +1),
    'prev_day_reversal':  ('ret1', -1),
    'wk_momentum':        ('ret5', +1),
    'wk_reversal':        ('ret5', -1),
    'mth_momentum':       ('ret20', +1),
    'mth_reversal':       ('ret20', -1),
    'strong_close':       ('clo_pos', +1),
    'weak_close':         ('clo_pos', -1),
    'volume_surge':       ('vol_ratio', +1),
    'volume_dry':         ('vol_ratio', -1),
    'wide_range':         ('range_y', +1),
    'narrow_range':       ('range_y', -1),
    'high_vol':           ('vol20d', +1),
    'low_vol':            ('vol20d', -1),
    'near_52wh':          ('pct52', +1),
    'far_52wh':           ('pct52', -1),
    'cheap':              ('price', -1),
}


def run(feats, i2c, mask, name, feat, sign, topn=20):
    """
    Rank the eligible names each day by the signal, take the top N,
    and measure their average open->close return that day.
    """
    x = feats[feat].where(mask)
    if sign < 0:
        x = -x
    rk = x.rank(axis=1, ascending=False, method='first')
    sel = rk <= topn
    n = sel.sum(axis=1)
    picked = i2c.where(sel)
    daily = picked.mean(axis=1)
    daily = daily[n >= max(3, topn // 3)]        # need a real basket
    if len(daily) < 250:
        return None

    # market-neutral view: excess over the eligible cross-section that day
    bench = i2c.where(mask).mean(axis=1).reindex(daily.index)
    excess = daily - bench

    return {
        'signal': name, 'days': len(daily),
        'mean_bp': daily.mean() * 1e4,
        'excess_bp': excess.mean() * 1e4,
        'hit': (daily > 0).mean() * 100,
        'std_bp': daily.std() * 1e4,
        'tstat': (daily.mean() / daily.std() * np.sqrt(len(daily))
                  if daily.std() else np.nan),
        'ann_gross': ((1 + daily).prod() ** (252 / len(daily)) - 1) * 100,
        'series': daily,
    }


def main():
    print('loading daily OHLC panels...', flush=True)
    c, o, h, l, v, t, ac = load()
    print(f'  {c.shape[1]:,} symbols x {c.shape[0]:,} days')

    # the thing being predicted: open -> close, same day
    i2c = (c / o - 1).replace([np.inf, -np.inf], np.nan)
    i2c = i2c.where(i2c.abs() < 0.30)         # drop corporate-action artifacts

    feats = build_features(c, o, h, l, v, t, ac)

    # eligibility: real price, real liquidity, valid open
    elig = (feats['price'] >= 20) & (feats['turn20'] >= 1e7) & o.notna() & i2c.notna()
    print(f'  eligible stock-days: {int(elig.sum().sum()):,}'
          f'  (avg {elig.sum(axis=1).mean():.0f} names/day)')
    print(f'  universe open->close mean: {i2c.where(elig).stack().mean()*1e4:+.1f} bp/day')

    tr = c.index <= TRAIN_END
    rows = []
    for name, (feat, sign) in SIGNALS.items():
        for topn in (10, 20, 50):
            r = run(feats.copy(), i2c[tr], elig[tr], f'{name}_top{topn}',
                    feat, sign, topn)
            if r:
                r.pop('series')
                r['base'] = name
                r['topn'] = topn
                rows.append(r)

    d = pd.DataFrame(rows).sort_values('excess_bp', ascending=False)
    d.to_csv(f'{OUT}/train_signals.csv', index=False)

    print(f'\n{"="*92}')
    print('  TRAIN 2017-2023   open->close, gross, before costs')
    print(f'{"="*92}')
    print(f'  {"signal":<26}{"days":>7}{"mean bp":>10}{"excess bp":>11}'
          f'{"hit%":>7}{"t-stat":>8}{"ann gross":>11}')
    print('  ' + '-' * 88)
    for _, r in d.head(14).iterrows():
        print(f"  {r.signal:<26}{int(r.days):>7}{r.mean_bp:>10.2f}"
              f"{r.excess_bp:>11.2f}{r.hit:>7.1f}{r.tstat:>8.2f}"
              f"{r.ann_gross:>10.1f}%")

    print('\n  COST HURDLE - what a round trip costs, and the bp/day needed')
    print('  ' + '-' * 88)
    for tier, lbl in ((1, 'liquid'), (2, 'mid'), (3, 'illiquid')):
        for ov in (25_000, 100_000):
            rt = round_trip_cost(ov, tier)
            print(f'    {lbl:<9} Rs{ov:>7,}/order: {rt*1e4:6.1f} bp per trade'
                  f'   -> need > {rt*1e4:.0f} bp/day just to break even')

    best = d.iloc[0]
    rt_mid = round_trip_cost(100_000, 2) * 1e4
    print(f'\n  Best train signal is {best.signal} at {best.mean_bp:.2f} bp/day.')
    print(f'  A mid-liquidity Rs 1 lakh order costs {rt_mid:.1f} bp per round trip.')
    verdict = ('CLEARS' if best.mean_bp > rt_mid else 'DOES NOT CLEAR')
    print(f'  -> {verdict} the cost hurdle before any out-of-sample haircut.')
    print(f'\n  saved -> {OUT}/train_signals.csv')


if __name__ == '__main__':
    main()
