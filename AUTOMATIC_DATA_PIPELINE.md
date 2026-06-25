# AUTOMATIC DATA PIPELINE — Phase 3L · Part B

**Purpose:** keep the NSE market-data cache and panels current every trading day
**without manual prompts**, while never touching the strategy. This is a
**data-only** maintenance loop.

> **Hard boundary (by design, enforced by what the code does *not* call):**
> the automatic job does **NOT** generate portfolios, **NOT** rebalance, **NOT**
> run paper trading, and **NOT** execute trades. The frozen quarterly strategy
> stays **manually initiated** at quarter-end rebalance dates. Only market-data
> maintenance is automated.

---

## 1. Components

| File | Role |
|---|---|
| `pipeline/auto_data_update.py` | Orchestrator. Detect → download → classify → (conditionally) rebuild → adjust → validate → health report. |
| `pipeline/run_daily_update.ps1` | Scheduler entry point. Forces UTF-8, runs the orchestrator, maps exit code, appends to `pipeline/logs/scheduler.log`. |
| `pipeline/register_task.ps1` | Registers/refreshes the Windows Task Scheduler job (weekday 19:00 local). |
| `pipeline/nse_daily_update.xml` | Importable Task Scheduler definition (alternative to the register script). |
| `pipeline/health/` | `latest_health.md`, `health_YYYYMMDD.json`, `freshness.json`. |
| `pipeline/logs/` | `run_YYYYMMDD.log` (per-run detail) + `scheduler.log` (one line per launch). |
| `data/nse_holidays_known.txt` *(optional)* | Operator-maintained authoritative holiday calendar. If present, a 404 on a listed date is a **confirmed** holiday. |

The orchestrator **reuses the repo's existing, validated scripts** rather than
re-implementing them — nothing in the strategy/controls path is modified:

- download primitives imported from `build_bhavcopy_cache.py`
  (`_make_opener`, `_url`, `fetch_day`, `CACHE`, holiday markers);
- `build_bhav_panels.py` and `adjust_bhav.py` invoked as subprocesses, only when
  new data exists;
- `controls.c2_data_source.reconcile()` called read-only for consistency
  validation.

---

## 2. Execution flow

```
   [Task Scheduler]  weekday ~19:00 IST
         │
         ▼
   run_daily_update.ps1   (UTF-8, exit-code mapping, scheduler.log)
         │
         ▼
   auto_data_update.py
     │
     1. now_ist()  +  known_holidays()  (_holidays.txt ∪ nse_holidays_known.txt)
     │
     2. last = cache_last_date()
        latest_expected = latest_expected_trading_day(now, holidays)
        missing = expected_trading_days(last+1 .. latest_expected)
     │
     3. for each missing day:  attempt_day()  ──► classify + backoff (see §3)
     │        published → write data/bhavcopy_cache/{date}.parquet
     │
     4. IF any day published:                         ◄── rebuild ONLY on new data
     │        py build_bhav_panels.py   (raw panels)
     │        py adjust_bhav.py          (split/bonus adjusted panels)
     │
     5. validate_cache():  trading-day freshness gate  +  C2 reconcile (read-only)
     │
     6. write freshness.json  +  health_YYYYMMDD.json  +  latest_health.md
     │
     ▼
   exit code  0=OK  1=WARNING  2=HALT   ──► scheduler last-run result
```

**Idempotent:** if the cache is already current, steps 3–4 do nothing and the run
reports `OK` with 0 downloads / panels not rebuilt.

---

## 3. Classification & retry policy

For every missing expected trading day, `attempt_day()` produces exactly one
classification. **A 404 is never auto-written to the holiday file.**

| Situation | Classification | Action | Severity |
|---|---|---|---|
| File served (HTTP 200) | `published` | save parquet → triggers rebuild | — |
| 404 **and** date ∈ known-holiday calendar | `holiday_confirmed` | skip silently | info |
| 404 **and** date == today **and** before 18:00 IST cutoff | `pending_publication` | skip, re-check next run | info |
| 404 on a weekday, after cutoff, ≤ 10 days old | `publication_delay` | exponential backoff, then **WARNING** | WARNING |
| 404 on a weekday, after cutoff, > 10 days old | `holiday_or_gap_unconfirmed` | **WARNING** for operator review (never auto-holiday) | WARNING |
| HTTP 403 / 401 / 429 | `nse_blocking` | backoff, then **WARNING** | WARNING |
| timeout / conn reset / DNS | `network_failure` | backoff, then **WARNING** | WARNING |

### Retry / backoff

- Per-day transient failures retry up to `--max-retries` (scheduler default **5**)
  with **exponential backoff**: `base_delay · 2^(n-1)` seconds
  (scheduler default base **60 s** → 60, 120, 240, 480, 960 s).
- `build_bhavcopy_cache.fetch_day` additionally retries 3× internally on socket
  errors, so transient blips are absorbed before the outer backoff even engages.
- **Distinct from a holiday:** the loop only converts an unresolved 404 into a
  *holiday-suspected* state for dates **older than 10 days**, and even then only
  as a `WARNING` — it is never written to `_holidays.txt` automatically. Recent
  missing days always surface as a publication-delay WARNING so a real trading
  day is never silently lost.

---

## 4. Failure handling (fail-safe contract)

The pipeline **never silently continues on stale data.** Overall status is the
worst of the gates:

| Condition | Status | Exit |
|---|---|---|
| Freshness > **5 trading days** OR C2 = HALT | **HALT** | 2 |
| Any warning (delay / blocking / network / unconfirmed-gap / rebuild failure) | **WARNING** | 1 |
| Current, validated, no warnings | **OK** | 0 |

- **HALT** is surfaced as a non-zero Task Scheduler last-run result and recorded
  in `latest_health.md` + `scheduler.log`. Panels are **never advanced past a
  failed validation** (rebuild runs before validation, but the status reflects
  validation; if C2/freshness fail the run is flagged HALT regardless of rebuild).
- Panel rebuild is gated on `published` days only — a failed/blocked fetch leaves
  the existing good panels untouched.

---

## 5. Scheduler

### Option A — PowerShell (recommended; auto-resolves paths)

```powershell
# from the repo root, elevated not required for an Interactive-token task:
powershell -ExecutionPolicy Bypass -File pipeline\register_task.ps1
# custom local time (e.g. machine not on IST), or remove:
powershell -ExecutionPolicy Bypass -File pipeline\register_task.ps1 -LocalTime 18:30
powershell -ExecutionPolicy Bypass -File pipeline\register_task.ps1 -Unregister
```

Registers **`NSE_Market_Data_Daily_Maintenance`**, trigger **Mon–Fri at 19:00
local**, restart-on-failure 3×/15 min, 2 h time limit, runs as the current user in
the logon session (no stored password).

> **Timezone note:** the trigger fires at 19:00 *local* time. If the machine clock
> is IST, that is 7:00 PM IST as specified. If not, pass `-LocalTime` to align to
> ~19:00 IST. The orchestrator is **IST-cutoff-aware regardless** (it computes the
> 18:00 IST publication cutoff from UTC internally), so a misaligned wall-clock
> only shifts *when* it checks — never *what* it treats as published.

### Option B — import the XML

```
schtasks /Create /TN "NSE_Market_Data_Daily_Maintenance" /XML pipeline\nse_daily_update.xml /F
```
(The XML's `<Command>` paths are set for this repo location; update them if the
repo moves, or just use Option A.)

### Option C — cron (Linux alternative)

```cron
# min hour dom mon dow   — 19:00 Mon–Fri; orchestrator handles IST cutoff itself
0 19 * * 1-5  cd /path/to/new-quant && PYTHONUTF8=1 python pipeline/auto_data_update.py --max-retries 5 --base-delay 60 >> pipeline/logs/cron.log 2>&1
```

### Manual run / test

```powershell
Start-ScheduledTask -TaskName NSE_Market_Data_Daily_Maintenance
Get-ScheduledTaskInfo -TaskName NSE_Market_Data_Daily_Maintenance      # LastTaskResult
# or directly:
py pipeline\auto_data_update.py            # real run
py pipeline\auto_data_update.py --dry-run  # classify only, no writes
```

---

## 6. Monitoring

After **every** run the job writes:

- `pipeline/health/latest_health.md` — human-readable snapshot: latest trading
  date, freshness (trading + calendar days), freshness gate, C2 result, downloaded
  days, holidays, retries, warnings/failures, panel end-dates, recovery pointer.
- `pipeline/health/health_YYYYMMDD.json` — machine-readable, same fields.
- `pipeline/health/freshness.json` — quick freshness probe for other tooling.
- `pipeline/logs/run_YYYYMMDD.log` — full per-run trace (every day's
  classification).
- `pipeline/logs/scheduler.log` — one line per launch: `timestamp  STATUS (exit N)`.

**What to watch:** any `WARNING` or `HALT` line in `scheduler.log`, or a
`Freshness gate: HALT` in `latest_health.md`. A single `publication_delay` warning
on the current day typically self-clears on the next run once NSE publishes.

---

## 7. Recovery procedure

| Symptom | Likely cause | Action |
|---|---|---|
| `WARNING publication_delay` on today only | NSE bhavcopy not yet up at run time | none — next run picks it up; backoff already tried. If it persists 2+ runs, check NSE manually. |
| `WARNING nse_blocking` (403/429) | scripted-access throttle | re-run later (`Start-ScheduledTask …`); the opener already negotiates cookies. Persistent → run from a non-blocked network. |
| `WARNING network_failure` | local network / DNS | confirm connectivity; re-run. |
| `WARNING holiday_or_gap_unconfirmed` (older date) | a true holiday not in the calendar, **or** a genuinely missing day | confirm against the official NSE calendar; if it is a holiday, add it to `data/nse_holidays_known.txt` (one ISO date per line) so it is recognized as `holiday_confirmed` and stops warning. **Do not** guess — that is exactly the "silently mark a trading day a holiday" failure this design avoids. |
| `HALT` — freshness > 5 trading days | several consecutive failed runs | resolve the underlying cause above, then run `py pipeline\auto_data_update.py` to catch up; verify `latest_health.md` returns to `OK`. |
| `HALT` — C2 | consistency/coverage problem | inspect `paper_trading/controls/reports/c2_data_discrepancy.csv`; do **not** trade until C2 clears. |
| Panel rebuild failed | subprocess error | see `pipeline/logs/run_YYYYMMDD.log`; re-run `py build_bhav_panels.py` then `py adjust_bhav.py` manually, then re-run the orchestrator. |

**Catch-up after downtime:** the orchestrator is range-aware — on the next run it
downloads *every* missing expected trading day between the cache's last date and
the latest expected day, rebuilds once, and re-validates. No special catch-up
command is needed; for a large gap you can also run
`py build_bhavcopy_cache.py <start> <end>` directly, then the orchestrator.

---

## 8. What stays manual (unchanged)

- Quarterly **rebalance** and trade-list generation (frozen strategy).
- **C1 approval** of each new trade list (hash-bound, deliberate human gate).
- **C3 corporate-action reconciliation** notes for held names (governance step).
- Promotion to / start of **PAPER_TRADING_CYCLE_002** — an operator decision,
  informed by `latest_health.md` showing `OK`.
