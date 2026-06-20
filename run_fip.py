"""
FROG-IN-THE-PAN (FIP) FACTOR — A/B/C/D on the honest (survivorship-free) universe.

NEW FACTOR (the only thing introduced):
    Frog-in-the-Pan (information-discreteness proxy)
        FIP score = percentile(12-1 momentum) + percentile(consistency)
        consistency = fraction of POSITIVE daily returns during the 12-1 momentum
                      formation window [T-252, T-21]
    Higher = better. Among stocks with similar momentum, this prefers those whose
    return was accumulated through MANY SMALL up-days (continuous information) over
    those built on a FEW LARGE jumps (discrete information). Price-only,
    survivorship-free, no new data — same close panel every scorer here uses.

Why this is worth testing (Da, Gurun & Warachka 2014, RFS, "Frog in the Pan"):
momentum delivered via continuous information persists, while momentum from discrete
jumps reverses. This is a momentum-QUALITY refinement that was NOT covered by the
earlier residual-momentum test (which adjusted for beta, not path smoothness).

FROZEN SHELL — reused EXACTLY as-is, nothing tuned or modified:
  - Backtest engine ........ run_buffered_backtest (run_buffer_experiment.py)
  - Universe ............... survivorship-free bhavcopy, top-500 by liquidity, PIT,
                             equity-only (ISIN 'INE') — TopNTurnoverUniverseBuilder
  - Costs .................. full Indian delivery cost model (NET of costs)
  - Rebalance frequency .... quarterly
  - Buffer ................. Buffer20
  - Position sizing ........ Top10, equal weight, whole-share rounding
  - Execution .............. identical (signal on rebalance date, engine mechanics)

The momentum leg of FIP IS the existing validated 12-1 momentum (compute_12_1_momentum).
The blend (C and D) is the validated champion's make_blend_scorer with w_mom = 0.5.
C and D differ from each other ONLY in the ranking leg (12-1 momentum vs FIP), so the
comparison isolates the factor and nothing else.

FOUR VARIANTS (Top10 / quarterly / Buffer20 / NET):
  A. Momentum          — validated 12-1 momentum (reference baseline)
  B. Frog-in-the-Pan   — the new momentum-quality factor, standalone
  C. Mom + LowVol      — the CURRENT VALIDATED CHAMPION (the bar to beat)
  D. FIP + LowVol      — the candidate upgrade

PRE-REGISTERED SUCCESS CRITERION (stated before running):
  Variant D improves Sharpe AND/OR CAGR vs the champion C WITHOUT materially
  worsening drawdown. "Materially worse" is fixed up front as MaxDD > 3.0 pts deeper.

VALIDATION (no parameter search anywhere):
  - Split-sample  : first half vs second half of the realized span, per variant.
  - Rolling window: rolling 3-year CAGR (min/median/max) + D-vs-C head-to-head.
  - Concentration : the SAME four variants at Top3 / Top5 / Top10, as a robustness
                    read only. Top10 stays the headline; N is NOT optimized.

NOTE: the benchmark CSV date-parse bug (which previously corrupted beta/alpha) was
repaired in data/benchmark.py, so Beta and Jensen's Alpha here are valid.

Outputs (results/factor_fip/): comparison.csv, concentration.csv, report.txt,
report.png, WALKTHROUGH.md.
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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

from config import SystemConfig, RESULTS_DIR
from data.benchmark import get_benchmark_returns, get_benchmark_equity_curve
from analytics.metrics import compute_metrics, compute_rolling_metrics

# ── Reused EXACTLY as-is (no edits to any of these) ──
from run_pure_momentum import compute_12_1_momentum
from run_buffer_experiment import (
    run_buffered_backtest, drawdown_analytics, rolling_3y_cagr, annual_returns,
)
from run_survivorship_validation import TopNTurnoverUniverseBuilder
from run_momentum_lowvol import compute_realized_vol, load_equity_symbols, VOL_LOOKBACK
from run_smart_momentum import make_blend_scorer   # validated 50/50 momentum+lowvol blend

# Frozen champion shell.
HEADLINE_N, BUFFER, FREQ = 10, 20, "quarterly"
GRID_N = [3, 5, 10]                     # concentration robustness only (NOT optimized)
LB, SKIP = 252, 21                      # 12-1 momentum formation window [T-252, T-21]
DD_TOLERANCE = 0.03                     # "materially worse drawdown" = >3.0 pts deeper
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"

CHAMP = "C. Mom + LowVol"
CAND = "D. FIP + LowVol"

PALETTE = {
    "A. Momentum":        "#ff6b6b",
    "B. Frog-in-the-Pan": "#ffd93d",
    "C. Mom + LowVol":    "#00ff88",    # champion
    "D. FIP + LowVol":    "#4ecdc4",    # candidate upgrade
}


# ─────────────────────────────────────────────────────────────────────
# NEW FACTOR — FROG-IN-THE-PAN  (price-only, drop-in scorer)
# ─────────────────────────────────────────────────────────────────────
def compute_consistency(close_panel, date, universe, lookback=LB, skip=SKIP):
    """Fraction of POSITIVE daily returns during the 12-1 formation window
    [T-252, T-21] (same window the 12-1 momentum return is measured over).
    Higher = smoother, more 'continuous' accumulation. Self-contained on the close
    panel."""
    cols = [s for s in universe if s in close_panel.columns]
    prices = close_panel.loc[close_panel.index <= date, cols]
    if len(prices) < lookback + skip + 1:
        return pd.Series(dtype=float)
    recent = prices.iloc[-(lookback + skip):]
    form_p = recent.iloc[:-skip] if skip > 0 else recent      # formation-window prices
    form_r = form_p.pct_change().iloc[1:]                      # daily returns in the window
    n_valid = form_r.notna().sum()
    frac_pos = (form_r > 0).sum() / n_valid.replace(0, np.nan)
    # keep names with enough valid history in the window (mirrors residual-mom guard)
    frac_pos = frac_pos.where(n_valid >= int(0.8 * len(form_r)))
    return frac_pos.replace([np.inf, -np.inf], np.nan).dropna()


def compute_fip(close_panel, date, universe, lookback=LB, skip=SKIP):
    """FIP score = percentile(existing 12-1 momentum) + percentile(consistency).

    Uses the EXISTING validated 12-1 momentum for the momentum leg (per the brief),
    then adds the consistency tilt so that, among similar-momentum names, smoother
    accumulators rank higher. Returns best->worst."""
    mom = compute_12_1_momentum(close_panel, date, universe, lookback, skip)
    cons = compute_consistency(close_panel, date, universe, lookback, skip)
    common = mom.index.intersection(cons.index)
    if len(common) < 2:
        return pd.Series(dtype=float)
    score = mom[common].rank(pct=True) + cons[common].rank(pct=True)
    return score.replace([np.inf, -np.inf], np.nan).dropna().sort_values(ascending=False)


# Variant -> ranking signal. C and D share make_blend_scorer; only the leading leg
# differs, so D isolates the FIP factor against the champion.
def build_specs():
    return [
        ("A. Momentum",        compute_12_1_momentum),
        ("B. Frog-in-the-Pan", compute_fip),
        ("C. Mom + LowVol",    make_blend_scorer(compute_12_1_momentum, 0.5, VOL_LOOKBACK)),
        ("D. FIP + LowVol",    make_blend_scorer(compute_fip, 0.5, VOL_LOOKBACK)),
    ]


# ─────────────────────────────────────────────────────────────────────
# RUN HELPERS
# ─────────────────────────────────────────────────────────────────────
def run_net(panels, scorer, n, cfg, cap, label):
    ac, ah, al, av, builder = panels
    return run_buffered_backtest(
        ac, ah, al, av, n_stocks=n, rebalance_freq=FREQ, buffer=BUFFER,
        initial_capital=cap, config=cfg, apply_costs=True, label=label,
        scorer=scorer, universe_builder=builder)


def run_gross(panels, scorer, n, cfg, cap, label):
    ac, ah, al, av, builder = panels
    return run_buffered_backtest(
        ac, ah, al, av, n_stocks=n, rebalance_freq=FREQ, buffer=BUFFER,
        initial_capital=cap, config=cfg, apply_costs=False, label=label + "(g)",
        scorer=scorer, universe_builder=builder)


def metrics_of(net, bench_ret, cap):
    return compute_metrics(net["equity_curve"], net["returns"], benchmark_returns=bench_ret,
                           trades=net["trades"], total_costs=net["total_costs"],
                           initial_capital=cap)


def subperiod(eq, bench_ret, cap):
    """Metrics on a sliced equity curve (drawdown/Sharpe measured within the slice)."""
    r = eq.pct_change().fillna(0)
    return compute_metrics(eq, r, benchmark_returns=bench_ret, initial_capital=cap)


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────
def main():
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital
    start, end = cfg.backtest.start_date, cfg.backtest.end_date

    print("=" * 100)
    print("  FROG-IN-THE-PAN — A/B/C/D on the honest universe (Top10/quarterly/Buffer20, NET)".center(100))
    print("=" * 100)

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
    panels = (ac, ah, al, av, builder)

    specs = build_specs()
    names = [n for n, _ in specs]

    # ── CONCENTRATION GRID (3/5/10) for every variant. N=10 is the headline; the
    #    smaller N are a robustness read only. The N=10 net runs are captured in full
    #    (equity curves) for the split-sample / rolling validations + charts. ──
    grid = {}            # (name, n) -> metrics dict
    headline = {}        # name -> {net, m, gross_cagr, extra, roll, annual}
    for name, scorer in specs:
        for n in GRID_N:
            label = f"{name}/Top{n}"
            print(f"\n  running {label} (net) ...")
            net = run_net(panels, scorer, n, cfg, cap, label)
            m = metrics_of(net, bench_ret, cap)
            extra = drawdown_analytics(net["equity_curve"])
            roll = rolling_3y_cagr(net["returns"])
            grid[(name, n)] = {
                "cagr": m.cagr, "max_dd": m.max_drawdown, "sharpe": m.sharpe_ratio,
                "calmar": m.calmar_ratio, "alpha": m.alpha, "vol": m.annualised_volatility,
                "beta": m.beta, "roll3y_min": roll.min() if not roll.empty else np.nan,
            }
            print(f"    CAGR {m.cagr:.2%} | MaxDD {m.max_drawdown:.2%} | "
                  f"Sharpe {m.sharpe_ratio:.2f} | Alpha {m.alpha:+.2%} | Beta {m.beta:.2f}")
            if n == HEADLINE_N:
                print(f"    [headline] running gross for cost drag ...")
                gross = run_gross(panels, scorer, n, cfg, cap, label)
                gm = compute_metrics(gross["equity_curve"], gross["returns"], initial_capital=cap)
                headline[name] = {
                    "net": net, "m": m, "gross_cagr": gm.cagr, "extra": extra,
                    "roll": roll, "annual": annual_returns(net["equity_curve"]),
                }

    # ── Benchmark aligned to the strategy's realized span. ──
    eqA = headline[names[0]]["net"]["equity_curve"]
    bstart, bend = str(eqA.index[0].date()), str(eqA.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, cap)
    bm_annual = annual_returns(bench_eq) if not bench_eq.empty else pd.Series(dtype=float)
    bm_cagr = compute_metrics(bench_eq, initial_capital=cap).cagr if not bench_eq.empty else np.nan
    print(f"\n  benchmark aligned {bstart}..{bend}: NIFTY500(px) CAGR {bm_cagr:.2%}")

    # ── SPLIT-SAMPLE (positional midpoint; identical index across variants). ──
    idx = eqA.index
    mid = len(idx) // 2
    mid_date = idx[mid]
    split = {}
    for name in names:
        eq = headline[name]["net"]["equity_curve"]
        h1 = subperiod(eq.iloc[:mid + 1], bench_ret, cap)
        h2 = subperiod(eq.iloc[mid:], bench_ret, cap)
        split[name] = {"h1": h1, "h2": h2}
    if not bench_eq.empty:
        bmid = bench_eq.index.get_indexer([mid_date], method="nearest")[0]
        bm_h1 = subperiod(bench_eq.iloc[:bmid + 1], None, cap)
        bm_h2 = subperiod(bench_eq.iloc[bmid:], None, cap)
    else:
        bm_h1 = bm_h2 = None

    # ── ROLLING WINDOW (rolling 3y CAGR + rolling 1y Sharpe). ──
    rolling = {}
    for name in names:
        r = headline[name]["net"]["returns"]
        roll3y = rolling_3y_cagr(r)
        roll1y = compute_rolling_metrics(r, window=252)["rolling_sharpe"].dropna()
        rolling[name] = {"roll3y": roll3y, "roll1y_sharpe": roll1y}
    cD = rolling[CAND]["roll3y"]; cC = rolling[CHAMP]["roll3y"]
    common = cD.index.intersection(cC.index)
    d_beats_c = float((cD[common] >= cC[common]).mean()) if len(common) else np.nan

    # ── OUTPUTS ──
    rdir = RESULTS_DIR / "factor_fip"
    rdir.mkdir(parents=True, exist_ok=True)
    write_csv(rdir, names, headline, grid, bm_cagr)
    txt = write_report(rdir, names, headline, grid, split, rolling, d_beats_c,
                       bm_cagr, bm_h1, bm_h2, mid_date, cap, bstart, bend)
    make_charts(names, headline, bench_eq, bm_annual, rdir / "report.png")
    write_walkthrough(rdir, names, headline, grid, split, rolling, d_beats_c,
                      bm_cagr, mid_date, cap, bstart, bend)
    print("\n" + txt)
    print(f"\n  All outputs in: {rdir}/")


# ─────────────────────────────────────────────────────────────────────
# VERDICT (shared by report.txt and WALKTHROUGH.md)
# ─────────────────────────────────────────────────────────────────────
def verdict_lines(headline):
    C = headline[CHAMP]["m"]
    D = headline[CAND]["m"]
    dcagr = D.cagr - C.cagr
    dsharpe = D.sharpe_ratio - C.sharpe_ratio
    ddd = D.max_drawdown - C.max_drawdown          # +ve => shallower (less negative)
    improves = (dsharpe > 0) or (dcagr > 0)
    dd_ok = ddd >= -DD_TOLERANCE                    # not more than 3.0 pts deeper
    passed = improves and dd_ok
    return passed, dcagr, dsharpe, ddd, C, D


# ─────────────────────────────────────────────────────────────────────
# CSV
# ─────────────────────────────────────────────────────────────────────
def write_csv(rdir, names, headline, grid, bm_cagr):
    rows = []
    for name in names:
        h = headline[name]; m = h["m"]; net = h["net"]
        rows.append({
            "variant": name, "cagr_net": m.cagr, "cagr_gross": h["gross_cagr"],
            "cost_drag": h["gross_cagr"] - m.cagr, "max_drawdown": m.max_drawdown,
            "sharpe": m.sharpe_ratio, "calmar": m.calmar_ratio, "alpha": m.alpha,
            "annual_vol": m.annualised_volatility, "beta": m.beta,
            "sortino": m.sortino_ratio, "total_return": m.total_return,
            "final_value": net["equity_curve"].iloc[-1],
            "trades": net["total_trades"], "avg_turnover": net["avg_turnover"],
            "total_costs": net["total_costs"],
            "time_underwater": h["extra"]["time_underwater_pct"],
            "roll3y_min": h["roll"].min() if not h["roll"].empty else np.nan,
            "roll3y_med": h["roll"].median() if not h["roll"].empty else np.nan,
            "roll3y_max": h["roll"].max() if not h["roll"].empty else np.nan,
            "excess_vs_bmk": m.cagr - bm_cagr,
        })
    pd.DataFrame(rows).to_csv(rdir / "comparison.csv", index=False)
    crows = [{"variant": n, "N": k[1], **{kk: vv for kk, vv in grid[k].items()}}
             for n in names for k in grid if k[0] == n]
    pd.DataFrame(crows).to_csv(rdir / "concentration.csv", index=False)


# ─────────────────────────────────────────────────────────────────────
# REPORT.TXT
# ─────────────────────────────────────────────────────────────────────
def write_report(rdir, names, headline, grid, split, rolling, d_beats_c,
                 bm_cagr, bm_h1, bm_h2, mid_date, cap, bstart, bend):
    L = []; w = L.append
    W = 100

    def row(lbl, fmt):
        s = f"{lbl:<22}"
        for n in names:
            s += f"{fmt(headline[n]):>19}"
        return s

    w("=" * W)
    w("FROG-IN-THE-PAN (FIP) FACTOR — SURVIVORSHIP-FREE UNIVERSE".center(W))
    w("Top10 / Quarterly / Equal Weight / Buffer20 / Net of Indian costs".center(W))
    w("=" * W)
    w(f"Initial Capital: Rs {cap:,.0f}   Period: {bstart}..{bend}")
    w(f"New factor: FIP = pct(12-1 momentum) + pct(consistency); consistency = fraction of")
    w(f"            positive daily returns over the 12-1 formation window [T-252, T-21].")
    w(f"C and D use the validated 50/50 momentum+lowvol blend; only the ranking leg differs.")
    w(f"Benchmark: NIFTY 500 PRICE index, CAGR {bm_cagr:.2%} (true TRI ~ {bm_cagr+0.013:.2%}).")
    w(f"Benchmark date-parse bug fixed earlier -> Beta/Alpha are valid.")
    w("")
    w(f"{'Metric':<22}" + "".join(f"{n:>19}" for n in names)); w("-" * W)
    w(row("CAGR (net)",      lambda h: f"{h['m'].cagr:.2%}"))
    w(row("CAGR (gross)",    lambda h: f"{h['gross_cagr']:.2%}"))
    w(row("Max Drawdown",    lambda h: f"{h['m'].max_drawdown:.2%}"))
    w(row("Sharpe",          lambda h: f"{h['m'].sharpe_ratio:.2f}"))
    w(row("Calmar",          lambda h: f"{h['m'].calmar_ratio:.2f}"))
    w(row("Alpha (ann.)",    lambda h: f"{h['m'].alpha:+.2%}"))
    w(row("Beta",            lambda h: f"{h['m'].beta:.2f}"))
    w(row("Annual Vol",      lambda h: f"{h['m'].annualised_volatility:.2%}"))
    w(row("Sortino",         lambda h: f"{h['m'].sortino_ratio:.2f}"))
    w(row("Excess vs Bmk",   lambda h: f"{h['m'].cagr-bm_cagr:+.2%}"))
    w(row("Trades (exec)",   lambda h: f"{h['net']['total_trades']}"))
    w(row("Avg Turnover/Reb",lambda h: f"{h['net']['avg_turnover']:.1%}"))
    w(row("Txn Costs (Rs)",  lambda h: f"{h['net']['total_costs']:,.0f}"))
    w(row("Cost Drag (pts)", lambda h: f"{h['gross_cagr']-h['m'].cagr:.2%}"))
    w(row("Time Underwater", lambda h: f"{h['extra']['time_underwater_pct']:.1%}"))
    w(row("Final Value (Rs)",lambda h: f"{h['net']['equity_curve'].iloc[-1]:,.0f}"))
    w("-" * W)

    # ── Success criterion ──
    passed, dcagr, dsharpe, ddd, C, D = verdict_lines(headline)
    w("")
    w("SUCCESS CRITERION".center(W, "-"))
    w("Pre-registered: D (FIP+LowVol) improves Sharpe AND/OR CAGR vs C (champion),")
    w(f"                without materially worsening drawdown (> {DD_TOLERANCE*100:.0f} pts deeper).")
    w(f"  C (champion)   : CAGR {C.cagr:.2%} | Sharpe {C.sharpe_ratio:.2f} | MaxDD {C.max_drawdown:.2%}")
    w(f"  D (candidate)  : CAGR {D.cagr:.2%} | Sharpe {D.sharpe_ratio:.2f} | MaxDD {D.max_drawdown:.2%}")
    w(f"  delta D - C    : dCAGR {dcagr:+.2%} | dSharpe {dsharpe:+.2f} | "
      f"dMaxDD {ddd:+.2%} ({'shallower' if ddd >= 0 else 'deeper'})")
    w(f"  => VERDICT: {'PASS' if passed else 'FAIL'} — "
      + ("D clears the bar." if passed else "D does not clear the bar; the champion stands."))
    w("=" * W)

    # ── Split-sample ──
    w("")
    w("SPLIT-SAMPLE VALIDATION".center(W, "-"))
    w(f"First half : {bstart} .. {mid_date.date()}    Second half : {mid_date.date()} .. {bend}")
    w(f"{'Variant':<22}{'CAGR_1':>11}{'Sharpe_1':>11}{'MaxDD_1':>11}{'CAGR_2':>11}{'Sharpe_2':>11}{'MaxDD_2':>11}")
    w("-" * W)
    for n in names:
        a, b = split[n]["h1"], split[n]["h2"]
        w(f"{n:<22}{a.cagr:>10.1%} {a.sharpe_ratio:>10.2f} {a.max_drawdown:>10.1%} "
          f"{b.cagr:>10.1%} {b.sharpe_ratio:>10.2f} {b.max_drawdown:>10.1%}")
    if bm_h1 is not None:
        w(f"{'NIFTY500 (px)':<22}{bm_h1.cagr:>10.1%} {'-':>10} {bm_h1.max_drawdown:>10.1%} "
          f"{bm_h2.cagr:>10.1%} {'-':>10} {bm_h2.max_drawdown:>10.1%}")
    w("-" * W)
    dc1 = split[CAND]["h1"].sharpe_ratio - split[CHAMP]["h1"].sharpe_ratio
    dc2 = split[CAND]["h2"].sharpe_ratio - split[CHAMP]["h2"].sharpe_ratio
    consistent = (dc1 > 0) == (dc2 > 0)
    w(f"D-vs-C Sharpe edge: half1 {dc1:+.2f}, half2 {dc2:+.2f}  "
      f"=> {'CONSISTENT sign across halves' if consistent else 'SIGN FLIPS between halves (fragile)'}")
    w("=" * W)

    # ── Rolling window ──
    w("")
    w("ROLLING-WINDOW VALIDATION".center(W, "-"))
    w("Rolling 3-Year CAGR (min / median / max) and rolling 1-Year Sharpe (median):")
    w(f"{'Variant':<22}{'3yCAGR_min':>13}{'3yCAGR_med':>13}{'3yCAGR_max':>13}{'1ySharpe_med':>15}")
    w("-" * W)
    for n in names:
        r3 = rolling[n]["roll3y"]; r1 = rolling[n]["roll1y_sharpe"]
        w(f"{n:<22}{(r3.min() if not r3.empty else np.nan):>12.1%} "
          f"{(r3.median() if not r3.empty else np.nan):>12.1%} "
          f"{(r3.max() if not r3.empty else np.nan):>12.1%} "
          f"{(r1.median() if not r1.empty else np.nan):>14.2f}")
    w("-" * W)
    w(f"D's rolling-3y CAGR >= C's on {d_beats_c:.0%} of overlapping windows.")
    w("=" * W)

    # ── Concentration ──
    w("")
    w("CONCENTRATION ANALYSIS (robustness only — N is NOT optimized; Top10 is the headline)".center(W, "-"))
    w(f"{'Variant':<22}{'N':>4}{'CAGR':>10}{'MaxDD':>10}{'Sharpe':>9}{'Calmar':>9}{'Alpha':>9}{'Vol':>9}")
    w("-" * W)
    for n in names:
        for k in GRID_N:
            g = grid[(n, k)]
            w(f"{n:<22}{k:>4}{g['cagr']:>9.1%}{g['max_dd']:>10.1%}{g['sharpe']:>9.2f}"
              f"{g['calmar']:>9.2f}{g['alpha']:>+9.1%}{g['vol']:>9.1%}")
        w("")
    w("Read: concentration (lower N) is a robustness check, not a tuning knob. The")
    w("prior honest concentration study found lower N raised drawdown without a")
    w("commensurate Sharpe gain; watch whether FIP behaves the same.")
    w("=" * W)

    txt = "\n".join(L)
    (rdir / "report.txt").write_text(txt, encoding="utf-8")
    return txt


# ─────────────────────────────────────────────────────────────────────
# REPORT.PNG
# ─────────────────────────────────────────────────────────────────────
def make_charts(names, headline, bench_eq, bm_annual, save_path):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 24))
    gs = GridSpec(5, 2, figure=fig, hspace=0.40, wspace=0.22)
    fig.suptitle("Frog-in-the-Pan vs Momentum / LowVol — Survivorship-Free Universe\n"
                 "Top10 / Quarterly / Buffer20 / Equal Weight (Net of Indian costs)",
                 fontsize=15, fontweight="bold", y=0.995, color="#fff")

    def eq_of(n): return headline[n]["net"]["equity_curve"]

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for n in names:
        eq = eq_of(n); ax1.plot(eq.index, eq / eq.iloc[0] * 100, color=PALETTE[n], lw=1.8, label=n)
    if bench_eq is not None and not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq / bench_eq.iloc[0] * 100, color="#888", lw=1.3,
                 ls="--", label="NIFTY 500 (price)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[1, :]); ax2.set_title("Drawdown", fontweight="bold")
    for n in names:
        eq = eq_of(n); dd = (eq - eq.cummax()) / eq.cummax() * 100
        ax2.plot(dd.index, dd, color=PALETTE[n], lw=1.1, label=n)
    ax2.legend(loc="lower left", framealpha=.3); ax2.grid(True, alpha=.2)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax3 = fig.add_subplot(gs[2, 0]); ax3.set_title("CAGR vs Max DD", fontweight="bold")
    cagrs = [headline[n]["m"].cagr * 100 for n in names]
    dds = [abs(headline[n]["m"].max_drawdown) * 100 for n in names]
    b = ax3.bar(names, cagrs, color=[PALETTE[n] for n in names])
    for bb, cc in zip(b, cagrs):
        ax3.text(bb.get_x() + bb.get_width() / 2, bb.get_height(), f"{cc:.1f}%",
                 ha="center", va="bottom", color="#fff", fontweight="bold")
    a3 = ax3.twinx(); a3.plot(names, dds, color="#ff6b6b", marker="o", lw=1.6)
    a3.set_ylabel("Max DD %", color="#ff6b6b")
    ax3.set_ylabel("CAGR %"); ax3.tick_params(axis="x", rotation=20); ax3.grid(True, alpha=.2, axis="y")

    ax4 = fig.add_subplot(gs[2, 1]); ax4.set_title("Sharpe & Alpha", fontweight="bold")
    x = np.arange(len(names))
    ax4.bar(x - .2, [headline[n]["m"].sharpe_ratio for n in names], .4, color="#4ecdc4", label="Sharpe")
    ax4.bar(x + .2, [headline[n]["m"].alpha * 100 for n in names], .4, color="#ffd93d", label="Alpha %")
    ax4.axhline(0, color="white", lw=.5, alpha=.4)
    ax4.set_xticks(x); ax4.set_xticklabels(names, rotation=20); ax4.legend(framealpha=.3)
    ax4.grid(True, alpha=.2, axis="y")

    ax5 = fig.add_subplot(gs[3, :]); ax5.set_title("Rolling 3-Year CAGR", fontweight="bold")
    for n in names:
        r = headline[n]["roll"]
        if not r.empty:
            ax5.plot(r.index, r * 100, color=PALETTE[n], lw=1.4, label=n)
    ax5.axhline(6.5, color="#ff6b6b", ls="--", lw=1, alpha=.6, label="FD 6.5%")
    ax5.axhline(0, color="white", lw=.5, ls="--", alpha=.3)
    ax5.legend(loc="upper right", framealpha=.3); ax5.grid(True, alpha=.2)
    ax5.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax6 = fig.add_subplot(gs[4, :]); ax6.set_title("Year-wise Returns vs Benchmark", fontweight="bold")
    yrs = sorted(set().union(*[set(headline[n]["annual"].index) for n in names]))
    xp = np.arange(len(yrs)); wbar = 0.8 / (len(names) + 1)
    for i, n in enumerate(names):
        ax6.bar(xp + i * wbar, [headline[n]["annual"].get(y, np.nan) * 100 for y in yrs],
                wbar, color=PALETTE[n], label=n)
    if bm_annual is not None and not bm_annual.empty:
        ax6.bar(xp + len(names) * wbar, [bm_annual.get(y, np.nan) * 100 for y in yrs],
                wbar, color="#888", label="NIFTY500(px)")
    ax6.axhline(0, color="white", lw=.5, alpha=.3)
    ax6.set_xticks(xp + wbar * len(names) / 2); ax6.set_xticklabels(yrs, rotation=45)
    ax6.legend(framealpha=.3, ncol=5); ax6.grid(True, alpha=.2, axis="y")

    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  Chart saved: {save_path}")


# ─────────────────────────────────────────────────────────────────────
# WALKTHROUGH.MD
# ─────────────────────────────────────────────────────────────────────
def write_walkthrough(rdir, names, headline, grid, split, rolling, d_beats_c,
                      bm_cagr, mid_date, cap, bstart, bend):
    passed, dcagr, dsharpe, ddd, C, D = verdict_lines(headline)

    def mrow(n):
        h = headline[n]; m = h["m"]; net = h["net"]
        return (f"| {n} | {m.cagr:.1%} | {m.max_drawdown:.1%} | {m.sharpe_ratio:.2f} | "
                f"{m.calmar_ratio:.2f} | {m.alpha:+.1%} | {m.beta:.2f} | "
                f"{m.annualised_volatility:.1%} | {net['avg_turnover']:.0%} | "
                f"{net['total_costs']:,.0f} |")

    L = []; w = L.append
    w("# Frog-in-the-Pan (FIP) — Factor Experiment Walkthrough\n")
    w(f"_Period {bstart} .. {bend}. Initial capital Rs {cap:,.0f}. "
      f"All figures **net** of the Indian delivery cost model._\n")

    w("## 1. What was tested\n")
    w("A single new **price-only** ranking factor, **Frog-in-the-Pan (FIP)**:\n")
    w("```")
    w("FIP score   = percentile(12-1 momentum) + percentile(consistency)")
    w("consistency = fraction of POSITIVE daily returns over the 12-1")
    w("              formation window [T-252, T-21]")
    w("```")
    w("Per Da, Gurun & Warachka (2014, *RFS*), momentum built from **continuous** "
      "information (many small up-days) persists, while momentum from **discrete** "
      "jumps reverses. FIP keeps the existing 12-1 momentum return and adds a "
      "consistency tilt so that, among similar-momentum names, smoother accumulators "
      "rank higher. This is a momentum-*quality* refinement distinct from the earlier "
      "residual-momentum test (which adjusted for beta, not path smoothness).\n")

    w("## 2. What was held fixed (engine frozen, nothing tuned)\n")
    w("| Component | Setting |")
    w("|---|---|")
    w("| Backtest engine | `run_buffered_backtest` — reused unchanged |")
    w("| Universe | survivorship-free bhavcopy, top-500 by liquidity, PIT, equity-only |")
    w("| Costs | full Indian delivery cost model (net) |")
    w("| Rebalance | quarterly |")
    w("| Buffer | Buffer20 |")
    w("| Sizing | Top10, equal weight, whole-share rounding |")
    w("| Execution | identical engine mechanics |")
    w("\nThe momentum leg of FIP **is** the existing validated 12-1 momentum. Variants "
      "**C** and **D** are produced by the *same* validated 50/50 momentum+low-vol "
      "blend (`make_blend_scorer`); they differ **only** in the ranking leg (12-1 "
      "momentum vs FIP). So D minus C isolates the factor.\n")
    w("> Beta/Alpha are valid here — the benchmark CSV date-parse bug found earlier was "
      "repaired in `data/benchmark.py` (benchmark daily vol back to ~16%).\n")

    w("## 3. Headline results (Top10 / quarterly / Buffer20, net)\n")
    w("| Variant | CAGR | MaxDD | Sharpe | Calmar | Alpha | Beta | Vol | Turnover | Costs (Rs) |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for n in names:
        w(mrow(n))
    w(f"\n_Benchmark: NIFTY 500 price index CAGR {bm_cagr:.1%} "
      f"(true TRI ~ {bm_cagr+0.013:.1%})._\n")

    w("## 4. Success criterion (pre-registered)\n")
    w("> Variant **D** must improve **Sharpe and/or CAGR** versus Variant **C** "
      f"without materially worsening drawdown (defined up front as MaxDD more than "
      f"{int(DD_TOLERANCE*100)} pts deeper).\n")
    w(f"- C (champion): CAGR **{C.cagr:.1%}**, Sharpe **{C.sharpe_ratio:.2f}**, "
      f"MaxDD **{C.max_drawdown:.1%}**")
    w(f"- D (candidate): CAGR **{D.cagr:.1%}**, Sharpe **{D.sharpe_ratio:.2f}**, "
      f"MaxDD **{D.max_drawdown:.1%}**")
    w(f"- delta (D − C): dCAGR **{dcagr:+.1%}**, dSharpe **{dsharpe:+.2f}**, "
      f"dMaxDD **{ddd:+.1%}** ({'shallower' if ddd >= 0 else 'deeper'})\n")
    w(f"### Verdict: **{'PASS' if passed else 'FAIL'}** — "
      + ("D clears the bar.\n" if passed else
         "D does not clear the bar; the champion stands.\n"))

    w("## 5. Split-sample validation\n")
    w(f"Realized span split at its midpoint ({mid_date.date()}); each half measured "
      "independently. A real factor should not live in only one half.\n")
    w("| Variant | CAGR H1 | Sharpe H1 | MaxDD H1 | CAGR H2 | Sharpe H2 | MaxDD H2 |")
    w("|---|---|---|---|---|---|---|")
    for n in names:
        a, b = split[n]["h1"], split[n]["h2"]
        w(f"| {n} | {a.cagr:.1%} | {a.sharpe_ratio:.2f} | {a.max_drawdown:.1%} | "
          f"{b.cagr:.1%} | {b.sharpe_ratio:.2f} | {b.max_drawdown:.1%} |")
    dc1 = split[CAND]["h1"].sharpe_ratio - split[CHAMP]["h1"].sharpe_ratio
    dc2 = split[CAND]["h2"].sharpe_ratio - split[CHAMP]["h2"].sharpe_ratio
    consistent = (dc1 > 0) == (dc2 > 0)
    w(f"\nD-vs-C Sharpe edge: half1 **{dc1:+.2f}**, half2 **{dc2:+.2f}** → "
      f"**{'consistent sign' if consistent else 'sign flips (fragile)'}** across halves.\n")

    w("## 6. Rolling-window validation\n")
    w("| Variant | Roll-3y CAGR min | median | max | Roll-1y Sharpe median |")
    w("|---|---|---|---|---|")
    for n in names:
        r3 = rolling[n]["roll3y"]; r1 = rolling[n]["roll1y_sharpe"]
        w(f"| {n} | {(r3.min() if not r3.empty else float('nan')):.1%} | "
          f"{(r3.median() if not r3.empty else float('nan')):.1%} | "
          f"{(r3.max() if not r3.empty else float('nan')):.1%} | "
          f"{(r1.median() if not r1.empty else float('nan')):.2f} |")
    w(f"\nD's rolling-3y CAGR ≥ C's on **{d_beats_c:.0%}** of overlapping windows.\n")

    w("## 7. Concentration analysis (robustness only)\n")
    w("Top3 / Top5 / Top10 for each variant — a **robustness read, not a tuning "
      "knob**. Top10 remains the headline and N is not optimized.\n")
    w("| Variant | N | CAGR | MaxDD | Sharpe | Calmar | Alpha |")
    w("|---|---|---|---|---|---|---|")
    for n in names:
        for k in GRID_N:
            g = grid[(n, k)]
            w(f"| {n} | {k} | {g['cagr']:.1%} | {g['max_dd']:.1%} | {g['sharpe']:.2f} | "
              f"{g['calmar']:.2f} | {g['alpha']:+.1%} |")

    w("\n## 8. Caveats\n")
    w("- FIP here uses **fraction of positive days** as the consistency proxy, exactly "
      "as specified. The literature's signed information-discreteness "
      "(`sign(PRET)·(%neg−%pos)`) is an alternative spec, not a tuning parameter — "
      "left for a separate robustness run.\n")
    w("- All conclusions are **net of costs** on the survivorship-free universe; no "
      "parameter was searched and the engine, costs, universe, rebalance, buffer, "
      "sizing, and execution are untouched.\n")

    w("## 9. Reproduce\n")
    w("```")
    w("py run_fip.py")
    w("```")
    w("Outputs: `results/factor_fip/{comparison.csv, concentration.csv, "
      "report.txt, report.png, WALKTHROUGH.md}`")

    (rdir / "WALKTHROUGH.md").write_text("\n".join(L), encoding="utf-8")
    print(f"  Walkthrough saved: {rdir / 'WALKTHROUGH.md'}")


if __name__ == "__main__":
    main()
