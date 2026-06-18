"""
STAGE-1 PILOT — STEP 1 ONLY: build the ~40-company pilot SAMPLE and an EMPTY template.

Scope (deliberately tiny): this script does PURE ANALYSIS on the existing survivorship-free
bhavcopy price spine. It builds NO scraper, NO PIT database, NO bitemporal store, NO SQL
schema, NO ingestion pipeline. It DOES NOT run a backtest, DOES NOT compute any Quality
score, and DOES NOT produce any investment conclusion. It only:

  1. samples ~40 representative companies from the Top-100 liquid universe over full history,
  2. writes data/cache_fundamentals/pilot_company_list.csv  (the sample),
  3. writes data/cache_fundamentals/pilot_fundamentals.csv  (an EMPTY template to verify),
  4. prints coverage statistics, and STOPS.

The next step begins only after a human verifies the fundamentals CSV.

Sampling rule (reproducible, fixed seed; no performance cherry-picking)
----------------------------------------------------------------------
1. Build the Top-100-by-₹turnover union over every quarterly rebalance 2011->2026 (the same
   liquidity/quality filters the validated strategy uses). A name is in the union if it was
   ever Top-100.
2. status      = delisted (in symbols_delisted.txt) else active.
   cap_bucket  = turnover terciles across the union (large / mid / small) — bhavcopy has no
                 shares-outstanding, so liquidity is the size proxy.
3. FORCE-INCLUDE recognisable CATASTROPHIC FAILURES that actually appear in the union (the
   pilot is dishonest without the names momentum buys on the way up that then collapse), then
   fill to ~40 by deterministic stratified sampling across cap_bucket x status so large/mid/
   small and active/delisted, winners and failures, are all represented.

Run:  py pilot_select_companies.py
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

from config import SystemConfig
from utils.helpers import get_rebalance_dates
from universe.filters import apply_all_filters

CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
OUT_DIR = PROJECT_ROOT / "data" / "cache_fundamentals"
TARGET_N = 40
SEED = 20260618

# Catastrophic failures (and near-death survivors) to force-include IF present in the union.
KNOWN_FAILURES = [
    "DHFL", "RCOM", "JETAIRWAYS", "RELCAPITAL", "RELINFRA", "IBREALEST", "GITANJALI",
    "KFA", "GVKPIL", "JPASSOCIAT", "HDIL", "GMRINFRA", "ABAN", "PUNJLLOYD", "VIDEOIND",
    "LANCOIN", "UNITECH", "SUZLON", "YESBANK", "MTNL",
]
# Best-effort sector labels for well-known names absent from the current constituents CSV
# (delisted names are not in it). Used for the coverage print only.
FAILURE_SECTORS = {
    "DHFL": "Financial Services", "RCOM": "Telecom", "JETAIRWAYS": "Transport/Aviation",
    "RELCAPITAL": "Financial Services", "RELINFRA": "Infrastructure/Power",
    "IBREALEST": "Realty", "GITANJALI": "Gems & Jewellery", "KFA": "Transport/Aviation",
    "GVKPIL": "Infrastructure", "JPASSOCIAT": "Construction/Cement", "HDIL": "Realty",
    "GMRINFRA": "Infrastructure", "ABAN": "Oil & Gas Services", "PUNJLLOYD": "Construction",
    "VIDEOIND": "Consumer Durables", "LANCOIN": "Power/Infrastructure", "UNITECH": "Realty",
    "SUZLON": "Capital Goods/Renewables", "YESBANK": "Financial Services", "MTNL": "Telecom",
}


def load_panels():
    ac = pd.read_parquet(CACHE_BHAV / "adj_close.parquet")
    ah = pd.read_parquet(CACHE_BHAV / "adj_high.parquet")
    al = pd.read_parquet(CACHE_BHAV / "adj_low.parquet")
    av = pd.read_parquet(CACHE_BHAV / "raw_volume.parquet")
    at = pd.read_parquet(CACHE_BHAV / "raw_turnover.parquet")
    eq = set(s.strip() for s in open(CACHE_BHAV / "symbols_equity.txt") if s.strip())
    cols = [c for c in ac.columns if c in eq]
    ac, ah, al, av, at = (df[cols] for df in (ac, ah, al, av, at))
    return ac, ah, al, av, at


def build_union(cfg, ac, ah, al, av, at):
    """Top-100-by-turnover union over quarterly rebalances. Returns per-symbol stats."""
    start = pd.Timestamp(cfg.backtest.start_date)
    end = min(pd.Timestamp(cfg.backtest.end_date), ac.index.max())
    all_dates = ac.index[(ac.index >= start) & (ac.index <= end)]
    rebs = get_rebalance_dates(all_dates, "quarterly")
    lookback = cfg.universe.turnover_lookback

    n_quarters, adtv_hist, first_seen, last_seen = {}, {}, {}, {}
    for d in rebs:
        fr = apply_all_filters(ac, ah, al, av, d, cfg.universe)
        syms = [s for s in fr.passed_symbols if s in at.columns]
        if not syms:
            continue
        m = at.index <= d
        adtv = at.loc[m].tail(lookback)[syms].mean()
        top = adtv.sort_values(ascending=False).head(100)   # Top-100 liquidity
        for s, v in top.items():
            n_quarters[s] = n_quarters.get(s, 0) + 1
            adtv_hist.setdefault(s, []).append(float(v))
            first_seen.setdefault(s, d)
            last_seen[s] = d
    rows = [{"symbol": s, "n_quarters": n_quarters[s],
             "first_seen": first_seen[s].date(), "last_seen": last_seen[s].date(),
             "median_adtv": np.median(adtv_hist[s])} for s in n_quarters]
    return pd.DataFrame(rows), rebs


def main():
    cfg = SystemConfig()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 78)
    print("  STAGE-1 PILOT — STEP 1: sample ~%d companies (survivorship-free, reproducible)" % TARGET_N)
    print("  (no backtest, no quality score, no conclusion — data scaffolding only)")
    print("=" * 78)

    ac, ah, al, av, at = load_panels()
    print(f"  Equity-restricted panel: {ac.shape[0]} dates x {ac.shape[1]} symbols")

    de = set(s.strip() for s in open(CACHE_BHAV / "symbols_delisted.txt") if s.strip())
    isin_map = pd.read_csv(CACHE_BHAV / "symbol_isin.csv").set_index("SYMBOL")["ISIN"].to_dict()
    cons = pd.read_csv(PROJECT_ROOT / "data" / "nifty500_constituents.csv")
    sector_by_isin = dict(zip(cons["ISIN Code"], cons["Industry"]))

    print("  Building Top-100 liquidity union over quarterly rebalances ...")
    u, rebs = build_union(cfg, ac, ah, al, av, at)
    print(f"  Union size: {len(u)} distinct names across {len(rebs)} quarterly rebalances")

    u["status"] = u["symbol"].apply(lambda s: "delisted" if s in de else "active")
    u["isin"] = u["symbol"].map(isin_map)
    u["cap_bucket"] = pd.qcut(u["median_adtv"].rank(method="first"),
                              3, labels=["small", "mid", "large"]).astype(str)
    u["sector"] = u["isin"].map(sector_by_isin)
    for i in u.index:
        if pd.isna(u.at[i, "sector"]) and u.at[i, "symbol"] in FAILURE_SECTORS:
            u.at[i, "sector"] = FAILURE_SECTORS[u.at[i, "symbol"]]

    # ── Selection: forced failures + deterministic stratified fill ──
    rng = np.random.default_rng(SEED)
    union_syms = set(u["symbol"])
    forced = [s for s in KNOWN_FAILURES if s in union_syms]
    selected, reason = list(forced), {s: "forced_failure" for s in forced}

    strata = {}
    for _, r in u.iterrows():
        strata.setdefault((r["cap_bucket"], r["status"]), []).append(r["symbol"])
    order = [(c, st) for c in ["large", "mid", "small"] for st in ["active", "delisted"]]
    pools = {k: list(rng.permutation(v)) for k, v in strata.items()}
    while len(selected) < TARGET_N and any(pools.get(k) for k in order):
        for k in order:
            if len(selected) >= TARGET_N:
                break
            pool = pools.get(k, [])
            while pool:
                cand = pool.pop()
                if cand not in selected:
                    selected.append(cand); reason[cand] = f"stratified_{k[0]}_{k[1]}"
                    break
    selected = selected[:TARGET_N]

    sel = u[u["symbol"].isin(selected)].copy()
    sel["reason_selected"] = sel["symbol"].map(reason)

    # ── Write pilot_company_list.csv (EXACT requested schema) ──
    list_cols = ["symbol", "isin", "status", "cap_bucket", "first_seen", "last_seen", "reason_selected"]
    sel_out = sel.sort_values(["cap_bucket", "status", "symbol"])[list_cols]
    sel_out.to_csv(OUT_DIR / "pilot_company_list.csv", index=False)

    # ── Write pilot_fundamentals.csv (EXACT requested schema; EMPTY; verified=FALSE) ──
    fund_cols = ["symbol", "isin", "fiscal_year", "period_end", "filing_date", "revenue",
                 "cogs", "gross_profit", "net_profit", "total_assets", "total_equity",
                 "total_debt", "ocf", "source", "confidence", "verified"]
    trows = []
    for _, r in sel.iterrows():
        s = ac[r["symbol"]].dropna()
        if s.empty:
            continue
        y0 = max(2010, s.index.min().year)
        y1 = min(2025, s.index.max().year + 1)
        for fy in range(y0, y1 + 1):
            row = {c: "" for c in fund_cols}
            row.update({"symbol": r["symbol"], "isin": r["isin"], "fiscal_year": fy,
                        "period_end": f"{fy}-03-31", "verified": "FALSE"})
            trows.append(row)
    tdf = pd.DataFrame(trows)[fund_cols]
    tdf.to_csv(OUT_DIR / "pilot_fundamentals.csv", index=False)

    # ── Coverage statistics ──
    print("\n" + "-" * 78)
    print("  COVERAGE STATISTICS (selected pilot sample)")
    print("-" * 78)
    print(f"  Total selected companies : {len(sel)}")
    print(f"  Active companies         : {(sel['status'] == 'active').sum()}")
    print(f"  Delisted companies       : {(sel['status'] == 'delisted').sum()}")
    print(f"  Catastrophic failures forced-in: {len(set(forced) & set(selected))} "
          f"-> {sorted(set(forced) & set(selected))}")
    print("\n  Cap-bucket split (large / mid / small):")
    for cb in ["large", "mid", "small"]:
        print(f"    {cb:<6}: {(sel['cap_bucket'] == cb).sum()}")
    print("\n  Sector distribution:")
    secs = sel["sector"].fillna("(unknown — fill on verification)").value_counts()
    for name, cnt in secs.items():
        print(f"    {cnt:>2}  {name}")
    print("-" * 78)
    print(f"\n  Wrote {OUT_DIR/'pilot_company_list.csv'}  ({len(sel_out)} companies)")
    print(f"  Wrote {OUT_DIR/'pilot_fundamentals.csv'}  "
          f"({len(tdf)} EMPTY company-year rows, all financials blank, verified=FALSE)")
    print("\n  >>> STOP. Next step begins only AFTER a human fills + verifies")
    print("      pilot_fundamentals.csv (set verified=TRUE per checked row).")
    print("=" * 78)


if __name__ == "__main__":
    main()
