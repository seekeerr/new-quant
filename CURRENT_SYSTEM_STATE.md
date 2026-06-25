# CURRENT SYSTEM STATE — Repository Inspection

**Type:** Read-only inspection. No code run, no files changed, no data rebuilt, no strategy executed.
**Inspection date:** 2026-06-25
**Strategy:** frozen at `8f0482f` / `price-only-final`.
**Method:** parquet contents read directly (not file timestamps); pipeline script docstrings read; control reports/holdings read.

---

## Inspected files

| File | Why |
|---|---|
| `data/cache_bhav/{adj_close,raw_close,raw_volume,raw_turnover}.parquet` | latest market date (Q1) |
| `data/bhavcopy_cache/*.parquet` (3,799 daily files + `_holidays.txt`) | raw EOD source currency (Q3/Q4) |
| `build_bhavcopy_cache.py · build_bhav_panels.py · adjust_bhav.py · build_equity_universe.py` | pipeline (Q3) |
| `paper_trading/holdings.csv` | C3 watch / C4 expected (Q5/Q6) |
| `paper_trading/controls/reports/c3_corp_action_report.csv` | RELIANCE status (Q5) |
| `paper_trading/controls/approvals/approval_2026-04-01.json` | C1 state (Q6) |
| `paper_trading/2026Q2/preflight_report.json` | prior verdict (Q4) |

---

## 1. Current market-data state (parquet contents, not mtime)

| Parquet | Latest trading date INSIDE the file | Rows × Cols | Non-NaN on last row |
|---|---|---|---|
| `adj_close.parquet` | **2026-05-29** | 3799 × 3803 | 2461 |
| `raw_close.parquet` | **2026-05-29** | 3799 × 3803 | 2461 |
| `raw_volume.parquet` | **2026-05-29** | 3799 × 3803 | 2461 |
| `raw_turnover.parquet` | **2026-05-29** | 3799 × 3803 | 2461 |

**All four panels share the same latest trading date: 2026-05-29.** The raw daily source
(`data/bhavcopy_cache/`) also ends at `2026-05-29.parquet` — the panels are **not** lagging
the source; both stop on the same day.

---

## 2. Freshness

| Quantity | Value |
|---|---|
| Latest data date | 2026-05-29 |
| Today | 2026-06-25 |
| **Cache age** | **27 calendar days · 19 business days elapsed** |
| 5-trading-day freshness rule | **FAIL** (19 ≫ 5) |
| **C2 verdict** | **HALT** (freshness branch) |

C2's *consistency* checks were clean in the last run (100% coverage, 0 unexplained
divergence); its only failing branch is freshness. The preflight freshness gate fails on the
same fact.

---

## 3. Current data pipeline — how fresh data enters the repo

Four scripts, all reading from / writing to `data/`. Execution order and run-state:

| Order | Script | Purpose | Inputs | Outputs | Already run? |
|---|---|---|---|---|---|
| 1 | **build_bhavcopy_cache.py** | Download NSE daily bhavcopy (EOD), one normalized parquet per trading day. Survivorship-free; resumable; records 404 holidays. **Only network step.** | NSE bhavcopy archive (web); `_holidays.txt` | `data/bhavcopy_cache/{YYYY-MM-DD}.parquet` | ✅ through **2026-05-29** (3,799 files) |
| 2 | **build_bhav_panels.py** | Stitch per-day files into wide RAW panels (dates × symbols); also derive active/delisted lists + latest ISIN map. | `data/bhavcopy_cache/*.parquet` | `raw_{close,high,low,volume,turnover}.parquet`, `symbols_active.txt`, `symbols_delisted.txt`, `symbol_isin.csv` | ✅ (outputs present, last date 2026-05-29) |
| 3 | **adjust_bhav.py** | Back-adjust raw close/high/low for splits & bonuses via gap detection (snap to clean CA ratios); validate vs Upstox sample. | raw panels (from #2) | `adj_{close,high,low}.parquet` (volume reused raw) | ✅ (adj panels present, last date 2026-05-29) |
| 4 | **build_equity_universe.py** | Build common-equity whitelist by ISIN prefix (`INE` keep; `INF`/`IN9`/blank drop). | `data/bhavcopy_cache/*.parquet` (ISINs) | `symbols_equity.txt`, `symbols_nonequity.csv` | ✅ (files present) |

```
            ┌──────────────────────────────────────────────────────────────┐
            │            FRESH MARKET DATA ENTRY (quarterly strategy,        │
            │                 daily pulls keep cache fresh)                  │
            └──────────────────────────────────────────────────────────────┘

   NSE bhavcopy (web)
        │  [1] build_bhavcopy_cache.py        (NETWORK — the only fetch step)
        ▼
   data/bhavcopy_cache/{date}.parquet   ── latest: 2026-05-29 ──┐
        │                                                       │
        │  [2] build_bhav_panels.py            [4] build_equity_universe.py
        ▼                                                       ▼
   data/cache_bhav/raw_*.parquet                 symbols_equity.txt / nonequity.csv
   + symbols_active/delisted.txt, symbol_isin.csv
        │
        │  [3] adjust_bhav.py  (splits/bonuses → adjusted)
        ▼
   data/cache_bhav/adj_{close,high,low}.parquet  ── latest: 2026-05-29
        │
        ▼
   (frozen strategy reads adj_* panels + equity whitelist; controls read the same)
```

**Dependencies:** [1] feeds [2] and [4]; [2] feeds [3]. To advance the cache you must re-run
[1] for the new dates, then [2], then [3] (and [4] if the universe identity changed).

---

## 4. Why PAPER_TRADING_CYCLE_001 reported stale data

**Answer: A) the cache actually contained stale data.**

Evidence:
- The parquet *contents* (read directly) end at **2026-05-29** — exactly the date the
  preflight reported (`primary_age_days = 26` at the cycle's run date of 2026-06-24).
- The raw source `data/bhavcopy_cache/` also ends at `2026-05-29.parquet`, so the staleness
  is in the data itself, not a stitching lag.
- **Not B** — the cache has *not* been refreshed since; it still ends 2026-05-29 today.
- **Not C** — preflight inspected the correct file (`adj_close.parquet`); its reported date
  matches the direct content read exactly.
- **Not D** — no other cause; the freshness gate fired on a true, verifiable fact.

---

## 5. Corporate-action status (RELIANCE)

**Status: STILL UNRESOLVED.**

Evidence:
- `c3_corp_action_report.csv` still contains: `adjustment, RELIANCE, 2024-10-28,
  adj/raw factor 0.5000 -> 1.0000, touches_watch=True` (a 1:1 bonus).
- `paper_trading/holdings.csv` still lists **RELIANCE** (31 sh) — it is in the current held
  watch, so C3 escalates to HALT.
- **No reconciliation/clearance artifact exists.** A repository-wide search for any
  corporate-action calendar / reconciliation / clearance file found only the C3 *detector*
  (`controls/c3_corp_actions.py`) and the C3 *report* that raises the flag — there is no
  log recording the RELIANCE event as confirmed/reconciled.

What remains: an operator must confirm the RELIANCE bonus against the official NSE record and
record that confirmation (clear the freeze by evidence, not override). Note: the panel is
*internally* adjusted (the 0.50 factor was snapped to 1.00 by `adjust_bhav.py`), so the data
is consistent — but the control has **no reconciliation record**, so it will keep HALTing
while RELIANCE is in the held watch.

---

## 6. Current readiness — execute the frozen strategy TODAY?

**Verdict: HALT.** (Identical blocking set to Cycle 001.)

| Gate | Status today | Why |
|---|---|---|
| Freshness | 🔴 HALT | cache 2026-05-29 = 19 business days old (> 5) |
| C2 Backup Data Source | 🔴 HALT | same staleness (consistency branch clean) |
| C3 Corp-Action | 🔴 HALT | RELIANCE bonus unreconciled, RELIANCE in held watch |
| C4 Broker Reconciliation | 🟢 PASS | `holdings.csv` (prior book) matches `broker_statement.csv` |
| C1 Approval | 🟢 PASS *(for the 2026-04-01 list)* | `approval_2026-04-01.json` matches that trade-list hash, commit, config |

**Blocking conditions: Freshness, C2, C3.** Preflight returns **HALT**. (If data were
refreshed to a *new* signal date, the regenerated trade list would also require a fresh C1
approval — the existing approval is hash-bound to the 2026-04-01 list.)

---

## 7. Recommended next command (exactly one)

**Refresh the bhavcopy cache** — the binding, immediately-actionable blocker is data
freshness, and the raw source can be advanced now (NSE has the post-2026-05-29 sessions):

```
py build_bhavcopy_cache.py 2026-05-30 2026-06-25
```

Rationale: this is step [1] of the existing pipeline and the prerequisite for clearing both
the freshness gate and C2. It requires NSE network access. It must be followed (separately)
by `build_bhav_panels.py` then `adjust_bhav.py` to propagate into the panels the strategy and
controls read — but the **single next action** is the bhavcopy refresh above. (The C3 RELIANCE
reconciliation is a parallel human task; and note the frozen strategy's next *scheduled*
rebalance is the 2026-07-01 quarter-end, so a full rebalance cycle would refresh again through
that date.)

---

## Readiness status

| Item | State |
|---|---|
| Market data | **STALE** — 2026-05-29 (19 business days old) |
| Pipeline | built & run through 2026-05-29; **not advanced since** |
| C2 / Freshness | **HALT** |
| C3 (RELIANCE) | **UNRESOLVED** (no reconciliation record) |
| C1 / C4 | PASS |
| **Execute frozen strategy today** | **HALT** |
| **Next command** | `py build_bhavcopy_cache.py 2026-05-30 2026-06-25` |

*Inspection only. No code changes, no rebuilding, no strategy run. Every date and status above
was read from the repository's current contents.*
