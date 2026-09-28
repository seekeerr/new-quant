"""
What does one of these 'strategies' actually DO on a real day?

The battery reports basket averages. That hides the mechanics: which names,
at what time, how many orders. This prints the actual trades for the best 15m
config on one real day, and then counts what a year of it costs.

Config: at each bar, rank the top-100 liquid names by their return over the
last 12 bars (3 hours), SHORT the 10 biggest losers, cover 8 bars (2h) later.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from intraday_lab import harness_fine as H

d = H.load('15m')
npd, date, C, O = H.bars_per_day(d), d['date'], d['close'], d['open']
el = H.eligible(d)
liq = H.liquidity(d)
el = el & (liq.where(el).rank(axis=1, ascending=False, method='first') <= 100)

k, h = 12, 8
r = C / C.shift(k) - 1
score = -r.where(H.bcast(date.shift(k) == date, r))
fwd = H.forward(d, h)

s = score.where(el).where(fwd.notna())
rk = s.rank(axis=1, ascending=False, method='first')
sel = rk <= 10
n = sel.sum(axis=1)

# a normal day in the middle of the sample
day = sorted(date.unique())[30]
bars = [t for t in C.index if date[t] == day and n.get(t, 0) >= 3]

print(f'DAY: {pd.Timestamp(day).date()}   tradeable entry bars: {len(bars)}\n')
for t in bars:
    picks = sel.loc[t][sel.loc[t]].index.tolist()
    ent = O.shift(-1).loc[t]
    ex = O.shift(-(1 + h)).loc[t]
    exit_t = C.index[C.index.get_loc(t) + 1 + h]
    print(f'  signal {t.strftime("%H:%M")} -> SHORT at {(t + pd.Timedelta(minutes=15)).strftime("%H:%M")} '
          f'open, COVER at {exit_t.strftime("%H:%M")} open')
    for p in picks:
        move = (r.loc[t, p]) * 100
        pnl = -(ex[p] / ent[p] - 1) * 1e4
        print(f'      {p:<14} 3h move {move:+6.2f}%   short {ent[p]:>9.2f} '
              f'-> cover {ex[p]:>9.2f}   {pnl:+7.1f} bp')
    basket = -(ex[picks] / ent[picks] - 1).mean() * 1e4
    print(f'      {"BASKET":<14} {"":>28} {"":>22}{basket:+7.1f} bp gross'
          f'   {basket-21:+7.1f} bp NET\n')

# ---- what a year of this costs
print('=' * 78)
print('  ORDER COUNT — the part the basket averages hide')
print('=' * 78)
per_day_overlap = float(n[n >= 3].groupby(date[n >= 3]).size().mean())
non_overlap = npd // h
for name, entries in (('every bar (as backtested, overlapping)', per_day_overlap),
                      ('non-overlapping only', non_overlap)):
    orders = entries * 10 * 2
    print(f'  {name:<40} {entries:>5.1f} entries/day'
          f'{orders:>7.0f} orders/day{orders*250:>10,.0f} orders/year')
# One basket = the whole capital spread over 10 names, so one basket round trip
# costs 21 bp OF CAPITAL, and the basket's gross bp is also a return ON capital.
GROSS = 11.6
cost_day = non_overlap * 21
gross_day = non_overlap * GROSS
print()
print('  One basket = full capital across 10 names, so ONE basket round trip')
print('  costs 21 bp OF CAPITAL and earns the basket bp ON capital.')
print()
print(f'  {non_overlap} non-overlapping entries/day:')
print(f'      gross {gross_day:>7.1f} bp/day   ({GROSS} bp x {non_overlap} entries)')
print(f'      cost  {cost_day:>7.1f} bp/day   (21 bp x {non_overlap} entries)')
print(f'      NET   {gross_day-cost_day:>+7.1f} bp/day')
print()
print(f'  Over 250 days:  gross {gross_day*250/100:>+6.0f}% of capital'
      f'   costs {-cost_day*250/100:>+6.0f}%'
      f'   net {(gross_day-cost_day)*250/100:>+6.0f}%')