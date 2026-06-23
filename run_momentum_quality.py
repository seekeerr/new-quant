"""
PHASE 2A — MOMENTUM + QUALITY PILOT  (frozen Phase-1 champion engine).

Tests whether a Quality factor (Novy-Marx gross profitability + ROE) adds statistically
and economically meaningful value on top of the frozen champion. NOTHING in the engine,
costs, execution, portfolio, turnover, or universe is modified — Quality enters only as a
new drop-in scorer (`quality_store.py`), exactly as every Phase-1 factor did.

Frozen champion shell (PHASE1_FINAL_REPORT.md §0):
    Top10 / quarterly / Buffer20 / equal weight / full Indian cost model / honest
    survivorship-free, equity-only top-500-liquid universe.

Variants (mirror the proven A/B/C/D protocol):
    A. Momentum standalone           (12-1, Jegadeesh-Titman)
    B. Quality standalone            (GP/Assets + ROE composite)
    C. Momentum + LowVol  *(champion — the bar to beat)*
    D. Momentum + LowVol + Quality   (quality-tilted champion)

Validation framework (same as Phase 1):
    full period · split sample · rolling windows · concentration · sector concentration
    · contribution analysis.

Pre-registered success criterion:
    D improves Sharpe AND/OR CAGR vs champion C, WITHOUT materially worsening drawdown
    (>3 pts), AND survives split-sample + rolling-window validation (no sign-flip across
    halves — the test that killed FIP). Otherwise FAIL.

DATA GATE (the honest stop):
    The single data source is `data/cache_fundamentals/pilot_fundamentals.csv`. Until a
    human fills + verifies it, this script computes NO backtest and prints NO verdict — it
    emits a PENDING framework-ready report and a plumbing self-test, then stops. No
    yfinance, no scraper, no PIT platform.

Run:  py run_momentum_quality.py
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
from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns
from costs.cost_model import CostModel
from analytics.metrics import compute_metrics
from utils.helpers import get_rebalance_dates

from run_pure_momentum import compute_12_1_momentum
from run_buffer_experiment import (
    run_buffered_backtest, drawdown_analytics, rolling_3y_cagr, annual_returns,
)
from run_momentum_lowvol import (
    make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK,
)
from run_survivorship_validation import TopNTurnoverUniverseBuilder

from quality_store import (
    QualityStore, make_quality_scorer, make_mom_lowvol_quality_scorer,
    REPORTING_LAG_DAYS, SAFETY_LAG_DAYS, METRICS,
)

# ── Frozen champion shell (Top10, NOT the Top5 of the earlier lowvol script) ──
N_STOCKS, BUFFER, FREQ = 10, 20, "quarterly"
# Variant-D blend weights. Champion C is 0.5/0.5 mom/lowvol; D adds quality as a third,
# roughly-equal offensive-fundamental leg while keeping momentum the largest weight.
W_MOM, W_LOWVOL, W_QUALITY = 0.40, 0.40, 0.20
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "momentum_quality_pilot"

# Minimum quality coverage to even attempt B/D: at least N_STOCKS names with PIT quality
# data in the universe at the median rebalance. Below this, a "Quality" portfolio cannot
# be formed and any verdict would be noise -> stay PENDING.
MIN_COVERED_FOR_VERDICT = N_STOCKS
# "Meaningful" improvement thresholds for the pre-registered success bar.
EPS_SHARPE, EPS_CAGR, MAXDD_TOLERANCE = 0.05, 0.005, 0.03

PALETTE = {
    "A. Momentum":              "#ff6b6b",
    "B. Quality":               "#c792ea",
    "C. Mom+LowVol (champion)": "#00ff88",
    "D. Mom+LowVol+Quality":    "#ffd93d",
}


# ─────────────────────────────────────────────────────────────────────
# PANELS / UNIVERSE  (loaded identically to the champion run)
# ─────────────────────────────────────────────────────────────────────

def load_panels_and_builder(cfg):
    ac = pd.read_parquet(CACHE_BHAV / "adj_close.parquet")
    ah = pd.read_parquet(CACHE_BHAV / "adj_high.parquet")
    al = pd.read_parquet(CACHE_BHAV / "adj_low.parquet")
    av = pd.read_parquet(CACHE_BHAV / "raw_volume.parquet")
    at = pd.read_parquet(CACHE_BHAV / "raw_turnover.parquet")
    eq_syms = load_equity_symbols()
    if eq_syms is not None:
        keep = [c for c in ac.columns if c in eq_syms]
        ac, ah, al, av, at = (p[keep] for p in (ac, ah, al, av, at))
    builder = TopNTurnoverUniverseBuilder(ac, ah, al, av, at, cfg.universe, max_size=500)
    return ac, ah, al, av, at, builder


def backtest_rebalance_dates(cfg, close_panel):
    start = max(pd.Timestamp(cfg.backtest.start_date),
                close_panel.index.min() + pd.Timedelta(days=365))
    end = min(pd.Timestamp(cfg.backtest.end_date), close_panel.index.max())
    dates = close_panel.index[(close_panel.index >= start) & (close_panel.index <= end)]
    return list(get_rebalance_dates(dates, FREQ))


def sector_map():
    """symbol -> Industry, via ISIN from the pilot company list + constituents file.
    Best-effort; names with no mapping are bucketed 'Unknown' for the report only."""
    try:
        cons = pd.read_csv(PROJECT_ROOT / "data" / "nifty500_constituents.csv")
        by_isin = dict(zip(cons["ISIN Code"], cons["Industry"]))
        cl = pd.read_csv(PROJECT_ROOT / "data" / "cache_fundamentals" / "pilot_company_list.csv")
        return {r["symbol"]: by_isin.get(r["isin"], "Unknown") for _, r in cl.iterrows()}
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────
# BACKTEST RUNNER + ANALYTICS REBUILT FROM TRADES  (engine untouched)
# ─────────────────────────────────────────────────────────────────────

def run_variant(scorer, c, h, l, v, cfg, cap, bench_ret, label, builder):
    common = dict(n_stocks=N_STOCKS, rebalance_freq=FREQ, buffer=BUFFER,
                  initial_capital=cap, config=cfg, universe_builder=builder, scorer=scorer)
    net = run_buffered_backtest(c, h, l, v, apply_costs=True, label=label, **common)
    gross = run_buffered_backtest(c, h, l, v, apply_costs=False, label=label + "(g)", **common)
    m = compute_metrics(net["equity_curve"], net["returns"], benchmark_returns=bench_ret,
                        trades=net["trades"], total_costs=net["total_costs"], initial_capital=cap)
    gm = compute_metrics(gross["equity_curve"], gross["returns"], initial_capital=cap)
    net["_m"] = m
    net["_gross_cagr"] = gm.cagr
    net["_extra"] = drawdown_analytics(net["equity_curve"])
    net["_annual"] = annual_returns(net["equity_curve"])
    net["_roll3y"] = rolling_3y_cagr(net["returns"])
    return net


def reconstruct_holdings(trades) -> pd.DataFrame:
    """Period-end share positions after each rebalance, rebuilt from the trade log
    (the engine returns trades, not snapshots — we never touch the engine)."""
    pos, rows = {}, []
    for d, grp in pd.DataFrame(trades).groupby("date") if trades else []:
        for _, t in grp.iterrows():
            pos[t["symbol"]] = pos.get(t["symbol"], 0) + (t["shares"] if t["side"] == "BUY" else -t["shares"])
        for sym, q in pos.items():
            if q > 0:
                rows.append({"date": d, "symbol": sym, "shares": int(q)})
    return pd.DataFrame(rows, columns=["date", "symbol", "shares"])


def concentration_stats(trades, close_panel, secmap) -> dict:
    """Name- and sector-level concentration averaged over rebalance snapshots."""
    hold = reconstruct_holdings(trades)
    if hold.empty:
        return {"avg_names": np.nan, "name_hhi": np.nan, "avg_max_sector_wt": np.nan,
                "top_sector": "N/A"}
    name_hhi, n_names, max_sec_wt, sec_accum = [], [], [], {}
    for d, grp in hold.groupby("date"):
        val = {}
        px = close_panel.loc[d] if d in close_panel.index else close_panel.ffill().loc[:d].iloc[-1]
        for _, r in grp.iterrows():
            p = px.get(r["symbol"], np.nan)
            if p > 0:
                val[r["symbol"]] = r["shares"] * p
        tot = sum(val.values())
        if tot <= 0:
            continue
        w = {s: x / tot for s, x in val.items()}
        n_names.append(len(w))
        name_hhi.append(sum(x * x for x in w.values()))
        sec_w = {}
        for s, x in w.items():
            sec = secmap.get(s, "Unknown")
            sec_w[sec] = sec_w.get(sec, 0) + x
            sec_accum[sec] = sec_accum.get(sec, 0) + x
        max_sec_wt.append(max(sec_w.values()))
    top_sector = max(sec_accum, key=sec_accum.get) if sec_accum else "N/A"
    return {"avg_names": float(np.mean(n_names)), "name_hhi": float(np.mean(name_hhi)),
            "avg_max_sector_wt": float(np.mean(max_sec_wt)), "top_sector": top_sector}


def contribution_analysis(trades, close_panel) -> pd.DataFrame:
    """Per-symbol P&L contribution = realised cashflow (sells - buys - costs) + terminal
    mark-to-market of any position still open at the end. A pilot-grade attribution rebuilt
    from the trade log (not a daily per-name return decomposition)."""
    if not trades:
        return pd.DataFrame(columns=["symbol", "pnl", "n_trades"])
    df = pd.DataFrame(trades)
    last_px = close_panel.ffill().iloc[-1]
    pos, pnl, ntr = {}, {}, {}
    for _, t in df.iterrows():
        s = t["symbol"]
        ntr[s] = ntr.get(s, 0) + 1
        signed = -t["value"] if t["side"] == "BUY" else t["value"]
        pnl[s] = pnl.get(s, 0) + signed - t["cost"]
        pos[s] = pos.get(s, 0) + (t["shares"] if t["side"] == "BUY" else -t["shares"])
    for s, q in pos.items():
        if q > 0:
            pnl[s] = pnl.get(s, 0) + q * last_px.get(s, 0)
    out = pd.DataFrame({"symbol": list(pnl), "pnl": list(pnl.values()),
                        "n_trades": [ntr[s] for s in pnl]})
    return out.sort_values("pnl", ascending=False).reset_index(drop=True)


def split_sample(net, cfg, close_panel) -> dict:
    """First-half vs second-half CAGR/Sharpe of a variant's equity curve."""
    eq = net["equity_curve"].dropna()
    if len(eq) < 8:
        return {}
    mid = eq.index[len(eq) // 2]
    h1, h2 = eq.loc[:mid], eq.loc[mid:]
    m1, m2 = compute_metrics(h1, initial_capital=h1.iloc[0]), compute_metrics(h2, initial_capital=h2.iloc[0])
    return {"split_date": mid.date(), "cagr_h1": m1.cagr, "cagr_h2": m2.cagr,
            "sharpe_h1": m1.sharpe_ratio, "sharpe_h2": m2.sharpe_ratio}


# ─────────────────────────────────────────────────────────────────────
# COVERAGE  (drives the PENDING gate)
# ─────────────────────────────────────────────────────────────────────

def coverage_over_rebalances(store, builder, rebal_dates):
    rows = []
    for d in rebal_dates:
        u = builder.build_universe(d)
        syms = u.symbols if u and u.symbols else []
        cov = store.coverage_at(d, syms)
        rows.append({"date": d.date(), **cov})
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital
    RDIR.mkdir(parents=True, exist_ok=True)

    print("=" * 84)
    print("  PHASE 2A — MOMENTUM + QUALITY PILOT  (frozen champion: Top10/Q/Buffer20)".center(84))
    print("=" * 84)

    store = QualityStore()
    print(f"\n  Fundamentals source : {store.csv_path}")
    print(f"  Template rows       : {store.n_template_rows} company-years across {store.n_companies} companies")
    print(f"  Verified+usable rows: {store.n_verified_rows}")
    print(f"  PIT policy          : knowledge = filing_date else period_end +{REPORTING_LAG_DAYS}d; "
          f"safety lag {SAFETY_LAG_DAYS}d; verified-only")
    workload = store.n_template_rows
    print(f"  Manual fill workload: ~{workload} rows x 5 fields "
          f"(gross_profit, total_assets, net_profit, total_equity, filing_date) "
          f"= ~{workload * 5} cells")

    print("\n  Loading survivorship-free bhavcopy panels ...")
    ac, ah, al, av, at, builder = load_panels_and_builder(cfg)
    print(f"  panel: {ac.shape[0]} dates x {ac.shape[1]} equity symbols")
    rebal_dates = backtest_rebalance_dates(cfg, ac)
    print(f"  rebalances: {len(rebal_dates)} ({rebal_dates[0].date()} .. {rebal_dates[-1].date()})")

    cov = coverage_over_rebalances(store, builder, rebal_dates)
    median_both = int(cov["both"].median()) if not cov.empty else 0
    print(f"  median quality-covered names in universe / rebalance: {median_both}")

    # Always write the framework documentation.
    write_walkthrough(workload, median_both)

    gate_ok = (store.n_verified_rows > 0) and (median_both >= MIN_COVERED_FOR_VERDICT)
    if not gate_ok:
        print("\n  >>> DATA GATE: insufficient verified quality data -> framework is READY but PENDING.")
        plumbing_self_test(store, ac, builder, rebal_dates)
        write_pending_outputs(store, cov, workload, median_both, cap)
        print(f"\n  Outputs (PENDING state) in: {RDIR}/")
        print("  Fill + verify pilot_fundamentals.csv, then re-run for the A/B/C/D verdict.")
        return

    # ── DATA PRESENT: full pilot ─────────────────────────────────────
    run_full_pilot(cfg, cap, ac, ah, al, av, builder, store, cov, rebal_dates, workload)


def run_full_pilot(cfg, cap, ac, ah, al, av, builder, store, cov, rebal_dates, workload):
    start, end = cfg.backtest.start_date, cfg.backtest.end_date
    bench_ret = get_benchmark_returns(start, end)
    secmap = sector_map()

    specs = [
        ("A. Momentum",              compute_12_1_momentum),
        ("B. Quality",               make_quality_scorer(store)),
        ("C. Mom+LowVol (champion)", make_mom_lowvol_scorer(0.5, VOL_LOOKBACK)),
        ("D. Mom+LowVol+Quality",    make_mom_lowvol_quality_scorer(
            store, W_MOM, W_LOWVOL, W_QUALITY, VOL_LOOKBACK)),
    ]
    variants = {}
    for name, scorer in specs:
        print(f"\n{'-'*84}\n  {name}\n{'-'*84}")
        variants[name] = run_variant(scorer, ac, ah, al, av, cfg, cap, bench_ret, name, builder)
        m = variants[name]["_m"]
        print(f"  CAGR {m.cagr:.2%} | MaxDD {m.max_drawdown:.2%} | Sharpe {m.sharpe_ratio:.2f}")

    # benchmark aligned to realized span
    _eq = variants["A. Momentum"]["equity_curve"]
    bench_eq = get_benchmark_equity_curve(str(_eq.index[0].date()), str(_eq.index[-1].date()), cap)
    bm_cagr = compute_metrics(bench_eq, initial_capital=cap).cagr if not bench_eq.empty else np.nan
    bm_annual = annual_returns(bench_eq) if not bench_eq.empty else pd.Series(dtype=float)

    # validation framework
    for name in variants:
        variants[name]["_split"] = split_sample(variants[name], cfg, ac)
        variants[name]["_conc"] = concentration_stats(variants[name]["trades"], ac, secmap)

    make_charts(variants, bench_eq, bm_annual)
    verdict = write_report(variants, cap, bm_cagr, bm_annual, bench_eq, store, cov, workload)
    write_comparison_csv(variants, bm_cagr)
    write_factor_breakdown(store, builder, ac, rebal_dates, secmap)
    write_holdings_csv(variants)
    write_contributions(variants, ac)
    print(f"\n  All outputs in: {RDIR}/")
    print(f"  VERDICT: {verdict}")


# ─────────────────────────────────────────────────────────────────────
# PLUMBING SELF-TEST  (proves the framework is wired; produces NO conclusion)
# ─────────────────────────────────────────────────────────────────────

def plumbing_self_test(store, close_panel, builder, rebal_dates):
    print("\n  Plumbing self-test (scorers execute on the frozen engine path):")
    d = rebal_dates[len(rebal_dates) // 2]
    u = builder.build_universe(d)
    syms = u.symbols if u and u.symbols else []
    scorers = {
        "A. Momentum": compute_12_1_momentum,
        "B. Quality": make_quality_scorer(store),
        "C. Mom+LowVol (champion)": make_mom_lowvol_scorer(0.5, VOL_LOOKBACK),
        "D. Mom+LowVol+Quality": make_mom_lowvol_quality_scorer(
            store, W_MOM, W_LOWVOL, W_QUALITY, VOL_LOOKBACK),
    }
    for name, sc in scorers.items():
        try:
            s = sc(close_panel, d, syms)
            print(f"    [OK] {name:<26} returned {len(s):>3} ranked names "
                  f"({'needs fundamentals' if name.startswith(('B','D')) and len(s)==0 else 'live'})")
        except Exception as e:  # pragma: no cover
            print(f"    [FAIL] {name}: {e}")


# ─────────────────────────────────────────────────────────────────────
# PENDING-STATE OUTPUTS
# ─────────────────────────────────────────────────────────────────────

def write_pending_outputs(store, cov, workload, median_both, cap):
    L = []; w = L.append
    w("=" * 84)
    w("PHASE 2A — MOMENTUM + QUALITY PILOT".center(84))
    w("STATUS: FRAMEWORK READY — DATA PENDING".center(84))
    w("=" * 84)
    w("")
    w("The complete pilot framework is built and wired to the frozen Phase-1 champion")
    w("engine (Top10 / quarterly / Buffer20 / equal weight / full Indian cost model).")
    w("It is waiting on ONE thing: verified fundamentals.")
    w("")
    w("DATA SOURCE (single, hand-filled, no network):")
    w(f"   {store.csv_path}")
    w(f"   template rows     : {store.n_template_rows} company-years, {store.n_companies} companies")
    w(f"   verified + usable : {store.n_verified_rows}")
    w(f"   manual workload   : ~{workload} rows x 5 fields = ~{workload*5} cells")
    w("")
    w("FIELDS TO FILL (per company-year row), then set verified=TRUE:")
    w("   gross_profit, total_assets, net_profit, total_equity   (revenue+cogs optional;")
    w("   gross_profit is auto-derived as revenue-cogs if left blank). filing_date is the")
    w("   PIT gatekeeper — use the real exchange announcement date where known; otherwise")
    w(f"   the engine falls back to period_end + {REPORTING_LAG_DAYS} days.")
    w("")
    w("QUALITY METRICS (derived, never imported):")
    for k, lab in METRICS.items():
        w(f"   {lab}")
    w("")
    w("COVERAGE GATE (why no verdict yet):")
    w(f"   median quality-covered names in the top-500 universe per rebalance = {median_both}")
    w(f"   required to form a Top{N_STOCKS} quality portfolio (B/D)            = {MIN_COVERED_FOR_VERDICT}")
    w("   Below the threshold, B (Quality) and D (Mom+LowVol+Quality) cannot be formed,")
    w("   so producing any PASS/FAIL would be noise. Held back by design.")
    w("")
    w("VARIANTS THAT WILL RUN ONCE DATA IS PRESENT:")
    w("   A. Momentum             — 12-1 momentum (needs no fundamentals)")
    w("   B. Quality              — GP/Assets + ROE composite")
    w("   C. Mom+LowVol (champion)— the bar to beat")
    w("   D. Mom+LowVol+Quality   — quality-tilted champion")
    w("")
    w("VALIDATION THAT WILL RUN: full period · split sample · rolling windows ·")
    w("   concentration · sector concentration · contribution analysis.")
    w("")
    w("SUCCESS CRITERION (pre-registered): D improves Sharpe and/or CAGR vs champion C")
    w("   without worsening drawdown by >3 pts, AND survives split-sample + rolling-window")
    w("   validation (no sign-flip across halves). Else FAIL.")
    w("")
    w("=" * 84)
    w("PENDING — fundamentals not yet populated/verified; NO backtest conclusion produced.")
    w("Fill + verify pilot_fundamentals.csv, then re-run:  py run_momentum_quality.py")
    w("=" * 84)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")

    # Stub deliverables that document their future schema (status=PENDING, no metrics).
    pd.DataFrame([
        {"variant": "A. Momentum", "definition": "12-1 momentum", "data_status": "ready"},
        {"variant": "B. Quality", "definition": "GP/Assets + ROE composite", "data_status": "PENDING"},
        {"variant": "C. Mom+LowVol (champion)", "definition": "0.5 mom + 0.5 lowvol", "data_status": "ready"},
        {"variant": "D. Mom+LowVol+Quality",
         "definition": f"{W_MOM} mom + {W_LOWVOL} lowvol + {W_QUALITY} quality", "data_status": "PENDING"},
    ]).to_csv(RDIR / "comparison.csv", index=False)
    cov.to_csv(RDIR / "coverage_by_rebalance.csv", index=False)
    pd.DataFrame(columns=["date", "symbol", "mom_pct", "lowvol_pct", "gp_pct", "roe_pct",
                          "quality_composite", "sector"]).to_csv(RDIR / "factor_breakdown.csv", index=False)
    pd.DataFrame(columns=["variant", "date", "symbol", "shares"]).to_csv(RDIR / "holdings.csv", index=False)
    make_pending_chart(store, cov)


def make_pending_chart(store, cov):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(16, 9))
    gs = GridSpec(2, 1, figure=fig, hspace=0.35)
    fig.suptitle("Momentum + Quality Pilot — FRAMEWORK READY, DATA PENDING",
                 fontsize=15, fontweight="bold", color="#fff")

    ax1 = fig.add_subplot(gs[0])
    fs = store.fill_status()
    if not fs.empty:
        piv = fs.assign(v=fs["filled"].astype(int)).pivot_table(
            index="symbol", columns="fiscal_year", values="v", aggfunc="max")
        ax1.imshow(piv.fillna(0).values, aspect="auto", cmap="Greens", vmin=0, vmax=1)
        ax1.set_yticks(range(len(piv.index))); ax1.set_yticklabels(piv.index, fontsize=6)
        ax1.set_xticks(range(len(piv.columns))); ax1.set_xticklabels(piv.columns, fontsize=7, rotation=90)
    ax1.set_title(f"Fundamentals fill matrix — {store.n_verified_rows}/{store.n_template_rows} "
                  f"company-years verified (green=filled)", fontweight="bold")

    ax2 = fig.add_subplot(gs[1])
    if not cov.empty:
        ax2.plot(pd.to_datetime(cov["date"]), cov["both"], color="#ffd93d", lw=1.6, label="quality-covered")
        ax2.axhline(MIN_COVERED_FOR_VERDICT, color="#ff6b6b", ls="--", lw=1,
                    label=f"Top{N_STOCKS} threshold")
    ax2.set_title("Quality-covered names in top-500 universe per rebalance", fontweight="bold")
    ax2.legend(framealpha=.3); ax2.grid(True, alpha=.2)
    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  Chart saved: {RDIR / 'report.png'}")


# ─────────────────────────────────────────────────────────────────────
# FULL-RESULT OUTPUTS  (only reached when data is present)
# ─────────────────────────────────────────────────────────────────────

def evaluate_verdict(variants):
    C, D = variants["C. Mom+LowVol (champion)"]["_m"], variants["D. Mom+LowVol+Quality"]["_m"]
    dsharpe, dcagr = D.sharpe_ratio - C.sharpe_ratio, D.cagr - C.cagr
    ddd = D.max_drawdown - C.max_drawdown   # positive = shallower (better)
    improves = (dsharpe >= EPS_SHARPE) or (dcagr >= EPS_CAGR)
    dd_ok = ddd >= -MAXDD_TOLERANCE
    s = variants["D. Mom+LowVol+Quality"]["_split"]
    cs = variants["C. Mom+LowVol (champion)"]["_split"]
    # No sign-flip: D must beat C (by CAGR) in BOTH halves, or at least not flip sign.
    h1 = s.get("cagr_h1", np.nan) - cs.get("cagr_h1", np.nan)
    h2 = s.get("cagr_h2", np.nan) - cs.get("cagr_h2", np.nan)
    no_flip = (np.sign(h1) == np.sign(h2)) and (h1 > 0) and (h2 > 0)
    roll_ok = variants["D. Mom+LowVol+Quality"]["_roll3y"].min() >= \
        variants["C. Mom+LowVol (champion)"]["_roll3y"].min() - 0.05 \
        if not variants["D. Mom+LowVol+Quality"]["_roll3y"].empty else False
    passed = improves and dd_ok and no_flip and roll_ok
    return passed, dict(dsharpe=dsharpe, dcagr=dcagr, ddd=ddd, improves=improves,
                        dd_ok=dd_ok, no_flip=no_flip, roll_ok=roll_ok, h1=h1, h2=h2)


def write_report(variants, cap, bm_cagr, bm_annual, bench_eq, store, cov, workload):
    names = list(variants.keys())
    L = []; w = L.append
    def row(lbl, fmt):
        return f"{lbl:<24}" + "".join(f"{fmt(variants[n]):>22}" for n in names)

    w("=" * 112)
    w("PHASE 2A — MOMENTUM + QUALITY PILOT  (frozen champion: Top10/Quarterly/Buffer20)".center(112))
    w("Survivorship-free · equity-only top-500 liquid · net of Indian costs".center(112))
    w("=" * 112)
    w(f"Capital Rs {cap:,.0f}   Period {variants[names[0]]['_m'].start_date}..{variants[names[0]]['_m'].end_date}")
    w(f"Quality: GP/Assets + ROE composite, PIT (filing_date else period_end +{REPORTING_LAG_DAYS}d), verified-only.")
    w(f"D blend weights: mom {W_MOM} / lowvol {W_LOWVOL} / quality {W_QUALITY}.")
    w(f"Verified quality rows: {store.n_verified_rows}/{store.n_template_rows}; "
      f"median covered/rebalance: {int(cov['both'].median())}.")
    w("")
    w(f"{'Metric':<24}" + "".join(f"{n:>22}" for n in names)); w("-" * 112)
    w(row("CAGR (net)",        lambda v: f"{v['_m'].cagr:.2%}"))
    w(row("CAGR (gross)",      lambda v: f"{v['_gross_cagr']:.2%}"))
    w(row("Max Drawdown",      lambda v: f"{v['_m'].max_drawdown:.2%}"))
    w(row("Sharpe",            lambda v: f"{v['_m'].sharpe_ratio:.2f}"))
    w(row("Sortino",           lambda v: f"{v['_m'].sortino_ratio:.2f}"))
    w(row("Calmar",            lambda v: f"{v['_m'].calmar_ratio:.2f}"))
    w(row("Annual Vol",        lambda v: f"{v['_m'].annualised_volatility:.2%}"))
    w(row("Alpha (Jensen)",    lambda v: f"{v['_m'].alpha:+.2%}"))
    w(row("Excess vs Bmk",     lambda v: f"{v['_m'].cagr-bm_cagr:+.2%}"))
    w(row("Beta",              lambda v: f"{v['_m'].beta:.2f}"))
    w(row("Avg Turnover/Reb",  lambda v: f"{v['avg_turnover']:.1%}"))
    w(row("Time Underwater",   lambda v: f"{v['_extra']['time_underwater_pct']:.1%}"))
    w(row("Final Value (Rs)",  lambda v: f"{v['equity_curve'].iloc[-1]:,.0f}"))
    w("-- concentration --")
    w(row("Avg # names",       lambda v: f"{v['_conc']['avg_names']:.1f}"))
    w(row("Name HHI",          lambda v: f"{v['_conc']['name_hhi']:.3f}"))
    w(row("Avg max sector wt", lambda v: f"{v['_conc']['avg_max_sector_wt']:.1%}"))
    w("-- split sample (CAGR) --")
    w(row("First half CAGR",   lambda v: f"{v['_split'].get('cagr_h1', float('nan')):.2%}"))
    w(row("Second half CAGR",  lambda v: f"{v['_split'].get('cagr_h2', float('nan')):.2%}"))
    w(row("Roll 3y min",       lambda v: f"{v['_roll3y'].min():.1%}" if not v['_roll3y'].empty else "N/A"))
    w(row("Roll 3y median",    lambda v: f"{v['_roll3y'].median():.1%}" if not v['_roll3y'].empty else "N/A"))
    w("-" * 112)
    w(f"NIFTY 500 price-index CAGR: {bm_cagr:.2%} (true TRI ~ {bm_cagr+0.013:.2%})")
    w("")

    passed, dd = evaluate_verdict(variants)
    w("VERDICT".center(112, "-"))
    w("Pre-registered: D beats champion C on Sharpe and/or CAGR, drawdown not >3pts worse,")
    w("and survives split-sample + rolling-window validation (no sign-flip).")
    w(f"  D vs C:  dSharpe {dd['dsharpe']:+.2f} | dCAGR {dd['dcagr']:+.2%} | "
      f"dMaxDD {dd['ddd']:+.2%} ({'shallower' if dd['ddd']>=0 else 'deeper'})")
    w(f"  Improves Sharpe/CAGR : {dd['improves']}")
    w(f"  Drawdown within 3pts : {dd['dd_ok']}")
    w(f"  Split-sample no-flip : {dd['no_flip']}  (h1 dCAGR {dd['h1']:+.2%}, h2 dCAGR {dd['h2']:+.2%})")
    w(f"  Rolling-window OK    : {dd['roll_ok']}")
    w("")
    if passed:
        verdict = "PASS — Quality adds enough validated value to justify building the PIT fundamentals platform."
    else:
        verdict = "FAIL — Quality does not justify building the PIT fundamentals platform."
    w(verdict)
    w("=" * 112)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")
    return verdict


def write_comparison_csv(variants, bm_cagr):
    rows = []
    for n, v in variants.items():
        m, e, c = v["_m"], v["_extra"], v["_conc"]
        s = v["_split"]
        rows.append({"variant": n, "cagr": m.cagr, "gross_cagr": v["_gross_cagr"],
                     "max_drawdown": m.max_drawdown, "sharpe": m.sharpe_ratio,
                     "sortino": m.sortino_ratio, "calmar": m.calmar_ratio,
                     "annual_vol": m.annualised_volatility, "alpha": m.alpha, "beta": m.beta,
                     "excess_vs_bm": m.cagr - bm_cagr, "avg_turnover": v["avg_turnover"],
                     "time_underwater": e["time_underwater_pct"],
                     "avg_names": c["avg_names"], "name_hhi": c["name_hhi"],
                     "avg_max_sector_wt": c["avg_max_sector_wt"], "top_sector": c["top_sector"],
                     "cagr_h1": s.get("cagr_h1"), "cagr_h2": s.get("cagr_h2"),
                     "roll3y_min": v["_roll3y"].min() if not v["_roll3y"].empty else np.nan,
                     "roll3y_med": v["_roll3y"].median() if not v["_roll3y"].empty else np.nan,
                     "final_value": v["equity_curve"].iloc[-1]})
    pd.DataFrame(rows).to_csv(RDIR / "comparison.csv", index=False)


def write_factor_breakdown(store, builder, close_panel, rebal_dates, secmap):
    from run_momentum_lowvol import compute_realized_vol
    rows = []
    for d in rebal_dates:
        u = builder.build_universe(d)
        syms = u.symbols if u and u.symbols else []
        if not syms:
            continue
        mom = compute_12_1_momentum(close_panel, d, syms)
        vol = compute_realized_vol(close_panel, d, syms, VOL_LOOKBACK)
        gp = store.metric_panel(d, syms, "gross_profitability")
        roe = store.metric_panel(d, syms, "roe")
        mom_p = mom.rank(pct=True); vol_p = (-vol).rank(pct=True)
        gp_p = gp.rank(pct=True); roe_p = roe.rank(pct=True)
        covered = set(gp.index) | set(roe.index)
        for s in covered:
            qc = np.nanmean([gp_p.get(s, np.nan), roe_p.get(s, np.nan)])
            rows.append({"date": d.date(), "symbol": s,
                         "mom_pct": mom_p.get(s, np.nan), "lowvol_pct": vol_p.get(s, np.nan),
                         "gp_pct": gp_p.get(s, np.nan), "roe_pct": roe_p.get(s, np.nan),
                         "quality_composite": qc, "sector": secmap.get(s, "Unknown")})
    pd.DataFrame(rows, columns=["date", "symbol", "mom_pct", "lowvol_pct", "gp_pct",
                                "roe_pct", "quality_composite", "sector"]
                 ).to_csv(RDIR / "factor_breakdown.csv", index=False)


def write_holdings_csv(variants):
    frames = []
    for n, v in variants.items():
        h = reconstruct_holdings(v["trades"])
        if not h.empty:
            h.insert(0, "variant", n)
            frames.append(h)
    out = pd.concat(frames, ignore_index=True) if frames else \
        pd.DataFrame(columns=["variant", "date", "symbol", "shares"])
    out.to_csv(RDIR / "holdings.csv", index=False)


def write_contributions(variants, close_panel):
    frames = []
    for n in ["C. Mom+LowVol (champion)", "D. Mom+LowVol+Quality"]:
        c = contribution_analysis(variants[n]["trades"], close_panel)
        c.insert(0, "variant", n)
        frames.append(c)
    pd.concat(frames, ignore_index=True).to_csv(RDIR / "contributions.csv", index=False)


def make_charts(variants, bench_eq, bm_annual):
    plt.style.use("dark_background")
    names = list(variants.keys())
    fig = plt.figure(figsize=(18, 20))
    gs = GridSpec(4, 2, figure=fig, hspace=0.38, wspace=0.22)
    fig.suptitle("Momentum + Quality Pilot — A/B/C/D (Top10 / Quarterly / Buffer20, net)",
                 fontsize=15, fontweight="bold", color="#fff")

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for n in names:
        eq = variants[n]["equity_curve"]; ax1.plot(eq.index, eq/eq.iloc[0]*100, color=PALETTE[n], lw=1.7, label=n)
    if bench_eq is not None and not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq/bench_eq.iloc[0]*100, color="#888", lw=1.2, ls="--", label="NIFTY 500 (px)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[1, :]); ax2.set_title("Drawdown", fontweight="bold")
    for n in names:
        eq = variants[n]["equity_curve"]; dd = (eq-eq.cummax())/eq.cummax()*100
        ax2.plot(dd.index, dd, color=PALETTE[n], lw=1.1, label=n)
    ax2.legend(loc="lower left", framealpha=.3); ax2.grid(True, alpha=.2)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax3 = fig.add_subplot(gs[2, 0]); ax3.set_title("CAGR vs Max DD", fontweight="bold")
    cagrs = [variants[n]["_m"].cagr*100 for n in names]; dds = [abs(variants[n]["_m"].max_drawdown)*100 for n in names]
    b = ax3.bar(range(len(names)), cagrs, color=[PALETTE[n] for n in names])
    for bb, cc in zip(b, cagrs):
        ax3.text(bb.get_x()+bb.get_width()/2, bb.get_height(), f"{cc:.1f}", ha="center", va="bottom", color="#fff")
    a3 = ax3.twinx(); a3.plot(range(len(names)), dds, color="#ff6b6b", marker="o"); a3.set_ylabel("MaxDD%", color="#ff6b6b")
    ax3.set_xticks(range(len(names))); ax3.set_xticklabels([n[:2] for n in names]); ax3.set_ylabel("CAGR%")

    ax4 = fig.add_subplot(gs[2, 1]); ax4.set_title("Sharpe", fontweight="bold")
    ax4.bar(range(len(names)), [variants[n]["_m"].sharpe_ratio for n in names],
            color=[PALETTE[n] for n in names])
    ax4.set_xticks(range(len(names))); ax4.set_xticklabels([n[:2] for n in names]); ax4.grid(True, alpha=.2, axis="y")

    ax5 = fig.add_subplot(gs[3, :]); ax5.set_title("Rolling 3-Year CAGR", fontweight="bold")
    for n in names:
        r = variants[n]["_roll3y"]
        if not r.empty:
            ax5.plot(r.index, r*100, color=PALETTE[n], lw=1.3, label=n)
    ax5.axhline(0, color="white", lw=.5, ls="--", alpha=.3)
    ax5.legend(loc="upper right", framealpha=.3); ax5.grid(True, alpha=.2)
    ax5.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  Chart saved: {RDIR / 'report.png'}")


# ─────────────────────────────────────────────────────────────────────
# WALKTHROUGH
# ─────────────────────────────────────────────────────────────────────

def write_walkthrough(workload, median_both):
    txt = f"""# Phase 2A — Momentum + Quality Pilot — WALKTHROUGH

## What this is
The smallest possible test of one question: **does a Quality factor add validated value
on top of the frozen Phase-1 champion (Momentum + LowVol, Top10 / quarterly / Buffer20)?**
Nothing in the engine, costs, execution, portfolio, turnover, or universe is modified.
Quality enters only as a new drop-in scorer — exactly as every Phase-1 factor did.

## Files
| File | Role |
|---|---|
| `quality_store.py` | `QualityStore` (PIT-gated reader over the fundamentals CSV) + the two new scorers (`make_quality_scorer`, `make_mom_lowvol_quality_scorer`). The only new dependency. |
| `run_momentum_quality.py` | A/B/C/D runner + validation framework + report/chart/CSV generation. |
| `data/cache_fundamentals/pilot_fundamentals.csv` | **The single data source.** Hand-filled, verified, no network. |
| `results/momentum_quality_pilot/` | All outputs. |

## The four variants
- **A. Momentum** — 12-1 momentum (needs no fundamentals).
- **B. Quality** — equal-weight percentile of gross-profitability (GP/Assets) + ROE.
- **C. Mom + LowVol** — the frozen champion, the bar to beat.
- **D. Mom + LowVol + Quality** — champion tilted by Quality
  (weights mom {W_MOM} / lowvol {W_LOWVOL} / quality {W_QUALITY}).

## Quality metrics (derived here, never imported)
- Gross Profitability = `gross_profit / total_assets` (Novy-Marx 2013).
- ROE = `net_profit / total_equity`.

## Point-in-time rule (the look-ahead gate)
A rebalance at date T may only read a report whose **knowledge date ≤ T − {SAFETY_LAG_DAYS}d**:
- `knowledge_date = filing_date` when the real exchange announcement date is filled;
- else `period_end + {REPORTING_LAG_DAYS} days` (a conservative fixed policy, >3 months,
  per PHASE1_DECISION). Reading by `period_end` alone would leak.
Only rows with `verified == TRUE` are ever used (the Phase-1 data-hygiene gate).

## How to populate the data (the only manual step)
Open `data/cache_fundamentals/pilot_fundamentals.csv`. For each company-year row fill:
`gross_profit, total_assets, net_profit, total_equity` (and `filing_date` where known;
`revenue`+`cogs` optional — `gross_profit` is auto-derived as `revenue − cogs` if blank).
Then set `verified = TRUE` on each checked row.

**Workload at current scope: ~{workload} rows × ~5 fields ≈ ~{workload*5} cells.**
Currently {median_both} names are quality-covered per rebalance (need ≥ {N_STOCKS} to form
B/D). If that workload is too large, reduce scope first (see below) — the framework is
scope-independent and will run at any N.

### Reduce scope (optional)
`pilot_select_companies.py` builds the company sample; lower its `TARGET_N` (e.g. 15–20)
and re-run it to regenerate a smaller `pilot_company_list.csv` + `pilot_fundamentals.csv`
template, then fill that. Fewer companies = fewer rows to fill, at the cost of thinner
cross-sectional coverage.

## Run
```
py run_momentum_quality.py
```
- **If the CSV is empty/unverified** → prints a PENDING report + a plumbing self-test
  (proves the scorers execute on the frozen engine) and stops. **No backtest, no verdict.**
- **Once enough rows are verified** → runs A/B/C/D, the full validation framework, and
  emits the verdict.

## Validation framework (same discipline as Phase 1)
full period · split sample (first vs second half — the FIP sign-flip test) · rolling 3-yr
windows · name concentration (HHI, avg # names) · sector concentration · contribution
analysis (per-name P&L from the trade log).

## Success criterion (pre-registered)
**D must improve Sharpe and/or CAGR vs champion C, without worsening drawdown by >3 pts,
AND survive split-sample + rolling-window validation (no sign-flip across halves).**
Otherwise **FAIL**, regardless of full-period performance. The report ends with exactly one of:
- `PASS — Quality adds enough validated value to justify building the PIT fundamentals platform.`
- `FAIL — Quality does not justify building the PIT fundamentals platform.`

## Outputs (`results/momentum_quality_pilot/`)
`report.txt` · `report.png` · `comparison.csv` · `factor_breakdown.csv` · `holdings.csv` ·
`contributions.csv` · `coverage_by_rebalance.csv`.
"""
    (RDIR / "WALKTHROUGH.md").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
