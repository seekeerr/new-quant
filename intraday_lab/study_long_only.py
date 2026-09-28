"""
LONG-ONLY, same day: buy in the morning, sell before close. No shorting.

This is the cheapest possible shape - ONE round trip a day, so 21 bp once,
not 63 - and the longest possible holding, so it collects the most of the
~6 bp/hour accrual. If anything intraday works, it is this.

Two things it has to beat:
  1. the 21 bp round trip
  2. the market's own open-to-close drift, which is what you get for free by
     buying a random eligible stock. If the drift is negative, a long-only
     book starts in a hole before any signal is applied.
"""
import sys, io, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from intraday_lab import harness_fine as H
from intraday_lab.agent_fine import signals   # this rewraps stdout; re-wrap after
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

COST = 21.0
d = H.load('15m')
npd, date, C, O = H.bars_per_day(d), d['date'], d['close'], d['open']
bar = pd.Series(range(len(C.index)), index=C.index)
pos = date.groupby(date).cumcount()

liq = H.liquidity(d)
el_all = H.eligible(d, drop_first=1, drop_last=0)
tiers = {'all': el_all,
         'top100': el_all & (liq.where(el_all).rank(axis=1, ascending=False,
                                                    method='first') <= 100)}

# exit: the close of the day's LAST bar, broadcast back onto every bar
last_close = C.groupby(date.values).transform('last')

print('=' * 92)
print('  THE FREE BASELINE — what a random eligible stock does, buy-to-close')
print('=' * 92)
print(f'  {"buy at":>8}{"hold h":>9}{"days":>7}{"avg stock":>12}{"after cost":>12}')
print('  ' + '-' * 88)
entry_pos = [1, 2, 3, 4, 6, 8, 12]
for ep in entry_pos:
    m = (pos == ep).values
    ent = O[m]
    ex = last_close[m]
    r = (ex / ent - 1).where(el_all[m])
    hrs = (npd - ep) * 15 / 60
    daily = r.mean(axis=1).dropna()
    tod = C.index[np.where(m)[0][0]].strftime('%H:%M')
    print(f'  {tod:>8}{hrs:>8.1f}h{len(daily):>7}'
          f'{daily.mean()*1e4:>+11.1f}bp{daily.mean()*1e4-COST:>+11.1f}bp')

sig = signals(d)
rows = []
for ep in entry_pos:
    m = (pos == ep).values
    idx = C.index[m]
    hrs = (npd - ep) * 15 / 60
    ent = O.loc[idx]
    ex = last_close.loc[idx]
    fwd_day = ex / ent - 1
    for tname, el in tiers.items():
        e = el.loc[idx]
        for sname, s in sig.items():
            # signal must be known BEFORE the entry bar's open -> use prior bar
            sc = s.shift(1).loc[idx].where(e).where(fwd_day.notna())
            for topn in (5, 10, 20):
                rk = sc.rank(axis=1, ascending=False, method='first')
                sel = rk <= topn
                n = sel.sum(axis=1)
                b = fwd_day.where(sel).mean(axis=1)[n >= 3].dropna()
                if len(b) < 40:
                    continue
                mid = b.index[len(b) // 2]
                a, c = b[b.index <= mid], b[b.index > mid]
                mkt = fwd_day.where(e).mean(axis=1).reindex(b.index)
                rows.append({
                    'label': f'{sname}|{idx[0].strftime("%H:%M")}|{tname}',
                    'topn': topn, 'days': len(b), 'hrs': hrs,
                    'gross_bp': round(b.mean() * 1e4, 2),
                    'net_bp': round(b.mean() * 1e4 - COST, 2),
                    'vs_mkt': round((b.mean() - mkt.mean()) * 1e4, 2),
                    'hit': round((b > 0).mean() * 100, 1),
                    'tstat': round(b.mean() / b.std() * np.sqrt(len(b)), 2),
                    'h1': round(a.mean() * 1e4, 2), 'h2': round(c.mean() * 1e4, 2),
                    'consistent': bool((a.mean() > 0) == (c.mean() > 0))})

t = pd.DataFrame(rows).sort_values('gross_bp', ascending=False)
print(f'\n{"="*92}')
print(f'  LONG-ONLY BUY-AND-SELL-SAME-DAY   ({len(t)} configs)   cost {COST} bp ONCE')
print(f'{"="*92}')
print(f'  {"strategy":<34}{"N":>4}{"days":>6}{"hrs":>6}{"gross":>8}{"net":>8}'
      f'{"vs mkt":>8}{"hit%":>7}{"t":>7}{"H1":>8}{"H2":>8}')
print('  ' + '-' * 88)
for _, r in t.head(20).iterrows():
    f = '' if r.consistent else ' *flips*'
    print(f"  {r.label:<34}{int(r.topn):>4}{int(r.days):>6}{r.hrs:>6.1f}"
          f"{r.gross_bp:>8.1f}{r.net_bp:>8.1f}{r.vs_mkt:>8.1f}{r.hit:>7.1f}"
          f"{r.tstat:>7.2f}{r.h1:>8.1f}{r.h2:>8.1f}{f}")

t.to_csv(os.path.join(H.OUT, 'long_only_sameday.csv'), index=False)
print(f'\n  best gross       : {t.gross_bp.max():.1f} bp   (cost {COST})')
print(f'  net-positive     : {int((t.net_bp>0).sum())} of {len(t)}')
print(f'  ...both halves agreeing: {int(((t.net_bp>0)&t.consistent).sum())}')
print(f'  noise bar N={len(t)}: expected max |t| = {np.sqrt(2*np.log(len(t))):.2f}'
      f'   best |t| = {t.tstat.abs().max():.2f}')
