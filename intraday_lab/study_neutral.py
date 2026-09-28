"""
Attack: is the ~6 bp/hour a real cross-sectional effect, or just a short book
in a falling 59-day window?

Jul-Sep 2026 is one regime. A short-the-losers basket earns the market's drift
for free if the market fell. Strip it: measure the basket against the
equal-weighted return of the SAME eligible universe over the SAME bars. What
survives is the part a market-neutral book would actually collect.
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from intraday_lab import harness_fine as H

COST = 21.0
d = H.load('15m')
date, C = d['date'], d['close']
el = H.eligible(d)
liq = H.liquidity(d)
el = el & (liq.where(el).rank(axis=1, ascending=False, method='first') <= 100)

k = 12
r = C / C.shift(k) - 1
score = -r.where(H.bcast(date.shift(k) == date, r))

print(f'  {"hold":>8}{"obs":>7}{"raw S":>9}{"mkt":>9}{"neutral":>10}'
      f'{"t(neu)":>9}{"bp/hr":>8}   long leg')
print('  ' + '-' * 76)

for h in (2, 4, 6, 8):
    fwd = H.forward(d, h)
    f = fwd.where(el)
    mkt = f.mean(axis=1)                      # equal-weight eligible universe

    rk = score.where(el).where(f.notna()).rank(axis=1, ascending=False,
                                               method='first')
    n = (rk <= 10).sum(axis=1)
    ok = n >= 3

    losers = f.where(rk <= 10).mean(axis=1)                    # biggest losers
    rk_w = score.where(el).where(f.notna()).rank(axis=1, ascending=True,
                                                 method='first')
    winners = f.where(rk_w <= 10).mean(axis=1)                 # biggest winners

    s_raw = (-losers)[ok].dropna()
    m = mkt[ok].reindex(s_raw.index)
    s_neu = (-(losers[ok].reindex(s_raw.index) - m)).dropna()
    l_neu = (winners[ok].reindex(s_raw.index) - m).dropna()

    t = s_neu.mean() / s_neu.std() * np.sqrt(len(s_neu))
    print(f'  {str(h)+"b":>8}{len(s_raw):>7}{s_raw.mean()*1e4:>9.1f}'
          f'{m.mean()*1e4:>9.1f}{s_neu.mean()*1e4:>10.1f}{t:>9.2f}'
          f'{s_neu.mean()*1e4/(h*15/60):>8.1f}   {l_neu.mean()*1e4:>+6.1f} bp')

print(f'\n  raw S    = short-the-losers basket, as traded')
print(f'  mkt      = equal-weight universe return over the same bars')
print(f'  neutral  = the short leg minus the market (what a L/S book collects)')
print(f'  long leg = buy-the-winners basket, market-neutral')
print(f'\n  A market-neutral book pays the cost TWICE: {COST*2:.0f} bp per round trip.')
