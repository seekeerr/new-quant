"""
Extract the actual trade history of the winning strategy, so the mechanics can
be inspected rather than taken on trust.

Produces:
  * every BUY / SELL with date, price, value and cost
  * the portfolio held after each monthly rebalance
  * realised round-trips (entry -> exit) with holding period and P&L
  * per-quarter activity: how many trades, what turnover, what return

Period: 2022-01-01 -> latest cached bar (2026-09-21). All of it is out of
sample - the search only ever saw 2012-2021.
"""
import sys
import io
import os

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')

import numpy as np
import pandas as pd

from research_harness import load_panels, evaluate
import signals as S

OUT = 'results/campaign'
CAP = 10_000_000.0        # Rs 1 crore - the size the strategy is meant for


def winner():
    mom, lv = S.momentum(252, 21), S.low_vol(252)
    close, high, low, vol, turn = load_panels()
    return S.blend([(mom, .375), (lv, .375), (S.amihud(60)(turn), .25)])


def main():
    close, high, low, vol, turn = load_panels()
    sc = winner()
    m = evaluate(sc, close, high, low, vol, turn, split='live', capital=CAP,
                 n_stocks=10, rebalance='monthly', buffer=20,
                 rank_band=(0, 500), label='winner')

    tr = pd.DataFrame(m['trades'])
    tr['date'] = pd.to_datetime(tr['date'])
    tr = tr.sort_values('date').reset_index(drop=True)
    tr.to_csv(f'{OUT}/winner_trades.csv', index=False)

    eq = m['equity']
    print('=' * 88)
    print(f'  WINNER - live trade extract   Rs {CAP:,.0f} book   '
          f'{eq.index[0]:%Y-%m-%d} .. {eq.index[-1]:%Y-%m-%d}')
    print(f'  CAGR {m["cagr"]*100:.2f}%   Sharpe {m["sharpe"]:.2f}   '
          f'MaxDD {m["maxdd"]*100:.1f}%   final Rs {m["final"]:,.0f}')
    print(f'  {len(tr):,} trades over {m["total_rebalances"]} rebalances   '
          f'avg turnover/rebalance {m["avg_turnover"]*100:.1f}%')
    print('=' * 88)

    # ---- reconstruct holdings after each rebalance date ----
    pos = {}
    snaps = []
    for d, g in tr.groupby('date'):
        for _, r in g.iterrows():
            if r['side'] == 'BUY':
                pos[r['symbol']] = pos.get(r['symbol'], 0) + r['shares']
            else:
                pos[r['symbol']] = pos.get(r['symbol'], 0) - r['shares']
                if pos[r['symbol']] <= 0:
                    pos.pop(r['symbol'], None)
        snaps.append({'date': d, 'n': len(pos),
                      'holdings': ', '.join(sorted(pos))})
    snap = pd.DataFrame(snaps)
    snap.to_csv(f'{OUT}/winner_holdings.csv', index=False)

    # ---- realised round trips (FIFO by symbol) ----
    lots, closed = {}, []
    for _, r in tr.iterrows():
        s = r['symbol']
        if r['side'] == 'BUY':
            lots.setdefault(s, []).append([r['date'], r['shares'], r['price']])
        else:
            q = r['shares']
            while q > 0 and lots.get(s):
                ed, eq_, ep = lots[s][0]
                take = min(q, eq_)
                closed.append({
                    'symbol': s, 'entry': ed, 'exit': r['date'],
                    'days': (r['date'] - ed).days, 'shares': take,
                    'entry_px': ep, 'exit_px': r['price'],
                    'ret_pct': (r['price'] / ep - 1) * 100,
                    'pnl': take * (r['price'] - ep),
                })
                q -= take
                lots[s][0][1] -= take
                if lots[s][0][1] <= 0:
                    lots[s].pop(0)
                if not lots[s]:
                    lots.pop(s)
    rt = pd.DataFrame(closed)
    rt.to_csv(f'{OUT}/winner_roundtrips.csv', index=False)

    print('\n  HOLDING PERIOD (closed round trips)')
    print(f'    round trips      : {len(rt):,}')
    print(f'    median hold      : {rt["days"].median():.0f} calendar days '
          f'(~{rt["days"].median()/30.4:.1f} months)')
    print(f'    mean hold        : {rt["days"].mean():.0f} days')
    print(f'    held > 6 months  : {(rt["days"]>182).mean()*100:.0f}%')
    print(f'    held > 12 months : {(rt["days"]>365).mean()*100:.0f}%')
    print(f'    win rate         : {(rt["ret_pct"]>0).mean()*100:.0f}%')
    print(f'    avg win / avg loss: {rt[rt.ret_pct>0].ret_pct.mean():.1f}% / '
          f'{rt[rt.ret_pct<=0].ret_pct.mean():.1f}%')

    # ---- per-quarter activity ----
    tr['q'] = tr['date'].dt.to_period('Q')
    qa = tr.groupby('q').agg(trades=('symbol', 'size'),
                             buys=('side', lambda s: (s == 'BUY').sum()),
                             sells=('side', lambda s: (s == 'SELL').sum()),
                             value=('value', 'sum'),
                             cost=('cost', 'sum'))
    qr = eq.resample('QE').last().pct_change().mul(100)
    qr.index = qr.index.to_period('Q')
    qa['ret_pct'] = qr
    qa.to_csv(f'{OUT}/winner_quarters.csv')
    print('\n  PER-QUARTER ACTIVITY (last 10)')
    print(f'    {"quarter":<10}{"trades":>8}{"buys":>7}{"sells":>7}'
          f'{"traded Rs":>14}{"costs Rs":>11}{"return":>9}')
    for q, r in qa.tail(10).iterrows():
        rp = f'{r.ret_pct:+.1f}%' if pd.notna(r.ret_pct) else '   n/a'
        print(f'    {str(q):<10}{int(r.trades):>8}{int(r.buys):>7}'
              f'{int(r.sells):>7}{r.value:>14,.0f}{r.cost:>11,.0f}{rp:>9}')

    print('\n  LAST 6 REBALANCES - what was held')
    for _, r in snap.tail(6).iterrows():
        print(f'    {r["date"]:%Y-%m-%d} ({r.n:2d}): {r.holdings}')

    print('\n  10 BIGGEST WINNERS (closed)')
    for _, r in rt.nlargest(10, 'ret_pct').iterrows():
        print(f'    {r.symbol:<13}{r.entry:%Y-%m-%d} -> {r.exit:%Y-%m-%d} '
              f'{r.days:>5}d  {r.ret_pct:>+8.1f}%  Rs {r.pnl:>+12,.0f}')
    print('\n  10 BIGGEST LOSERS (closed)')
    for _, r in rt.nsmallest(10, 'ret_pct').iterrows():
        print(f'    {r.symbol:<13}{r.entry:%Y-%m-%d} -> {r.exit:%Y-%m-%d} '
              f'{r.days:>5}d  {r.ret_pct:>+8.1f}%  Rs {r.pnl:>+12,.0f}')
    print(f'\n  saved -> {OUT}/winner_{{trades,holdings,roundtrips,quarters}}.csv')


if __name__ == '__main__':
    main()
