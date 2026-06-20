"""
ROAD 2 — STEP 1: SMARTER (RESIDUAL / BETA-ADJUSTED) MOMENTUM.

Plain idea: rank a stock by how much it rose FOR ITS OWN REASONS, not because the
whole market lifted it. Concretely, residual momentum = the stock's 12-1 return MINUS
(its market beta x the market's 12-1 return). This strips out high-beta names that
merely rode the market up and then crash hardest at turns (the momentum-crash driver).
Price-only, survivorship-free, no new data.

Clean A/B/C/D on the honest bhavcopy universe (quarterly / equal weight / Buffer20 /
Top10 / NET of Indian costs). The ONLY thing that changes is the ranking signal:
  A. PlainMom          - the validated 12-1 momentum.
  B. SmartMom          - residual (beta-adjusted) momentum.
  C. PlainMom + LowVol - the CURRENT BEST (~17.4% CAGR). Reference to beat.
  D. SmartMom + LowVol - the upgrade: residual momentum blended with low volatility.

Success read (stated up front): does SmartMom+LowVol beat PlainMom+LowVol on CAGR
AND/OR risk-adjusted (Sharpe / drawdown), net of costs? Reported plainly, pass or fail.
"""
import sys, io, warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import logging
logging.basicConfig(level=logging.ERROR)
for _n in logging.root.manager.loggerDict:
    logging.getLogger(_n).setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from config import SystemConfig, RESULTS_DIR
from data.benchmark import get_benchmark_returns, get_benchmark_equity_curve
from analytics.metrics import compute_metrics

from run_pure_momentum import compute_12_1_momentum
from run_buffer_experiment import run_buffered_backtest, drawdown_analytics, rolling_3y_cagr
from run_survivorship_validation import TopNTurnoverUniverseBuilder
from run_momentum_lowvol import compute_realized_vol, load_equity_symbols, VOL_LOOKBACK

N_STOCKS, BUFFER, FREQ = 10, 20, "quarterly"
LB, SKIP = 252, 21                       # 12-month formation, skip most-recent month
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"


# ─────────────────────────────────────────────────────────────────────
# SMARTER MOMENTUM  (residual / beta-adjusted)
# ─────────────────────────────────────────────────────────────────────
def compute_residual_momentum(close_panel, date, universe, lookback=LB, skip=SKIP):
    cols = [s for s in universe if s in close_panel.columns]
    prices = close_panel.loc[close_panel.index <= date, cols]
    if len(prices) < lookback + skip + 1:
        return pd.Series(dtype=float)
    recent = prices.iloc[-(lookback + skip):]
    form_p = recent.iloc[:-skip] if skip > 0 else recent      # lookback rows, ending skip days ago
    form_r = form_p.pct_change().iloc[1:]                      # daily returns in formation window
    # keep names with enough valid history in the window
    valid = form_r.notna().sum() >= int(0.8 * len(form_r))
    form_p = form_p.loc[:, valid[valid].index]
    form_r = form_r.loc[:, valid[valid].index]
    if form_r.shape[1] < 2:
        return pd.Series(dtype=float)
    cum_s = form_p.iloc[-1] / form_p.iloc[0] - 1.0            # each stock's 12-1 cumulative return
    m = form_r.mean(axis=1)                                    # equal-weight market proxy (daily)
    mc = m - m.mean()
    var_m = float((mc * mc).sum())
    if var_m <= 0:
        return pd.Series(dtype=float)
    beta = form_r.sub(form_r.mean()).mul(mc, axis=0).sum() / var_m   # per-stock beta to market
    cum_m = float(cum_s.mean())                                # market's 12-1 cumulative return
    score = cum_s - beta * cum_m                               # stock-specific (residual) momentum
    return score.replace([np.inf, -np.inf], np.nan).dropna().sort_values(ascending=False)


def make_blend_scorer(mom_fn, w_mom=0.5, vol_lookback=VOL_LOOKBACK):
    """Blend a momentum signal with low volatility on a common percentile scale."""
    def scorer(close_panel, date, universe):
        mom = mom_fn(close_panel, date, universe)
        vol = compute_realized_vol(close_panel, date, universe, vol_lookback)
        common = mom.index.intersection(vol.index)
        if len(common) < 2:
            return pd.Series(dtype=float)
        mom_pct = mom[common].rank(pct=True)
        lowvol_pct = (-vol[common]).rank(pct=True)
        blend = w_mom * mom_pct + (1.0 - w_mom) * lowvol_pct
        return blend.sort_values(ascending=False)
    return scorer


def main():
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital
    start, end = cfg.backtest.start_date, cfg.backtest.end_date

    print("=" * 92)
    print("  ROAD 2 / STEP 1 — SMARTER MOMENTUM (residual) on the honest universe".center(92))
    print("=" * 92)

    bench_ret = get_benchmark_returns(start, end)
    print("\nLoading survivorship-free bhavcopy panels ...")
    ac = pd.read_parquet(CACHE_BHAV / "adj_close.parquet")
    ah = pd.read_parquet(CACHE_BHAV / "adj_high.parquet")
    al = pd.read_parquet(CACHE_BHAV / "adj_low.parquet")
    av = pd.read_parquet(CACHE_BHAV / "raw_volume.parquet")
    at = pd.read_parquet(CACHE_BHAV / "raw_turnover.parquet")
    eq_syms = load_equity_symbols()
    if eq_syms is not None:
        keep = [c for c in ac.columns if c in eq_syms]
        ac, ah, al, av, at = (p[keep] for p in (ac, ah, al, av, at))
        print(f"  equity-only universe: {len(keep)} symbols")
    builder = TopNTurnoverUniverseBuilder(ac, ah, al, av, at, cfg.universe, max_size=500)

    specs = [
        ("A. PlainMom",          compute_12_1_momentum),
        ("B. SmartMom",          compute_residual_momentum),
        ("C. PlainMom+LowVol",   make_blend_scorer(compute_12_1_momentum, 0.5)),
        ("D. SmartMom+LowVol",   make_blend_scorer(compute_residual_momentum, 0.5)),
    ]

    rows = []
    for name, scorer in specs:
        print(f"\n  running {name} (Top{N_STOCKS}, net) ...")
        net = run_buffered_backtest(
            ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=FREQ, buffer=BUFFER,
            initial_capital=cap, config=cfg, apply_costs=True, label=name,
            scorer=scorer, universe_builder=builder)
        m = compute_metrics(net["equity_curve"], net["returns"], benchmark_returns=bench_ret,
                            trades=net["trades"], total_costs=net["total_costs"], initial_capital=cap)
        extra = drawdown_analytics(net["equity_curve"])
        roll = rolling_3y_cagr(net["returns"])
        rows.append({"name": name, "cagr": m.cagr, "max_dd": m.max_drawdown,
                     "sharpe": m.sharpe_ratio, "calmar": m.calmar_ratio,
                     "vol": m.annualised_volatility, "final": net["equity_curve"].iloc[-1],
                     "tuw": extra["time_underwater_pct"],
                     "roll3y_min": roll.min() if not roll.empty else np.nan,
                     "eq": net["equity_curve"]})
        print(f"    CAGR {m.cagr:.2%} | MaxDD {m.max_drawdown:.2%} | Sharpe {m.sharpe_ratio:.2f}")

    _eq = rows[0]["eq"]
    bstart, bend = str(_eq.index[0].date()), str(_eq.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, cap)
    bm_cagr = compute_metrics(bench_eq, initial_capital=cap).cagr if not bench_eq.empty else np.nan

    L = []; w = L.append
    w("=" * 92)
    w("  SMARTER MOMENTUM — HONEST UNIVERSE, Top10 / quarterly / Buffer20, NET of costs".center(92))
    w("=" * 92)
    w(f"Period: {bstart}..{bend}   NIFTY500(px) CAGR {bm_cagr:.2%}   (true TRI ~ {bm_cagr+0.013:.2%})")
    w("")
    w(f"{'Variant':<22}{'CAGR':>9}{'MaxDD':>9}{'Sharpe':>8}{'Calmar':>8}{'Vol':>8}{'Worst3yr':>10}{'FinalRs':>14}")
    w("-" * 92)
    for r in rows:
        w(f"{r['name']:<22}{r['cagr']:>8.1%}{r['max_dd']:>9.1%}{r['sharpe']:>8.2f}"
          f"{r['calmar']:>8.2f}{r['vol']:>8.1%}{r['roll3y_min']:>10.1%}{r['final']:>14,.0f}")
    w("-" * 92)
    base = next(r for r in rows if r["name"].startswith("C."))      # current best
    new = next(r for r in rows if r["name"].startswith("D."))       # the upgrade
    w(f"Reference (current best, C): CAGR {base['cagr']:.1%}, Sharpe {base['sharpe']:.2f}, MaxDD {base['max_dd']:.1%}")
    w(f"Upgrade (D = SmartMom+LowVol): CAGR {new['cagr']:.1%}, Sharpe {new['sharpe']:.2f}, MaxDD {new['max_dd']:.1%}")
    dcagr = new["cagr"] - base["cagr"]; dsharpe = new["sharpe"] - base["sharpe"]; ddd = new["max_dd"] - base["max_dd"]
    verdict = "HELPS" if (dcagr > 0.005 or dsharpe > 0.05) else "no meaningful improvement"
    w(f"=> Smarter momentum {verdict}:  dCAGR {dcagr:+.1%} | dSharpe {dsharpe:+.2f} | "
      f"dMaxDD {ddd:+.1%} ({'shallower' if ddd>0 else 'deeper'})")
    w("=" * 92)

    txt = "\n".join(L)
    print("\n" + txt)
    rdir = RESULTS_DIR / "smart_momentum"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "report.txt").write_text(txt, encoding="utf-8")
    pd.DataFrame([{k: v for k, v in r.items() if k != "eq"} for r in rows]).to_csv(
        rdir / "comparison.csv", index=False)
    print(f"\n  Saved to {rdir}/")


if __name__ == "__main__":
    main()
