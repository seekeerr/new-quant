"""
Shared harness for the strategy-discovery campaign.

ONE rule that makes this campaign worth anything:
    You may search as much as you like inside DISCOVERY.
    HOLDOUT is touched ONCE, at the very end, by the handful of finalists.
If you peek at HOLDOUT while searching, the campaign is dead and the numbers
mean nothing. With hundreds of configs tested, the best DISCOVERY result is
guaranteed to be partly luck - HOLDOUT is the only thing that separates a real
edge from a lucky curve.

    DISCOVERY  2012-01-01 .. 2021-12-31   (10 years - search here)
    HOLDOUT    2022-01-01 .. 2026-05-30   (4.4 years - do not look)

Benchmark (NIFTY 500 TRI) CAGR: 13.63% full period.
Frozen champion: Mom+LowVol Top-10, ~17.4% (Top-5 shell).

Usage:
    from research_harness import load_panels, evaluate, CAP
    close, high, low, vol, turn = load_panels()
    m = evaluate(my_scorer, close, high, low, vol, turn, split='discovery')
    print(m['cagr'], m['sharpe'], m['maxdd'])

A "strategy" is just a scorer:
    scorer(close_panel, date, universe) -> pd.Series   (best first, sorted desc)
"""
import sys
import io
import os
import warnings
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
logging.basicConfig(level=logging.ERROR)
for _n in list(logging.root.manager.loggerDict):
    logging.getLogger(_n).setLevel(logging.ERROR)
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd

from config import SystemConfig
from run_program2_smallcap_validation import run_impact_aware_backtest
from run_smallcap_universe import RankBandUniverseBuilder
from run_momentum_lowvol import (make_mom_lowvol_scorer, load_equity_symbols,
                                 VOL_LOOKBACK)
from analytics.metrics import compute_metrics
from data.benchmark import get_benchmark_returns

CACHE = 'data/cache_bhav'
CAP = 1_000_000.0          # Rs 10 lakh default - NOT 1 lakh
BENCH_CAGR = 0.1363

SPLITS = {
    'discovery': ('2012-01-01', '2021-12-31'),
    'holdout':   ('2022-01-01', '2026-05-30'),
    # 'live' extends holdout to the latest cached bar. Still clean out-of-sample
    # (the search only ever saw 2012-2021) - used for showing recent trades.
    'live':      ('2022-01-01', '2026-09-21'),
    'full':      ('2012-01-01', '2026-05-30'),
}


def load_panels(equity_only=True):
    """adj close/high/low + raw volume/turnover, equity symbols only."""
    def rd(n):
        return pd.read_parquet(os.path.join(CACHE, n))
    close = rd('adj_close.parquet')
    high = rd('adj_high.parquet')
    low = rd('adj_low.parquet')
    vol = rd('raw_volume.parquet')
    turn = rd('raw_turnover.parquet')
    if equity_only:
        syms = set(load_equity_symbols())
        keep = [c for c in close.columns if c in syms]
        close, high, low, vol, turn = [p[keep] for p in
                                       (close, high, low, vol, turn)]
    return close, high, low, vol, turn


def load_open():
    """Raw OPEN panel (built by build_open_panel.py) for microstructure work."""
    return pd.read_parquet(os.path.join(CACHE, 'raw_open.parquet'))


# Universe construction (PIT filters + liquidity ranking) is by far the most
# expensive part of a backtest and does NOT depend on the scorer - so one
# builder per (split, rank_band) is shared across every strategy tested. This
# turns a ~75s backtest into ~15s after the first run of that combination.
_UB_CACHE = {}


def get_builder(c, h, l, v, t, cfg, split, rank_band):
    key = (split, rank_band)
    if key not in _UB_CACHE:
        _UB_CACHE[key] = RankBandUniverseBuilder(c, h, l, v, t, cfg.universe,
                                                 rank_band[0], rank_band[1])
    return _UB_CACHE[key]


def evaluate(scorer, close, high, low, vol, turn, *, split='discovery',
             n_stocks=10, rebalance='monthly', buffer=20, capital=CAP,
             rank_band=(0, 500), label='', config=None):
    """
    Run one strategy and return a metrics dict. Slices panels to `split` FIRST,
    so a discovery run physically cannot see holdout data.
    """
    if split not in SPLITS:
        raise ValueError(f'split must be one of {list(SPLITS)}')
    s, e = SPLITS[split]
    c, h, l, v, t = [p.loc[s:e] for p in (close, high, low, vol, turn)]

    cfg = config or SystemConfig()
    # The engine bounds its loop by cfg.backtest.start/end, not by the panel, so
    # a split that runs past the config's end_date would silently stop early
    # (the 'live' split otherwise halted in May while data ran to September).
    cfg.backtest.start_date = s
    cfg.backtest.end_date = e
    ub = get_builder(c, h, l, v, t, cfg, split, rank_band)
    res = run_impact_aware_backtest(
        c, h, l, v, t, n_stocks=n_stocks, rebalance_freq=rebalance,
        buffer=buffer, initial_capital=capital, config=cfg,
        scorer=scorer, universe_builder=ub, label=label or split)

    br = get_benchmark_returns(s, e)
    m = compute_metrics(res['equity_curve'], res['returns'],
                        benchmark_returns=br, trades=res['trades'],
                        total_costs=res['total_costs'],
                        initial_capital=capital)
    eq, rr = res['equity_curve'], res['returns']
    return {
        'label': label, 'split': split,
        'cagr': m.cagr, 'sharpe': m.sharpe_ratio, 'maxdd': m.max_drawdown,
        'calmar': m.cagr / abs(m.max_drawdown) if m.max_drawdown else np.nan,
        'alpha': getattr(m, 'alpha', np.nan),
        'turnover': getattr(m, 'turnover', np.nan),
        'n_trades': len(res['trades']) if res.get('trades') is not None else 0,
        'costs': res['total_costs'],
        'final': float(eq.iloc[-1]), 'n_days': len(rr),
        'equity': eq, 'returns': rr,
        'trades': res.get('trades', []),
        'avg_turnover': res.get('avg_turnover', np.nan),
        'total_rebalances': res.get('total_rebalances', 0),
    }


def rolling_3y_min(returns):
    """Worst 3-year annualised window - the champion's key robustness gate."""
    if returns is None or len(returns) < 756:
        return np.nan
    eq = (1 + returns).cumprod()
    r3 = (eq / eq.shift(756)) ** (1 / 3) - 1
    return float(r3.dropna().min()) if r3.notna().any() else np.nan


def deflated_sharpe(best_sharpe, n_trials, n_obs):
    """
    Haircut a Sharpe for the fact that it is the MAX of `n_trials` searches.
    Expected max Sharpe of n independent zero-edge trials is roughly
    sqrt(2*ln(n)) / sqrt(n_obs) in annualised terms - if your best does not
    clear that, you found noise. Returns (expected_max_under_null, passes).
    """
    if n_trials < 2:
        return 0.0, True
    e_max = np.sqrt(2 * np.log(n_trials)) / np.sqrt(n_obs / 252.0)
    return float(e_max), bool(best_sharpe > e_max)


def summarize(rows, sort_by='cagr'):
    """rows: list of metric dicts -> tidy DataFrame, no equity curves."""
    keep = ['label', 'split', 'cagr', 'sharpe', 'maxdd', 'calmar',
            'n_trades', 'final']
    d = pd.DataFrame([{k: r.get(k) for k in keep} for r in rows])
    return d.sort_values(sort_by, ascending=False).reset_index(drop=True)


def champion_scorer():
    """The frozen benchmark strategy every candidate must beat."""
    return make_mom_lowvol_scorer(0.5, VOL_LOOKBACK)


if __name__ == '__main__':
    close, high, low, vol, turn = load_panels()
    print(f'panels: {close.shape[1]:,} symbols x {close.shape[0]:,} days')
    for sp in ('discovery', 'holdout'):
        m = evaluate(champion_scorer(), close, high, low, vol, turn,
                     split=sp, label='champion')
        print(f'  champion {sp:<10} CAGR {m["cagr"]*100:6.2f}%  '
              f'Sharpe {m["sharpe"]:.2f}  MaxDD {m["maxdd"]*100:6.1f}%  '
              f'roll3y-min {rolling_3y_min(m["returns"])*100 if not np.isnan(rolling_3y_min(m["returns"])) else float("nan"):.1f}%')
