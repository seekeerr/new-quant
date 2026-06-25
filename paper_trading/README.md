# paper_trading/ — Operational Data Contract

This directory holds the **operator-owned** live operational state for paper
trading the frozen champion. It is the *only* new data area the dashboard
introduces; everything else it reads already exists in the repo.

- **The dashboard reads these files; it never writes them.**
- These files are maintained by the operator following
  [../PAPER_TRADING_PROTOCOL.md](../PAPER_TRADING_PROTOCOL.md).
- The repo ships **EXAMPLE** data so the dashboard renders on first launch.
  Replace each file with your real ledger and set `"mode": "PAPER"` in
  `state.json`. A banner in the dashboard always shows the current mode.

All schemas are also summarised in
[../DASHBOARD_ARCHITECTURE.md §5](../DASHBOARD_ARCHITECTURE.md).

## Files

### `state.json`
```json
{
  "mode": "EXAMPLE | PAPER | LIVE",
  "strategy_label": "Momentum + LowVol · Top10 · Quarterly · Buffer20 · Equal Weight",
  "frozen_commit": "8f0482f",
  "frozen_tag": "price-only-final",
  "inception_date": "YYYY-MM-DD",
  "initial_capital": 500000.0,
  "cash": 0.0,
  "last_rebalance": "YYYY-MM-DD",
  "next_rebalance": "YYYY-MM-DD",
  "benchmark": "NIFTY 500 (price)"
}
```

### `holdings.csv`
`symbol, quantity, cost_price, entry_date` — one row per open position.
Current price, market value, weight and P&L% are **derived** by the dashboard
from the price cache + cash; do not store them here.

### `target_portfolio.csv`
`rank, symbol, score, in_top10, in_buffer20, classification, current_held`
- `in_top10` / `in_buffer20`: booleans (`True`/`False`).
- `classification`: `BUY` (target, not held) · `HOLD` (target & held) ·
  `SELL` (held & dropped from target).

### `rebalance_history.csv`
`date, num_holdings, turnover_pct, holdings_snapshot, notes, snapshot_id`
- `holdings_snapshot`: `;`-joined symbol list.
- `snapshot_id`: links to `audit/<id>/`.

### `trade_log.csv` (append-only)
`date, symbol, action, quantity, price, costs, notes` — `action ∈ {BUY, SELL}`.
Never edit in place; corrections are new dated rows.

### `equity_curve.csv`
`date, portfolio_value` — periodic paper NAV. Drives the Performance page and
the drawdown / CAGR KPIs.

### `audit/<YYYY-Qn>/`
Immutable per-quarter package (data snapshot ref, ranks, trade list, fills,
commit/config hash, logs) per
[../LIVE_TRADING_ARCHITECTURE.md §3 Stage 12](../LIVE_TRADING_ARCHITECTURE.md).
A file whose name contains `FAIL` or `HALT` raises a validation alert.
