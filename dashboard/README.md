# Operational Dashboard (Phase 3F MVP)

Read-only, local-first monitoring for the frozen momentum champion
(**Momentum + LowVol · Top10 · Quarterly · Buffer20 · Equal Weight**).

> Not a research tool. Never writes trading state. Never recomputes signals.
> Full design: [../DASHBOARD_ARCHITECTURE.md](../DASHBOARD_ARCHITECTURE.md).

## Run

```bash
py -m pip install -r ../requirements.txt     # installs streamlit + plotly
py -m streamlit run dashboard/app.py         # from the project root
# or:  py dashboard/run.py
```

Opens http://localhost:8501. Eight pages: Portfolio Overview, Current Holdings,
Target Portfolio, Rebalance History, Trade Log, Performance, Audit Package
Viewer, Alerts.

## Data it reads

| Source | Used for |
|---|---|
| `paper_trading/*` (operator-owned) | NAV, cash, holdings, target, rebalances, trades, equity curve, audit |
| `data/cache_bhav/adj_close.parquet` | latest prices for P&L / weights (read-only) |
| `data/nifty500_tri.csv` | benchmark comparison |
| `results/**` PNGs + CSVs | reference research charts on the Performance/Audit pages |
| root `*_AUDIT.md` / `*_PROTOCOL.md` | governance docs on the Audit page |

The repo ships **EXAMPLE** data in `paper_trading/` so every page renders on
first launch. Replace those files with your real paper-trading ledger and set
`"mode": "PAPER"` in `paper_trading/state.json`. The data contract is documented
in [../paper_trading/README.md](../paper_trading/README.md).

## Structure

- `app.py` — navigation router · `run.py` — launcher
- `pages/` — one module per page
- `components/` — cards, tables, charts, layout (import only `utils`)
- `utils/` — paths, data_loader, prices, metrics, alerts, formatting (UI-free)

Every loader returns empty-on-missing; missing files show a notice, never a
traceback.
