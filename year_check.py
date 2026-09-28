"""Year-by-year of the winner. A strategy carried by one lucky year is not a strategy."""
import sys,io
if __name__=='__main__': sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace')
import numpy as np,pandas as pd
from research_harness import load_panels, evaluate, champion_scorer
import signals as S
close,high,low,vol,turn=load_panels()
mom,lv=S.momentum(252,21),S.low_vol(252)
win=S.blend([(mom,.375),(lv,.375),(S.amihud(60)(turn),.25)])
kw=dict(n_stocks=10,rebalance='monthly',buffer=20,rank_band=(0,500))
res={}
for nm,sc in [('winner',win),('champion',champion_scorer())]:
    parts=[]
    for sp in ('discovery','holdout'):
        m=evaluate(sc,close,high,low,vol,turn,split=sp,label=nm,**kw)
        parts.append(m['returns'])
    res[nm]=pd.concat(parts)
d=pd.DataFrame(res).dropna()
yr=d.groupby(d.index.year).apply(lambda g:(1+g).prod()-1)*100
print('CALENDAR-YEAR RETURNS %  (2022+ = holdout, never used in search)')
print(yr.round(1).to_string())
print()
w=d['winner']; print(f"winner: win-years {int((yr['winner']>0).sum())}/{len(yr)}  "
      f"worst {yr['winner'].min():.1f}%  best {yr['winner'].max():.1f}%")
print(f"beats champion in {int((yr['winner']>yr['champion']).sum())}/{len(yr)} years")
h=d.loc['2022':]
for half,lbl in [(h.loc[:'2024-03'],'holdout H1 22-24Q1'),(h.loc['2024-04':],'holdout H2 24Q2-26')]:
    e=(1+half['winner']).prod()**(252/len(half))-1
    print(f'  {lbl}: CAGR {e*100:.1f}%')
