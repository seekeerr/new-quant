"""
Harness for sub-hourly bars (5m / 15m / 30m).

WHY THIS EXISTS SEPARATELY FROM harness.py
------------------------------------------
`harness.py` is built around 7 named slots a day and a single open->close
holding period. That shape cannot express "hold for 15 minutes". This module
works on raw bar indices instead, so the holding period is a parameter.

THE TRADEABILITY CONTRACT (the thing that killed every earlier result)
----------------------------------------------------------------------
A signal at bar t may use bars 0..t inclusive - t's CLOSE is fair game, because
you observe it before you can act on it. You then transact at the OPEN of bar
t+1 and exit at the OPEN of bar t+1+h. Both legs are bar opens strictly after
the signal is known, so there is no way to buy at a price the signal saw.

This is deliberately more conservative than close-to-close: entering at the
close of the signal bar is what manufactured the gap-fade artifact, where the
picked names' opens sat at the low of the day's range.

Same-day only. Any trade whose exit falls on a later date is dropped, so
nothing carries overnight drift into an intraday result.

COSTS
-----
Intraday round trip, liquid NSE: ~21 bp (STT 2.5 sell-side, brokerage,
exchange+GST, stamp, plus ~2x half-spread). At 15m bars with h=1 that is paid
25 times a day. `net_bp` is per TRADE - multiply by trades/day for the daily
number, which is how a 5 bp per-trade edge turns into a 125 bp/day cost bill.

SAMPLE
------
5m/15m have a hard 60-day window at the source, so this is ~60 days, not 490.
Per-BAR observations are plentiful (60d x 25 bars = 1,500 at 15m) but they come
from one 3-month regime. Split-half here splits time, and a result that only
works in one half means nothing.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(ROOT, 'data', 'cache_intraday')
OUT = os.path.join(ROOT, 'results', 'intraday_lab')
os.makedirs(OUT, exist_ok=True)

COST_BP = {'liquid': 21.0, 'mid': 38.0}

_CACHE = {}


def load(interval='15m'):
    """{field: DataFrame(timestamp x symbol)} for one interval."""
    if interval in _CACHE:
        return _CACHE[interval]
    d = {}
    for f in ('open', 'high', 'low', 'close', 'volume'):
        p = os.path.join(IN, f'{interval}_{f}.parquet')
        d[f] = pd.read_parquet(p).sort_index()
    # common columns across all fields
    cols = None
    for f in d:
        cols = d[f].columns if cols is None else cols.intersection(d[f].columns)
    for f in d:
        d[f] = d[f][cols]
    d['date'] = pd.Series(pd.to_datetime(d['close'].index.date),
                          index=d['close'].index)
    d['tod'] = pd.Series(d['close'].index.strftime('%H:%M'),
                         index=d['close'].index)
    _CACHE[interval] = d
    return d


def bcast(mask, df):
    """Row-wise boolean Series -> full-shape mask aligned to df."""
    return pd.DataFrame(np.broadcast_to(mask.values[:, None], df.shape),
                        index=df.index, columns=df.columns)


def bars_per_day(d):
    return int(d['date'].value_counts().mode().iloc[0])


def forward(d, h=1):
    """
    Return of the tradeable leg: buy at open[t+1], sell at open[t+1+h].
    Indexed by the SIGNAL bar t. NaN wherever the round trip would cross a day.
    """
    O = d['open']
    entry = O.shift(-1)
    exit_ = O.shift(-(1 + h))
    r = exit_ / entry - 1
    same = (d['date'].shift(-(1 + h)) == d['date']).reindex(r.index).fillna(False)
    return r.where(np.broadcast_to(same.values[:, None], r.shape))


def liquidity(d, win=None):
    """Median rupee volume per bar over the prior `win` bars (strictly prior)."""
    if win is None:
        win = bars_per_day(d) * 5
    rv = d['close'] * d['volume']
    return rv.shift(1).rolling(win, min_periods=win // 3).median()


def eligible(d, min_price=20.0, min_rv=None, drop_first=1, drop_last=1):
    """
    Tradeable mask. Drops the opening bar (auction noise, and the 1h feed had
    volume==0 on 74.9% of 09:15 rows - check yours) and the closing bars where
    no exit exists.
    """
    if min_rv is None:
        min_rv = 2e5          # Rs 2 lakh per bar ~ Rs 5cr/day at 25 bars
    liq = liquidity(d)
    ok = (d['close'] >= min_price) & (liq >= min_rv) & d['open'].notna()
    # position of each bar within its day
    pos = d['date'].groupby(d['date']).cumcount()
    npd = d['date'].map(d['date'].value_counts())
    keep = (pos >= drop_first) & (pos < npd - drop_last)
    return ok & np.broadcast_to(keep.values[:, None], ok.shape)


def evaluate(score, d, fwd, topn=10, long=True, cost_bp=21.0,
             el=None, label='', min_names=3):
    """
    score : DataFrame(timestamp x symbol) known at bar t. Higher = buy.
    Returns per-TRADE bp, t-stat, split halves. None if too few observations.
    """
    s = score if el is None else score.where(el)
    s = s.where(fwd.notna())
    rk = s.rank(axis=1, ascending=False, method='first')
    sel = rk <= topn
    n = sel.sum(axis=1)

    r = fwd if long else -fwd
    b = r.where(sel).mean(axis=1).replace([np.inf, -np.inf], np.nan)
    b = b[(n >= min_names).reindex(b.index).fillna(False)].dropna()
    if len(b) < 200:
        return None

    bp = b.mean() * 1e4
    sd = b.std()
    mid = b.index[len(b) // 2]
    a, c = b[b.index <= mid], b[b.index > mid]
    return {
        'label': label, 'obs': len(b), 'topn': topn,
        'side': 'L' if long else 'S',
        'gross_bp': round(bp, 2), 'net_bp': round(bp - cost_bp, 2),
        'hit': round((b > 0).mean() * 100, 1),
        'std_bp': round(sd * 1e4, 1),
        'tstat': round(b.mean() / sd * np.sqrt(len(b)), 2) if sd else np.nan,
        'h1_bp': round(a.mean() * 1e4, 2),
        'h2_bp': round(c.mean() * 1e4, 2),
        'consistent': bool((a.mean() > 0) == (c.mean() > 0)),
    }


def zscore(df):
    m = df.mean(axis=1)
    s = df.std(axis=1).replace(0, np.nan)
    return df.sub(m, axis=0).div(s, axis=0)


def report(rows, title, top=25, sort='gross_bp'):
    rows = [r for r in rows if r]
    if not rows:
        return print(f'{title}: nothing ran')
    t = pd.DataFrame(rows).sort_values(sort, ascending=False)
    print(f'\n{"="*102}\n  {title}   ({len(t)} configs)\n{"="*102}')
    print(f'  {"strategy":<36}{"side":>5}{"N":>4}{"obs":>7}{"gross":>8}'
          f'{"net":>8}{"hit%":>7}{"t":>7}{"H1":>8}{"H2":>8}')
    print('  ' + '-' * 98)
    for _, r in t.head(top).iterrows():
        flag = '' if r['consistent'] else '  *flips*'
        print(f"  {r.label:<36}{r.side:>5}{int(r.topn):>4}{int(r.obs):>7}"
              f"{r.gross_bp:>8.1f}{r.net_bp:>8.1f}{r.hit:>7.1f}{r.tstat:>7.2f}"
              f"{r.h1_bp:>8.1f}{r.h2_bp:>8.1f}{flag}")
    return t
