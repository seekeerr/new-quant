# MARKET DATA REFRESH REPORT — Phase 3L · Part A

**Run date:** 2026-06-25
**Operator action:** market-data pipeline refresh + validation (data only).
**Strategy / factors / params / controls / dashboard / construction:** UNCHANGED.
**Frozen tag:** `price-only-final` · commit `8f0482f`.

The single blocking issue identified in `CURRENT_SYSTEM_STATE.md` — stale market
data (cache last close 2026-05-29, 19 business days old, freshness/C2 HALT) — has
been cleared. The cache, raw panels and adjusted panels now all end on the latest
NSE trading day, **2026-06-25**.

---

## 1. Bhavcopy cache refresh

Command run (Part A, step 1):

```
py build_bhavcopy_cache.py 2026-05-30 2026-06-25
```

| Metric | Value |
|---|---|
| Window requested | 2026-05-30 → 2026-06-25 |
| **Trading days downloaded** | **19** |
| Holidays (404 on weekday) | 0 |
| Failed downloads | 0 |
| Retries needed | 0 |
| Weekends skipped (no fetch) | 05-30, 05-31, 06-06, 06-07, 06-13, 06-14, 06-20, 06-21 |
| Elapsed | ~8 s (2.3 days/s) |
| **Latest market date** | **2026-06-25** |

Downloaded dates (all `SERIES==EQ`, survivorship-free, UDiFF format):

```
2026-06-01  2026-06-02  2026-06-03  2026-06-04  2026-06-05
2026-06-08  2026-06-09  2026-06-10  2026-06-11  2026-06-12
2026-06-15  2026-06-16  2026-06-17  2026-06-18  2026-06-19
2026-06-22  2026-06-23  2026-06-24  2026-06-25
```

No weekday returned a 404 in the window, so **no dates were added to
`_holidays.txt`** — consistent with June 2026 having no NSE trading holiday in
this range. (NSE archive reachable; the `www.nseindia.com` homepage returns 403
to scripted clients, which is normal — the `archives.nseindia.com` content feed
served every requested day.)

Daily cache: `data/bhavcopy_cache/` now holds **3,818** per-day parquet files,
last file `2026-06-25.parquet`.

---

## 2. Panel rebuild

Commands run (Part A, step 2):

```
py build_bhav_panels.py     # raw wide panels + active/delisted/ISIN
py adjust_bhav.py           # split/bonus back-adjustment (gap-detect)
```

| Panel | Last trading date | Shape (dates × symbols) | Non-NaN on last row |
|---|---|---|---|
| `adj_close.parquet`    | **2026-06-25** | 3818 × 3808 | 2406 |
| `raw_close.parquet`    | **2026-06-25** | 3818 × 3808 | 2406 |
| `raw_volume.parquet`   | **2026-06-25** | 3818 × 3808 | 2406 |
| `raw_turnover.parquet` | **2026-06-25** | 3818 × 3808 | 2406 |
| `adj_high.parquet`     | 2026-06-25 | 3818 × 3808 | 2406 |
| `adj_low.parquet`      | 2026-06-25 | 3818 × 3808 | 2406 |

All four required panels (and the high/low panels) share the same latest date,
**2026-06-25** — the panels do not lag the daily source. Date range
2011-01-03 → 2026-06-25. Adjustment: 1,232 symbols carry ≥1 detected corporate
action; 2,187 actions total (unchanged detector; Upstox cross-validation skipped —
no token present, same as the frozen build).

Universe identity unchanged in character: total 3,808 symbols, 2,485 active
(traded in last 20 sessions), 1,323 delisted; ISIN mapped for 3,294.

---

## 3. Validation

### Freshness (5-trading-day rule)

| Quantity | Before (CURRENT_SYSTEM_STATE) | After refresh |
|---|---|---|
| Cache last close | 2026-05-29 | **2026-06-25** |
| Age (business days) | 19 | **0** |
| 5-trading-day gate | 🔴 FAIL | 🟢 **PASS** |

### Control checks

| Control | Before | After | Note |
|---|---|---|---|
| **Freshness** | 🔴 HALT | 🟢 PASS | cache current to latest trading day |
| **C2 Backup Data Source** | 🔴 HALT (stale) | 🟢 **PASS** | primary fresh; secondary covers 100.0%; no unexplained divergence |
| **C3 Corp-Action** | 🔴 HALT (RELIANCE) | 🟡 **NOTIFY** | see note below |
| **C4 Broker Reconciliation** | 🟢 PASS | 🟢 PASS | all 10 positions reconcile |
| **C1 Approval** | 🟢 PASS (2026-04-01 list) | ⚪ pending new list | hash-bound; a new approval is required for any new trade list |

**Preflight verdict on the data gates (`--no-approval`):**

```
REBALANCE PREFLIGHT — 2026-07-01  ->  GO
  [PASS  ] C2 Backup Data Source: Primary fresh, secondary covers 100.0%, no unexplained divergence.
  [NOTIFY] C3 Corp-Action Reconciliation: 269 corporate-action event(s) detected (none on watched names).
  [PASS  ] C4 Broker Reconciliation: All 10 positions reconcile with the broker.
```

### Note on C3 / RELIANCE (read this — it is a behavior change, not a silent fix)

C3 now returns **NOTIFY**, not HALT. Two things changed:

1. The only events C3 detects on the held watch are **historical ticker renames**
   (`HEROHONDA → HEROMOTOCO`, `MAX → MFSL`) — `symbol_change` events, which the
   control deliberately excludes from HALT escalation. They are informational.
2. The **RELIANCE 1:1 bonus (ex-2024-10-28)** that drove the prior C3 HALT has
   **aged out of C3's 400-trading-day factor lookback** now that the panel extends
   to 2026-06-25. It is therefore no longer surfaced by the detector.

This means C3 no longer *blocks*, but the underlying RELIANCE event still has **no
written reconciliation record** in the repo. The panel itself is internally
consistent (the 0.50 factor was snapped to 1.00 by `adjust_bhav.py`), and C2's
divergence check is clean. Recommendation: have an operator record a one-line
RELIANCE reconciliation note for the audit trail before CYCLE_002 acts on any
RELIANCE position — this is a governance/paper-trail step, not a data defect.

---

## 4. Can PAPER_TRADING_CYCLE_002 begin?

**Data readiness: YES.** The data-side blockers are cleared:

- ✅ Freshness PASS (0 trading days old)
- ✅ C2 PASS (fresh, 100% coverage, no unexplained divergence)
- ✅ C4 PASS (broker reconciliation)
- 🟡 C3 NOTIFY (no actionable corporate action on held names; RELIANCE paper-trail
  note advised but non-blocking)

**Remaining (non-data) gate before an actual GO:** the **C1 approval is hash-bound
to the 2026-04-01 trade list**. CYCLE_002's next scheduled quarterly rebalance is
**2026-07-01**. When that trade list is generated (manually, at rebalance time),
it must receive a fresh C1 approval before execution. That is a normal,
intended manual step — not a data blocker.

### Recommendation

**Proceed to `PAPER_TRADING_CYCLE_002`** at the 2026-07-01 quarterly rebalance.
The data pipeline is current and validated. From now on it is kept current
automatically by the daily maintenance job — see **`AUTOMATIC_DATA_PIPELINE.md`**.
No research, no optimization, no strategy changes were made.

---

## 5. Artifacts written this run

| Path | What |
|---|---|
| `data/bhavcopy_cache/2026-06-0*..2026-06-25.parquet` | 19 new daily EOD files |
| `data/cache_bhav/{adj_close,raw_close,raw_volume,raw_turnover,adj_high,adj_low}.parquet` | rebuilt panels (last date 2026-06-25) |
| `data/cache_bhav/{symbols_active,symbols_delisted}.txt`, `symbol_isin.csv` | refreshed universe identity |
| `paper_trading/controls/reports/c2_data_discrepancy.csv` | C2 report (clean) |
| `paper_trading/controls/reports/c3_corp_action_report.csv` | C3 report (symbol_change only on watch) |
| `paper_trading/controls/reports/preflight_2026-07-01.json` | preflight data-gate verdict (GO) |
| `pipeline/health/latest_health.md`, `health_20260625.json`, `freshness.json` | first automated health snapshot |
