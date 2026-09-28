"""
Capacity test for the two holdout survivors.

Critical because the amihud component RANKS ILLIQUIDITY AS GOOD - it deliberately
buys hard-to-trade names. That is exactly the setup where a backtest fills at
prices a real book could never get. If the edge evaporates with size, it is a
small-money curiosity, not a strategy.
"""
import sys, io
if __name__=='__main__':
    sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace')
import numpy as np, pandas as pd
from research_harness import load_panels, evaluate, champion_scorer
import signals as S

close,high,low,vol,turn=load_panels()
mom,lv=S.momentum(252,21),S.low_vol(252)
cands=[('mom+lv+amihud_.25',S.blend([(mom,.375),(lv,.375),(S.amihud(60)(turn),.25)]),
        dict(n_stocks=10,rebalance='monthly',buffer=20,rank_band=(0,500))),
       ('champion',champion_scorer(),
        dict(n_stocks=10,rebalance='monthly',buffer=20,rank_band=(0,500)))]
rows=[]
for cap in (1e6,1e7,5e7,1e8,5e8):
    for nm,sc,kw in cands:
        for sp in ('discovery','holdout'):
            try:
                m=evaluate(sc,close,high,low,vol,turn,split=sp,capital=cap,label=nm,**kw)
                rows.append(dict(config=nm,capital=cap,split=sp,cagr=m['cagr'],
                                 sharpe=m['sharpe'],maxdd=m['maxdd']))
                print(f'  {nm:<20} Rs{cap:>12,.0f} {sp:<10} CAGR {m["cagr"]*100:6.2f}%  Sh {m["sharpe"]:.2f}',flush=True)
            except Exception as e: print(f'  {nm} {cap} {sp}: ERR {str(e)[:60]}',flush=True)
d=pd.DataFrame(rows); d.to_csv('results/campaign/capacity.csv',index=False)
print('\nHOLDOUT CAGR % vs BOOK SIZE')
print(d[d.split=='holdout'].pivot(index='capital',columns='config',values='cagr').mul(100).round(2).to_string())
