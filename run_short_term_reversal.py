"""
PHASE 2B — EXPERIMENT #1: SHORT-TERM REVERSAL  (standalone, survivorship-free).

QUESTION: Can a Short-Term Reversal style compete with the frozen Momentum + LowVol
champion *inside the existing framework*?

NOTHING in the engine, cost model, universe construction, benchmark methodology, or
rebalance framework is modified. Reversal enters ONLY as a new drop-in scorer, exactly
as every Phase-1 factor did (`run_buffered_backtest` is reused verbatim).

SIGNAL (the only new thing):
    Rank stocks by their most recent 21-trading-day return.
    LOWEST return  => HIGHEST rank  (buy recent losers).
    No skip, no smoothing, no parameter search.

SHELL (frozen, identical to the champion):
    survivorship-free, equity-only (ISIN INE), top-500-liquid point-in-time universe;
    equal weight; Buffer20; full Indian delivery cost model; gross AND net.

VARIANTS:
    A. Short-Term Reversal — Top3 / Top5 / Top10, QUARTERLY first.
       If quarterly turnover is extreme, ALSO run monthly and report the difference.
    Bar to beat:
    C. Momentum + LowVol champion — Top10 / Quarterly / Buffer20  (the frozen product).

    Do NOT blend reversal with momentum. Do NOT optimise parameters.

VALIDATION (same discipline as Phase 1): split sample · rolling 3y windows ·
    name-concentration (avg # names, HHI).

REPORT: CAGR · Sharpe · Calmar · MaxDD · Alpha · Beta · Vol · Turnover · Costs, vs champion.

PRE-REGISTERED VERDICT (viability as an alternative style, judged on the BEST reversal
config by Sharpe, all NET of costs):
    PASS — Mean Reversion merits further research   IF ALL of:
        (1) net CAGR  > NIFTY 500 benchmark CAGR
        (2) net Jensen alpha > 0
        (3) Sharpe >= 0.45                  (materially positive; ~2/3 of champion)
        (4) survives split-sample           (CAGR positive in BOTH halves; no sign-flip)
    else:
    FAIL — Momentum remains the superior style.

Run:  py run_short_term_reversal.py
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
from analytics.metrics import compute_metrics
from utils.helpers import get_rebalance_dates

from run_buffer_experiment import (
    run_buffered_backtest, drawdown_analytics, rolling_3y_cagr, annual_returns,
)
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK
from run_survivorship_validation import TopNTurnoverUniverseBuilder

# ── Frozen shell ───────────────────────────────────────────────────────
BUFFER, FREQ = 20, "quarterly"
REVERSAL_LOOKBACK = 21          # most recent 21 trading days (~1 month)
CHAMPION_N = 10                 # the frozen champion is Top10
SIZES = [3, 5, 10]             # reversal across Top3 / Top5 / Top10
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "short_term_reversal"

# "Extreme" quarterly turnover that triggers an additional monthly evaluation.
EXTREME_TURNOVER = 0.50
# Pre-registered viability thresholds (see module docstring).
SHARPE_BAR = 0.45

CHAMPION_LABEL = "Champion Mom+LowVol T10"
PALETTE = {
    "STR Top3":  "#ff6b6b",
    "STR Top5":  "#ffa94d",
    "STR Top10": "#ffd93d",
    CHAMPION_LABEL: "#00ff88",
}


# ─────────────────────────────────────────────────────────────────────
# SIGNAL  (the only new code)
# ─────────────────────────────────────────────────────────────────────

def compute_str_reversal(close_panel, date, universe, lookback=REVERSAL_LOOKBACK):
    """Short-term reversal scorer.

    score = -(most-recent `lookback`-day return). Biggest recent loser => highest
    score => selected first. Returned sorted best->worst so `select_with_buffer`
    reads index order as rank (rank 1 = best), exactly like the momentum scorer.
    """
    cols = [s for s in universe if s in close_panel.columns]
    prices = close_panel.loc[close_panel.index <= date, cols]
    if len(prices) < lookback + 1:
        return pd.Series(dtype=float)
    ret = (prices.iloc[-1] / prices.iloc[-(lookback + 1)]) - 1
    ret = ret.replace([np.inf, -np.inf], np.nan).dropna()
    if ret.empty:
        return pd.Series(dtype=float)
    return (-ret).sort_values(ascending=False)   # most negative return first


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


# ─────────────────────────────────────────────────────────────────────
# RUNNER + VALIDATION ANALYTICS  (engine untouched)
# ─────────────────────────────────────────────────────────────────────

def run_variant(scorer, n_stocks, freq, c, h, l, v, cfg, cap, bench_ret, label, builder):
    common = dict(n_stocks=n_stocks, rebalance_freq=freq, buffer=BUFFER,
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
    net["_n"] = n_stocks
    net["_freq"] = freq
    return net


def reconstruct_holdings(trades):
    """Period-end share positions after each rebalance, rebuilt from the trade log."""
    pos, rows = {}, []
    for d, grp in (pd.DataFrame(trades).groupby("date") if trades else []):
        for _, t in grp.iterrows():
            pos[t["symbol"]] = pos.get(t["symbol"], 0) + (t["shares"] if t["side"] == "BUY" else -t["shares"])
        for sym, q in pos.items():
            if q > 0:
                rows.append({"date": d, "symbol": sym, "shares": int(q)})
    return pd.DataFrame(rows, columns=["date", "symbol", "shares"])


def concentration_stats(trades, close_panel):
    """Name-level concentration averaged over rebalance snapshots (avg # names, HHI)."""
    hold = reconstruct_holdings(trades)
    if hold.empty:
        return {"avg_names": np.nan, "name_hhi": np.nan, "max_name_wt": np.nan}
    n_names, hhi, max_wt = [], [], []
    ff = close_panel.ffill()
    for d, grp in hold.groupby("date"):
        px = ff.loc[d] if d in ff.index else ff.loc[:d].iloc[-1]
        val = {r["symbol"]: r["shares"] * px.get(r["symbol"], np.nan) for _, r in grp.iterrows()}
        val = {s: x for s, x in val.items() if x and x > 0}
        tot = sum(val.values())
        if tot <= 0:
            continue
        w = {s: x / tot for s, x in val.items()}
        n_names.append(len(w))
        hhi.append(sum(x * x for x in w.values()))
        max_wt.append(max(w.values()))
    return {"avg_names": float(np.mean(n_names)), "name_hhi": float(np.mean(hhi)),
            "max_name_wt": float(np.mean(max_wt))}


def split_sample(net):
    """First-half vs second-half CAGR/Sharpe of a variant's equity curve."""
    eq = net["equity_curve"].dropna()
    if len(eq) < 8:
        return {}
    mid = eq.index[len(eq) // 2]
    h1, h2 = eq.loc[:mid], eq.loc[mid:]
    m1 = compute_metrics(h1, initial_capital=h1.iloc[0])
    m2 = compute_metrics(h2, initial_capital=h2.iloc[0])
    return {"split_date": mid.date(), "cagr_h1": m1.cagr, "cagr_h2": m2.cagr,
            "sharpe_h1": m1.sharpe_ratio, "sharpe_h2": m2.sharpe_ratio}


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital
    start, end = cfg.backtest.start_date, cfg.backtest.end_date
    RDIR.mkdir(parents=True, exist_ok=True)

    print("=" * 88)
    print("  PHASE 2B #1 — SHORT-TERM REVERSAL vs MOMENTUM+LOWVOL CHAMPION".center(88))
    print("  survivorship-free · equity-only top-500 liquid · Buffer20 · net of Indian costs".center(88))
    print("=" * 88)

    bench_ret = get_benchmark_returns(start, end)
    print("\n  Loading survivorship-free bhavcopy panels ...")
    ac, ah, al, av, at, builder = load_panels_and_builder(cfg)
    print(f"  panel: {ac.shape[0]} dates x {ac.shape[1]} equity symbols")

    # ── A. Short-Term Reversal, QUARTERLY, Top3/5/10 ──
    variants = {}
    for n in SIZES:
        label = f"STR Top{n}"
        print(f"\n{'-'*88}\n  {label}  (quarterly, buffer{BUFFER}, 21d reversal)\n{'-'*88}")
        variants[label] = run_variant(compute_str_reversal, n, FREQ, ac, ah, al, av,
                                       cfg, cap, bench_ret, label, builder)
        m = variants[label]["_m"]
        print(f"  CAGR {m.cagr:.2%} | MaxDD {m.max_drawdown:.2%} | Sharpe {m.sharpe_ratio:.2f} | "
              f"Turnover/reb {variants[label]['avg_turnover']:.1%}")

    # ── C. Champion (the bar to beat): Mom+LowVol Top10 / quarterly / Buffer20 ──
    print(f"\n{'-'*88}\n  {CHAMPION_LABEL}  (quarterly, buffer{BUFFER})\n{'-'*88}")
    champ_scorer = make_mom_lowvol_scorer(0.5, VOL_LOOKBACK)
    variants[CHAMPION_LABEL] = run_variant(champ_scorer, CHAMPION_N, FREQ, ac, ah, al, av,
                                           cfg, cap, bench_ret, CHAMPION_LABEL, builder)
    m = variants[CHAMPION_LABEL]["_m"]
    print(f"  CAGR {m.cagr:.2%} | MaxDD {m.max_drawdown:.2%} | Sharpe {m.sharpe_ratio:.2f} | "
          f"Turnover/reb {variants[CHAMPION_LABEL]['avg_turnover']:.1%}")

    # Validation analytics for every variant.
    for name in variants:
        variants[name]["_split"] = split_sample(variants[name])
        variants[name]["_conc"] = concentration_stats(variants[name]["trades"], ac)

    # ── Turnover-triggered MONTHLY evaluation of reversal ──
    rev_quarterly = [f"STR Top{n}" for n in SIZES]
    max_rev_turn = max(variants[k]["avg_turnover"] for k in rev_quarterly)
    monthly = {}
    if max_rev_turn >= EXTREME_TURNOVER:
        print(f"\n  >>> Quarterly reversal turnover is extreme (max {max_rev_turn:.1%} >= "
              f"{EXTREME_TURNOVER:.0%}). Running MONTHLY for comparison ...")
        for n in SIZES:
            label = f"STR Top{n}"
            print(f"\n  {label}  (MONTHLY)")
            mv = run_variant(compute_str_reversal, n, "monthly", ac, ah, al, av,
                             cfg, cap, bench_ret, label + " (M)", builder)
            mv["_split"] = split_sample(mv)
            mv["_conc"] = concentration_stats(mv["trades"], ac)
            monthly[label] = mv
            mm = mv["_m"]
            print(f"     CAGR {mm.cagr:.2%} | Sharpe {mm.sharpe_ratio:.2f} | "
                  f"Turnover/reb {mv['avg_turnover']:.1%}")
    else:
        print(f"\n  Quarterly reversal turnover not extreme (max {max_rev_turn:.1%} < "
              f"{EXTREME_TURNOVER:.0%}); monthly evaluation skipped.")

    # Benchmark aligned to the realized span (same fix as the champion run).
    _eq = variants[CHAMPION_LABEL]["equity_curve"]
    bench_eq = get_benchmark_equity_curve(str(_eq.index[0].date()), str(_eq.index[-1].date()), cap)
    bm_cagr = compute_metrics(bench_eq, initial_capital=cap).cagr if not bench_eq.empty else np.nan
    bm_annual = annual_returns(bench_eq) if not bench_eq.empty else pd.Series(dtype=float)
    print(f"\n  benchmark aligned to span: NIFTY500(px) CAGR {bm_cagr:.2%}")

    make_charts(variants, bench_eq, bm_annual)
    verdict = write_report(variants, monthly, cap, bm_cagr, bm_annual, bench_eq, max_rev_turn)
    write_comparison_csv(variants, monthly, bm_cagr)
    write_walkthrough(max_rev_turn, bool(monthly))
    print(f"\n  All outputs in: {RDIR}/")
    print(f"  VERDICT: {verdict}")


# ─────────────────────────────────────────────────────────────────────
# VERDICT
# ─────────────────────────────────────────────────────────────────────

def best_reversal(variants):
    rev = {k: v for k, v in variants.items() if k.startswith("STR ")}
    return max(rev, key=lambda k: rev[k]["_m"].sharpe_ratio)


def evaluate_verdict(variants, bm_cagr):
    best = best_reversal(variants)
    v = variants[best]; m = v["_m"]; s = v["_split"]
    beats_bm = m.cagr > bm_cagr
    pos_alpha = m.alpha > 0
    sharpe_ok = m.sharpe_ratio >= SHARPE_BAR
    no_flip = (s.get("cagr_h1", -1) > 0) and (s.get("cagr_h2", -1) > 0)
    passed = beats_bm and pos_alpha and sharpe_ok and no_flip
    return passed, best, dict(beats_bm=beats_bm, pos_alpha=pos_alpha,
                              sharpe_ok=sharpe_ok, no_flip=no_flip,
                              cagr=m.cagr, alpha=m.alpha, sharpe=m.sharpe_ratio,
                              h1=s.get("cagr_h1", float("nan")),
                              h2=s.get("cagr_h2", float("nan")))


# ─────────────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────────────

def write_report(variants, monthly, cap, bm_cagr, bm_annual, bench_eq, max_rev_turn):
    names = list(variants.keys())
    L = []; w = L.append
    def row(lbl, fmt):
        return f"{lbl:<24}" + "".join(f"{fmt(variants[n]):>22}" for n in names)

    W = 24 + 22 * len(names)
    w("=" * W)
    w("PHASE 2B #1 — SHORT-TERM REVERSAL vs MOMENTUM+LOWVOL CHAMPION".center(W))
    w("Survivorship-free · equity-only top-500 liquid · Buffer20 · net of Indian costs".center(W))
    w("=" * W)
    w(f"Capital Rs {cap:,.0f}   Period {variants[names[0]]['_m'].start_date}..{variants[names[0]]['_m'].end_date}")
    w(f"Reversal signal: rank by most-recent {REVERSAL_LOOKBACK}-day return, lowest=best (buy losers). "
      f"No skip, no tuning.")
    w("Shell: equal weight / Buffer20 / quarterly / full Indian cost model — IDENTICAL to champion.")
    w(f"Champion: Momentum + LowVol (0.5/0.5), Top{CHAMPION_N} / quarterly / Buffer20 — the frozen product.")
    w("")
    w(f"{'Metric':<24}" + "".join(f"{n:>22}" for n in names)); w("-" * W)
    w(row("CAGR (net)",        lambda v: f"{v['_m'].cagr:.2%}"))
    w(row("CAGR (gross)",      lambda v: f"{v['_gross_cagr']:.2%}"))
    w(row("Sharpe",            lambda v: f"{v['_m'].sharpe_ratio:.2f}"))
    w(row("Calmar",            lambda v: f"{v['_m'].calmar_ratio:.2f}"))
    w(row("Sortino",           lambda v: f"{v['_m'].sortino_ratio:.2f}"))
    w(row("Max Drawdown",      lambda v: f"{v['_m'].max_drawdown:.2%}"))
    w(row("Annual Vol",        lambda v: f"{v['_m'].annualised_volatility:.2%}"))
    w(row("Alpha (Jensen)",    lambda v: f"{v['_m'].alpha:+.2%}"))
    w(row("Beta",              lambda v: f"{v['_m'].beta:.2f}"))
    w(row("Excess vs Bmk",     lambda v: f"{v['_m'].cagr-bm_cagr:+.2%}"))
    w(row("Avg Turnover/Reb",  lambda v: f"{v['avg_turnover']:.1%}"))
    w(row("Txn Costs (Rs)",    lambda v: f"{v['total_costs']:,.0f}"))
    w(row("Cost Drag (pts)",   lambda v: f"{v['_gross_cagr']-v['_m'].cagr:.2%}"))
    w(row("Time Underwater",   lambda v: f"{v['_extra']['time_underwater_pct']:.1%}"))
    w(row("Final Value (Rs)",  lambda v: f"{v['equity_curve'].iloc[-1]:,.0f}"))
    w("-- concentration --")
    w(row("Avg # names",       lambda v: f"{v['_conc']['avg_names']:.1f}"))
    w(row("Name HHI",          lambda v: f"{v['_conc']['name_hhi']:.3f}"))
    w("-- split sample (CAGR) --")
    w(row("First half CAGR",   lambda v: f"{v['_split'].get('cagr_h1', float('nan')):.2%}"))
    w(row("Second half CAGR",  lambda v: f"{v['_split'].get('cagr_h2', float('nan')):.2%}"))
    w(row("Roll 3y min",       lambda v: f"{v['_roll3y'].min():.1%}" if not v['_roll3y'].empty else "N/A"))
    w(row("Roll 3y median",    lambda v: f"{v['_roll3y'].median():.1%}" if not v['_roll3y'].empty else "N/A"))
    w("-" * W)
    w(f"NIFTY 500 price-index CAGR: {bm_cagr:.2%} (true TRI ~ {bm_cagr+0.013:.2%})")
    w("")

    # ── Monthly comparison (only if triggered) ──
    if monthly:
        w("MONTHLY vs QUARTERLY (reversal) — triggered because quarterly turnover was extreme".center(W, "-"))
        w(f"{'Config':<16}{'CAGR(Q)':>12}{'CAGR(M)':>12}{'Sharpe(Q)':>12}{'Sharpe(M)':>12}"
          f"{'Turn(Q)':>12}{'Turn(M)':>12}{'Cost(Q)':>14}{'Cost(M)':>14}")
        for n in [f"STR Top{s}" for s in SIZES]:
            q, mo = variants[n], monthly[n]
            w(f"{n:<16}{q['_m'].cagr:>11.2%} {mo['_m'].cagr:>11.2%} "
              f"{q['_m'].sharpe_ratio:>11.2f} {mo['_m'].sharpe_ratio:>11.2f} "
              f"{q['avg_turnover']:>11.1%} {mo['avg_turnover']:>11.1%} "
              f"{q['total_costs']:>13,.0f} {mo['total_costs']:>13,.0f}")
        w("")

    # ── Direct comparison vs champion ──
    w("DIRECT COMPARISON vs CHAMPION".center(W, "-"))
    cm = variants[CHAMPION_LABEL]["_m"]
    w(f"  Champion: CAGR {cm.cagr:.2%} | Sharpe {cm.sharpe_ratio:.2f} | Calmar {cm.calmar_ratio:.2f} | "
      f"MaxDD {cm.max_drawdown:.2%} | Alpha {cm.alpha:+.2%}")
    for n in [f"STR Top{s}" for s in SIZES]:
        m = variants[n]["_m"]
        w(f"  {n} vs champion:  dCAGR {m.cagr-cm.cagr:+.2%} | dSharpe {m.sharpe_ratio-cm.sharpe_ratio:+.2f} | "
          f"dCalmar {m.calmar_ratio-cm.calmar_ratio:+.2f} | dMaxDD {m.max_drawdown-cm.max_drawdown:+.2%} "
          f"({'shallower' if m.max_drawdown>cm.max_drawdown else 'deeper'})")
    w("")

    # ── Verdict ──
    passed, best, dd = evaluate_verdict(variants, bm_cagr)
    w("VERDICT".center(W, "-"))
    w("Pre-registered viability bar (best reversal config by Sharpe, net of costs):")
    w(f"  Best reversal config: {best}  (CAGR {dd['cagr']:.2%}, Sharpe {dd['sharpe']:.2f}, Alpha {dd['alpha']:+.2%})")
    w(f"  (1) net CAGR > benchmark ({bm_cagr:.2%})      : {dd['beats_bm']}")
    w(f"  (2) net Jensen alpha > 0                      : {dd['pos_alpha']}")
    w(f"  (3) Sharpe >= {SHARPE_BAR:.2f}                          : {dd['sharpe_ok']}")
    w(f"  (4) split-sample no sign-flip (both halves +) : {dd['no_flip']}  "
      f"(h1 {dd['h1']:.2%}, h2 {dd['h2']:.2%})")
    w("")
    verdict = ("PASS — Mean Reversion merits further research." if passed
               else "FAIL — Momentum remains the superior style.")
    w(verdict)
    w("=" * W)

    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")
    return verdict


def write_comparison_csv(variants, monthly, bm_cagr):
    rows = []
    def rec(n, v):
        m, e, s, c = v["_m"], v["_extra"], v["_split"], v["_conc"]
        return {"variant": n, "n_stocks": v["_n"], "rebalance": v["_freq"],
                "cagr": m.cagr, "gross_cagr": v["_gross_cagr"], "sharpe": m.sharpe_ratio,
                "calmar": m.calmar_ratio, "sortino": m.sortino_ratio,
                "max_drawdown": m.max_drawdown, "annual_vol": m.annualised_volatility,
                "alpha": m.alpha, "beta": m.beta, "excess_vs_bm": m.cagr - bm_cagr,
                "avg_turnover": v["avg_turnover"], "total_costs": v["total_costs"],
                "cost_drag": v["_gross_cagr"] - m.cagr,
                "time_underwater": e["time_underwater_pct"],
                "avg_names": c["avg_names"], "name_hhi": c["name_hhi"],
                "cagr_h1": s.get("cagr_h1"), "cagr_h2": s.get("cagr_h2"),
                "roll3y_min": v["_roll3y"].min() if not v["_roll3y"].empty else np.nan,
                "roll3y_med": v["_roll3y"].median() if not v["_roll3y"].empty else np.nan,
                "final_value": v["equity_curve"].iloc[-1]}
    for n, v in variants.items():
        rows.append(rec(n, v))
    for n, v in monthly.items():
        rows.append(rec(n + " (M)", v))
    pd.DataFrame(rows).to_csv(RDIR / "comparison.csv", index=False)


# ─────────────────────────────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────────────────────────────

def make_charts(variants, bench_eq, bm_annual):
    plt.style.use("dark_background")
    names = list(variants.keys())
    fig = plt.figure(figsize=(18, 20))
    gs = GridSpec(4, 2, figure=fig, hspace=0.40, wspace=0.22)
    fig.suptitle("Phase 2B #1 — Short-Term Reversal (Top3/5/10) vs Momentum+LowVol Champion\n"
                 "Quarterly / Buffer20 / Equal Weight (net of Indian costs)",
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
    ax3.set_xticks(range(len(names))); ax3.set_xticklabels([n.replace("Champion ", "") for n in names], rotation=20, fontsize=8)
    ax3.set_ylabel("CAGR%")

    ax4 = fig.add_subplot(gs[2, 1]); ax4.set_title("Sharpe & Turnover/Reb", fontweight="bold")
    x = np.arange(len(names))
    ax4.bar(x-0.2, [variants[n]["_m"].sharpe_ratio for n in names], 0.4, color="#4ecdc4", label="Sharpe")
    a4 = ax4.twinx()
    a4.bar(x+0.2, [variants[n]["avg_turnover"]*100 for n in names], 0.4, color="#ff6b6b", label="Turnover/reb %")
    a4.set_ylabel("Turnover/reb %", color="#ff6b6b")
    ax4.set_xticks(x); ax4.set_xticklabels([n.replace("Champion ", "") for n in names], rotation=20, fontsize=8)
    ax4.set_ylabel("Sharpe"); ax4.grid(True, alpha=.2, axis="y")

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

def write_walkthrough(max_rev_turn, ran_monthly):
    txt = f"""# Phase 2B — Experiment #1: Short-Term Reversal — WALKTHROUGH

## The one question
**Can a Short-Term Reversal style compete with the frozen Momentum + LowVol champion
inside the existing framework?** Reversal is the canonical *price-only, non-momentum,
negatively-correlated* diversifier of the champion's offensive leg — the top fundamentals-free
candidate from `PHASE2B_STRATEGY_LANDSCAPE.md`.

## What is held FROZEN (nothing modified)
Engine (`run_buffered_backtest`), cost model, universe construction
(`TopNTurnoverUniverseBuilder`, equity-only top-500-liquid, survivorship-free), benchmark
methodology, and the rebalance framework (equal weight / Buffer20 / quarterly) are **all reused
verbatim**. Reversal enters ONLY as a new drop-in scorer (`compute_str_reversal`) — exactly as
every Phase-1 factor did.

## The signal (the only new code)
`compute_str_reversal`: rank by the **most recent {REVERSAL_LOOKBACK}-trading-day return**;
**lowest return = highest rank** (buy recent losers). No skip, no smoothing, **no parameter search**.

## Variants
- **A. Short-Term Reversal** — Top3 / Top5 / Top10, **quarterly** first.
  Because a {REVERSAL_LOOKBACK}-day signal is fast-decaying and turned out high-turnover
  (max quarterly turnover/reb {max_rev_turn:.1%}), {'a MONTHLY run was ALSO executed and the difference reported' if ran_monthly else 'a monthly run was not triggered'}.
- **C. Champion** — Momentum + LowVol (0.5/0.5), Top10 / quarterly / Buffer20 — the bar to beat.

Reversal is **not** blended with momentum.

## Metrics reported
CAGR (net & gross) · Sharpe · Calmar · Sortino · Max Drawdown · Alpha · Beta · Volatility ·
Turnover/rebalance · Transaction costs · Cost drag · Time underwater.

## Validation (same discipline as Phase 1)
- **Split sample** — first-half vs second-half CAGR/Sharpe (the FIP sign-flip test).
- **Rolling 3-year windows** — min/median across all 3y windows.
- **Concentration** — avg # names held and name-level HHI (rebuilt from the trade log).

## Why these costs matter
Short-term reversal is the most cost-sensitive style tested: it churns the bottom of the
return distribution every rebalance. The verdict is judged **net of the full Indian delivery
cost model**, never gross — a gross-only "edge" that costs eat is not a viable style.

## Pre-registered verdict (judged on the BEST reversal config by Sharpe, all NET)
PASS — Mean Reversion merits further research, IF ALL of:
1. net CAGR > NIFTY 500 benchmark CAGR;
2. net Jensen alpha > 0;
3. Sharpe >= {SHARPE_BAR:.2f} (materially positive, ~2/3 of the champion);
4. survives split-sample (CAGR positive in BOTH halves; no sign-flip).
Otherwise: **FAIL — Momentum remains the superior style.**

## Run
```
py run_short_term_reversal.py
```

## Outputs (`results/short_term_reversal/`)
`report.txt` · `report.png` · `comparison.csv` · `WALKTHROUGH.md`.
"""
    (RDIR / "WALKTHROUGH.md").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
