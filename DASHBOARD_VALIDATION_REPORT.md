# DASHBOARD VALIDATION REPORT — Phase 3G

**Subject:** `dashboard/` operational MVP (8 Streamlit pages) — see [DASHBOARD_ARCHITECTURE.md](DASHBOARD_ARCHITECTURE.md)
**Date:** 2026-06-24
**Method:** Headless validation via Streamlit `AppTest` (no browser), plus direct
exercise of the UI-free `utils` and `components`. Read-only throughout.
**Environment:** Streamlit 1.58.0 · pandas 3.0.3 · plotly · Python 3.14
**Verdict:** ✅ **PASS** — all 8 pages load and render; navigation, empty-state,
missing-file, alerts, charts, and the audit viewer all behave correctly. No
functional bugs. Three minor findings (all cosmetic/data-hygiene), listed below.

---

## 1. Pass/Fail per page

Each page was run via `AppTest.from_file(...).run()` against the shipped EXAMPLE
seed data. "Loads" = no exception raised. Element counts confirm content rendered.

| # | Page | Loads | Renders content | Notes |
|---|---|---|---|---|
| 1 | Portfolio Overview | ✅ PASS | 8 metrics, NAV chart, holdings glance table | KPIs populated (NAV ₹5.12 L, DD, CAGR, dates) |
| 2 | Current Holdings | ✅ PASS | 4 metrics, holdings table w/ P&L coloring | price-join + weight/P&L derive correctly |
| 3 | Target Portfolio | ✅ PASS | 4 metrics, 3 tables (Top10 / Buffer / full) | BUY/HOLD/SELL coloring works |
| 4 | Rebalance History | ✅ PASS | 3 metrics, history table, snapshot selector | turnover KPI + snapshot drill-down |
| 5 | Trade Log | ✅ PASS | 4 metrics, filterable ledger table | symbol/action filters work; cost total sums |
| 6 | Performance | ✅ PASS | 4 metrics, equity + drawdown plotly, ref PNGs | falls back to research PNGs when present |
| 7 | Audit Package Viewer | ✅ PASS | 3 tabs (packages / docs / artifacts) | lists `2026-Q3` pkg + 5 governance docs |
| 8 | Alerts | ✅ PASS | 3 metrics + categorized alert list | HALT/NOTIFY split renders |

**Navigation:** ✅ PASS — `dashboard/app.py` (the `st.navigation` router) loads with
default page title "Portfolio Overview"; all 8 pages registered.

> **Per-page `error` element note:** every page renders exactly **one** `st.error`
> from the shared header *alert badge*, and the Alerts page renders **two** (badge
> + body). This is **correct behaviour**, not a bug — it is the HALT for "Stale
> price data" firing because the shipped price cache's last close is 2026-05-29
> (25 days before the run date). See Finding F2.

---

## 2. Empty-state handling — ✅ PASS

All operational paths were redirected to an empty temp directory (simulating a
fresh checkout with no `paper_trading/` data). Every loader returned a safe empty
value and **nothing raised**:

| Loader | Result on missing file |
|---|---|
| `state()` | `{}` ✅ |
| `holdings()` | empty DataFrame ✅ |
| `target()` | empty DataFrame ✅ |
| `rebalances()` | empty DataFrame ✅ |
| `trades()` | empty DataFrame ✅ |
| `equity_curve()` | empty Series ✅ |
| `list_audit_packages()` | `[]` ✅ |
| `alerts.evaluate()` | no crash, returned graceful alert list ✅ |
| `metrics.enrich_holdings(empty)` | empty frame, NAV `0.0` ✅ |

Pages display the standard "No data yet" notice instead of a traceback.

---

## 3. Missing-file handling — ✅ PASS

Partial-data scenarios (some files present, others absent) are covered by the same
per-file graceful readers; each file is independently optional. Charts render with
empty inputs (0 traces, no exception). The Performance page degrades to showing only
the reference research PNGs when no paper equity curve exists.

---

## 4. Alert engine — ✅ PASS

Five scenarios were injected; the engine produced exactly the expected HALT/NOTIFY
set in each (severity model per [LIVE_TRADING_ARCHITECTURE.md §10](LIVE_TRADING_ARCHITECTURE.md)):

| Scenario | Expected | Produced | Result |
|---|---|---|---|
| S1 fresh data, balanced book, rebalance far off | (clear / drift only) | NOTIFY: Weight drift | ✅ |
| S2 price cache 40 days stale | HALT stale data | HALT: Stale price data (+drift) | ✅ |
| S3 held name missing from cache | HALT price gap | HALT: Price gap on held name(s) | ✅ |
| S4 rebalance due tomorrow | NOTIFY rebalance due | NOTIFY: Rebalance due | ✅ |
| S5 PAPER mode, no holdings | HALT missing holdings | HALT: No holdings recorded | ✅ |

The weight-drift NOTIFY in S1 is correct: the toy holdings were not at exactly 10%.

---

## 5. Charts — ✅ PASS

| Chart | With data | Empty input |
|---|---|---|
| Equity curve (rebased, vs benchmark) | 2 traces ✅ | 0 traces, no crash ✅ |
| Drawdown | 1 trace ✅ | — |

Both are Plotly figures built without exception; log/linear toggle present.

---

## 6. Audit viewer — ✅ PASS

- **Quarterly packages:** lists `2026-Q3` and previews its files
  (`commit.txt`, `rebalance_log.md`, `trade_list.csv`). ✅
- **Governance docs:** all 5 present and rendered as markdown — PRODUCTION_READINESS_AUDIT,
  LIVE_TRADING_ARCHITECTURE, PAPER_TRADING_PROTOCOL, CAPACITY_ANALYSIS, PRICE_ONLY_FINAL_CONCLUSION. ✅
- **Generated artifacts:** discovers 17 `report.txt` and 15 `comparison.csv` under `results/`. ✅

---

## 7. Bugs found

**None functional.** No page raised; no loader threw; no chart failed. All empty-
and missing-file paths are handled gracefully.

---

## 8. Findings (minor — cosmetic / data hygiene)

| ID | Severity | Finding | Recommended fix |
|---|---|---|---|
| **F1** | Cosmetic | Streamlit emits `use_container_width` deprecation warnings (slated for removal after 2025-12-31; still functional on 1.58). | When pinning Streamlit ≥ a version that drops it, migrate `use_container_width=True` → `width="stretch"`. Kept as-is now to preserve the `>=1.36` floor. |
| **F2** | Data hygiene | Shipped seed price cache last close is **2026-05-29**, so a "Stale price data" **HALT** badge shows on every page out of the box. | Expected & honest (it proves the freshness gate works). Document for the operator; clears once the daily-pull refreshes the cache. |
| **F3** | UX | No in-app "refresh data" affordance — the operator must reload the browser to pick up edited files (cache is mtime-keyed, so a reload is sufficient). | Add a sidebar "Refresh / clear cache" button (nice-to-have; see gap analysis). |

> A fourth item — `list_audit_packages()` returning `[]` — appeared once during
> testing but was traced to a **monkeypatch leak in the validation harness**, not
> the product; a clean-process re-check returned `['2026-Q3']` correctly. Not a bug.

---

## 9. Conclusion

The dashboard is **fit for operational use as a read-only monitor.** It loads,
navigates, survives missing/empty data, computes holdings/P&L/weights from the
price cache, classifies BUY/HOLD/SELL, renders performance charts, surfaces the
audit trail, and fires the correct HALT/NOTIFY alerts. The only findings are
cosmetic or data-hygiene and do not block the first paper-trading rehearsal.
