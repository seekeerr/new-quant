"""
SURVIVORSHIP-FREE VALIDATION.

The champion (Top5 / EW / quarterly / Buffer20 / 12-1 momentum, no risk mgmt) run
on THREE universes, all on the identical engine/signal/costs/dates:

  A) Fallback (49)        - the accidental 49-stock large-cap sample (original bug)
  B) Biased NIFTY 500     - the 500 CURRENT constituents (yfinance) => survivorship-
                            biased: today's index membership applied to all history
  C) Survivorship-Free    - the FULL NSE cross-section from daily bhavcopy (incl.
                            stocks now delisted), corp-action adjusted (gap-detect,
                            validated vs Upstox), capped to the top-500 most liquid
                            names per rebalance date (a point-in-time, bias-free,
                            NIFTY-500-sized liquidity universe).

Key question: once we STOP letting the strategy peek at tomorrow's index winners
(survivorship) and let it also hold names that later died, what is the honest CAGR?

Benchmark: NIFTY 500 PRICE index (data/nifty500_tri.csv). Not the true TRI (that
endpoint is gated) -> understates the real total return by ~1.2-1.5%/yr dividends.
"""
import sys, io, time, warnings
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
from data.downloader import download_all_stocks, build_price_panel, load_nifty500_symbols, _get_sample_symbols
from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns
from analytics.metrics import compute_metrics
from universe.universe_builder import UniverseBuilder, UniverseSnapshot
from universe.filters import apply_all_filters, classify_liquidity_tier
from run_buffer_experiment import (
    run_buffered_backtest, drawdown_analytics, rolling_3y_cagr, annual_returns,
)

N_STOCKS, BUFFER, FREQ = 5, 20, "quarterly"
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
PALETTE = {"Fallback (49)": "#ff6b6b", "Biased 500": "#ffd93d", "Survivorship-Free": "#00ff88"}


class TopNTurnoverUniverseBuilder(UniverseBuilder):
    """Standard PIT filters, then keep the top-N names by real 20-day avg turnover."""
    def __init__(self, close, high, low, volume, turnover, config, max_size=500):
        super().__init__(close, high, low, volume, config)
        self.turnover = turnover
        self.max_size = max_size

    def build_universe(self, date):
        date = pd.Timestamp(date)
        if date in self._cache:
            return self._cache[date]
        fr = apply_all_filters(self.close, self.high, self.low, self.volume, date, self.config)
        syms = fr.passed_symbols
        if len(syms) > self.max_size:
            m = self.turnover.index <= date
            cols = [s for s in syms if s in self.turnover.columns]
            adtv = self.turnover.loc[m].tail(self.config.turnover_lookback)[cols].mean()
            syms = adtv.sort_values(ascending=False).head(self.max_size).index.tolist()
        tiers = classify_liquidity_tier(self.close, self.volume, date, syms)
        snap = UniverseSnapshot(date=date, symbols=syms, liquidity_tiers=tiers, filter_result=fr)
        self._cache[date] = snap
        return snap


def run_champion(close, high, low, vol, config, cap, bench_ret, label, builder=None):
    net = run_buffered_backtest(close, high, low, vol, n_stocks=N_STOCKS, rebalance_freq=FREQ,
        buffer=BUFFER, initial_capital=cap, config=config, apply_costs=True, label=label,
        universe_builder=builder)
    gross = run_buffered_backtest(close, high, low, vol, n_stocks=N_STOCKS, rebalance_freq=FREQ,
        buffer=BUFFER, initial_capital=cap, config=config, apply_costs=False, label=label+"(g)",
        universe_builder=builder)
    m = compute_metrics(net["equity_curve"], net["returns"], benchmark_returns=bench_ret,
        trades=net["trades"], total_costs=net["total_costs"], initial_capital=cap)
    gm = compute_metrics(gross["equity_curve"], gross["returns"], initial_capital=cap)
    net["_m"] = m; net["_gross_cagr"] = gm.cagr
    net["_extra"] = drawdown_analytics(net["equity_curve"])
    net["_annual"] = annual_returns(net["equity_curve"])
    net["_roll3y"] = rolling_3y_cagr(net["returns"])
    return net


def main():
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital
    start, end = cfg.backtest.start_date, cfg.backtest.end_date

    print("="*78); print("  SURVIVORSHIP-FREE VALIDATION  (Top5/quarterly/Buffer20/12-1 momentum)"); print("="*78)

    bench_ret = get_benchmark_returns(start, end)
    bench_eq = get_benchmark_equity_curve(start, end, cap)
    bm_annual = annual_returns(bench_eq) if not bench_eq.empty else pd.Series(dtype=float)
    bm_cagr = compute_metrics(bench_eq, initial_capital=cap).cagr if not bench_eq.empty else np.nan

    variants = {}

    # ---- A) Fallback 49 (yfinance) ----
    print("\n[A] Fallback (49) ...")
    d = download_all_stocks(symbols=_get_sample_symbols(), use_cache=True)
    c, h, l, v = (build_price_panel(d, f) for f in ["Close","High","Low","Volume"])
    variants["Fallback (49)"] = run_champion(c, h, l, v, cfg, cap, bench_ret, "Fallback")

    # ---- B) Biased current NIFTY 500 (yfinance) ----
    print("[B] Biased NIFTY 500 (current constituents, yfinance) ...")
    d = download_all_stocks(symbols=load_nifty500_symbols(), use_cache=True)
    c, h, l, v = (build_price_panel(d, f) for f in ["Close","High","Low","Volume"])
    variants["Biased 500"] = run_champion(c, h, l, v, cfg, cap, bench_ret, "Biased500")

    # ---- C) Survivorship-free (bhavcopy, top-500 liquidity) ----
    print("[C] Survivorship-Free (full bhavcopy cross-section, top-500 liquidity) ...")
    ac = pd.read_parquet(CACHE_BHAV/"adj_close.parquet")
    ah = pd.read_parquet(CACHE_BHAV/"adj_high.parquet")
    al = pd.read_parquet(CACHE_BHAV/"adj_low.parquet")
    av = pd.read_parquet(CACHE_BHAV/"raw_volume.parquet")
    at = pd.read_parquet(CACHE_BHAV/"raw_turnover.parquet")
    print(f"    bhavcopy panel: {ac.shape[0]} dates x {ac.shape[1]} symbols")
    sf_builder = TopNTurnoverUniverseBuilder(ac, ah, al, av, at, cfg.universe, max_size=500)
    variants["Survivorship-Free"] = run_champion(ac, ah, al, av, cfg, cap, bench_ret,
                                                 "SurvFree", builder=sf_builder)

    names = list(variants.keys())
    results_dir = RESULTS_DIR / "survivorship_free"
    results_dir.mkdir(parents=True, exist_ok=True)

    make_charts(variants, bench_eq, bm_annual, results_dir / "report.png")
    write_report(variants, names, cap, bm_cagr, bm_annual, bench_eq, results_dir)
    print(f"\n  All outputs in: {results_dir}/")


def make_charts(variants, bench_eq, bm_annual, save_path):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 24)); gs = GridSpec(5, 2, figure=fig, hspace=0.38, wspace=0.22)
    fig.suptitle("Survivorship-Free Validation — Champion on 3 Universes\n"
                 "Fallback 49  vs  Biased NIFTY 500  vs  Survivorship-Free (bhavcopy, top-500 liquidity)",
                 fontsize=15, fontweight="bold", y=0.995, color="#fff")
    names = list(variants.keys())
    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for n in names:
        eq = variants[n]["equity_curve"]; ax1.plot(eq.index, eq/eq.iloc[0]*100, color=PALETTE[n], lw=1.8, label=n)
    if bench_eq is not None and not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq/bench_eq.iloc[0]*100, color="#888", lw=1.3, ls="--", label="NIFTY 500 (price)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2 = fig.add_subplot(gs[1, :]); ax2.set_title("Drawdown", fontweight="bold")
    for n in names:
        eq = variants[n]["equity_curve"]; dd=(eq-eq.cummax())/eq.cummax()*100
        ax2.plot(dd.index, dd, color=PALETTE[n], lw=1.1, label=n)
    ax2.legend(loc="lower left", framealpha=.3); ax2.grid(True, alpha=.2); ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax3 = fig.add_subplot(gs[2, 0]); ax3.set_title("CAGR vs Max DD", fontweight="bold")
    cagrs=[variants[n]["_m"].cagr*100 for n in names]; dds=[abs(variants[n]["_m"].max_drawdown)*100 for n in names]
    b=ax3.bar(names, cagrs, color=[PALETTE[n] for n in names])
    for bb,cc in zip(b,cagrs): ax3.text(bb.get_x()+bb.get_width()/2, bb.get_height(), f"{cc:.1f}%", ha="center", va="bottom", color="#fff", fontweight="bold")
    a3=ax3.twinx(); a3.plot(names, dds, color="#ff6b6b", marker="o", lw=1.6); a3.set_ylabel("Max DD %", color="#ff6b6b")
    ax3.set_ylabel("CAGR %"); ax3.tick_params(axis="x", rotation=12); ax3.grid(True, alpha=.2, axis="y")
    ax4 = fig.add_subplot(gs[2, 1]); ax4.set_title("Sharpe & Calmar", fontweight="bold")
    x=np.arange(len(names))
    ax4.bar(x-.2,[variants[n]["_m"].sharpe_ratio for n in names], .4, color="#4ecdc4", label="Sharpe")
    ax4.bar(x+.2,[variants[n]["_m"].calmar_ratio for n in names], .4, color="#ffd93d", label="Calmar")
    ax4.set_xticks(x); ax4.set_xticklabels(names, rotation=12); ax4.legend(framealpha=.3); ax4.grid(True, alpha=.2, axis="y")
    ax5 = fig.add_subplot(gs[3, :]); ax5.set_title("Rolling 3-Year CAGR", fontweight="bold")
    for n in names:
        r=variants[n]["_roll3y"]
        if not r.empty: ax5.plot(r.index, r*100, color=PALETTE[n], lw=1.4, label=n)
    ax5.axhline(6.5, color="#ff6b6b", ls="--", lw=1, alpha=.6, label="FD 6.5%"); ax5.axhline(0, color="white", lw=.5, ls="--", alpha=.3)
    ax5.legend(loc="upper right", framealpha=.3); ax5.grid(True, alpha=.2); ax5.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax6 = fig.add_subplot(gs[4, :]); ax6.set_title("Year-wise Returns vs Benchmark", fontweight="bold")
    yrs = sorted(set().union(*[set(variants[n]["_annual"].index) for n in names]))
    xp=np.arange(len(yrs)); w=0.8/(len(names)+1)
    for i,n in enumerate(names):
        ax6.bar(xp+i*w, [variants[n]["_annual"].get(y, np.nan)*100 for y in yrs], w, color=PALETTE[n], label=n)
    if bm_annual is not None and not bm_annual.empty:
        ax6.bar(xp+len(names)*w, [bm_annual.get(y, np.nan)*100 for y in yrs], w, color="#888", label="NIFTY500(px)")
    ax6.axhline(0, color="white", lw=.5, alpha=.3); ax6.set_xticks(xp+w*len(names)/2); ax6.set_xticklabels(yrs, rotation=45)
    ax6.legend(framealpha=.3, ncol=4); ax6.grid(True, alpha=.2, axis="y")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor()); plt.close(fig)
    print(f"  Chart saved: {save_path}")


def write_report(variants, names, cap, bm_cagr, bm_annual, bench_eq, rdir):
    bm = not bench_eq.empty
    L=[]; w=L.append
    def row(lbl, fmt):
        s=f"{lbl:<28}";
        for n in names: s+=f"{fmt(variants[n]):>22}"
        return s
    w("="*100); w("SURVIVORSHIP-FREE VALIDATION — CHAMPION ON 3 UNIVERSES".center(100))
    w("Top5 / Quarterly / Equal Weight / Buffer20 / 12-1 Momentum / Net of Costs".center(100)); w("="*100)
    w(f"Initial Capital: Rs {cap:,.0f}   Period: {variants[names[0]]['_m'].start_date}..{variants[names[0]]['_m'].end_date}")
    w("A=Fallback 49 (yfinance)  B=Biased current NIFTY500 (yfinance)  C=Survivorship-Free (bhavcopy top-500)")
    w("Benchmark: NIFTY 500 PRICE index (true TRI ~+1.3%/yr higher).")
    w("Adjustment (bhavcopy): gap-detection, validated vs Upstox (median single-day error ~0.25%).")
    w("")
    w(f"{'Metric':<28}{names[0]:>22}{names[1]:>22}{names[2]:>22}"); w("-"*100)
    w(row("CAGR", lambda v: f"{v['_m'].cagr:.2%}"))
    w(row("Total Return", lambda v: f"{v['_m'].total_return:.0%}"))
    w(row("Max Drawdown", lambda v: f"{v['_m'].max_drawdown:.2%}"))
    w(row("Sharpe", lambda v: f"{v['_m'].sharpe_ratio:.2f}"))
    w(row("Sortino", lambda v: f"{v['_m'].sortino_ratio:.2f}"))
    w(row("Calmar", lambda v: f"{v['_m'].calmar_ratio:.2f}"))
    w(row("Annual Vol", lambda v: f"{v['_m'].annualised_volatility:.2%}"))
    w(row("Final Value (Rs)", lambda v: f"{v['equity_curve'].iloc[-1]:,.0f}"))
    w(row("Time Underwater", lambda v: f"{v['_extra']['time_underwater_pct']:.1%}"))
    w(row("Trades (exec)", lambda v: f"{v['total_trades']}"))
    w(row("Avg Turnover/Rebal", lambda v: f"{v['avg_turnover']:.1%}"))
    w(row("Txn Costs (Rs)", lambda v: f"{v['total_costs']:,.0f}"))
    w(row("Cost Drag (CAGR pts)", lambda v: f"{v['_gross_cagr']-v['_m'].cagr:.2%}"))
    if bm:
        w(row("Alpha (Jensen ann.)", lambda v: f"{v['_m'].alpha:+.2%}"))
        w(row("Excess vs Bmk (CAGR)", lambda v: f"{v['_m'].cagr-bm_cagr:+.2%}"))
        w(row("Beta", lambda v: f"{v['_m'].beta:.2f}"))
    w("-"*100)
    if bm: w(f"NIFTY 500 price-index CAGR over period: {bm_cagr:.2%}  (true TRI ~ {bm_cagr+0.013:.2%})")
    w("")
    w("ROLLING 3Y CAGR (min/median/max):")
    for n in names:
        r=variants[n]["_roll3y"]
        if not r.empty: w(f"   {n:<20}: min {r.min():.1%} | median {r.median():.1%} | max {r.max():.1%}")
    w("")
    w("YEAR-WISE RETURNS"); w("-"*100)
    yh=f"{'Year':<8}"+"".join(f"{n:>22}" for n in names)+(f"{'NIFTY500(px)':>16}" if bm else ""); w(yh)
    yrs=sorted(set().union(*[set(variants[n]["_annual"].index) for n in names]))
    for y in yrs:
        ln=f"{y:<8}"
        for n in names:
            vv=variants[n]["_annual"].get(y, np.nan); ln+= f"{'N/A':>22}" if pd.isna(vv) else f"{vv:>21.1%} "
        if bm:
            bv=bm_annual.get(y, np.nan); ln+= f"{'N/A':>16}" if pd.isna(bv) else f"{bv:>15.1%} "
        w(ln)
    w("="*100)
    w("VERDICT".center(100,"-"))
    A,B,C = (variants[n]["_m"].cagr for n in names)
    w(f"  A Fallback 49      CAGR {A:.2%} | MaxDD {variants[names[0]]['_m'].max_drawdown:.2%} | Sharpe {variants[names[0]]['_m'].sharpe_ratio:.2f}")
    w(f"  B Biased 500       CAGR {B:.2%} | MaxDD {variants[names[1]]['_m'].max_drawdown:.2%} | Sharpe {variants[names[1]]['_m'].sharpe_ratio:.2f}")
    w(f"  C Survivorship-Free CAGR {C:.2%} | MaxDD {variants[names[2]]['_m'].max_drawdown:.2%} | Sharpe {variants[names[2]]['_m'].sharpe_ratio:.2f}")
    w(f"  Survivorship bias cost (B - C): {B-C:+.2%} CAGR  <-- the inflation removed")
    w(f"  Honest edge vs benchmark (C - bench): {C-bm_cagr:+.2%} CAGR" if bm else "")
    surv = "SURVIVES" if C >= 0.12 else "DOES NOT survive convincingly"
    w(f"  => On a bias-free universe the momentum alpha {surv} (CAGR {C:.2%}).")
    w("="*100)
    txt="\n".join(L); print("\n"+txt)
    (rdir/"report.txt").write_text(txt, encoding="utf-8")
    rows=[]
    for n in names:
        v=variants[n]; m=v["_m"]; e=v["_extra"]; r=v["_roll3y"]
        rows.append({"universe":n,"cagr":m.cagr,"total_return":m.total_return,"max_drawdown":m.max_drawdown,
            "sharpe":m.sharpe_ratio,"sortino":m.sortino_ratio,"calmar":m.calmar_ratio,"annual_vol":m.annualised_volatility,
            "final_value":v["equity_curve"].iloc[-1],"time_underwater":e["time_underwater_pct"],
            "trades":v["total_trades"],"avg_turnover":v["avg_turnover"],"total_costs":v["total_costs"],
            "gross_cagr":v["_gross_cagr"],"alpha":m.alpha,"beta":m.beta,"excess_vs_bm":m.cagr-bm_cagr if bm else np.nan,
            "roll3y_min":r.min() if not r.empty else np.nan,"roll3y_med":r.median() if not r.empty else np.nan,
            "roll3y_max":r.max() if not r.empty else np.nan})
    pd.DataFrame(rows).to_csv(rdir/"comparison.csv", index=False)
    ydf=pd.DataFrame({n:variants[n]["_annual"] for n in names})
    if bm and not bm_annual.empty: ydf["NIFTY500_price"]=bm_annual
    ydf.index.name="year"; ydf.to_csv(rdir/"yearwise_returns.csv")
    print(f"  Report + CSVs saved to {rdir}")


if __name__ == "__main__":
    main()
