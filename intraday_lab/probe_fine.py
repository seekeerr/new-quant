"""First look at the 15m panel: shape, the volume defect, and the size of the
per-bar move a signal would have to predict."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from intraday_lab import harness_fine as H

d = H.load('15m')
C, V, O = d['close'], d['volume'], d['open']
print(f'shape {C.shape}  days {d["date"].nunique()}  bars/day {H.bars_per_day(d)}')
print(f'range {C.index.min()} .. {C.index.max()}')

tod = d['tod']
print('\nper time-of-day: volume==0 share, and cross-sec median |bar return|')
r = (C / O - 1).abs()
for t in sorted(tod.unique()):
    m = (tod == t).values
    z = (V[m] == 0).mean().mean() * 100
    print(f'  {t}   vol==0 {z:5.1f}%   |ret| {r[m].median().median()*1e4:6.1f} bp'
          f'   nan {C[m].isna().mean().mean()*100:5.1f}%')

fwd = H.forward(d, h=1)
el = H.eligible(d)
print(f'\ntradeable bar-symbol cells: {int((el & fwd.notna()).sum().sum()):,}'
      f'  ({(el & fwd.notna()).sum(axis=1).mean():.0f} names/bar)')
f = fwd.where(el)
print(f'next-bar open->open return: sd {f.stack().std()*1e4:.1f} bp, '
      f'mean {f.stack().mean()*1e4:+.2f} bp')
print(f'cost floor 21 bp = {21/(f.stack().std()*1e4):.2f} sd of a single bar move')
