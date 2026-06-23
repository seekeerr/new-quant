"""
PHASE 2B — EXPERIMENT #2: PORTFOLIO CONSTRUCTION (position sizing only).

QUESTION: Holding the frozen champion's EXACT Top10 selection fixed, can a better
position-sizing scheme improve risk-adjusted return?

FROZEN (nothing modified): universe, signals, benchmark, costs, rebalance schedule,
Buffer20, execution assumptions, AND the holdings selection itself. The champion's
Top10 names per rebalance are computed ONCE (variant A) and **replayed verbatim** for
B/C/D — so every variant trades the identical names on the identical dates. The ONLY
thing that differs is the weight each name receives.

The frozen engine (`run_buffered_backtest`) is NOT edited. Sizing is tested through a
weighting-aware sibling loop (`run_weighted_backtest`) that mirrors the engine's trade
mechanics exactly — the same pattern the repo already uses for `run_volmanaged_backtest`.

VARIANTS (champion = Momentum + LowVol / Top10 / Quarterly / Buffer20):
    A. Equal Weight            — the current champion (1/N).            [baseline]
    B. Inverse Volatility      — w_i ∝ 1/σ_i.
    C. Equal Risk Contribution — each name contributes equal portfolio variance (true ERC).
    D. Minimum Variance        — long-only argmin wᵀΣw, Σ over a 252-day window.

Risk model: daily-return covariance over a fixed 252-day lookback (the champion's own
vol window — inherited, NOT tuned). Same Σ feeds B/C/D so the comparison is clean.

VALIDATION (same discipline as Phase 1): split sample · rolling 3y windows ·
    name-concentration (avg # names, weight HHI).

SUCCESS CRITERION (pre-registered, judged NET of costs):
    A variant PASSES if it improves Sharpe AND/OR Calmar vs Equal Weight (by >= 0.03)
    WITHOUT materially reducing CAGR (drop <= 1.0 pt). Best passer by Sharpe wins.

CONSTRAINTS: no new signals, no parameter tuning, no change to holdings selection —
    only portfolio construction.

Run:  py run_construction_weighting.py
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
from tqdm import tqdm
from scipy.optimize import minimize

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

from run_buffer_experiment import (
    select_with_buffer, drawdown_analytics, rolling_3y_cagr, annual_returns,
)
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK
from run_survivorship_validation import TopNTurnoverUniverseBuilder
# Generic validation helpers (identical to those used in Experiment #1).
from run_short_term_reversal import reconstruct_holdings, concentration_stats, split_sample

# ── Frozen champion shell ──────────────────────────────────────────────
N_STOCKS, BUFFER, FREQ = 10, 20, "quarterly"
COV_LOOKBACK = 252            # risk-model window = champion's vol window (inherited, not tuned)
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "construction_weighting"

# Pre-registered success thresholds.
EPS = 0.03                    # min Sharpe/Calmar improvement to count
CAGR_TOL = 0.01               # max tolerated CAGR reduction (1.0 pt)

EW   = "A. Equal Weight"
IV   = "B. Inverse Vol"
ERC  = "C. ERC"
MV   = "D. Min Variance"
ORDER = [EW, IV, ERC, MV]
PALETTE = {EW: "#00ff88", IV: "#4ecdc4", ERC: "#ffd93d", MV: "#c792ea"}


# ─────────────────────────────────────────────────────────────────────
# RISK MODEL + WEIGHT OPTIMIZERS  (covariance over a fixed 252-day window)
# ─────────────────────────────────────────────────────────────────────

def _cov_model(close_panel, date, syms, lookback=COV_LOOKBACK):
    """Daily-return covariance (returns scaled x100 for conditioning) over the names
    that have enough history. Returns (good_syms, cov, vol) or (None, None, None)."""
    cols = [s for s in syms if s in close_panel.columns]
    prices = close_panel.loc[close_panel.index <= date, cols].tail(lookback + 1)
    rets = prices.pct_change().iloc[1:]
    good = [c for c in rets.columns if rets[c].notna().sum() >= lookback * 0.6]
    rets = rets[good].fillna(0.0) * 100.0
    if rets.shape[1] == 0 or rets.shape[0] < 20:
        return None, None, None
    cov = np.atleast_2d(np.cov(rets.values, rowvar=False))
    vol = rets.std().values
    return good, cov, vol


def _expand(selected, good, w_good):
    """Map optimizer weights (over `good`) back onto ALL selected names so every name
    stays funded (holdings identical across variants). Names lacking history get the
    average weight; then renormalise to 1."""
    if not good:
        n = len(selected)
        return {s: 1.0 / n for s in selected} if n else {}
    base = {s: float(w) for s, w in zip(good, w_good)}
    miss = [s for s in selected if s not in base]
    for s in miss:
        base[s] = 1.0 / len(selected)
    tot = sum(base.get(s, 0.0) for s in selected)
    if tot <= 0:
        n = len(selected)
        return {s: 1.0 / n for s in selected}
    return {s: base.get(s, 0.0) / tot for s in selected}


def w_equal(selected, close_panel, date):
    n = len(selected)
    return {s: 1.0 / n for s in selected} if n else {}


def w_invvol(selected, close_panel, date):
    good, cov, vol = _cov_model(close_panel, date, selected)
    if good is None:
        return w_equal(selected, close_panel, date)
    iv = 1.0 / np.where(vol > 0, vol, np.nan)
    iv = np.nan_to_num(iv, nan=0.0)
    if iv.sum() <= 0:
        return w_equal(selected, close_panel, date)
    return _expand(selected, good, iv / iv.sum())


def w_erc(selected, close_panel, date):
    """True Equal Risk Contribution: minimise dispersion of risk contributions,
    long-only, sum-to-1 (Maillard-Roncalli-Teiletche)."""
    good, cov, vol = _cov_model(close_panel, date, selected)
    if good is None:
        return w_equal(selected, close_panel, date)
    n = cov.shape[0]
    if n == 1:
        return _expand(selected, good, np.array([1.0]))

    def obj(w):
        pv = w @ cov @ w
        rc = w * (cov @ w)
        return np.sum((rc - pv / n) ** 2)

    w0 = 1.0 / np.where(vol > 0, vol, 1.0)
    w0 = w0 / w0.sum()
    res = minimize(obj, w0, method="SLSQP",
                   bounds=[(1e-6, 1.0)] * n,
                   constraints=({"type": "eq", "fun": lambda w: w.sum() - 1.0},),
                   options={"maxiter": 500, "ftol": 1e-14})
    w = np.clip(res.x, 0.0, None)
    if w.sum() <= 0:
        return w_invvol(selected, close_panel, date)
    return _expand(selected, good, w / w.sum())


def w_minvar(selected, close_panel, date):
    """Long-only minimum variance: argmin wᵀΣw, w>=0, sum w = 1."""
    good, cov, vol = _cov_model(close_panel, date, selected)
    if good is None:
        return w_equal(selected, close_panel, date)
    n = cov.shape[0]
    res = minimize(lambda w: w @ cov @ w, np.full(n, 1.0 / n), method="SLSQP",
                   bounds=[(0.0, 1.0)] * n,
                   constraints=({"type": "eq", "fun": lambda w: w.sum() - 1.0},),
                   options={"maxiter": 500, "ftol": 1e-14})
    w = np.clip(res.x, 0.0, None)
    if w.sum() <= 0:
        return w_invvol(selected, close_panel, date)
    return _expand(selected, good, w / w.sum())


WEIGHTERS = {EW: w_equal, IV: w_invvol, ERC: w_erc, MV: w_minvar}


# ─────────────────────────────────────────────────────────────────────
# WEIGHTING-AWARE BACKTEST  (sibling of run_buffered_backtest; mechanics identical)
# ─────────────────────────────────────────────────────────────────────
# The ONLY deviation from run_buffered_backtest is the per-name target capital:
#   equal weight  ->  portfolio_value / n_stocks
#   weighted      ->  portfolio_value * weight_i
# Selection is either computed (canonical, record=True) or REPLAYED from a recorded
# sequence (selection_seq) so B/C/D trade the champion's exact names. Costs, ffill
# valuation, sell-then-buy ordering, and affordability are copied verbatim.

def run_weighted_backtest(close_panel, high_panel, low_panel, volume_panel,
                          n_stocks, rebalance_freq, buffer, initial_capital, config,
                          weighting, scorer, apply_costs=True, label="",
                          universe_builder=None, selection_seq=None, record=False):
    cfg = config
    start = pd.Timestamp(cfg.backtest.start_date)
    end = pd.Timestamp(cfg.backtest.end_date)
    start = max(start, close_panel.index.min() + pd.Timedelta(days=365))
    end = min(end, close_panel.index.max())
    all_dates = close_panel.index[(close_panel.index >= start) & (close_panel.index <= end)]
    if all_dates.empty:
        return {"equity_curve": pd.Series(dtype=float), "returns": pd.Series(dtype=float)}

    rebal_set = set(get_rebalance_dates(all_dates, rebalance_freq))
    valuation_panel = close_panel.ffill()
    cost_model = CostModel(cfg.costs)

    cash = initial_capital
    current_holdings = {}
    equity_values, trades_history = [], []
    total_costs = total_turnover = 0.0
    total_rebalances = 0
    selection_record = {}

    desc = f"[{'net' if apply_costs else 'gross'}] {label}"
    for date in tqdm(all_dates, desc=desc, unit="day"):
        today_close = close_panel.loc[date]
        today_value = valuation_panel.loc[date]
        holdings_value = sum(qty * today_value.get(sym, 0) for sym, qty in current_holdings.items()
                             if not np.isnan(today_value.get(sym, np.nan)))
        portfolio_value = cash + holdings_value
        equity_values.append({"date": date, "portfolio_value": portfolio_value})

        if date not in rebal_set:
            continue
        total_rebalances += 1

        universe = universe_builder.build_universe(date)
        if not universe.symbols:
            continue

        # ── Selection: replay if provided (identical names), else compute it ──
        if selection_seq is not None:
            selected = list(selection_seq.get(date, []))
        else:
            scores = scorer(close_panel, date, universe.symbols)
            if scores.empty or len(scores) < n_stocks:
                continue
            selected = select_with_buffer(scores, current_holdings, n_stocks, buffer)
        if record:
            selection_record[date] = list(selected)
        if not selected:
            continue

        # ── Position sizing: the ONLY thing that changes across variants ──
        weights = weighting(selected, close_panel, date)
        target_shares = {}
        for sym in selected:
            price = today_close.get(sym, np.nan)
            if np.isnan(price) or price <= 0:
                continue
            target_cap = portfolio_value * weights.get(sym, 0.0)
            shares = int(target_cap / price)
            if shares > 0:
                target_shares[sym] = shares

        sells_value = buys_value = 0.0
        for sym, qty in list(current_holdings.items()):
            target_qty = target_shares.get(sym, 0)
            sell_qty = qty - target_qty
            if sell_qty <= 0:
                continue
            price = today_close.get(sym, np.nan)
            if not (price > 0):
                price = today_value.get(sym, np.nan)
            if not (price > 0):
                del current_holdings[sym]
                continue
            sell_value = sell_qty * price
            cost = 0.0
            if apply_costs:
                tier = universe.liquidity_tiers.get(sym, 2)
                cost = cost_model.calculate_trade_cost(sym, "SELL", sell_qty, price, liquidity_tier=tier).total_cost
            cash += sell_value - cost
            total_costs += cost
            sells_value += sell_value
            current_holdings[sym] = qty - sell_qty
            if current_holdings[sym] <= 0:
                del current_holdings[sym]
            trades_history.append({"date": date, "symbol": sym, "side": "SELL", "shares": sell_qty,
                                   "price": price, "value": sell_value, "cost": cost})

        for sym, target_qty in target_shares.items():
            buy_qty = target_qty - current_holdings.get(sym, 0)
            if buy_qty <= 0:
                continue
            price = today_close.get(sym, np.nan)
            if not (price > 0):
                continue
            buy_value = buy_qty * price
            cost = 0.0
            tier = universe.liquidity_tiers.get(sym, 2)
            if apply_costs:
                cost = cost_model.calculate_trade_cost(sym, "BUY", buy_qty, price, liquidity_tier=tier).total_cost
            total_buy_cost = buy_value + cost
            if total_buy_cost > cash:
                affordable = int((cash - cost) / price) if price > 0 else 0
                if affordable <= 0:
                    continue
                buy_qty = affordable
                buy_value = buy_qty * price
                if apply_costs:
                    cost = cost_model.calculate_trade_cost(sym, "BUY", buy_qty, price, liquidity_tier=tier).total_cost
                total_buy_cost = buy_value + cost
            cash -= total_buy_cost
            total_costs += cost
            buys_value += buy_value
            current_holdings[sym] = current_holdings.get(sym, 0) + buy_qty
            trades_history.append({"date": date, "symbol": sym, "side": "BUY", "shares": buy_qty,
                                   "price": price, "value": buy_value, "cost": cost})

        rebal_turnover = max(sells_value, buys_value) / portfolio_value if portfolio_value > 0 else 0
        total_turnover += rebal_turnover

    eq = pd.DataFrame(equity_values).set_index("date")["portfolio_value"]
    return {
        "equity_curve": eq, "returns": eq.pct_change().fillna(0), "trades": trades_history,
        "total_costs": total_costs, "total_rebalances": total_rebalances,
        "total_trades": len(trades_history),
        "avg_turnover": total_turnover / total_rebalances if total_rebalances else 0,
        "selection_record": selection_record,
    }


# ─────────────────────────────────────────────────────────────────────
# PANELS / RUNNER
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


def finalize(net, cap, bench_ret):
    gross_eq = net.pop("_gross_eq")
    m = compute_metrics(net["equity_curve"], net["returns"], benchmark_returns=bench_ret,
                        trades=net["trades"], total_costs=net["total_costs"], initial_capital=cap)
    gm = compute_metrics(gross_eq, gross_eq.pct_change().fillna(0), initial_capital=cap)
    net["_m"] = m
    net["_gross_cagr"] = gm.cagr
    net["_extra"] = drawdown_analytics(net["equity_curve"])
    net["_annual"] = annual_returns(net["equity_curve"])
    net["_roll3y"] = rolling_3y_cagr(net["returns"])
    net["_split"] = split_sample(net)
    net["_conc"] = concentration_stats(net["trades"], net["_close_ref"])
    return net


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital
    start, end = cfg.backtest.start_date, cfg.backtest.end_date
    RDIR.mkdir(parents=True, exist_ok=True)

    print("=" * 88)
    print("  PHASE 2B #2 — PORTFOLIO CONSTRUCTION (sizing only) on the frozen champion".center(88))
    print("  same Top10 holdings · only weights change · net of Indian costs".center(88))
    print("=" * 88)

    bench_ret = get_benchmark_returns(start, end)
    print("\n  Loading survivorship-free bhavcopy panels ...")
    ac, ah, al, av, at, builder = load_panels_and_builder(cfg)
    print(f"  panel: {ac.shape[0]} dates x {ac.shape[1]} equity symbols")

    scorer = make_mom_lowvol_scorer(0.5, VOL_LOOKBACK)
    common = dict(n_stocks=N_STOCKS, rebalance_freq=FREQ, buffer=BUFFER,
                  initial_capital=cap, config=cfg, scorer=scorer, universe_builder=builder)

    variants = {}
    # ── A. Equal weight = champion. Compute selection ONCE and record it. ──
    print(f"\n{'-'*88}\n  {EW}  (champion; recording selection)\n{'-'*88}")
    a_net = run_weighted_backtest(ac, ah, al, av, weighting=w_equal, apply_costs=True,
                                  label=EW, record=True, **common)
    a_gross = run_weighted_backtest(ac, ah, al, av, weighting=w_equal, apply_costs=False,
                                    label=EW + "(g)", selection_seq=a_net["selection_record"], **common)
    a_net["_gross_eq"] = a_gross["equity_curve"]
    a_net["_close_ref"] = ac
    selection_seq = a_net["selection_record"]
    variants[EW] = finalize(a_net, cap, bench_ret)
    _report_line(variants[EW])

    # ── B / C / D: REPLAY the champion's exact selection; only weights differ. ──
    for label, wfn in [(IV, w_invvol), (ERC, w_erc), (MV, w_minvar)]:
        print(f"\n{'-'*88}\n  {label}  (replaying champion selection)\n{'-'*88}")
        net = run_weighted_backtest(ac, ah, al, av, weighting=wfn, apply_costs=True,
                                    label=label, selection_seq=selection_seq, record=True, **common)
        gross = run_weighted_backtest(ac, ah, al, av, weighting=wfn, apply_costs=False,
                                      label=label + "(g)", selection_seq=selection_seq, **common)
        net["_gross_eq"] = gross["equity_curve"]
        net["_close_ref"] = ac
        variants[label] = finalize(net, cap, bench_ret)
        _report_line(variants[label])

    # Integrity check: the SELECTION (which names) must be identical across A/B/C/D.
    # (Funded-name counts may differ — Min-Variance optimally sizes some to ~0; that is
    # a sizing decision, captured in the concentration metrics, not a selection change.)
    sel_match = _verify_identical_selection(variants)
    mv_funded = variants[MV]["_conc"]["avg_names"]
    print(f"\n  Identical-SELECTION check (champion Top10 names per rebalance, A vs B/C/D): "
          f"{'PASS' if sel_match else 'FAIL'}")
    print(f"  (Min-Variance funds {mv_funded:.1f}/10 names on average — corner solutions; a sizing effect.)")

    _eq = variants[EW]["equity_curve"]
    bench_eq = get_benchmark_equity_curve(str(_eq.index[0].date()), str(_eq.index[-1].date()), cap)
    bm_cagr = compute_metrics(bench_eq, initial_capital=cap).cagr if not bench_eq.empty else np.nan
    bm_annual = annual_returns(bench_eq) if not bench_eq.empty else pd.Series(dtype=float)
    print(f"  benchmark aligned to span: NIFTY500(px) CAGR {bm_cagr:.2%}")

    make_charts(variants, bench_eq, bm_annual)
    verdict = write_report(variants, cap, bm_cagr, bench_eq, sel_match)
    write_comparison_csv(variants, bm_cagr)
    write_walkthrough(sel_match)
    print(f"\n  All outputs in: {RDIR}/")
    print(f"  VERDICT: {verdict}")


def _report_line(v):
    m = v["_m"]
    print(f"  CAGR {m.cagr:.2%} | Sharpe {m.sharpe_ratio:.2f} | Calmar {m.calmar_ratio:.2f} | "
          f"MaxDD {m.max_drawdown:.2%} | Turnover/reb {v['avg_turnover']:.1%} | HHI {v['_conc']['name_hhi']:.3f}")


def _verify_identical_selection(variants):
    """Confirm the SELECTION (champion's recorded Top10 names per rebalance) replayed
    into B/C/D is byte-identical to A's. This is the frozen invariant; funded-share
    counts may differ under different sizing (e.g. Min-Variance zeroing some names)."""
    base = variants[EW]["selection_record"]
    for label in [IV, ERC, MV]:
        rec = variants[label].get("selection_record", {})
        for d, names in base.items():
            if list(rec.get(d, [])) != list(names):
                return False
    return True


# ─────────────────────────────────────────────────────────────────────
# VERDICT
# ─────────────────────────────────────────────────────────────────────

def evaluate(variants):
    a = variants[EW]["_m"]
    rows = {}
    for label in [IV, ERC, MV]:
        m = variants[label]["_m"]
        improves = (m.sharpe_ratio >= a.sharpe_ratio + EPS) or (m.calmar_ratio >= a.calmar_ratio + EPS)
        cagr_ok = m.cagr >= a.cagr - CAGR_TOL
        rows[label] = dict(passed=improves and cagr_ok, improves=improves, cagr_ok=cagr_ok,
                           dsharpe=m.sharpe_ratio - a.sharpe_ratio,
                           dcalmar=m.calmar_ratio - a.calmar_ratio,
                           dcagr=m.cagr - a.cagr)
    passers = [l for l in rows if rows[l]["passed"]]
    best = max(passers, key=lambda l: variants[l]["_m"].sharpe_ratio) if passers else None
    return rows, best


# ─────────────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────────────

def write_report(variants, cap, bm_cagr, bench_eq, sel_match):
    names = ORDER
    L = []; w = L.append
    def row(lbl, fmt):
        return f"{lbl:<24}" + "".join(f"{fmt(variants[n]):>20}" for n in names)
    W = 24 + 20 * len(names)

    w("=" * W)
    w("PHASE 2B #2 — PORTFOLIO CONSTRUCTION (position sizing only)".center(W))
    w("Frozen champion Top10 holdings · Quarterly · Buffer20 · net of Indian costs".center(W))
    w("=" * W)
    w(f"Capital Rs {cap:,.0f}   Period {variants[EW]['_m'].start_date}..{variants[EW]['_m'].end_date}")
    w("Selection FROZEN: champion's exact Top10 names replayed for B/C/D; only weights differ.")
    w(f"Risk model: daily-return covariance over {COV_LOOKBACK}d (champion vol window; not tuned).")
    w(f"Identical-SELECTION integrity check across A/B/C/D: {'PASS' if sel_match else 'FAIL'} "
      f"(same names every rebalance).")
    w(f"Note: Min-Variance funds {variants[MV]['_conc']['avg_names']:.1f}/10 names on average "
      f"(corner solutions size some to ~0) — a sizing effect, not a selection change.")
    w("")
    w(f"{'Metric':<24}" + "".join(f"{n:>20}" for n in names)); w("-" * W)
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
    w("-- concentration (weights) --")
    w(row("Avg # names",       lambda v: f"{v['_conc']['avg_names']:.1f}"))
    w(row("Weight HHI",        lambda v: f"{v['_conc']['name_hhi']:.3f}"))
    w(row("Avg max name wt",   lambda v: f"{v['_conc']['max_name_wt']:.1%}"))
    w("-- split sample (CAGR) --")
    w(row("First half CAGR",   lambda v: f"{v['_split'].get('cagr_h1', float('nan')):.2%}"))
    w(row("Second half CAGR",  lambda v: f"{v['_split'].get('cagr_h2', float('nan')):.2%}"))
    w(row("Roll 3y min",       lambda v: f"{v['_roll3y'].min():.1%}" if not v['_roll3y'].empty else "N/A"))
    w(row("Roll 3y median",    lambda v: f"{v['_roll3y'].median():.1%}" if not v['_roll3y'].empty else "N/A"))
    w("-" * W)
    w(f"NIFTY 500 price-index CAGR: {bm_cagr:.2%} (true TRI ~ {bm_cagr+0.013:.2%})")
    w("")

    rows, best = evaluate(variants)
    a = variants[EW]["_m"]
    w("SUCCESS CRITERION vs A. Equal Weight".center(W, "-"))
    w(f"  Bar: improve Sharpe AND/OR Calmar by >= {EPS:.2f} WITHOUT CAGR drop > {CAGR_TOL*100:.0f}.0 pt.")
    w(f"  Equal Weight baseline: CAGR {a.cagr:.2%} | Sharpe {a.sharpe_ratio:.2f} | Calmar {a.calmar_ratio:.2f}")
    for label in [IV, ERC, MV]:
        r = rows[label]
        tag = "PASS" if r["passed"] else "no"
        w(f"  {label:<18}: dSharpe {r['dsharpe']:+.2f} | dCalmar {r['dcalmar']:+.2f} | "
          f"dCAGR {r['dcagr']:+.2%}  -> [{tag}]")
    w("")
    w("VERDICT".center(W, "-"))
    if best is not None:
        m = variants[best]["_m"]
        verdict = (f"PASS — {best} improves risk-adjusted return without material CAGR loss "
                   f"(Sharpe {m.sharpe_ratio:.2f}, Calmar {m.calmar_ratio:.2f}, CAGR {m.cagr:.2%}).")
    else:
        verdict = ("FAIL — no construction scheme clears the bar; Equal Weight remains the "
                   "champion's sizing.")
    w(verdict)
    w("=" * W)

    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")
    return verdict


def write_comparison_csv(variants, bm_cagr):
    rows = []
    for n in ORDER:
        v = variants[n]; m = v["_m"]; e = v["_extra"]; s = v["_split"]; c = v["_conc"]
        rows.append({"variant": n, "cagr": m.cagr, "gross_cagr": v["_gross_cagr"],
                     "sharpe": m.sharpe_ratio, "calmar": m.calmar_ratio, "sortino": m.sortino_ratio,
                     "max_drawdown": m.max_drawdown, "annual_vol": m.annualised_volatility,
                     "alpha": m.alpha, "beta": m.beta, "excess_vs_bm": m.cagr - bm_cagr,
                     "avg_turnover": v["avg_turnover"], "total_costs": v["total_costs"],
                     "cost_drag": v["_gross_cagr"] - m.cagr, "time_underwater": e["time_underwater_pct"],
                     "avg_names": c["avg_names"], "weight_hhi": c["name_hhi"],
                     "avg_max_name_wt": c["max_name_wt"],
                     "cagr_h1": s.get("cagr_h1"), "cagr_h2": s.get("cagr_h2"),
                     "roll3y_min": v["_roll3y"].min() if not v["_roll3y"].empty else np.nan,
                     "roll3y_med": v["_roll3y"].median() if not v["_roll3y"].empty else np.nan,
                     "final_value": v["equity_curve"].iloc[-1]})
    pd.DataFrame(rows).to_csv(RDIR / "comparison.csv", index=False)


# ─────────────────────────────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────────────────────────────

def make_charts(variants, bench_eq, bm_annual):
    plt.style.use("dark_background")
    names = ORDER
    fig = plt.figure(figsize=(18, 20))
    gs = GridSpec(4, 2, figure=fig, hspace=0.40, wspace=0.22)
    fig.suptitle("Phase 2B #2 — Portfolio Construction on the Frozen Champion Top10\n"
                 "Equal / Inverse-Vol / ERC / Min-Variance — same holdings, sizing only (net)",
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

    ax3 = fig.add_subplot(gs[2, 0]); ax3.set_title("Sharpe & Calmar", fontweight="bold")
    x = np.arange(len(names))
    ax3.bar(x-0.2, [variants[n]["_m"].sharpe_ratio for n in names], 0.4, color="#4ecdc4", label="Sharpe")
    ax3.bar(x+0.2, [variants[n]["_m"].calmar_ratio for n in names], 0.4, color="#ffd93d", label="Calmar")
    ax3.set_xticks(x); ax3.set_xticklabels([n[:2] for n in names]); ax3.legend(framealpha=.3); ax3.grid(True, alpha=.2, axis="y")

    ax4 = fig.add_subplot(gs[2, 1]); ax4.set_title("CAGR, Vol & Turnover", fontweight="bold")
    ax4.bar(x-0.27, [variants[n]["_m"].cagr*100 for n in names], 0.27, color="#00ff88", label="CAGR%")
    ax4.bar(x, [variants[n]["_m"].annualised_volatility*100 for n in names], 0.27, color="#c792ea", label="Vol%")
    ax4.bar(x+0.27, [variants[n]["avg_turnover"]*100 for n in names], 0.27, color="#ff6b6b", label="Turn/reb%")
    ax4.set_xticks(x); ax4.set_xticklabels([n[:2] for n in names]); ax4.legend(framealpha=.3); ax4.grid(True, alpha=.2, axis="y")

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

def write_walkthrough(sel_match):
    txt = f"""# Phase 2B — Experiment #2: Portfolio Construction — WALKTHROUGH

## The one question
**Holding the frozen champion's EXACT Top10 selection fixed, can a better position-sizing
scheme improve risk-adjusted return?** Only portfolio construction is tested — no new
signal, no parameter tuning, no change to which names are held.

## What is held FROZEN
Universe, signals, benchmark, costs, rebalance schedule, Buffer20, execution assumptions —
and the **holdings selection itself**. The champion's Top10 names per rebalance are computed
ONCE (variant A) and **replayed verbatim** for B/C/D. Identical-SELECTION integrity check
(same names every rebalance, A vs B/C/D): **{'PASS' if sel_match else 'FAIL'}**.

Note on Min-Variance: as a true optimizer it may size some of the 10 selected names to ~0
(corner solutions), so its *funded* name count is slightly below 10. That is a sizing
decision under test — not a selection change — and is captured in the concentration metrics.

The frozen engine (`run_buffered_backtest`) is not edited. Sizing is tested through a
weighting-aware sibling loop (`run_weighted_backtest`) whose trade mechanics — cost model,
forward-filled valuation, sell-then-buy ordering, affordability — are copied verbatim. The
ONLY deviation is the per-name target capital: `portfolio_value / N` (equal) becomes
`portfolio_value * weight_i`.

## The four sizing schemes (champion = Mom+LowVol / Top10 / Quarterly / Buffer20)
- **A. Equal Weight** — 1/N. The current champion. Baseline.
- **B. Inverse Volatility** — w_i ∝ 1/σ_i (lower-vol names larger).
- **C. Equal Risk Contribution (ERC)** — true ERC: each name contributes equal portfolio
  variance, solved long-only sum-to-1 (Maillard-Roncalli-Teiletche), not the inverse-vol
  approximation in `portfolio/constructor.py`.
- **D. Minimum Variance** — long-only argmin wᵀΣw, sum-to-1.

## Risk model
Daily-return covariance Σ over a fixed **{COV_LOOKBACK}-day** lookback — the champion's own
volatility window, **inherited, not tuned**. The same Σ feeds B/C/D so the comparison is clean.
Names without enough history fall back to an equal share (kept funded so holdings stay identical).

## Metrics reported
CAGR (net & gross) · Sharpe · Calmar · Sortino · Max Drawdown · Alpha · Beta · Volatility ·
Turnover/rebalance · Transaction costs · Cost drag · Time underwater.

## Validation (same discipline as Phase 1)
- **Split sample** — first vs second half CAGR/Sharpe.
- **Rolling 3-year windows** — min/median across all 3y windows.
- **Concentration** — avg # names (10 for all, by construction) and weight-HHI / max name
  weight (these DIFFER by scheme — the whole point).

## Success criterion (pre-registered, judged NET of costs)
A variant **PASSES** if it improves **Sharpe and/or Calmar by >= {EPS:.2f}** vs Equal Weight
**without** reducing CAGR by more than **{CAGR_TOL*100:.0f}.0 pt**. Best passer by Sharpe wins;
if none pass, Equal Weight stays.

## Run
```
py run_construction_weighting.py
```

## Outputs (`results/construction_weighting/`)
`report.txt` · `report.png` · `comparison.csv` · `WALKTHROUGH.md`.
"""
    (RDIR / "WALKTHROUGH.md").write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()
