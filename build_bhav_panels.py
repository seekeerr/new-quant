"""
Stitch the per-day bhavcopy parquet cache into wide panels (dates x symbols)
for CLOSE, HIGH, LOW, VOLUME, TURNOVER. RAW (unadjusted) prices.

Also writes:
  data/cache_bhav/symbols_active.txt   - traded in the last ~20 sessions (still listed)
  data/cache_bhav/symbols_delisted.txt - traded historically but NOT recently
  data/cache_bhav/symbol_isin.csv      - latest ISIN per symbol (for Upstox keys)

Output: data/cache_bhav/raw_{close,high,low,volume,turnover}.parquet
"""
import glob
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "bhavcopy_cache"
OUT = ROOT / "data" / "cache_bhav"
OUT.mkdir(parents=True, exist_ok=True)

files = sorted(f for f in glob.glob(str(CACHE / "*.parquet")))
print(f"Reading {len(files)} daily bhavcopy files...")

close, high, low, vol, turn = {}, {}, {}, {}, {}
isin_latest = {}

for i, f in enumerate(files):
    d = pd.Timestamp(Path(f).stem)
    df = pd.read_parquet(f)
    df = df[~df["SYMBOL"].duplicated(keep="last")].set_index("SYMBOL")
    close[d] = df["CLOSE"]; high[d] = df["HIGH"]; low[d] = df["LOW"]
    vol[d] = df["VOLUME"]; turn[d] = df["TURNOVER"]
    for sym, iz in df["ISIN"].items():
        if isinstance(iz, str) and iz.startswith("INE"):
            isin_latest[sym] = iz           # last seen wins -> most recent ISIN
    if (i + 1) % 500 == 0:
        print(f"  ...{i+1}/{len(files)}")

def panel(dct):
    p = pd.DataFrame(dct).T
    p.index = pd.to_datetime(p.index); p.sort_index(inplace=True)
    return p.astype("float32")

cp = panel(close); hp = panel(high); lp = panel(low); vp = panel(vol); tp = panel(turn)
print(f"Panel shape: {cp.shape[0]} dates x {cp.shape[1]} symbols")

cp.to_parquet(OUT / "raw_close.parquet")
hp.to_parquet(OUT / "raw_high.parquet")
lp.to_parquet(OUT / "raw_low.parquet")
vp.to_parquet(OUT / "raw_volume.parquet")
tp.to_parquet(OUT / "raw_turnover.parquet")

# Active vs delisted: traded in the last 20 sessions?
last20 = cp.tail(20)
active = sorted(last20.columns[last20.notna().any()].tolist())
all_syms = sorted(cp.columns.tolist())
delisted = sorted(set(all_syms) - set(active))

(OUT / "symbols_active.txt").write_text("\n".join(active))
(OUT / "symbols_delisted.txt").write_text("\n".join(delisted))
pd.Series(isin_latest, name="ISIN").rename_axis("SYMBOL").to_csv(OUT / "symbol_isin.csv")

print(f"Symbols total={len(all_syms)}  active(recent)={len(active)}  delisted={len(delisted)}")
print(f"ISIN mapped for {len(isin_latest)} symbols")
print(f"Date range: {cp.index.min().date()} .. {cp.index.max().date()}")
print("Saved panels to", OUT)
