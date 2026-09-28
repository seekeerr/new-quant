"""
Which is it - a special regime, or a broken test?

The 15m panel says +47.7 bp. The 1h panel over 490 days says +0.9 bp. They
overlap on exactly one stretch: Jul 3 - Sep 24 2026. Run the 1h version on
ONLY those days.

  1h restricted to Jul-Sep 2026 comes out big  -> the window is a real regime,
                                                 and the 15m number is honest
                                                 about a period that will end.
  1h restricted to Jul-Sep 2026 stays flat     -> the two tests disagree on the
                                                 SAME days, so the difference is
                                                 in the test, not the market,
                                                 and the 15m number is an artifact.
"""
import sys, io, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from intraday_lab import harness as H1

COST = 21.0
ctx = H1.context('10:15')
days = ctx['days']
sc = ctx['today_sofar']

el = H1.eligible(ctx, min_price=20.0, min_liq=1e7)
ret = ctx['exit_close'] / ctx['entry_open'] - 1

def run(mask_days, topn, tag):
    s = sc.where(el).where(ret.notna()).loc[mask_days]
    sel = s.rank(axis=1, ascending=False, method='first') <= topn
    r = ret.loc[mask_days]
    b = r.where(sel).mean(axis=1).dropna()
    m = r.where(el.loc[mask_days]).mean(axis=1).reindex(b.index)
    if len(b) < 20:
        return
    t = b.mean() / b.std() * np.sqrt(len(b))
    print(f'  {tag:<26}{topn:>4}{len(b):>7}{b.mean()*1e4:>+10.1f}'
          f'{m.mean()*1e4:>+9.1f}{(b.mean()-m.mean())*1e4:>+9.1f}'
          f'{b.mean()*1e4-COST:>+8.1f}{t:>7.2f}')

win = (days >= '2026-07-03') & (days <= '2026-09-24')
print('=' * 92)
print('  1h panel: buy the morning winners at 10:15, sell at the close')
print('=' * 92)
print(f'  {"period":<26}{"N":>4}{"days":>7}{"strategy":>10}{"market":>9}'
      f'{"vs mkt":>9}{"net":>8}{"t":>7}')
print('  ' + '-' * 88)
for topn in (5, 10):
    run(days[win], topn, 'Jul-Sep 2026 ONLY')
for topn in (5, 10):
    run(days[~win], topn, 'everything BEFORE Jul 26')
for topn in (5, 10):
    run(days, topn, 'full 490 days')

# year by year, top 5
print()
print('  year by year (top 5):')
print(f'  {"year":<26}{"N":>4}{"days":>7}{"strategy":>10}{"market":>9}'
      f'{"vs mkt":>9}{"net":>8}{"t":>7}')
print('  ' + '-' * 88)
for y, grp in pd.Series(days, index=days).groupby(days.year):
    run(grp.index, 5, f'{y}')
