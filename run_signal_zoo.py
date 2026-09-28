"""
CROSS-SECTIONAL SIGNAL ZOO  —  mass test of ranking signals derivable from daily
price / volume / turnover, run through the shared research harness.

RULES OBEYED
------------
* Every signal is a pure function of data with index <= the rebalance date.
  Signals are precomputed as PANELS using only backward-looking rolling windows
  (`shift`, `rolling`), and the scorer reads the row AT `date`.  There is no
  look-ahead by construction: row `t` of a `rolling(w)` / `shift(k)` panel is a
  function of rows <= t only.
* Panels are sliced to the split BEFORE any signal is computed, so a discovery
  run physically cannot touch holdout data.
* SEARCH happens only on split='discovery'.  `--split holdout` is gated behind
  an explicit `--i-am-finished` flag so it cannot be run by accident.

SHELL (frozen, identical for every config, = the baseline champion shell)
    Top-10 / monthly / Buffer-20 / equal weight / Rs 10,00,000 / rank band 0-500
    impact-aware Indian cost model, NET.

Baseline to beat (verified reproduced):
    champion Mom+LowVol Top-10 monthly, DISCOVERY CAGR 24.30% Sharpe 1.12 DD -31.4%

Usage
-----
    py run_signal_zoo.py list
    py run_signal_zoo.py standalone            # all solo signals, discovery
    py run_signal_zoo.py blend                 # champion x candidate blends
    py run_signal_zoo.py holdout --i-am-finished --only champion,<lab1>,<lab2>
    py run_signal_zoo.py report
"""
import argparse
import io
import json
import logging
import os
import sys
import time
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.ERROR)
for _n in list(logging.root.manager.loggerDict):
    logging.getLogger(_n).setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

RDIR = PROJECT_ROOT / "results" / "signal_zoo"
RDIR.mkdir(parents=True, exist_ok=True)

SHELL = dict(n_stocks=10, rebalance="monthly", buffer=20)


# ════════════════════════════════════════════════════════════════════
# 1. SIGNAL LIBRARY   name -> (builder, higher_is_better, description)
#    builder(P) -> DataFrame aligned to close, one column per symbol.
#    P is a dict of the split-sliced panels: close/high/low/vol/turn/ret/mkt.
# ════════════════════════════════════════════════════════════════════
MP = 0.75          # min_periods as a fraction of the window


def _mp(w):
    return max(20, int(w * MP))


def _clean(df):
    return df.replace([np.inf, -np.inf], np.nan)


# --- momentum family -------------------------------------------------
def mom(form, skip):
    def f(P):
        c = P["close"]
        return _clean(c.shift(skip) / c.shift(form + skip) - 1.0)
    return f


# --- 52-week-high proximity (George & Hwang) -------------------------
def wh52(source, w=252):
    def f(P):
        c, ref = P["close"], P[source]
        return _clean(c / ref.rolling(w, min_periods=_mp(w)).max())
    return f


# --- volatility family -----------------------------------------------
def totvol(w):
    def f(P):
        return _clean(P["ret"].rolling(w, min_periods=_mp(w)).std() * np.sqrt(252))
    return f


def parkinson(w):
    """Range-based vol from high/low; 1/(4 ln2) * mean(ln(H/L)^2)."""
    def f(P):
        lr = np.log(_clean(P["high"] / P["low"])) ** 2
        v = lr.rolling(w, min_periods=_mp(w)).mean() / (4 * np.log(2))
        return _clean(np.sqrt(v) * np.sqrt(252))
    return f


def _beta_idio(P, w):
    """Rolling market-model beta and residual (idiosyncratic) vol."""
    r, m = P["ret"], P["mkt"]
    n = _mp(w)
    rm = r.mul(m, axis=0).rolling(w, min_periods=n).mean()
    rb = r.rolling(w, min_periods=n).mean()
    mb = m.rolling(w, min_periods=n).mean()
    cov = rm.sub(rb.mul(mb, axis=0))
    varm = m.rolling(w, min_periods=n).var(ddof=0)
    beta = _clean(cov.div(varm, axis=0))
    varr = r.rolling(w, min_periods=n).var(ddof=0)
    resid = varr - (beta ** 2).mul(varm, axis=0)
    idio = _clean(np.sqrt(resid.clip(lower=0)) * np.sqrt(252))
    return beta, idio


def beta_sig(w):
    return lambda P: _beta_idio(P, w)[0]


def idio_sig(w):
    return lambda P: _beta_idio(P, w)[1]


def dsd(w):
    """Downside deviation: std of negative daily returns only."""
    def f(P):
        neg = P["ret"].where(P["ret"] < 0)
        return _clean(neg.rolling(w, min_periods=30).std() * np.sqrt(252))
    return f


def skew_sig(w):
    return lambda P: _clean(P["ret"].rolling(w, min_periods=_mp(w)).skew())


def maxret(w):
    """MAX anomaly (Bali et al.): largest single-day return in the window."""
    return lambda P: _clean(P["ret"].rolling(w, min_periods=_mp(w)).max())


# --- liquidity / participation ---------------------------------------
def amihud(w):
    """Amihud illiquidity: mean(|r| / Rs turnover) * 1e6, higher = more illiquid."""
    def f(P):
        ill = P["ret"].abs().div(P["turn"].replace(0, np.nan)) * 1e6
        return _clean(ill).rolling(w, min_periods=_mp(w)).mean()
    return f


def trend_of(src, fast, slow):
    """log( mean(src, fast) / mean(src, slow) ) - rising vs falling participation."""
    def f(P):
        x = P[src].replace(0, np.nan)
        a = x.rolling(fast, min_periods=_mp(fast)).mean()
        b = x.rolling(slow, min_periods=_mp(slow)).mean()
        return _clean(np.log(a / b))
    return f


# --- reversal / short-horizon ----------------------------------------
def pastret(w):
    def f(P):
        c = P["close"]
        return _clean(c / c.shift(w) - 1.0)
    return f


# --- path quality -----------------------------------------------------
def poscons(form, skip):
    """Fraction of positive 21-day blocks inside the formation window."""
    def f(P):
        c = P["close"]
        n = form // 21
        parts = []
        for k in range(n):
            a, b = skip + k * 21, skip + (k + 1) * 21
            parts.append((c.shift(a) / c.shift(b) - 1.0) > 0)
        return _clean(sum(x.astype(float) for x in parts) / n)
    return f


def fip(form, skip):
    """Frog-in-the-Pan information discreteness: sign(PRET)*(%neg - %pos) of daily
    returns in the formation window.  LOW = continuous info = better (rank low)."""
    def f(P):
        c, r = P["close"], P["ret"]
        pret = c.shift(skip) / c.shift(form + skip) - 1.0
        win = r.shift(skip)
        pos = (win > 0).rolling(form, min_periods=_mp(form)).mean()
        neg = (win < 0).rolling(form, min_periods=_mp(form)).mean()
        return _clean(np.sign(pret) * (neg - pos))
    return f


# --- distance from moving average -------------------------------------
def distma(w):
    def f(P):
        c = P["close"]
        return _clean(c / c.rolling(w, min_periods=_mp(w)).mean() - 1.0)
    return f


# name: (builder, higher_is_better, description)
SIGNALS = {
    # --- momentum formation / skip sweep (9) --------------------------
    "mom_3_0":     (mom(63, 0),    True,  "3m momentum, no skip"),
    "mom_3_1":     (mom(63, 21),   True,  "3m momentum, 1m skip"),
    "mom_6_0":     (mom(126, 0),   True,  "6m momentum, no skip"),
    "mom_6_1":     (mom(126, 21),  True,  "6m momentum, 1m skip"),
    "mom_9_1":     (mom(189, 21),  True,  "9m momentum, 1m skip"),
    "mom_12_0":    (mom(252, 0),   True,  "12m momentum, no skip"),
    "mom_12_1":    (mom(252, 21),  True,  "12-1 momentum (repo default)"),
    "mom_12_2":    (mom(252, 42),  True,  "12m momentum, 2m skip"),
    "mom_18_1":    (mom(378, 21),  True,  "18m momentum, 1m skip"),
    # --- 52-week-high proximity (2) -----------------------------------
    "wh52_close":  (wh52("close"), True,  "close / 252d max close"),
    "wh52_high":   (wh52("high"),  True,  "close / 252d max high"),
    # --- idiosyncratic vol / beta (4) ---------------------------------
    "idiovol_lo":  (idio_sig(252), False, "LOW 252d idiosyncratic vol"),
    "idiovol_hi":  (idio_sig(252), True,  "HIGH 252d idiosyncratic vol (bookend)"),
    "beta_lo":     (beta_sig(252), False, "LOW 252d market beta"),
    "beta_hi":     (beta_sig(252), True,  "HIGH 252d market beta (bookend)"),
    # --- Amihud illiquidity (2) ---------------------------------------
    "amihud_hi":   (amihud(60),    True,  "HIGH Amihud illiquidity (premium)"),
    "amihud_lo":   (amihud(60),    False, "LOW Amihud illiquidity (bookend)"),
    # --- participation trend (4) --------------------------------------
    "turntrend_up": (trend_of("turn", 21, 252), True,  "rising turnover 1m vs 12m"),
    "turntrend_dn": (trend_of("turn", 21, 252), False, "falling turnover (bookend)"),
    "voltrend_up":  (trend_of("vol", 21, 252),  True,  "rising share volume 1m vs 12m"),
    "voltrend_dn":  (trend_of("vol", 21, 252),  False, "falling share volume (bookend)"),
    # --- short-horizon reversal / continuation (10) -------------------
    "rev_1":       (pastret(1),   False, "1d reversal (buy losers)"),
    "cont_1":      (pastret(1),   True,  "1d continuation"),
    "rev_3":       (pastret(3),   False, "3d reversal"),
    "cont_3":      (pastret(3),   True,  "3d continuation"),
    "rev_5":       (pastret(5),   False, "5d reversal"),
    "cont_5":      (pastret(5),   True,  "5d continuation"),
    "rev_10":      (pastret(10),  False, "10d reversal"),
    "cont_10":     (pastret(10),  True,  "10d continuation"),
    "rev_21":      (pastret(21),  False, "21d reversal"),
    "cont_21":     (pastret(21),  True,  "21d continuation"),
    # --- path quality (3) ---------------------------------------------
    "poscons_12_1": (poscons(252, 21), True,  "frac of positive months in 12-1 window"),
    "fip_lo":       (fip(252, 21),     False, "FIP: continuous info (low ID)"),
    "fip_hi":       (fip(252, 21),     True,  "FIP: discrete info (bookend)"),
    # --- lottery / higher moments (5) ---------------------------------
    "maxret_lo":   (maxret(21),   False, "LOW max 1d return in past month"),
    "maxret_hi":   (maxret(21),   True,  "HIGH max 1d return (lottery bookend)"),
    "skew_lo":     (skew_sig(252), False, "LOW 1y return skewness"),
    "skew_hi":     (skew_sig(252), True,  "HIGH 1y return skewness (bookend)"),
    "dsd_lo":      (dsd(252),     False, "LOW downside deviation"),
    # --- distance from moving average (4) -----------------------------
    "distma_21":   (distma(21),   True,  "close vs 21d SMA"),
    "distma_50":   (distma(50),   True,  "close vs 50d SMA"),
    "distma_100":  (distma(100),  True,  "close vs 100d SMA"),
    "distma_200":  (distma(200),  True,  "close vs 200d SMA"),
    # --- range-based vol (2) ------------------------------------------
    "parkvol_lo":  (parkinson(252), False, "LOW 1y Parkinson (high-low) vol"),
    "totvol_lo":   (totvol(252),    False, "LOW 1y close-to-close vol (champion leg)"),
}


# ════════════════════════════════════════════════════════════════════
# 2. PANEL PREP + SCORERS
# ════════════════════════════════════════════════════════════════════
def make_context(close, high, low, vol, turn):
    ret = close.pct_change()
    # Broad equal-weight market proxy: cross-sectional MEDIAN daily return of the
    # whole surviving cross-section.  Backward-looking by construction (row t uses
    # only row t).  Robust to single-name blowups.
    mkt = ret.median(axis=1)
    return {"close": close, "high": high, "low": low, "vol": vol, "turn": turn,
            "ret": ret, "mkt": mkt}


_PANEL_CACHE = {}


def get_panel(name, ctx):
    if name not in _PANEL_CACHE:
        if len(_PANEL_CACHE) > 4:
            _PANEL_CACHE.clear()
        builder = SIGNALS[name][0]
        _PANEL_CACHE[name] = builder(ctx).astype("float32")
    return _PANEL_CACHE[name]


def _row(panel, date, universe):
    idx = panel.index
    if date not in idx:
        prev = idx[idx <= date]
        if len(prev) == 0:
            return pd.Series(dtype=float)
        date = prev[-1]
    cols = [s for s in universe if s in panel.columns]
    if not cols:
        return pd.Series(dtype=float)
    v = panel.loc[date, cols]
    return v.replace([np.inf, -np.inf], np.nan).dropna().astype(float)


def solo_scorer(panel, higher_is_better):
    def scorer(close_panel, date, universe):
        v = _row(panel, date, universe)
        if v.empty:
            return pd.Series(dtype=float)
        if not higher_is_better:
            v = -v
        return v.sort_values(ascending=False)
    return scorer


def blend_scorer(base_scorer, panel, higher_is_better, w_cand):
    """(1-w) * pctile(base) + w * pctile(candidate), on the common names."""
    def scorer(close_panel, date, universe):
        b = base_scorer(close_panel, date, universe)
        v = _row(panel, date, universe)
        if b.empty or v.empty:
            return pd.Series(dtype=float)
        if not higher_is_better:
            v = -v
        common = b.index.intersection(v.index)
        if len(common) < 2:
            return pd.Series(dtype=float)
        s = (1 - w_cand) * b[common].rank(pct=True) + w_cand * v[common].rank(pct=True)
        return s.sort_values(ascending=False)
    return scorer


def two_panel_scorer(pa, da, pb, db, wb):
    def scorer(close_panel, date, universe):
        a = _row(pa, date, universe)
        b = _row(pb, date, universe)
        if a.empty or b.empty:
            return pd.Series(dtype=float)
        if not da:
            a = -a
        if not db:
            b = -b
        common = a.index.intersection(b.index)
        if len(common) < 2:
            return pd.Series(dtype=float)
        s = (1 - wb) * a[common].rank(pct=True) + wb * b[common].rank(pct=True)
        return s.sort_values(ascending=False)
    return scorer


# ════════════════════════════════════════════════════════════════════
# 3. RUNNER (shared universe cache => ~1 universe build per process)
# ════════════════════════════════════════════════════════════════════
_STATE = {}


def _init(split):
    """Load panels for `split`, build the shared PIT universe builder."""
    from research_harness import load_panels, SPLITS
    from config import SystemConfig
    from run_smallcap_universe import RankBandUniverseBuilder
    import run_program2_smallcap_validation as eng

    # silence the per-day progress bar in workers
    eng.tqdm = lambda it, **k: it

    s, e = SPLITS[split]
    close, high, low, vol, turn = load_panels()
    c, h, l, v, t = [p.loc[s:e] for p in (close, high, low, vol, turn)]
    cfg = SystemConfig()
    _STATE["split"] = split
    _STATE["range"] = (s, e)
    _STATE["panels"] = (c, h, l, v, t)
    _STATE["ctx"] = make_context(c, h, l, v, t)
    _STATE["cfg"] = cfg
    _STATE["ub"] = RankBandUniverseBuilder(c, h, l, v, t, cfg.universe, 0, 500)


def _run(scorer, label):
    from run_program2_smallcap_validation import run_impact_aware_backtest
    from analytics.metrics import compute_metrics
    from data.benchmark import get_benchmark_returns
    from research_harness import rolling_3y_min, CAP

    c, h, l, v, t = _STATE["panels"]
    s, e = _STATE["range"]
    res = run_impact_aware_backtest(
        c, h, l, v, t, initial_capital=CAP, config=_STATE["cfg"],
        scorer=scorer, universe_builder=_STATE["ub"], label=label, **SHELL)
    br = get_benchmark_returns(s, e)
    m = compute_metrics(res["equity_curve"], res["returns"], benchmark_returns=br,
                        trades=res["trades"], total_costs=res["total_costs"],
                        initial_capital=CAP)
    rr = res["returns"]
    return {
        "label": label, "split": _STATE["split"],
        "cagr": m.cagr, "sharpe": m.sharpe_ratio, "maxdd": m.max_drawdown,
        "calmar": m.cagr / abs(m.max_drawdown) if m.max_drawdown else np.nan,
        "sortino": getattr(m, "sortino_ratio", np.nan),
        "vol": getattr(m, "annual_volatility", np.nan),
        "roll3y_min": rolling_3y_min(rr),
        "n_trades": len(res["trades"]), "turnover": res["avg_turnover"],
        "costs": res["total_costs"], "final": float(res["equity_curve"].iloc[-1]),
    }, rr


def build_scorer(job):
    """job = {'kind': ..., ...} -> scorer callable"""
    ctx = _STATE["ctx"]
    k = job["kind"]
    if k == "champion":
        from research_harness import champion_scorer
        return champion_scorer()
    if k == "solo":
        n = job["sig"]
        return solo_scorer(get_panel(n, ctx), SIGNALS[n][1])
    if k == "blend_champ":
        from research_harness import champion_scorer
        n = job["sig"]
        return blend_scorer(champion_scorer(), get_panel(n, ctx),
                            SIGNALS[n][1], job["w"])
    if k == "blend_two":
        a, b = job["sig_a"], job["sig_b"]
        return two_panel_scorer(get_panel(a, ctx), SIGNALS[a][1],
                                get_panel(b, ctx), SIGNALS[b][1], job["w"])
    raise ValueError(k)


def worker(args):
    split, job = args
    if _STATE.get("split") != split:
        _PANEL_CACHE.clear()
        _init(split)
    t0 = time.time()
    try:
        row, rr = _run(build_scorer(job), job["label"])
    except Exception as ex:          # a dead signal must not kill the sweep
        return {"label": job["label"], "split": split, "error": repr(ex)}, None
    row["secs"] = round(time.time() - t0, 1)
    row["kind"] = job["kind"]
    row["desc"] = job.get("desc", "")
    return row, rr


# ════════════════════════════════════════════════════════════════════
# 4. JOB SETS
# ════════════════════════════════════════════════════════════════════
def jobs_standalone():
    js = [{"kind": "champion", "label": "champion", "desc": "Mom+LowVol 50/50 (baseline)"}]
    for n, (_, hib, d) in SIGNALS.items():
        js.append({"kind": "solo", "sig": n, "label": n, "desc": d})
    return js


def save(rows, rets, tag, split):
    path = RDIR / f"{tag}_{split}.csv"
    df = pd.DataFrame(rows)
    if path.exists():
        old = pd.read_csv(path)
        df = pd.concat([old[~old["label"].isin(df["label"])], df], ignore_index=True)
    df.to_csv(path, index=False)
    rp = RDIR / f"returns_{split}.parquet"
    r = pd.DataFrame(rets)
    if rp.exists():
        old = pd.read_parquet(rp)
        keep = [c for c in old.columns if c not in r.columns]
        r = pd.concat([old[keep], r], axis=1)
    r.to_parquet(rp)
    return path


def run_jobs(jobs, split, tag, procs):
    print(f"\n{len(jobs)} configs on split={split} with {procs} process(es)\n")
    rows, rets = [], {}
    t0 = time.time()
    if procs <= 1:
        _init(split)
        for i, j in enumerate(jobs, 1):
            row, rr = worker((split, j))
            rows.append(row)
            if rr is not None:
                rets[row["label"]] = rr
            print(f"  [{i}/{len(jobs)}] {row['label']:<16} "
                  f"CAGR {row.get('cagr', float('nan'))*100 if row.get('cagr') is not None else float('nan'):6.2f}%  "
                  f"Sharpe {row.get('sharpe', float('nan')):5.2f}", flush=True)
    else:
        import multiprocessing as mp
        with mp.Pool(procs) as pool:
            for i, (row, rr) in enumerate(
                    pool.imap_unordered(worker, [(split, j) for j in jobs]), 1):
                rows.append(row)
                if rr is not None:
                    rets[row["label"]] = rr
                c = row.get("cagr")
                print(f"  [{i}/{len(jobs)}] {row['label']:<16} "
                      + (f"CAGR {c*100:6.2f}%  Sharpe {row.get('sharpe'):5.2f}"
                         if c is not None else f"ERROR {row.get('error')}"), flush=True)
    p = save(rows, rets, tag, split)
    print(f"\ndone in {(time.time()-t0)/60:.1f} min -> {p}")
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════════
# 5. CLI
# ════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "standalone", "blend", "holdout", "report"])
    ap.add_argument("--procs", type=int, default=5)
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", default="")       # json file of explicit jobs
    ap.add_argument("--tag", default="")
    ap.add_argument("--i-am-finished", action="store_true")
    a = ap.parse_args()

    if a.cmd == "list":
        for n, (_, hib, d) in SIGNALS.items():
            print(f"  {n:<16} {'HIGH' if hib else 'LOW ':<5} {d}")
        print(f"\n{len(SIGNALS)} signals")
        return

    if a.cmd == "report":
        make_report()
        return

    if a.cmd == "standalone":
        jobs = jobs_standalone()
        if a.only:
            keep = set(a.only.split(","))
            jobs = [j for j in jobs if j["label"] in keep]
        run_jobs(jobs, "discovery", a.tag or "standalone", a.procs)
        return

    if a.cmd == "blend":
        jobs = json.loads(Path(a.jobs).read_text())
        run_jobs(jobs, "discovery", a.tag or "blend", a.procs)
        return

    if a.cmd == "holdout":
        if not a.i_am_finished:
            print("REFUSED: holdout is single-use. Pass --i-am-finished.")
            sys.exit(2)
        jobs = json.loads(Path(a.jobs).read_text())
        run_jobs(jobs, "holdout", a.tag or "final", a.procs)
        return


def make_report():
    """Correlation matrix of the top signals' daily return series + league table."""
    rp = RDIR / "returns_discovery.parquet"
    sp = RDIR / "standalone_discovery.csv"
    if not (rp.exists() and sp.exists()):
        print("nothing to report yet")
        return
    df = pd.read_csv(sp).sort_values("cagr", ascending=False)
    r = pd.read_parquet(rp)
    top = [l for l in df["label"].head(8) if l in r.columns]
    print("\nTOP-8 daily-return correlation (discovery)\n")
    print(r[top].corr().round(2).to_string())
    (r[top].corr()).to_csv(RDIR / "corr_top8_discovery.csv")
    print("\n" + df.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
