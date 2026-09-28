"""
ATTACK on the long-only same-day winner.

`mom2|10:15|all top5` - buy the 5 biggest gainers of the last 30 minutes at
10:15, sell at the close - showed +47.7 bp gross / +26.7 net on the 15m panel.

That panel is 57 days of Jul-Sep 2026. The 1h panel is 490 days going back to
Sep 2024 and contains the SAME strategy in a slightly coarser form: at 10:15,
rank by the morning's move so far, buy the top 5, exit at the 15:15 close.

If the edge is real it survives the longer sample. If it is a property of
Jul-Sep 2026, it will not.
"""
import sys, io, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from intraday_lab import harness as H1          # 1h, 490 days
from intraday_lab import harness_fine as HF     # 15m, 57 days

COST = 21.0

# ---------------------------------------------------------------- 1h, 490 days
print('=' * 94)
print('  SAME STRATEGY ON 490 DAYS (1h panel, Sep 2024 - Sep 2026)')
print('=' * 94)
ctx = H1.context('10:15')
morning = ctx['today_sofar']          # 09:15 open -> 10:15 open: the morning move
first_bar = ctx['slot_ret_0']         # the 09:15 bar's own return

print(f'  {"signal":<26}{"N":>4}{"days":>7}{"gross":>9}{"net":>8}{"hit%":>7}'
      f'{"t":>7}{"H1":>8}{"H2":>8}')
print('  ' + '-' * 90)
rows = []
for nm, sc in (('buy morning winners', morning), ('buy 1st-bar winners', first_bar)):
    for topn in (5, 10, 20):
        r = H1.evaluate(sc, ctx, topn=topn, long=True, cost_bp=COST,
                        label=nm, min_liq=1e7)
        if r:
            rows.append(r)
            print(f"  {nm:<26}{topn:>4}{r['days']:>7}{r['gross_bp']:>9.1f}"
                  f"{r['net_bp']:>8.1f}{r['hit']:>7.1f}{r['tstat']:>7.2f}"
                  f"{r['h1_bp']:>8.1f}{r['h2_bp']:>8.1f}")

# ------------------------------------------------- month by month on 15m panel
print()
print('=' * 94)
print('  THE 15m WINNER, MONTH BY MONTH (is +47.7 bp spread out, or one month?)')
print('=' * 94)
d = HF.load('15m')
npd, date, C, O = HF.bars_per_day(d), d['date'], d['close'], d['open']
pos = date.groupby(date).cumcount()
el = HF.eligible(d, drop_first=1, drop_last=0)
last_close = C.groupby(date.values).transform('last')

m = (pos == 4).values                       # the 10:15 bar
idx = C.index[m]
r2 = (C / C.shift(2) - 1)
r2 = r2.where(HF.bcast(date.shift(2) == date, r2))
sc = r2.shift(1).loc[idx].where(el.loc[idx])
fwd = (last_close.loc[idx] / O.loc[idx] - 1)
sel = sc.where(fwd.notna()).rank(axis=1, ascending=False, method='first') <= 5
b = fwd.where(sel).mean(axis=1).dropna()
mkt = fwd.where(el.loc[idx]).mean(axis=1).reindex(b.index)

print(f'  {"month":<10}{"days":>6}{"strategy":>11}{"market":>10}{"vs mkt":>9}'
      f'{"net":>8}')
print('  ' + '-' * 90)
g = pd.DataFrame({'s': b, 'm': mkt}).groupby(b.index.to_period('M'))
for k, v in g:
    print(f'  {str(k):<10}{len(v):>6}{v.s.mean()*1e4:>+10.1f}{v.m.mean()*1e4:>+10.1f}'
          f'{(v.s.mean()-v.m.mean())*1e4:>+9.1f}{v.s.mean()*1e4-COST:>+8.1f}')
print('  ' + '-' * 90)
print(f'  {"ALL":<10}{len(b):>6}{b.mean()*1e4:>+10.1f}{mkt.mean()*1e4:>+10.1f}'
      f'{(b.mean()-mkt.mean())*1e4:>+9.1f}{b.mean()*1e4-COST:>+8.1f}')

top = b.sort_values(ascending=False)
print(f'\n  single best day contributes {top.iloc[0]*1e4:+.0f} bp of the '
      f'{b.mean()*1e4:+.1f} bp average')
print(f'  drop the best 3 days ({len(b)} total): '
      f'{top.iloc[3:].mean()*1e4:+.1f} bp gross, '
      f'{top.iloc[3:].mean()*1e4-COST:+.1f} bp net')
print(f'  median day: {b.median()*1e4:+.1f} bp   (mean {b.mean()*1e4:+.1f} bp)')
