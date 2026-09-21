"""
PROGRAM #2 — PAPER-TRADING TARGET PORTFOLIOS for the two production candidates.

USER DECISION (2026-07-06): run BOTH ensembles in parallel forward paper trading; decide live
allocation later on forward out-of-sample evidence. This script generates the CURRENT target
portfolios (holdings + weights + whole-share quantities) for each candidate from the latest
cached data, so paper tracking can start. It is DELIBERATELY SEPARATE from the champion's
operator-validation pipeline (`paper_trading/`, frozen commit 8f0482f) — that program validates
the operator/process and forbids strategy changes; this one is a RETURNS/robustness bake-off of
two research candidates, a different purpose.

TWO CANDIDATES (exact specs, both Top-10 EW per sleeve, survivorship-free Liquid/tail universes):
  A+C(0.3): 70% champion  [Mom+LowVol, Top-500, quarterly]
          + 30% breakout  [volume-confirmed breakout, Top-500, MONTHLY]
  A+B(0.5): 50% champion  [Mom+LowVol, Top-500, quarterly]
          + 50% smalltail [Mom+LowVol, SmallCap rank-band 300-1000, quarterly]

Combined portfolio = union of each sleeve's Top-10, each name weighted sleeve_weight/10;
overlapping names sum. Whole-share rounded to the chosen book size. Cold start (no prior
holdings) so each sleeve is plain Top-10 by score (buffer reduces to Top-N with no holdings).

FRESHNESS: portfolios are AS-OF the latest cached date. If that is stale vs today, refresh the
data cache (`main.py download` / the data pipeline) before starting live paper tracking — the
holdings must be generated on fresh EOD data.

Run:  py run_program2_paper_portfolios.py
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
from run_smallcap_universe import RankBandUniverseBuilder
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK
from run_program2_breakout import make_breakout_scorer

CAPITAL = 500_000.0        # paper book size (matches the champion's paper context)
N_STOCKS = 10
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
ODIR = RESULTS_DIR / "program2_paper"

# candidate -> list of (sleeve_name, sleeve_weight, scorer_key, band)
CANDIDATES = {
    "A+C(0.3)": [("champion", 0.70, "mlv", (0, 500)),
                 ("breakout", 0.30, "breakout", (0, 500))],
    "A+B(0.5)": [("champion", 0.50, "mlv", (0, 500)),
                 ("smalltail", 0.50, "mlv", (300, 1000))],
}


def sleeve_topn(ac, ah, al, av, at, cfg, scorer, band, date):
    bld = RankBandUniverseBuilder(ac, ah, al, av, at, cfg.universe, band[0], band[1])
    uni = bld.build_universe(date).symbols
    scores = scorer(ac, date, uni)
    return list(scores.index[:N_STOCKS])


def build_portfolio(candidate, sleeves, ac, ah, al, av, at, cfg, date, scorers):
    """Combine sleeves' Top-10 into a weighted target portfolio (aggregated by symbol)."""
    weights = {}   # symbol -> total weight
    detail = []    # per (sleeve, symbol)
    for sleeve_name, sw, key, band in sleeves:
        picks = sleeve_topn(ac, ah, al, av, at, cfg, scorers[key], band, date)
        per = sw / N_STOCKS if picks else 0.0
        for s in picks:
            weights[s] = weights.get(s, 0.0) + per
            detail.append((sleeve_name, sw, s, per))
    close = ac.loc[date]
    rows = []
    for s, wtot in sorted(weights.items(), key=lambda kv: -kv[1]):
        price = float(close.get(s, np.nan))
        if not (price > 0):
            continue
        val = CAPITAL * wtot
        shares = int(val / price)
        rows.append({"symbol": s, "target_weight": round(wtot, 4), "price": round(price, 2),
                     "shares": shares, "value": round(shares * price, 0),
                     "actual_weight": round(shares * price / CAPITAL, 4),
                     "sleeves": "+".join(sorted({d[0] for d in detail if d[2] == s}))})
    df = pd.DataFrame(rows)
    return df, detail


def main():
    cfg = SystemConfig()
    print("=" * 92)
    print("  PROGRAM #2 — PAPER-TRADING TARGET PORTFOLIOS (A+C and A+B)".center(92))
    print("=" * 92)

    ac = pd.read_parquet(CACHE_BHAV / "adj_close.parquet")
    ah = pd.read_parquet(CACHE_BHAV / "adj_high.parquet")
    al = pd.read_parquet(CACHE_BHAV / "adj_low.parquet")
    av = pd.read_parquet(CACHE_BHAV / "raw_volume.parquet")
    at = pd.read_parquet(CACHE_BHAV / "raw_turnover.parquet")
    eq_syms = load_equity_symbols()
    if eq_syms is not None:
        keep = [c for c in ac.columns if c in eq_syms]
        ac, ah, al, av, at = (p[keep] for p in (ac, ah, al, av, at))
    date = ac.index[-1]
    print(f"\n  As-of date (latest cached): {date.date()}   Book: Rs {CAPITAL:,.0f}")
    print(f"  (If stale vs today, refresh the data cache before live paper start.)\n")

    scorers = {"mlv": make_mom_lowvol_scorer(0.5, VOL_LOOKBACK),
               "breakout": make_breakout_scorer(av, need_volume=True)}

    ODIR.mkdir(parents=True, exist_ok=True)
    summary = []
    for cand, sleeves in CANDIDATES.items():
        df, detail = build_portfolio(cand, sleeves, ac, ah, al, av, at, cfg, date, scorers)
        fname = ODIR / (cand.replace("(", "_").replace(")", "").replace(".", "").replace("+", "") + "_target.csv")
        df.to_csv(fname, index=False)
        invested = df["value"].sum()
        print(f"[{cand}]  {len(df)} names, invested Rs {invested:,.0f} "
              f"({invested/CAPITAL:.0%}), cash Rs {CAPITAL-invested:,.0f}")
        print(df.to_string(index=False))
        print(f"  -> {fname}\n")
        summary.append({"candidate": cand, "n_names": len(df), "invested": invested,
                        "cash": CAPITAL - invested, "file": fname.name})

    pd.DataFrame(summary).to_csv(ODIR / "summary.csv", index=False)
    (ODIR / "asof.txt").write_text(f"as_of_date={date.date()}\nbook={CAPITAL:.0f}\n", encoding="utf-8")
    print(f"  Saved target portfolios + summary to {ODIR}/")
    print("  NOTE: as-of the latest cached date; refresh data before starting live paper tracking.")


if __name__ == "__main__":
    main()
