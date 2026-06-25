# DASHBOARD ARCHITECTURE — Phase 3F (Operational MVP)

**Strategy (frozen, unchanged):** Momentum + LowVol · Top 10 · Quarterly · Buffer 20 · Equal Weight · Equity Only · Survivorship-Free
**Frozen commit:** `8f0482f` · **Tag:** `price-only-final`
**Date:** 2026-06-23
**Scope:** A lightweight, **read-only**, **local-first** operational dashboard for **paper trading** (and, later, monitoring live trading) of the frozen champion. It is *not* a research dashboard, *not* a factor-research platform, and *not* a backtesting engine.

> **Non-goals (explicit):** no broker integration, no order execution, no authentication, no multi-user support, no cloud deployment, no strategy/parameter changes. The dashboard never *writes* trading state and never *computes* signals. It only *reads and displays* artifacts the operator and the frozen system produce.

---

## 1. Design Principles

1. **Read-only, always.** The dashboard opens files for reading only. It never mutates the paper ledger, holdings, trade log, or any research artifact. The operator maintains those files via the [PAPER_TRADING_PROTOCOL.md](PAPER_TRADING_PROTOCOL.md) runbook; the dashboard merely surfaces them.
2. **Survive missing files.** Every loader returns a safe empty value and every page renders an explicit "no data yet" state instead of crashing. A fresh checkout with no paper-trading data must still launch all 8 pages.
3. **Reuse existing outputs.** Research PNGs, comparison CSVs, the benchmark TRI, the price cache, and the audit Markdown docs are read in place. The dashboard adds one new, small, operator-owned data area (`paper_trading/`) for live operational state that does not exist anywhere else yet.
4. **Deterministic & stateless.** No background jobs, no schedulers, no sockets. Pure function of files-on-disk at page-load time. Caching (`st.cache_data`) is keyed on file mtime so edits show up on refresh.
5. **Operational, not analytical.** Pages answer "what do I hold, what must I trade, is anything wrong?" — not "which factor is best?".

---

## 2. Technology

| Concern | Choice | Why |
|---|---|---|
| UI framework | **Streamlit** | Single-file pages, zero front-end code, local-first by default. Already aligned with project's Python 3.9. |
| Charts | **Plotly** | Already in `requirements.txt`; interactive equity/drawdown curves. |
| Data | **pandas + pyarrow** | Already used everywhere; reads the existing parquet price cache and CSV artifacts. |
| Static reports | Existing **matplotlib PNGs** | Rendered as images; not regenerated. |

Run locally:

```bash
py -m pip install -r requirements.txt        # adds streamlit
py -m streamlit run dashboard/app.py
# opens http://localhost:8501
```

(`dashboard/run.py` is a thin convenience wrapper that fixes UTF-8 and launches the same command.)

---

## 3. Project Structure

```
new-quant/
├── DASHBOARD_ARCHITECTURE.md          # this document
├── dashboard/
│   ├── app.py                         # entry point + navigation router
│   ├── run.py                         # convenience launcher (UTF-8 safe)
│   ├── README.md                      # quickstart + data-contract summary
│   ├── pages/                         # one module per dashboard page
│   │   ├── overview.py                # 1. Portfolio Overview
│   │   ├── holdings.py                # 2. Current Holdings
│   │   ├── target.py                  # 3. Target Portfolio (Top10 / Buffer20)
│   │   ├── rebalances.py              # 4. Rebalance History
│   │   ├── trades.py                  # 5. Trade Log
│   │   ├── performance.py             # 6. Performance (equity/DD/benchmark)
│   │   ├── audit.py                   # 7. Audit Package Viewer
│   │   └── alerts.py                  # 8. Alerts
│   ├── components/                    # reusable, page-agnostic UI fragments
│   │   ├── layout.py                  # page header, "no data" notices, mode banner
│   │   ├── cards.py                   # metric cards / KPI rows
│   │   ├── tables.py                  # styled dataframes (P&L & BUY/HOLD/SELL coloring)
│   │   └── charts.py                  # plotly equity / drawdown / benchmark
│   └── utils/                         # pure, UI-free data access & logic
│       ├── paths.py                   # all on-disk locations (single source of truth)
│       ├── data_loader.py             # graceful readers for every paper_trading file
│       ├── prices.py                  # latest close per symbol from the price cache
│       ├── metrics.py                 # CAGR / drawdown / P&L from an equity curve
│       ├── alerts.py                  # operational alert rules (Section 6)
│       └── formatting.py              # ₹ / % / date / color helpers
│
├── paper_trading/                     # NEW — operator-owned live operational state
│   ├── README.md                      # the data contract (authoritative)
│   ├── state.json                     # NAV, cash, dates, mode, strategy stamp
│   ├── holdings.csv                   # current positions
│   ├── target_portfolio.csv           # latest Top10 + Buffer20 + BUY/HOLD/SELL
│   ├── rebalance_history.csv          # one row per rebalance
│   ├── trade_log.csv                  # append-only paper fills
│   ├── equity_curve.csv               # daily/periodic paper NAV
│   └── audit/                         # per-quarter immutable packages (read-only view)
│       └── <YYYY-Qn>/ ...             # snapshot, ranks, trade list, fills, logs
│
├── results/ ... results/pure_momentum/   # existing research PNGs + CSVs (read-only reuse)
├── data/cache_bhav/adj_close.parquet     # existing price cache (read-only reuse)
└── data/nifty500_tri.csv                 # existing benchmark (read-only reuse)
```

**Layering rule:** `pages → components → utils`. `utils` imports nothing from `components`/`pages`; `components` import only `utils`. This keeps data logic testable without Streamlit.

---

## 4. Data Flow

```
            EXISTING (read-only reuse)                 NEW (operator-owned)
   ┌──────────────────────────────────────┐   ┌──────────────────────────────────┐
   │ data/cache_bhav/adj_close.parquet     │   │ paper_trading/state.json          │
   │ data/nifty500_tri.csv  (benchmark)    │   │ paper_trading/holdings.csv        │
   │ results/**/*.png  (research charts)   │   │ paper_trading/target_portfolio.csv│
   │ results/**/comparison.csv (ref metrics)│  │ paper_trading/rebalance_history.csv│
   │ *_AUDIT.md / *_PROTOCOL.md (audit docs)│  │ paper_trading/trade_log.csv       │
   └───────────────────┬──────────────────┘   │ paper_trading/equity_curve.csv    │
                       │                       │ paper_trading/audit/<Q>/...        │
                       │                       └───────────────┬───────────────────┘
                       │                                       │
                       ▼                                       ▼
          ┌───────────────────────────────────────────────────────────────┐
          │  dashboard/utils  (graceful, cached, UI-free)                   │
          │  paths · data_loader · prices · metrics · alerts · formatting   │
          │  - every reader returns empty-on-missing, never raises          │
          │  - st.cache_data keyed on file mtime                            │
          └───────────────────────────────┬───────────────────────────────┘
                                          │ clean DataFrames / dicts / Series
                                          ▼
          ┌───────────────────────────────────────────────────────────────┐
          │  dashboard/components  (cards · tables · charts · layout)       │
          └───────────────────────────────┬───────────────────────────────┘
                                          ▼
          ┌───────────────────────────────────────────────────────────────┐
          │  dashboard/pages  (8 read-only views)  ── app.py navigation     │
          └───────────────────────────────────────────────────────────────┘
                                          ▼
                                  Operator's browser (localhost:8501)
```

**Live price join:** Current price / P&L is computed by joining `holdings.csv` (symbol, quantity, cost_price) against the **last available close** in `data/cache_bhav/adj_close.parquet`. The cache is refreshed by the existing daily-pull workflow (`main.py download` / bhavcopy build) — the dashboard never downloads. If the cache is stale or a held symbol is absent, that name's price shows `—` and an alert fires (Section 6).

---

## 5. Data Contract (`paper_trading/`)

The dashboard's operational data is the single new artifact set. It is **owned by the operator/runbook, not the dashboard.** Authoritative copy of this contract lives in [paper_trading/README.md](paper_trading/README.md). Summary:

### `state.json`
```json
{
  "mode": "EXAMPLE | PAPER | LIVE",
  "strategy_label": "Momentum + LowVol · Top10 · Quarterly · Buffer20 · Equal Weight",
  "frozen_commit": "8f0482f",
  "frozen_tag": "price-only-final",
  "inception_date": "2026-07-01",
  "initial_capital": 500000.0,
  "cash": 12450.0,
  "last_rebalance": "2026-07-01",
  "next_rebalance": "2026-10-01",
  "benchmark": "NIFTY 500 (price)"
}
```

### `holdings.csv`
`symbol, quantity, cost_price, entry_date` — one row per open position. Current price, market value, weight, and P&L% are **derived** by the dashboard (not stored), using the price cache + cash from `state.json`.

### `target_portfolio.csv`
`rank, symbol, score, in_top10, in_buffer20, classification, current_held` — the latest generated target. `classification ∈ {BUY, HOLD, SELL}` (BUY = target & not held; HOLD = target & held; SELL = held & not in target). Ranks 1–10 are the Top10; ranks within the Buffer20 band are flagged `in_buffer20=true`.

### `rebalance_history.csv`
`date, num_holdings, turnover_pct, holdings_snapshot, notes, snapshot_id` — one row per rebalance. `holdings_snapshot` is a `;`-joined symbol list; `snapshot_id` links to `audit/<Q>/`.

### `trade_log.csv` (append-only)
`date, symbol, action, quantity, price, costs, notes` — `action ∈ {BUY, SELL}`. Mirrors the protocol's paper ledger. Never edited in place; corrections are new dated rows.

### `equity_curve.csv`
`date, portfolio_value` — periodic paper NAV. Drives the Performance page and the drawdown/CAGR KPIs.

### `audit/<YYYY-Qn>/`
Immutable per-quarter package per [LIVE_TRADING_ARCHITECTURE.md §3 Stage 12]: data snapshot ref, scores/ranks, trade list, fills, commit/config hash, logs. The dashboard lists and previews these files read-only.

**Seed data:** the repo ships an `EXAMPLE`-mode sample set so every page renders on first launch. The operator replaces these with real paper-trading files (set `"mode": "PAPER"`); a persistent banner shows the current mode so example data is never mistaken for real positions.

---

## 6. Alerts (operational rules)

The Alerts page (and a summary badge in the header) evaluates pure, file-derived rules — no thresholds touch the strategy:

| Alert | Condition | Severity |
|---|---|---|
| **Missing data** | Price cache missing, or last close older than 5 trading days | HALT |
| **Missing holdings** | `holdings.csv` empty/absent while `state.json` mode ≠ EXAMPLE | HALT |
| **Price gap** | A held symbol has no price in the cache | HALT |
| **Rebalance due** | `today ≥ next_rebalance` (or within 5 sessions) | NOTIFY |
| **Validation failure** | A `VALIDATION_FAILED` / HALT marker present in latest audit dir or logs | HALT |
| **Weight drift** | Any holding's derived weight off its 10% target by > ±1.0% | NOTIFY |
| **Stale state** | `state.json` not updated since before `last_rebalance` | NOTIFY |

Severity mirrors the architecture's **HALT vs NOTIFY** model. The dashboard only *reports*; it never blocks or acts.

---

## 7. Page → Data mapping

| # | Page | Reads | Empty-state |
|---|---|---|---|
| 1 | Portfolio Overview | `state.json`, `holdings.csv`, `equity_curve.csv`, prices | KPI cards show `—`, prompt to seed data |
| 2 | Current Holdings | `holdings.csv` + prices + `state.json` cash | "No holdings recorded yet" |
| 3 | Target Portfolio | `target_portfolio.csv` | "No target generated yet" |
| 4 | Rebalance History | `rebalance_history.csv` | "No rebalances recorded yet" |
| 5 | Trade Log | `trade_log.csv` | "No trades recorded yet" |
| 6 | Performance | `equity_curve.csv`, `nifty500_tri.csv`, `results/**` PNGs | Falls back to research PNGs only |
| 7 | Audit Package Viewer | `paper_trading/audit/**`, `results/**`, root `*_AUDIT.md` | Lists whatever exists |
| 8 | Alerts | all of the above (Section 6 rules) | "All clear" |

---

## 8. MVP Implementation Plan

**Phase A — Foundations (utils) ✅ first**
1. `paths.py` — centralize every location; nothing else hard-codes a path.
2. `data_loader.py` — graceful readers (`safe_read_csv`, `load_state`, `load_holdings`, …), each empty-on-missing.
3. `prices.py` — `latest_prices()` from the parquet cache (cached); `last_close_date()`.
4. `metrics.py` — `cagr`, `drawdown_series`, `current_drawdown`, `enrich_holdings` (price/value/weight/PnL).
5. `formatting.py` — `rupees`, `pct`, `signed_pct`, color helpers.
6. `alerts.py` — Section 6 rules → list of `{severity, title, detail}`.

**Phase B — Components**
7. `layout.py` (header + mode banner + no-data notice), `cards.py` (KPI row), `tables.py` (colored frames), `charts.py` (plotly equity/DD/benchmark).

**Phase C — Pages & router**
8. `app.py` navigation across the 8 pages; build each page top-down using components.

**Phase D — Seed & verify**
9. Ship `paper_trading/` EXAMPLE data so all pages render.
10. Add `streamlit` to `requirements.txt`; import-smoke-test all modules; launch and click through.

**Acceptance:**
- App launches with **and** without `paper_trading/` present (graceful both ways).
- No page raises; missing files show notices, not tracebacks.
- KPIs, holdings P&L, target BUY/HOLD/SELL, equity/DD/benchmark charts, audit listing, and alerts all populate from the EXAMPLE set.
- Zero writes to any file; zero strategy/engine imports that recompute signals.

**Deliberately out of MVP (future):** broker/API integration, order execution, auth, multi-user, cloud deploy, live signal recomputation inside the dashboard, editable ledgers. The dashboard stays a viewer.
