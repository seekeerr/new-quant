"""
Where does the Jul-Sep edge actually live?

The Rs 1 lakh book made +13.6% on the unrestricted universe and LOST 7.4% on
the top-100 by liquidity, over the same 57 days. That gap is the whole result.

This raises the liquidity floor step by step. Alpha does not care how liquid a
stock is. Compensation for providing liquidity cares enormously - it lives in
the names that are hard to trade and vanishes in the ones that are not.

The hourly campaign found this signature three separate times. If it shows up
here too, the Jul-Sep 2026 "regime" is the same artifact in a new costume.
"""
import sys, io, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from intraday_lab import harness_fine as HF

COST = 21.0
d = HF.load('15m')
npd, date, C, O = HF.bars_per_day(d), d['date'], d['close'], d['open']
pos = date.groupby(date).cumcount()
liq_bar = HF.liquidity(d)                       # median rupee volume per bar
liq_day = liq_bar * npd                         # ~ rupee turnover per day
el0 = HF.eligible(d, drop_first=1, drop_last=0)
last_close = C.groupby(date.values).transform('last')

m = (pos == 4).values
idx = C.index[m]
r = C / O.shift(1) - 1
r = r.where(HF.bcast(date.shift(1) == date, r)).shift(1)

fwd = (last_close.loc[idx] / O.loc[idx] - 1)

print('=' * 96)
print('  15m panel, Jul-Sep 2026 — the SAME strategy, raising the liquidity floor')
print('=' * 96)
print(f'  {"floor (Rs/day turnover)":<28}{"names/day":>11}{"gross":>9}{"net":>8}'
      f'{"t":>7}{"median turnover of picks":>28}')
print('  ' + '-' * 92)

for label, floor in (('no floor (as tested)', 0),
                     ('>= Rs 1 crore', 1e7),
                     ('>= Rs 5 crore', 5e7),
                     ('>= Rs 10 crore', 1e8),
                     ('>= Rs 25 crore', 2.5e8),
                     ('>= Rs 50 crore', 5e8),
                     ('>= Rs 100 crore', 1e9)):
    el = el0 & (liq_day >= floor)
    sc = r.loc[idx].where(el.loc[idx]).where(fwd.notna())
    sel = sc.rank(axis=1, ascending=False, method='first') <= 5
    n = sel.sum(axis=1)
    b = fwd.where(sel).mean(axis=1)[n >= 3].dropna()
    if len(b) < 20:
        print(f'  {label:<28}{"too few":>11}')
        continue
    picks_liq = liq_day.loc[idx].where(sel).stack().median()
    t = b.mean() / b.std() * np.sqrt(len(b))
    avail = el.loc[idx].sum(axis=1).mean()
    print(f'  {label:<28}{avail:>11.0f}{b.mean()*1e4:>+9.1f}'
          f'{b.mean()*1e4-COST:>+8.1f}{t:>7.2f}{picks_liq/1e7:>24.1f} cr')

print()
print('  "names/day" is how many stocks pass the floor, not how many are bought.')
print('  "median turnover of picks" is what the strategy actually chose to buy.')
