"""
Re-test the gap-fade with REALISTIC entries, using hourly bars.

The daily-bar study found a large gap-fade edge that existed only at the exact
opening print - an order you cannot reliably place, because for gap-down names
the open sits at the very bottom of the day's range. That study could not say
what happens if you enter a little later, because daily bars have no path.

Hourly bars answer it directly. NSE trades 09:15-15:30, so a 1h series gives
seven bars stamped 09:15, 10:15, 11:15, 12:15, 13:15, 14:15, 15:15. An entry at
the 10:15 bar's OPEN is a real, placeable order: you watch the first hour, then
buy. If the edge survives that, it is tradeable. If it evaporates, the daily
result was the open print's artifact and nothing more.

Exit is always the 15:15 bar's close - the end of the session.

    py -m intraday_lab.hourly_test
"""
import sys
import io
import os

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN = os.path.join(ROOT, 'data', 'cache_intraday')
OUT = os.path.join(ROOT, 'results', 'intraday_lab')
os.makedirs(OUT, exist_ok=True)

COST_BP = {'liquid': 21, 'mid': 38}      # intraday round trip, from research.py


def load():
    o = pd.read_parquet(os.path.join(IN, '1h_open.parquet'))
    c = pd.read_parquet(os.path.join(IN, '1h_close.parquet'))
    h = pd.read_parquet(os.path.join(IN, '1h_high.parquet'))
    l = pd.read_parquet(os.path.join(IN, '1h_low.parquet'))
    v = pd.read_parquet(os.path.join(IN, '1h_volume.parquet'))
    return o, c, h, l, v


def by_slot(df):
    """Reshape a bar panel into {slot_label: DataFrame indexed by date}."""
    out = {}
    hhmm = df.index.strftime('%H:%M')
    dates = pd.to_datetime(df.index.date)
    for slot in sorted(set(hhmm)):
        m = hhmm == slot
        sub = df[m].copy()
        sub.index = dates[m]
        out[slot] = sub[~sub.index.duplicated(keep='first')]
    return out


def main():
    o, c, h, l, v = load()
    O, C, H, L, V = (by_slot(x) for x in (o, c, h, l, v))
    slots = sorted(O)
    print(f'bars per day: {len(slots)}  ->  {", ".join(slots)}')

    first, last = slots[0], slots[-1]
    days = O[first].index.intersection(C[last].index)
    for s in slots:
        days = days.intersection(O[s].index)
    print(f'trading days: {len(days)}   symbols: {O[first].shape[1]}')

    open915 = O[first].loc[days]
    close_eod = C[last].loc[days]
    prev_close = close_eod.shift(1)

    gap = (open915 / prev_close - 1).replace([np.inf, -np.inf], np.nan)
    gap = gap.where(gap.abs() < 0.25)

    # liquidity: median rupee volume per day over the previous 20 sessions
    dayval = sum(C[s].loc[days] * V[s].loc[days] for s in slots)
    liq = dayval.shift(1).rolling(20, min_periods=10).median()

    print(f'\n{"="*86}')
    print('  GAP-DOWN FADE - does the edge survive a realistic entry?')
    print(f'{"="*86}')
    print('  entry = the OPEN of that hourly bar. exit = 15:15 close, same day.')
    print('  "09:15" is the idealised daily-bar result; later slots are placeable.\n')

    for liq_lbl, thr, cost in (('>=Rs1cr/day', 1e7, 38), ('>=Rs10cr/day', 1e8, 21)):
        elig = (prev_close >= 20) & (liq >= thr) & gap.notna() & close_eod.notna()
        g = gap.where(elig)
        rk = (-g).rank(axis=1, ascending=False, method='first')
        sel = rk <= 10
        n = sel.sum(axis=1)

        print(f'  {liq_lbl}   (cost {cost} bp/round trip, '
              f'avg {n[n > 0].mean():.0f} names/day)')
        print(f'    {"entry":<9}{"days":>6}{"gross bp":>10}{"net bp":>9}'
              f'{"hit%":>7}{"ann net":>10}')
        for s in slots[:-1]:
            entry = O[s].loc[days]
            r = (close_eod / entry - 1).where(sel)
            d = r.mean(axis=1).replace([np.inf, -np.inf], np.nan).dropna()
            d = d[n.reindex(d.index) >= 3]
            if len(d) < 100:
                continue
            bp = d.mean() * 1e4
            net = bp - cost
            ann = ((1 + d - cost / 1e4).prod() ** (252 / len(d)) - 1) * 100
            flag = '  <- idealised' if s == first else ''
            print(f'    {s:<9}{len(d):>6}{bp:>10.1f}{net:>9.1f}'
                  f'{(d > 0).mean()*100:>7.1f}{ann:>9.0f}%{flag}')
        print()

    # Split the two years in half - a thin but honest out-of-sample check
    mid = days[len(days) // 2]
    print(f'  SPLIT CHECK  (first half to {mid.date()}, second half after)')
    elig = (prev_close >= 20) & (liq >= 1e7) & gap.notna() & close_eod.notna()
    g = gap.where(elig)
    sel = (-g).rank(axis=1, ascending=False, method='first') <= 10
    print(f'    {"entry":<9}{"1st half bp":>13}{"2nd half bp":>13}')
    for s in (first, slots[1], slots[2]):
        entry = O[s].loc[days]
        r = (close_eod / entry - 1).where(sel)
        d = r.mean(axis=1).dropna()
        a, b = d[d.index <= mid], d[d.index > mid]
        print(f'    {s:<9}{a.mean()*1e4:>13.1f}{b.mean()*1e4:>13.1f}')

    print(f'\n  NOTE: yfinance serves only currently-listed symbols, so this '
          f'2-year\n  sample has survivorship bias the daily bhavcopy spine '
          f'does not.')


if __name__ == '__main__':
    main()
