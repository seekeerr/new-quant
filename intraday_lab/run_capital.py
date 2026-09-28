"""
The long-only same-day strategy, run as an actual book at Rs 1 lakh and Rs 5 lakh.

No basis points. Whole shares only, per-order brokerage, real statutory rates,
slippage inside the fill price, and whatever cash cannot be deployed just sits
there earning nothing.

  entry   10:15, the 5 biggest gainers of the prior 30 minutes
  exit    the closing bar (every alternative exit rule tested worse)
  fills   buy at the entry bar's open +5 bp, sell at the closing price -5 bp

Run on both panels, because they say different things and both are true:
  15m  57 days, Jul-Sep 2026   - the regime where this works
  1h   488 days, Sep 2024 on   - the regime where it does not
"""
import sys, io, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
if __name__ == '__main__':   # importing this module must not touch stdout
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
from intraday_lab import harness_fine as HF

from intraday_lab.groww_costs import leg_cost      # real Groww rate card

SLIP = 0.0005          # 5 bp per side, folded into the fill price


def simulate(interval, capital, tier, topn=5, verbose=False):
    d = HF.load(interval)
    npd, date = HF.bars_per_day(d), d['date']
    C, O = d['close'], d['open']
    pos = date.groupby(date).cumcount()
    entry_pos = {'15m': 4, '1h': 1}[interval]
    lookback = {'15m': 2, '1h': 1}[interval]

    el = HF.eligible(d, drop_first=1, drop_last=0)
    if tier == 'top100':
        liq = HF.liquidity(d)
        el = el & (liq.where(el).rank(axis=1, ascending=False,
                                      method='first') <= 100)
    r = C / O.shift(lookback - 1) - 1
    sc = r.where(HF.bcast(date.shift(lookback - 1) == date, r)).shift(1).where(el)
    last_close = C.groupby(date.values).transform('last')

    cash = float(capital)
    rows = []
    for day in sorted(date.unique()):
        ridx = np.where((date == day).values)[0]
        if len(ridx) < entry_pos + 2:
            continue
        e = ridx[entry_pos]
        ts = C.index[e]
        row = sc.loc[ts].dropna()
        if len(row) < topn:
            continue
        names = list(row.sort_values(ascending=False).index[:topn])

        per = cash / topn
        spent = costs = 0.0
        held = []
        for s in names:
            px = O.iat[e, C.columns.get_loc(s)] * (1 + SLIP)
            if not np.isfinite(px) or px <= 0:
                continue
            n = int(per // px)
            if n <= 0:
                continue
            val = n * px
            spent += val
            costs += leg_cost(val, 'B')
            held.append((s, n, px))
        if not held:
            continue

        proceeds = 0.0
        for s, n, _ in held:
            ex = last_close.iat[e, C.columns.get_loc(s)] * (1 - SLIP)
            if not np.isfinite(ex):
                ex = O.iat[e, C.columns.get_loc(s)]
            val = n * ex
            proceeds += val
            costs += leg_cost(val, 'S')

        pnl = proceeds - spent - costs
        idle = (cash - spent) / cash * 100
        cash += pnl
        rows.append({'day': pd.Timestamp(day), 'pnl': pnl, 'equity': cash,
                     'names': len(held), 'idle_pct': idle, 'costs': costs,
                     'deployed': spent})
    return pd.DataFrame(rows).set_index('day')


def summarise(t, capital, tag):
    if t is None or len(t) < 20:
        print(f'  {tag:<34} — not enough days')
        return
    fin = t.equity.iloc[-1]
    ret = fin / capital - 1
    days = len(t)
    ann = (fin / capital) ** (250 / days) - 1
    dd = (t.equity / t.equity.cummax() - 1).min()
    print(f'  {tag:<34}{days:>6}{t.pnl.mean():>+10,.0f}{fin:>13,.0f}'
          f'{ret*100:>+9.1f}%{ann*100:>+10.1f}%{(t.pnl>0).mean()*100:>7.1f}'
          f'{dd*100:>8.1f}%{t.costs.sum():>12,.0f}{t.idle_pct.mean():>8.1f}%')


def main():
    print('=' * 118)
    print('  LONG-ONLY SAME-DAY, RUN AS A REAL BOOK — whole shares, real costs,'
          ' 5 bp/side slippage')
    print('=' * 118)
    hdr = (f'  {"book":<34}{"days":>6}{"Rs/day":>10}{"final":>13}{"total":>10}'
           f'{"annual":>10}{"win%":>7}{"maxDD":>8}{"costs Rs":>12}{"idle":>9}')
    for interval, label in (('15m', 'Jul-Sep 2026 (the good regime)'),
                            ('1h', 'Sep 2024 - Sep 2026 (2 years)')):
        print(f'\n  --- {label} ---')
        print(hdr)
        print('  ' + '-' * 114)
        for capital in (100_000, 500_000):
            for tier in ('all', 'top100'):
                t = simulate(interval, capital, tier)
                tag = f'Rs {capital//100000} lakh, universe={tier}'
                summarise(t, capital, tag)

    # a closer look at the Rs 1 lakh / top100 book on the 2-year panel
    print()
    print('=' * 118)
    print('  Rs 1 LAKH, top-100 universe, 2-year panel — year by year')
    print('=' * 118)
    t = simulate('1h', 100_000, 'top100')
    for y, v in t.groupby(t.index.year):
        print(f'  {y}{len(v):>8} days   Rs/day {v.pnl.mean():>+9,.0f}'
              f'   total {v.pnl.sum():>+12,.0f}   costs {v.costs.sum():>10,.0f}')
    print(f'\n  cost as a share of gross turnover: '
          f'{t.costs.sum()/t.deployed.sum()*1e4:.1f} bp per round trip')
    print(f'  average cash left idle: {t.idle_pct.mean():.1f}%')


if __name__ == '__main__':
    main()
