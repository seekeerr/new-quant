---
name: run-quant
description: Run, backtest, validate, scan, or screenshot the systematic quant trading system for Indian equities (NSE/NIFTY). Use to launch the 12-1 momentum backtest, regenerate the report PNG charts, run cost/data-quality checks, or smoke-test the CLI after a change.
---

# Run the quant backtest system

A **Python 3.9 CLI** backtesting system for NSE/NIFTY equities. No GUI, no
server — you drive it by running entry-point scripts that read cached price
data (`data/cache/*.parquet`, `data/market_data.db`) and emit text tables plus
multi-panel **report PNGs** under `results/`.

All paths below are relative to the project root (the directory containing
`main.py`). Run everything from there.

The reliable way to drive this app is the committed driver at
`.claude/skills/run-quant/driver.py`. It forces UTF-8 in child processes and
captures their output internally — which sidesteps two real traps (see
Gotchas) that bite you if you invoke the scripts by hand.

## Prerequisites

- Python 3.9 on PATH via the `py` launcher (`py --version` → `Python 3.9.7`).
- Dependencies already installed in this environment. Verify:

```powershell
py -c "import pandas,numpy,scipy,matplotlib,yfinance,pyarrow,tqdm; print('all imports OK')"
```

If that fails: `py -m pip install -r requirements.txt`.

Cached data ships with the repo (50 parquet files + a 24 MB SQLite db), so
backtests run offline. No download or build step is needed.

## Run (agent path) — use the driver

```powershell
py .claude/skills/run-quant/driver.py smoke      # fast, cache-only, no network (~20s)
py .claude/skills/run-quant/driver.py backtest   # flagship 12-1 momentum, regenerates PNGs (~40s)
py .claude/skills/run-quant/driver.py all         # smoke + backtest
```

- `smoke` runs `main.py costs` and `main.py validate-data`, asserting key
  output strings and exit 0.
- `backtest` runs `run_pure_momentum.py`, asserts the diagnosis output is
  present, then confirms these PNGs were **freshly regenerated** (mtime
  advanced) under `results/pure_momentum/`:
  `factor_report_5stocks_quarterly.png`, `factor_report_10stocks_monthly.png`,
  `factor_comparison.png`.
- Driver prints `==== DRIVER PASS ====` and exits 0 on success.

**To "screenshot" the app**, run `backtest`, then open a report PNG — e.g.
`results/pure_momentum/factor_report_5stocks_quarterly.png`. It's a 6-panel
chart: equity curve (gross vs net vs benchmark), drawdown, monthly-returns
heatmap, return distribution, rolling 3-year CAGR, and a metrics table.
Expected flagship result: best config `5stocks_quarterly` ≈ **22% gross /
21% net CAGR** (matches the project's known 19–22% momentum finding).

## Run (human path) — individual commands

`main.py` is the documented CLI. **It prints the ₹ sign and crashes under
Windows' default console encoding** — you must force UTF-8 first:

```powershell
$env:PYTHONUTF8=1; py main.py costs           # transaction-cost table (instant)
$env:PYTHONUTF8=1; py main.py validate-data    # data-quality report (~15s, cache)
$env:PYTHONUTF8=1; py main.py scan             # current signals — MAKES LIVE NETWORK CALLS
$env:PYTHONUTF8=1; py run_pure_momentum.py      # flagship backtest (self-fixes encoding)
```

Other `main.py` subcommands: `download` (fetches via yfinance — needs network),
`backtest` / `backtest-quick` (full grid), `report` (stub, prints "coming soon").

`run_pure_momentum.py` and `run_fast.py` already reconfigure their own stdout to
UTF-8, so they run without the `$env:PYTHONUTF8` prefix.

## Gotchas

- **₹ (U+20B9) crashes `main.py` on Windows.** Default console encoding is
  cp1252; printing the Rupee sign raises `UnicodeEncodeError` and aborts the
  command (e.g. `main.py costs` dies after the header). Fix: `$env:PYTHONUTF8=1`
  (PowerShell) or `PYTHONUTF8=1` (bash). The driver sets this for you.
- **Don't pipe these scripts into `Select-Object -First N` in PowerShell.**
  Closing the pipe early makes Python exit nonzero (looks like a failure when
  the program actually worked). The driver captures output internally and
  avoids this — another reason to prefer it.
- **`scan` hits the network** (`download_market_proxy` always refetches Nifty 50,
  ignoring cache). Expect a slow yfinance call and possibly a `TATMOTORS.NS
  delisted` warning; it still exits 0. The backtest/validate paths are offline.
- **`scan` can legitimately select 0 stocks.** If it reports `Market Regime:
  BEAR` with 0% allocation, the top-stocks table is empty by design — not a bug.
- Backtests are CPU-only and fast from cache (~40s for the 4-config momentum
  grid). The cached data ends ~2026-05-29, so the final partial year shows
  negative returns.

## Troubleshooting

- `UnicodeEncodeError: 'charmap' codec can't encode character '₹'` → you
  forgot UTF-8. Use the driver, or prefix `$env:PYTHONUTF8=1`.
- `No stock data. Run 'python main.py download' first.` → the parquet cache
  under `data/cache/` is missing/empty. The repo ships it; if absent, run
  `$env:PYTHONUTF8=1; py main.py download` (needs network).
- `Python was not found` → use the `py` launcher (not bare `python`); confirm
  with `py --version`.

## The driver

`.claude/skills/run-quant/driver.py` — committed alongside this skill. Modes:
`smoke`, `backtest`, `all`. It launches the entry-point scripts as subprocesses
with `PYTHONUTF8=1`, checks exit codes + expected output strings, and (for
`backtest`) verifies the report PNGs were regenerated. Extend it by adding modes
to `main()`.
