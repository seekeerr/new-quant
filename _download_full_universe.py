"""
One-off: download full NIFTY 500 OHLCV into the parquet cache and record
exactly which symbols loaded vs failed. Also fetch the ^CRSLDX (Nifty 500
PRICE index) benchmark proxy and write it as data/nifty500_tri.csv.

Run: py _download_full_universe.py
"""
import sys, io, time, json, ssl, urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import warnings; warnings.filterwarnings("ignore")
import logging; logging.disable(logging.WARNING)
import pandas as pd
import yfinance as yf

from config import DownloadConfig, CACHE_DIR, BENCHMARK_CSV_PATH
from data.downloader import load_nifty500_symbols, download_all_stocks

cfg = DownloadConfig()
symbols = load_nifty500_symbols()
print(f"Constituent list: {len(symbols)} symbols", flush=True)

t0 = time.time()
data = download_all_stocks(cfg, symbols=symbols, use_cache=True)
print(f"\nDownload finished in {time.time()-t0:.0f}s", flush=True)

loaded = sorted(data.keys())
failed = sorted(set(symbols) - set(loaded))

# Coverage stats on what loaded
cov = []
for s in loaded:
    df = data[s]
    cov.append({
        "symbol": s,
        "rows": len(df),
        "first": str(df.index.min().date()),
        "last": str(df.index.max().date()),
    })
cov_df = pd.DataFrame(cov)
cov_df.to_csv(PROJECT_ROOT / "_universe_coverage.csv", index=False)

summary = {
    "requested": len(symbols),
    "loaded": len(loaded),
    "failed": len(failed),
    "failed_symbols": failed,
}
(PROJECT_ROOT / "_download_summary.json").write_text(json.dumps(summary, indent=2))
print(f"LOADED {len(loaded)} / {len(symbols)}  |  FAILED {len(failed)}", flush=True)
print("Failed symbols:", failed, flush=True)

# ── Benchmark proxy: ^CRSLDX (Nifty 500 PRICE index) ──
print("\nDownloading ^CRSLDX benchmark proxy...", flush=True)
try:
    bm = yf.download("^CRSLDX", start=cfg.start_date, end=cfg.end_date,
                     auto_adjust=True, progress=False, timeout=60)
    if isinstance(bm.columns, pd.MultiIndex):
        bm.columns = bm.columns.get_level_values(0)
    bm = bm[["Close"]].dropna()
    bm.index.name = "Date"
    bm.reset_index().to_csv(BENCHMARK_CSV_PATH, index=False)
    print(f"Benchmark saved: {BENCHMARK_CSV_PATH}  rows={len(bm)} "
          f"{bm.index.min().date()}..{bm.index.max().date()}", flush=True)
except Exception as e:
    print("Benchmark download FAILED:", repr(e), flush=True)

print("\nDONE.", flush=True)
