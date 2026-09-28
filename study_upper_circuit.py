"""
Study: WHY and ON WHAT BASIS do stocks lock at a +10% upper circuit (UC),
and can the NEXT day's UC hitters be predicted from price/volume alone?

Data: survivorship-free NSE bhavcopy spine (data/cache_bhav/), equity-only
(ISIN 'INE', ETFs/funds excluded). Delisted names retained.

Mechanics that drive the design (verified against NSE rules):
  * A stock can only lock at +10% if the exchange assigned it the 10% band.
    Bands are 2/5/10/20%; F&O names have NO band, only a 10% "dynamic operating
    range" that FLEXES +5% at a time once touched. So an F&O stock printing
    +10% is NOT circuit-locked - it can and does go further. Excluded from the
    target, else we'd be predicting a different phenomenon.
  * Detection: return in [0.097, 0.103] off prev close AND close == high
    (locked at the band into the close). The return histogram shows a sharp
    pile-up at 9.9-10.0% (3,179 obs vs ~600/bucket baseline), confirming a hard
    band rather than a continuous distribution.
  * Band inference: a symbol's band is the tightest of {5,10,20} containing
    ~all trailing 250d moves. Rolling + shifted -> point-in-time, no look-ahead.

No-look-ahead: every feature uses data up to and including day T; the target is
a UC on day T+1.

Fillability: an UC print is not a fill. Gap-locked UCs (open == high == close)
are unbuyable - there is no seller. Turnover on the UC day bounds executable
size. Same trap as the repo's earlier "fillability mirage" finding.
"""
import sys
import io
import os

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')

import numpy as np
import pandas as pd

CACHE = 'data/cache_bhav'
OUT = 'results/upper_circuit'
START = '2018-01-01'
MIN_PRICE = 5.0
UC_LO, UC_HI = 0.097, 0.103
AT_HIGH_TOL = 0.9995

LIQ_TIERS = [
    ('micro  (<Rs25L)',      0.0,    2.5e6),
    ('small  (25L-1cr)',     2.5e6,  1e7),
    ('mid    (1cr-5cr)',     1e7,    5e7),
    ('liquid (>=Rs5cr)',     5e7,    1e18),
]


def load():
    def rd(n):
        return pd.read_parquet(os.path.join(CACHE, n))

    close = rd('adj_close.parquet')
    high = rd('adj_high.parquet')
    low = rd('adj_low.parquet')
    vol = rd('raw_volume.parquet')
    turn = rd('raw_turnover.parquet')

    iso = pd.read_csv(os.path.join(CACHE, 'symbol_isin.csv'))
    scol = 'SYMBOL' if 'SYMBOL' in iso.columns else iso.columns[0]
    icol = 'ISIN' if 'ISIN' in iso.columns else iso.columns[1]
    eq = set(iso.loc[iso[icol].astype(str).str.startswith('INE'), scol])

    keep = [c for c in close.columns if c in eq]
    out = [p.reindex(columns=keep).loc[START:] for p in
           (close, high, low, vol, turn)]
    return out


def detect_uc(close, high):
    ret = close.pct_change()
    at_high = close >= high * AT_HIGH_TOL
    uc = (ret >= UC_LO) & (ret <= UC_HI) & at_high & close.notna()
    return uc, ret


def infer_band(ret):
    """
    Point-in-time band classification.

    Evidence-based, not quantile-based: a SINGLE print beyond a band proves the
    band is wider, so we use the rolling MAX of |ret|, not a percentile. An
    earlier quantile version let 20%-band names (which merely closed +10%) into
    the 10% cohort and contaminated the target - e.g. QUINT, which has printed
    exactly 20.00%, is a 20%-band stock and can never "lock" at +10%.

    Windows include day T (legitimate: we predict T+1), so today's own move
    immediately reclassifies a stock.
      recent 60d max |ret| > 10.5%  -> band is wider than 10 (20% or F&O)
      250d max |ret| <= 5.3%        -> 5% band
      otherwise                     -> 10% band
    """
    a = ret.abs()
    # Use a 1-YEAR window as the primary evidence. A 60d window was too short:
    # names like ALKALI/SHIVAMAUTO printed an exact 20.00% inside the year but
    # not the last 60d, and were wrongly admitted as 10%-band. min_periods is
    # counted on non-NaN observations, so gappy/suspended names yield NaN and
    # are excluded rather than silently defaulting.
    mx = a.rolling(250, min_periods=60).max()

    band = pd.DataFrame(np.nan, index=ret.index, columns=ret.columns)
    band = band.mask(mx.notna() & (mx > 0.105), 20.0)      # 20% band or wider
    band = band.mask(mx.notna() & (mx > 0.21), 99.0)       # unbanded / F&O
    band = band.mask(mx.notna() & (mx <= 0.105) & (mx > 0.053), 10.0)
    band = band.mask(mx.notna() & (mx <= 0.053), 5.0)
    return band


def build_features(close, high, low, vol, turn, ret, uc, band):
    f = {}
    f['ret_1d'] = ret
    f['ret_5d'] = close.pct_change(5)
    f['ret_20d'] = close.pct_change(20)

    medv = vol.rolling(20, min_periods=10).median()
    f['vol_ratio'] = vol / medv.replace(0, np.nan)
    f['turn_med20'] = turn.rolling(20, min_periods=10).median()

    f['uc_today'] = uc.astype(float)
    f['uc_5d'] = uc.rolling(5, min_periods=2).sum()
    f['uc_20d'] = uc.rolling(20, min_periods=5).sum()

    rng = (high - low).replace(0, np.nan)
    f['range_pos'] = (close - low) / rng
    hi252 = close.rolling(252, min_periods=60).max()
    f['pct_52wh'] = close / hi252

    f['vol20'] = ret.rolling(20, min_periods=10).std()
    atr = (high - low) / close
    f['atr_ratio'] = (atr.rolling(5, min_periods=3).mean() /
                      atr.rolling(60, min_periods=30).mean().replace(0, np.nan))

    f['price'] = close
    return f


def stack_events(f, uc, close, turn, band):
    target = uc.shift(-1)
    elig = ((band == 10.0) & (close >= MIN_PRICE) &
            f['turn_med20'].notna() & target.notna())

    rows, cols = np.where(elig.values)
    out = {
        'date': elig.index.values[rows],
        'symbol': np.array(elig.columns)[cols],
    }
    for k, v in f.items():
        out[k] = v.values[rows, cols]
    out['uc_next'] = target.values[rows, cols]
    out['turn_next'] = turn.shift(-1).values[rows, cols]
    return pd.DataFrame(out)


def liq_tier(t):
    for name, lo, hi in LIQ_TIERS:
        if lo <= t < hi:
            return name
    return LIQ_TIERS[-1][0]


def bucket_table(ev, col, bins, labels, base):
    b = pd.cut(ev[col], bins=bins, labels=labels, include_lowest=True)
    g = ev.groupby(b, observed=True)['uc_next'].agg(['mean', 'sum', 'count'])
    g.columns = ['p_uc', 'n_uc', 'n_obs']
    g = g.astype(float)
    g['lift'] = g['p_uc'] / base
    g['ci95'] = 1.96 * np.sqrt(g['p_uc'] * (1 - g['p_uc']) /
                               g['n_obs'].clip(lower=1))
    return g


def fmt_table(g, title, base):
    L = [f'  {title}', '  ' + '-' * 76]
    L.append(f'  {"bucket":<24}{"P(UC tmrw)":>12}{"+/-95%":>9}'
             f'{"lift":>7}{"n UC":>9}{"n obs":>12}')
    for k, r in g.iterrows():
        L.append(f'  {str(k):<24}{r["p_uc"]*100:>11.3f}%{r["ci95"]*100:>8.3f}%'
                 f'{r["lift"]:>7.2f}{int(r["n_uc"]):>9,}{int(r["n_obs"]):>12,}')
    L.append(f'  {"-- BASE RATE --":<24}{base*100:>11.3f}%{"":>9}{1.0:>7.2f}')
    return '\n'.join(L)


def main():
    os.makedirs(OUT, exist_ok=True)
    print('loading panels...', flush=True)
    close, high, low, vol, turn = load()
    print(f'  universe {close.shape[1]:,} symbols x {close.shape[0]:,} days')

    uc_raw, ret = detect_uc(close, high)
    band = infer_band(ret)
    # a +10% close only counts as a LOCK if the stock is actually 10%-band
    uc = uc_raw & (band == 10.0)
    print(f'  +10% closes at high      : {int(uc_raw.sum().sum()):,}')
    print(f'  of which true 10%-band UC: {int(uc.sum().sum()):,} '
          f'({100*uc.sum().sum()/max(uc_raw.sum().sum(),1):.0f}%)')

    f = build_features(close, high, low, vol, turn, ret, uc, band)
    ev = stack_events(f, uc, close, turn, band)
    ev = ev.dropna(subset=['uc_next', 'vol_ratio', 'turn_med20'])
    print(f'  eligible 10%-band observations: {len(ev):,}')

    base = ev['uc_next'].mean()
    ev['tier'] = ev['turn_med20'].apply(liq_tier)

    R = []
    R.append('=' * 80)
    R.append('  WHAT DRIVES A +10% UPPER CIRCUIT  -  NSE, survivorship-free')
    R.append(f'  window {ev.date.min():%Y-%m-%d} .. {ev.date.max():%Y-%m-%d}'
             f'   |   {len(ev):,} stock-days in the 10% band')
    R.append('=' * 80)
    R.append('')
    R.append(f'  BASE RATE  P(stock locks +10% UC tomorrow) = {base*100:.3f}%'
             f'   ({int(ev.uc_next.sum()):,} events)')
    R.append('  -> roughly 1 in {:.0f} stock-days. Any predictor must be read'
             .format(1 / base))
    R.append('     against this floor.')
    R.append('')

    specs = [
        ('uc_today', [-.1, .5, 1.1], ['no UC today', 'UC TODAY'],
         'A) SERIAL CLUSTERING - did it lock today?'),
        ('uc_20d', [-.1, .5, 1.5, 3.5, 99], ['0 in 20d', '1 in 20d',
         '2-3 in 20d', '4+ in 20d'], 'B) UC FREQUENCY over last 20 days'),
        ('vol_ratio', [0, 1, 2, 3, 5, 10, 1e9], ['<1x', '1-2x', '2-3x',
         '3-5x', '5-10x', '>10x'], 'C) VOLUME SURGE vs 20d median'),
        ('ret_1d', [-1, -.05, 0, .03, .06, .097, 1], ['< -5%', '-5..0%',
         '0..3%', '3..6%', '6..9.7%', 'UC zone'], 'D) TODAY RETURN'),
        ('ret_20d', [-1, -.1, 0, .2, .5, 1e3], ['< -10%', '-10..0%',
         '0..20%', '20..50%', '> 50%'], 'E) 20-DAY MOMENTUM'),
        ('pct_52wh', [0, .5, .8, .95, .999, 1e3], ['<50% of 52wH',
         '50-80%', '80-95%', '95-100%', 'AT 52w HIGH'],
         'F) PROXIMITY TO 52-WEEK HIGH'),
        ('atr_ratio', [0, .7, 1, 1.5, 2.5, 1e3], ['<0.7 (coiled)',
         '0.7-1.0', '1.0-1.5', '1.5-2.5', '>2.5 (expanding)'],
         'G) RANGE EXPANSION  5d ATR / 60d ATR'),
        ('price', [0, 20, 50, 200, 1000, 1e9], ['Rs5-20', 'Rs20-50',
         'Rs50-200', 'Rs200-1000', '>Rs1000'], 'H) PRICE LEVEL'),
    ]
    for col, bins, labels, title in specs:
        g = bucket_table(ev, col, bins, labels, base)
        R.append(fmt_table(g, title, base))
        R.append('')

    # liquidity tier
    g = ev.groupby('tier')['uc_next'].agg(['mean', 'sum', 'count'])
    g.columns = ['p_uc', 'n_uc', 'n_obs']
    g = g.astype(float)
    g['lift'] = g['p_uc'] / base
    g['ci95'] = 1.96 * np.sqrt(g['p_uc'] * (1 - g['p_uc']) / g['n_obs'])
    order = [t[0] for t in LIQ_TIERS if t[0] in g.index]
    R.append(fmt_table(g.loc[order], 'I) LIQUIDITY TIER (median 20d turnover)',
                       base))
    R.append('')

    txt = '\n'.join(R)
    print(txt)
    with open(os.path.join(OUT, 'drivers.txt'), 'w', encoding='utf-8') as fh:
        fh.write(txt)
    ev.to_parquet(os.path.join(OUT, 'events.parquet'))
    print(f'\nsaved -> {OUT}/drivers.txt, events.parquet')


if __name__ == '__main__':
    main()
