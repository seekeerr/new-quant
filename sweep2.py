"""
Wave 2: sleeve ensembles, capital scaling, and the untested microstructure family.

The ensemble part exploits a big asymmetry: running a sleeve's backtest costs
~10s, but once you hold its daily RETURN series, evaluating a weight combination
costs microseconds. So we run ~12 sleeves once and then search thousands of
weightings for free.

What return-level blending IGNORES, and which is stated in the report rather
than hidden:
  1. the cost of rebalancing BETWEEN sleeves,
  2. overlap - two sleeves often hold the same stock, so the combined book is
     more concentrated (and less diversified) than the weights suggest.
Both make the true combined result worse than the blended number.

    py sweep2.py ensemble
    py sweep2.py capital
    py sweep2.py micro
"""
import sys
import io
import os
import time
import itertools

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')

import numpy as np
import pandas as pd

from research_harness import (load_panels, load_open, evaluate,
                              champion_scorer, rolling_3y_min, CAP)
import signals as S

OUT = 'results/campaign'
os.makedirs(OUT, exist_ok=True)


def _stats(r):
    """CAGR / Sharpe / MaxDD from a daily return series."""
    if r is None or len(r) < 100:
        return dict(cagr=np.nan, sharpe=np.nan, maxdd=np.nan)
    eq = (1 + r).cumprod()
    yrs = len(r) / 252.0
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    sh = r.mean() / r.std() * np.sqrt(252) if r.std() else np.nan
    dd = (eq / eq.cummax() - 1).min()
    return dict(cagr=float(cagr), sharpe=float(sh), maxdd=float(dd))


# ── sleeves ──────────────────────────────────────────────────────────────

def sleeve_defs(close, high, low, vol, turn):
    ch = champion_scorer()
    mom = S.momentum(252, 21)
    def b(**k):
        # defaults first, then overrides - dict(n_stocks=10, **k) would raise
        # a duplicate-keyword TypeError whenever k overrides a default.
        d = dict(n_stocks=10, rebalance='monthly', buffer=20,
                 rank_band=(0, 500))
        d.update(k)
        return d
    return [
        ('champ',        ch,                      b()),
        ('champ_n5',     ch,                      b(n_stocks=5)),
        ('champ_n20',    ch,                      b(n_stocks=20)),
        ('champ_qtr',    ch,                      b(rebalance='quarterly')),
        ('champ_large',  ch,                      b(rank_band=(0, 100))),
        ('champ_tail',   ch,                      b(rank_band=(250, 750))),
        ('champ_mid',    ch,                      b(rank_band=(100, 500))),
        ('mom_only',     mom,                     b()),
        ('mom_fast',     S.momentum(126, 0),      b()),
        ('lowvol',       S.low_vol(252),          b()),
        ('prox52',       S.prox_52wh(252),        b()),
        ('lowmax',       S.low_max_ret(21),       b()),
        ('momcons',      S.momentum_consistency(252), b()),
        ('amihud',       S.amihud(60)(turn),      b()),
    ]


def run_ensemble():
    close, high, low, vol, turn = load_panels()
    sl = sleeve_defs(close, high, low, vol, turn)

    rets, rows = {}, []
    for name, sc, kw in sl:
        t0 = time.time()
        try:
            m = evaluate(sc, close, high, low, vol, turn, split='discovery',
                         label=name, **kw)
            rets[name] = m['returns']
            rows.append(dict(sleeve=name, **_stats(m['returns'])))
            print(f'  sleeve {name:<14} CAGR {m["cagr"]*100:6.2f}%  '
                  f'Sh {m["sharpe"]:.2f}  ({time.time()-t0:.0f}s)', flush=True)
        except Exception as e:
            print(f'  sleeve {name}: ERROR {str(e)[:70]}', flush=True)
    R = pd.DataFrame(rets).dropna(how='all').fillna(0.0)
    pd.DataFrame(rows).to_csv(f'{OUT}/ens_sleeves.csv', index=False)
    R.corr().round(3).to_csv(f'{OUT}/ens_corr.csv')
    print('\nsleeve return correlations written')

    names = list(R.columns)
    out = []
    # 1/N over every subset size 2..5 - naive equal weight is a hard baseline
    for k in (2, 3, 4, 5):
        for combo in itertools.combinations(names, k):
            r = R[list(combo)].mean(axis=1)
            out.append(dict(kind=f'eq{k}', sleeves='+'.join(combo), **_stats(r)))
    # weighted 2- and 3-way grids
    for combo in itertools.combinations(names, 2):
        for w in np.arange(0.1, 1.0, 0.1):
            r = R[combo[0]] * w + R[combo[1]] * (1 - w)
            out.append(dict(kind='w2', sleeves=f'{combo[0]}:{w:.1f}+{combo[1]}',
                            **_stats(r)))
    for combo in itertools.combinations(names, 3):
        for w1 in (0.2, 0.34, 0.5):
            for w2 in (0.2, 0.33, 0.5):
                if w1 + w2 >= 1:
                    continue
                w3 = 1 - w1 - w2
                r = (R[combo[0]] * w1 + R[combo[1]] * w2 + R[combo[2]] * w3)
                out.append(dict(
                    kind='w3',
                    sleeves=f'{combo[0]}:{w1:.2f}+{combo[1]}:{w2:.2f}+{combo[2]}:{w3:.2f}',
                    **_stats(r)))
    # inverse-vol across all sleeves, point-in-time (60d trailing, shifted)
    iv = 1.0 / R.rolling(60).std().shift(1)
    iv = iv.div(iv.sum(axis=1), axis=0)
    out.append(dict(kind='invvol', sleeves='ALL', **_stats((R * iv).sum(axis=1))))
    # trailing-12m-Sharpe weighting (momentum of strategies), point-in-time
    tr = R.rolling(252).mean().shift(1) / R.rolling(252).std().shift(1)
    tw = tr.clip(lower=0)
    tw = tw.div(tw.sum(axis=1).replace(0, np.nan), axis=0).fillna(1 / len(names))
    out.append(dict(kind='sharpe_mom', sleeves='ALL', **_stats((R * tw).sum(axis=1))))

    d = pd.DataFrame(out).sort_values('cagr', ascending=False)
    d.to_csv(f'{OUT}/ens_combos.csv', index=False)
    print(f'\nevaluated {len(d):,} allocations')
    print('\nTOP 15 BY CAGR')
    print(d.head(15).to_string(index=False))
    print('\nTOP 10 BY SHARPE')
    print(d.sort_values('sharpe', ascending=False).head(10).to_string(index=False))


def run_capital():
    """How the best simple configs decay with book size - the user explicitly
    does NOT want this tuned to Rs 1 lakh."""
    close, high, low, vol, turn = load_panels()
    ch = champion_scorer()
    cands = [
        ('champ_n10', ch, dict(n_stocks=10, rebalance='monthly', buffer=20,
                               rank_band=(0, 500))),
        ('champ_n20', ch, dict(n_stocks=20, rebalance='monthly', buffer=20,
                               rank_band=(0, 500))),
        ('champ_large', ch, dict(n_stocks=10, rebalance='monthly', buffer=20,
                                 rank_band=(0, 100))),
    ]
    rows = []
    for cap in (1e5, 1e6, 1e7, 5e7, 1e8, 5e8):
        for nm, sc, kw in cands:
            try:
                m = evaluate(sc, close, high, low, vol, turn, split='discovery',
                             capital=cap, label=f'{nm}@{cap:.0e}', **kw)
                rows.append(dict(config=nm, capital=cap, cagr=m['cagr'],
                                 sharpe=m['sharpe'], maxdd=m['maxdd']))
                print(f'  {nm:<12} Rs{cap:>12,.0f}  CAGR {m["cagr"]*100:6.2f}%  '
                      f'Sh {m["sharpe"]:.2f}', flush=True)
            except Exception as e:
                print(f'  {nm} @ {cap}: ERROR {str(e)[:60]}', flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(f'{OUT}/capital_ladder.csv', index=False)
    print('\nCAGR vs capital (pivot)')
    print(d.pivot(index='capital', columns='config', values='cagr').mul(100).round(2).to_string())


def run_micro():
    """Overnight vs intraday decomposition - the family this repo's own audit
    records as never tested.

    Corporate-action safety: adjusted close is split/bonus adjusted, raw open is
    NOT. Mixing them across a day invents huge fake returns. So intraday is
    computed from RAW open/close within the SAME day (adjustment cancels), and
    overnight is derived as (1+total_adj) / (1+intraday) - 1, which never
    divides a raw price by an adjusted one.
    """
    close, high, low, vol, turn = load_panels()
    opn = load_open()
    rawc = pd.read_parquet('data/cache_bhav/raw_close.parquet')
    cols = [c for c in close.columns if c in opn.columns and c in rawc.columns]
    close2 = close[cols]
    o = opn.reindex(index=close2.index, columns=cols)
    rc = rawc.reindex(index=close2.index, columns=cols)

    intraday = (rc / o - 1).replace([np.inf, -np.inf], np.nan)
    total = close2.pct_change()
    overnight = ((1 + total) / (1 + intraday) - 1)
    # residual corporate-action artifacts
    overnight = overnight.where(overnight.abs() < 0.25)
    intraday = intraday.where(intraday.abs() < 0.25)
    print(f'  intraday  mean {intraday.stack().mean()*1e4:+.2f} bp/day')
    print(f'  overnight mean {overnight.stack().mean()*1e4:+.2f} bp/day')

    def cum_scorer(panel, lb, sign=1):
        def sc(c, date, universe):
            colsu = [s for s in universe if s in panel.columns]
            if not colsu:
                return pd.Series(dtype=float)
            h = panel.loc[panel.index <= date, colsu].tail(lb)
            if len(h) < lb // 2:
                return pd.Series(dtype=float)
            return S._out(sign * h.sum())
        return sc

    base = dict(n_stocks=10, rebalance='monthly', buffer=20, rank_band=(0, 500))
    cfgs = []
    for lb in (21, 63, 126, 252):
        cfgs.append((f'overnight_mom_{lb}', cum_scorer(overnight, lb, 1), base))
        cfgs.append((f'intraday_mom_{lb}', cum_scorer(intraday, lb, 1), base))
        cfgs.append((f'intraday_rev_{lb}', cum_scorer(intraday, lb, -1), base))
    diff = overnight - intraday
    for lb in (63, 252):
        cfgs.append((f'on_minus_id_{lb}', cum_scorer(diff, lb, 1), base))

    from sweep import run_batch
    run_batch('micro', cfgs)


if __name__ == '__main__':
    w = sys.argv[1] if len(sys.argv) > 1 else 'ensemble'
    {'ensemble': run_ensemble, 'capital': run_capital, 'micro': run_micro}[w]()
