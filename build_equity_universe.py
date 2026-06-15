"""
Build the COMMON-EQUITY whitelist from the daily bhavcopy ISINs, so the backtest
universe can exclude every non-equity instrument that leaks through NSE's
SERIES=="EQ" bhavcopy (ETFs are listed under EQ on NSE).

Classification by ISIN prefix (the authoritative identity, not the ticker string):
  INE...  -> common company equity            -> KEEP
  INF...  -> mutual-fund / ETF units          -> DROP  (gold/silver/liquid/index ETFs, fund units)
  IN9...  -> DVR / special class (e.g. TATAMTRDVR) -> DROP
  (blank/other) -> cannot confirm equity      -> DROP

A symbol is EQUITY iff it ever traded under an INE ISIN AND never under an INF ISIN
(guards the rare ticker-reuse where an equity ticker was later an ETF).

Outputs (data/cache_bhav/):
  symbols_equity.txt      - the whitelist the champion universe will use
  symbols_nonequity.csv   - what was removed, with latest ISIN + reason (for audit)

Run:  py build_equity_universe.py
"""
import glob
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
DAILY = ROOT / "data" / "bhavcopy_cache"
OUT = ROOT / "data" / "cache_bhav"

files = sorted(glob.glob(str(DAILY / "*.parquet")))
print(f"Scanning {len(files)} daily bhavcopy files for ISIN identity...")

prefixes = {}      # symbol -> set of ISIN prefixes seen
latest_isin = {}   # symbol -> latest non-blank ISIN (chronological)
for i, f in enumerate(files):
    try:
        df = pd.read_parquet(f, columns=["SYMBOL", "ISIN"])
    except Exception:
        continue
    for s, iz in zip(df["SYMBOL"].astype(str), df["ISIN"].astype(str)):
        if iz and iz != "nan" and len(iz) >= 3:
            prefixes.setdefault(s, set()).add(iz[:3])
            latest_isin[s] = iz
    if (i + 1) % 500 == 0:
        print(f"  ...{i+1}/{len(files)}")

equity, nonequity = [], []
for s, pfx in prefixes.items():
    if ("INE" in pfx) and ("INF" not in pfx):
        equity.append(s)
    else:
        reason = "fund/ETF (INF)" if "INF" in pfx else (
                 "DVR/special (IN9)" if "IN9" in pfx else f"other {sorted(pfx)}")
        nonequity.append((s, latest_isin.get(s, ""), reason))

equity = sorted(set(equity))
(OUT / "symbols_equity.txt").write_text("\n".join(equity))
ne = pd.DataFrame(nonequity, columns=["SYMBOL", "latest_ISIN", "reason"]).sort_values("SYMBOL")
ne.to_csv(OUT / "symbols_nonequity.csv", index=False)

print(f"\nEQUITY (INE)        : {len(equity)}")
print(f"NON-EQUITY removed  : {len(ne)}")
print(ne["reason"].value_counts().to_string())
print(f"\nWrote {OUT/'symbols_equity.txt'}")
print(f"Wrote {OUT/'symbols_nonequity.csv'}")
