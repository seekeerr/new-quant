"""
Fast harness for hourly intraday strategy search.

Data: 1h bars, 398 NSE symbols, ~490 trading days, 7 slots/day
(09:15 10:15 11:15 12:15 13:15 14:15 15:15).

A STRATEGY here is: at entry slot E on day D, rank the eligible symbols by some
score computed ONLY from bars at or before E; buy the top N at slot E's open;
sell at the exit slot's close the same day.

THREE RULES THAT MAKE A RESULT MEAN ANYTHING
--------------------------------------------
1. NO LOOK-AHEAD. A score for entry slot E may use bars strictly before E, plus
   E's own OPEN (known at the moment you transact). Never E's close, high or
   low, and never any later slot. `bars_before()` enforces this.

2. ENTRY AT 09:15 IS NOT TRADEABLE and is excluded by default. The gap-fade
   study already established that the 09:15 print sits at the bottom of the
   day's range for exactly the names a signal would pick, and the edge is gone
   by 10:15. Anything that only works at 09:15 is an artifact, so DEFAULT_ENTRY
   starts at 10:15.

3. COSTS ARE NOT OPTIONAL. Intraday round trip is ~21 bp liquid / ~38 bp mid,
   and a daily-trading strategy pays it ~250 times a year. `net_bp` is the only
   number worth reading; gross is shown to make the size of the haircut visible.

SAMPLE SIZE WARNING: two years is ~490 days, split into ~245 train / ~245 test.
That is thin. Search hundreds of configs here and the best train result is
mostly luck - which is why `evaluate()` always reports both halves and why the
campaign runner applies a multiple-testing hurdle.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(ROOT, 'data', 'cache_intraday')
OUT = os.path.join(ROOT, 'results', 'intraday_lab')
os.makedirs(OUT, exist_ok=True)

SLOTS = ['09:15', '10:15', '11:15', '12:15', '13:15', '14:15', '15:15']
DEFAULT_ENTRY = '10:15'
EXIT_SLOT = '15:15'
COST_BP = {'liquid': 21.0, 'mid': 38.0}

_CACHE = {}


def load():
    """{field: {slot: DataFrame(date x symbol)}} plus the common date index."""
    if 'data' in _CACHE:
        return _CACHE['data']

    raw = {}
    for f in ('open', 'high', 'low', 'close', 'volume'):
        raw[f] = pd.read_parquet(os.path.join(IN, f'1h_{f}.parquet'))

    out = {}
    for f, df in raw.items():
        hhmm = df.index.strftime('%H:%M')
        dates = pd.to_datetime(df.index.date)
        slots = {}
        for s in SLOTS:
            m = hhmm == s
            if not m.any():
                continue
            sub = df[m].copy()
            sub.index = dates[m]
            slots[s] = sub[~sub.index.duplicated(keep='first')]
        out[f] = slots

    days = None
    for s in SLOTS:
        if s in out['close']:
            idx = out['close'][s].index
            days = idx if days is None else days.intersection(idx)
    for f in out:
        for s in list(out[f]):
            out[f][s] = out[f][s].reindex(days)

    _CACHE['data'] = (out, days)
    return out, days


def bars_before(entry_slot):
    """Slots strictly earlier than the entry slot - the only ones a score may see."""
    return SLOTS[:SLOTS.index(entry_slot)]


def context(entry_slot=DEFAULT_ENTRY):
    """
    Everything a strategy is allowed to know at `entry_slot`, pre-computed.

    Keys are plain DataFrames (date x symbol):
      prev_close   yesterday's 15:15 close
      gap          entry-slot open vs yesterday's close
      today_sofar  return from 09:15 open to the entry slot's open
      slot_ret_k   return of the k-th completed bar today
      hi_sofar / lo_sofar / range_sofar   today's extremes before entry
      pos_in_range where the entry open sits inside today's range so far
      entry_open   the price you transact at
      liq          median daily rupee volume over the prior 20 sessions
      d1..d20      prior-day returns and momentum
      vol20        daily realised vol
    """
    data, days = load()
    O, H, L, C, V = (data[k] for k in ('open', 'high', 'low', 'close', 'volume'))
    before = bars_before(entry_slot)

    eod = C[EXIT_SLOT]
    prev_close = eod.shift(1)
    entry_open = O[entry_slot]

    ctx = {
        'days': days,
        'entry_open': entry_open,
        'exit_close': eod,
        'prev_close': prev_close,
        'gap': (O[SLOTS[0]] / prev_close - 1).where(lambda x: x.abs() < .25),
        'entry_gap': (entry_open / prev_close - 1).where(lambda x: x.abs() < .25),
    }

    if before:
        ctx['today_sofar'] = (entry_open / O[SLOTS[0]] - 1)
        hi = pd.concat([H[s] for s in before]).groupby(level=0).max()
        lo = pd.concat([L[s] for s in before]).groupby(level=0).min()
        ctx['hi_sofar'], ctx['lo_sofar'] = hi, lo
        rng = (hi - lo).replace(0, np.nan)
        ctx['range_sofar'] = rng / prev_close
        ctx['pos_in_range'] = (entry_open - lo) / rng
        for k, s in enumerate(before):
            ctx[f'slot_ret_{k}'] = (C[s] / O[s] - 1)
        vol_today = sum(V[s] for s in before)
        ctx['vol_sofar'] = vol_today
        dv = sum(C[s] * V[s] for s in SLOTS if s in C)
        ctx['vol_ratio'] = vol_today / (
            sum(V[s] for s in before).shift(1).rolling(20, min_periods=5).median()
            .replace(0, np.nan))
    else:
        ctx['today_sofar'] = pd.DataFrame(0.0, index=days,
                                          columns=entry_open.columns)

    dv = sum(C[s] * V[s] for s in SLOTS if s in C)
    ctx['liq'] = dv.shift(1).rolling(20, min_periods=10).median()

    r = eod.pct_change()
    for k in (1, 2, 5, 10, 20):
        ctx[f'd{k}'] = (prev_close / eod.shift(k + 1) - 1)
    ctx['vol20'] = r.shift(1).rolling(20, min_periods=10).std()
    ctx['atr'] = ((H[EXIT_SLOT] - L[SLOTS[0]]) / eod).shift(1) \
        .rolling(10, min_periods=5).mean()
    hi252 = eod.shift(1).rolling(250, min_periods=60).max()
    ctx['pct52'] = prev_close / hi252
    ctx['price'] = prev_close
    return ctx


def eligible(ctx, min_price=20.0, min_liq=1e7):
    return ((ctx['price'] >= min_price) & (ctx['liq'] >= min_liq)
            & ctx['entry_open'].notna() & ctx['exit_close'].notna())


def evaluate(score, ctx, topn=10, long=True, cost_bp=38.0,
             min_price=20.0, min_liq=1e7, label='', split=True):
    """
    score : DataFrame (date x symbol), higher = more attractive.
    Returns a dict of gross/net bp per day, hit rate, and both halves.
    """
    el = eligible(ctx, min_price, min_liq)
    s = score.where(el)
    rk = s.rank(axis=1, ascending=False, method='first')
    sel = rk <= topn
    n = sel.sum(axis=1)

    ret = (ctx['exit_close'] / ctx['entry_open'] - 1)
    if not long:
        ret = -ret
    d = ret.where(sel).mean(axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    d = d[n.reindex(d.index).fillna(0) >= max(3, topn // 3)]
    if len(d) < 120:
        return None

    bp = d.mean() * 1e4
    net = bp - cost_bp
    out = {
        'label': label, 'days': len(d), 'topn': topn, 'side': 'L' if long else 'S',
        'gross_bp': round(bp, 2), 'net_bp': round(net, 2),
        'hit': round((d > 0).mean() * 100, 1),
        'std_bp': round(d.std() * 1e4, 1),
        'tstat': round(d.mean() / d.std() * np.sqrt(len(d)), 2) if d.std() else np.nan,
        'ann_net': round((((1 + d - cost_bp / 1e4).prod())
                          ** (252 / len(d)) - 1) * 100, 1),
    }
    if split:
        mid = d.index[len(d) // 2]
        a, b = d[d.index <= mid], d[d.index > mid]
        out['h1_bp'] = round(a.mean() * 1e4, 2)
        out['h2_bp'] = round(b.mean() * 1e4, 2)
        out['consistent'] = bool((a.mean() > 0) == (b.mean() > 0))
    return out


def zscore(df):
    """Cross-sectional z-score, so scores of different units can be blended."""
    m = df.mean(axis=1)
    s = df.std(axis=1).replace(0, np.nan)
    return df.sub(m, axis=0).div(s, axis=0)


def report(rows, title, top=20, sort='net_bp'):
    if not rows:
        return print(f'{title}: nothing ran')
    d = pd.DataFrame([r for r in rows if r]).sort_values(sort, ascending=False)
    print(f'\n{"="*104}\n  {title}   ({len(d)} configs)\n{"="*104}')
    print(f'  {"strategy":<34}{"side":>5}{"N":>4}{"days":>6}{"gross":>8}'
          f'{"net bp":>8}{"hit%":>7}{"t":>7}{"H1":>8}{"H2":>8}{"ann net":>9}')
    print('  ' + '-' * 100)
    for _, r in d.head(top).iterrows():
        ok = '' if r.get('consistent', True) else '  *flips*'
        print(f"  {r.label:<34}{r.side:>5}{int(r.topn):>4}{int(r.days):>6}"
              f"{r.gross_bp:>8.1f}{r.net_bp:>8.1f}{r.hit:>7.1f}{r.tstat:>7.2f}"
              f"{r.get('h1_bp', np.nan):>8.1f}{r.get('h2_bp', np.nan):>8.1f}"
              f"{r.ann_net:>8.0f}%{ok}")
    return d
