# CLAUDE.md

Systematic quant trading/backtest system for Indian equities (NSE / NIFTY 500),
Python 3.9. Reads cached price data and emits text tables + multi-panel report PNGs.

## Environment

- Run with the `py` launcher (`py main.py ...`), **not** bare `python`.
- **`main.py` crashes on the ₹ sign under Windows cp1252.** Prefix `$env:PYTHONUTF8=1`
  (PowerShell) or use the run-quant driver. `run_pure_momentum.py` / `run_fast.py`
  self-fix encoding and need no prefix.
- Cached data ships in repo (`data/cache/*.parquet`, `data/market_data.db`) — backtests
  run offline. Only `download` and `scan` hit the network (yfinance).

## Entry points

- `main.py <cmd>` — CLI: `download`, `backtest`, `backtest-quick`, `scan`,
  `validate-data`, `costs`, `report` (report = stub).
- `run_pure_momentum.py` — flagship: pure 12-1 momentum factor isolation, gross+net,
  makes `results/pure_momentum/*.png`. **This is the validated strategy (~19–22% CAGR).**
- `run_fast.py` — quick monthly/quarterly grid from cache.
- `analyze_*.py` (root) — ad-hoc post-run analysis of saved results.

## Code map — where things live

| Area | File | Does |
|---|---|---|
| Config | `config.py` | All hyperparams, paths, grids, capital. Start here to change params. |
| Backtest loop | `backtest/engine.py` | Vectorized engine: PIT universe, signals, rebalance, equity curve. |
| Overfit checks | `backtest/anti_overfit.py` | Walk-forward + parameter stability. |
| Strategy base | `strategies/base.py` | ABC; every strategy returns 0–100 cross-sectional rank via `compute_scores()`. |
| Momentum | `strategies/momentum.py` | 12-1 momentum (Jegadeesh-Titman). Core alpha source. |
| Trend | `strategies/trend_following.py` | Price-vs-EMA uptrend signal. |
| Breakout | `strategies/breakout.py` | Donchian breakout + volume surge. |
| Mean reversion | `strategies/mean_reversion.py` | Mean-revert only within uptrend. |
| Ranking | `portfolio/ranker.py` | Blends strategy scores by regime weights + sector caps. |
| Position sizing | `portfolio/constructor.py` | Equal / inverse-vol / risk-parity, whole-share rounding. |
| Regime | `regime/regime_filter.py` | BULL/NEUTRAL/BEAR from Nifty 50 proxy → capital allocation. |
| Risk | `risk/risk_manager.py` | Stop losses, drawdown limits. (Known: hurt returns — see memory.) |
| Rebalance | `risk/rebalancer.py` | Target vs current → trade list. |
| Universe | `universe/universe_builder.py` | PIT tradeable universe per rebalance date. |
| Filters | `universe/filters.py` | Liquidity / quality / anti-manipulation filters. |
| Data fetch | `data/downloader.py` | yfinance OHLCV download + parquet cache + `build_price_panel`. |
| DB | `data/database.py` | SQLite store/retrieve. |
| Benchmark | `data/benchmark.py` | NIFTY 500 TRI loader (user CSV). |
| Data QA | `data/quality.py` | Completeness/anomaly checks (`validate-data`). |
| Costs | `costs/cost_model.py` | STT, stamp, GST, brokerage, slippage — Indian delivery trades. |
| Metrics | `analytics/metrics.py` | CAGR, Sharpe, Sortino, MaxDD, Calmar, alpha/beta, turnover. |
| Charts | `analytics/visualizer.py` | Equity/drawdown/heatmap/rolling report PNGs. |
| Indicators | `utils/indicators.py` | Pure vectorized TA (EMA, ATR, etc.). |
| Helpers | `utils/helpers.py` | Rebalance dates, lot rounding, logging. |

## Skills (`.claude/skills/`)

- `/run-quant` — launch/backtest/screenshot the system. Use its driver
  (`.claude/skills/run-quant/driver.py`) to run: `smoke | backtest | all`.
- `/caveman` — respond in caveman talk (style only; code stays normal).

## Outputs

- `results/` and `results/pure_momentum/` — report PNGs + comparison charts.
- `logs/` — per-module log files.
