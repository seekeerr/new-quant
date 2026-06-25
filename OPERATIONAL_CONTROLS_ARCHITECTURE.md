# OPERATIONAL CONTROLS ARCHITECTURE — Phase 3I

**Subject:** Implementation of the five Critical operational controls (C1–C5) from
[OPERATIONAL_GAP_ANALYSIS.md](OPERATIONAL_GAP_ANALYSIS.md), per Investment-Committee
decision **B — Deploy After Paper-Trading Program**.
**Strategy:** Momentum + LowVol · Top 10 · Quarterly · Buffer 20 · Equal Weight — **FROZEN, UNCHANGED.**
**Frozen commit:** `8f0482f` · **Tag:** `price-only-final`
**Date:** 2026-06-24
**Package:** [`controls/`](controls/)

> **Hard boundary:** these controls are an **operational wrapper**. They do not
> change — and do not even *import* — strategy logic, factors, parameters, or
> universe rules. They read data artifacts on disk and emit reports/alerts. The
> independence is enforced and tested (see §5, "Independence").

---

## 1. Design

### 1.1 Principles
1. **Read-only & non-strategic.** Controls never write trading state, never
   generate signals, never touch `strategies/ · portfolio/ · backtest/ · regime/
   · risk/ · run_*.py`. They consume the same artifacts the dashboard reads.
2. **Fail-closed.** The preflight returns **GO only if every blocking control is
   non-HALT.** Absence of evidence (missing approval, missing broker statement,
   stale data) is treated as HALT, not as PASS.
3. **Uniform result contract.** Every check returns a `ControlResult(control,
   name, status ∈ {PASS, HALT, NOTIFY}, summary, details, report_path)`. This is
   what makes them composable into one gate and one alert stream.
4. **Severity mirrors the architecture.** HALT blocks the pipeline; NOTIFY is
   review-at-leisure — identical to [LIVE_TRADING_ARCHITECTURE.md §10](LIVE_TRADING_ARCHITECTURE.md).
5. **Offline-testable.** No control requires the network to be validated; the
   secondary data source and the email channel both have offline/dry-run modes.

### 1.2 Package layout
```
controls/
├── __init__.py            # independence contract (documented)
├── config.py              # control thresholds + IO locations (NOT strategy params)
├── common.py              # ControlResult, hashing, git/commit, report IO
├── c1_approval.py         # C1 — approval gate
├── c2_data_source.py      # C2 — backup data source validation
├── c3_corp_actions.py     # C3 — corporate-action reconciliation
├── c4_broker_recon.py     # C4 — broker reconciliation
├── c5_alerts.py           # C5 — alert delivery (local + email)
└── preflight.py           # orchestrator: C1–C5 as one GO/HALT gate
```
Outputs are written under the operator-owned area:
```
paper_trading/controls/
├── approvals/  approval_<date>.json
├── reports/    c2_data_discrepancy.csv · c3_corp_action_report.csv
│               c4_broker_reconciliation.csv · preflight_<date>.json
└── alert_outbox/  alerts_<YYYYMMDD>.jsonl · email_dryrun_*.txt
```

### 1.3 Per-control design

| Control | What it proves | Inputs | Output | Blocks GO? |
|---|---|---|---|---|
| **C1 Approval Gate** | A human approved *this exact* trade list, under the frozen code/config | `trade_list` file, git commit, `config.py` fingerprint | `approvals/approval_<date>.json` | **Yes** |
| **C2 Backup Data Source** | The primary price source agrees with an independent secondary | `adj_close.parquet` (primary) vs `raw_close.parquet` / bhavcopy (secondary) | `c2_data_discrepancy.csv` | **Yes** (stale/coverage) |
| **C3 Corp-Action Reconciliation** | No split/bonus/merger/delisting/symbol-change silently corrupts a held/target name | `adj_close` vs `raw_close`, `symbol_isin.csv`, `symbols_delisted.txt` | `c3_corp_action_report.csv` | **Yes** if it touches a watched name |
| **C4 Broker Reconciliation** | The system's book equals the broker's | `holdings.csv` (expected) vs `broker_statement.csv` | `c4_broker_reconciliation.csv` | **Yes** |
| **C5 Alert Delivery** | Operators are actually notified | the other controls' results + freshness/rebalance checks | `alert_outbox/*` + email | No (it reports) |

**C1 binding fingerprints.** An approval records *approver, timestamp, git commit,
config-file SHA-256, and the trade-list SHA-256*. `require_approval()` re-checks
all four at preflight time, so an approval cannot be reused for a changed trade
list, a drifted commit, or an edited config.

**C2 corporate-action awareness.** Comparing adjusted vs unadjusted prices would
legitimately diverge on any name with a corporate action. C2 therefore cross-
references the same adjustment factor C3 uses and **excludes names with a detected
adjustment** from its divergence test — so it flags *unexplained* divergence only.

**C3 detection method (price-derived, read-only).**
- *Splits/bonuses/dividends:* a step in the adjustment factor `adj_close/raw_close`;
  magnitude classifies the action (e.g. factor → ½ ≈ 2:1).
- *Unexplained moves:* a >20% one-day move with **no** factor step = probable
  *unadjusted* action (the highest-impact, signal-corrupting case).
- *Delistings:* a name on `symbols_delisted.txt` with no recent print.
- *Symbol changes:* one ISIN mapped to >1 symbol in `symbol_isin.csv`.
- *Mergers:* best-effort — delisting whose ISIN continues under another symbol →
  flagged for human confirmation.

**C5 channels.** *local* (always: JSONL outbox + console + best-effort Windows
toast) and *email* (SMTP via env vars; **dry-run to a file** when unconfigured, so
the pipeline never blocks on mail). Categories: `HALT · DATA_FRESHNESS ·
VALIDATION · REBALANCE`.

---

## 2. Data Flow

```
   FROZEN / EXISTING ARTIFACTS (read-only)            OPERATOR INPUTS (read-only)
   ┌───────────────────────────────────┐   ┌────────────────────────────────────┐
   │ data/cache_bhav/adj_close.parquet  │   │ paper_trading/holdings.csv          │
   │ data/cache_bhav/raw_close.parquet  │   │ paper_trading/broker_statement.csv  │
   │ data/cache_bhav/symbol_isin.csv    │   │ paper_trading/state.json            │
   │ data/cache_bhav/symbols_delisted   │   │ audit_packages/<id>/trade_list.csv  │
   │ config.py  (fingerprinted, NOT run)│   │ approvals/approval_<date>.json      │
   └─────────────────┬─────────────────┘   └──────────────────┬─────────────────┘
                    │                                          │
                    ▼                                          ▼
        ┌───────────────────────────────────────────────────────────────┐
        │                    controls.preflight.run()                    │
        │   C2 data source ─► C3 corp actions(watch=holdings) ─► C4 broker│
        │        └────────── freshness & rebalance-due checks ───────────┤
        │                         C1 approval gate                       │
        └───────────────┬───────────────────────────────┬───────────────┘
                       │ ControlResult[]                 │ alerts[]
                       ▼                                 ▼
        ┌──────────────────────────┐        ┌──────────────────────────────┐
        │ GO / HALT verdict         │        │ C5 deliver(local + email)    │
        │ preflight_<date>.json     │        │ alert_outbox/* · SMTP/dry-run │
        └──────────────┬───────────┘        └──────────────────────────────┘
                      ▼
        Operator proceeds with the (separately generated) trade list ONLY on GO.
```

The control layer sits **between** trade-list generation (the frozen
`run_rehearsal.py` / future live generator) and execution. It is a gate, not a
generator.

---

## 3. Failure Modes

| Control | Failure mode | Detection | Disposition |
|---|---|---|---|
| C1 | No approval recorded | `require_approval` finds no file | **HALT** |
| C1 | Trade list edited after approval | trade-list SHA-256 ≠ approved | **HALT** ("re-approve") |
| C1 | Commit / config drift after approval | live commit/fingerprint ≠ approved | **HALT** |
| C2 | Primary cache stale | last close age > 5 (+2) trading days | **HALT** |
| C2 | Secondary missing / thin coverage | coverage < 98% | **HALT** |
| C2 | Unexplained price divergence | >0.5% on a non-CA name | **NOTIFY** + report |
| C2 | *False alarm on a split* | excluded via C3 adjustment factor | (suppressed by design) |
| C3 | Split/bonus on held name | adjustment-factor step on a watched name | **HALT** ("freeze name") |
| C3 | Unadjusted action (silent) | >20% move, no factor step | **NOTIFY/review** (HALT if watched) |
| C3 | Delisting of held name | delisted list + no recent print | **HALT** if watched |
| C3 | Symbol/ISIN remap | ISIN→multiple symbols | **NOTIFY** (informational) |
| C4 | Missing / extra / wrong qty | outer-join delta ≠ 0 | **HALT** |
| C4 | Broker statement absent | file missing/unreadable | **HALT** (cannot reconcile) |
| C5 | Email misconfigured | env vars absent | **dry-run to file** (never blocks) |
| C5 | SMTP send error | exception on send | logged in receipt; local channel still delivers |
| Preflight | Any blocking control HALT | aggregation | **verdict = HALT** |
| Preflight | Control raises unexpectedly | controls return results, not exceptions; loaders are empty-on-error | fail-closed (missing data ⇒ HALT) |

**Design stance on the unknown:** every control degrades to HALT (not silent
PASS) when its input is missing or unreadable. The cost of a false HALT (defer a
quarter) is far smaller than a false GO (trade a wrong/unreconciled book).

---

## 4. Validation Rules

| Rule | Control | Threshold (in `controls/config.py`) |
|---|---|---|
| Trade-list immutability | C1 | SHA-256 must equal approved hash |
| Commit lock | C1 / preflight | live commit == approved == `FROZEN_COMMIT`/tag |
| Config lock | C1 | `config.py` SHA-256 == approved fingerprint |
| Data freshness | C2 / preflight | ≤ `FRESHNESS_MAX_TRADING_DAYS` (5) +2 cal. days |
| Source coverage | C2 | secondary covers ≥ `MIN_SYMBOL_COVERAGE` (98%) |
| Price divergence | C2 | ≤ `PRICE_DIVERGENCE_TOL` (0.5%) per non-CA name |
| Adjustment step | C3 | factor step > `ADJ_FACTOR_STEP_TOL` (1%) ⇒ event |
| Unexplained move | C3 | \|1-day return\| > `UNEXPLAINED_MOVE_TOL` (20%) w/o factor step |
| Delisting | C3 | on delisted list + no print in `RECENT_INACTIVITY_DAYS` (20) |
| Holding parity | C4 | `quantity_broker − quantity_expected == 0` for every name |
| Alert escalation | C5 | any HALT ⇒ all channels + urgent subject |

All thresholds are **operational** (how the controls behave) and live in
`controls/config.py`. None are strategy parameters; the frozen `config.py` is only
ever *read for fingerprinting*, never modified.

---

## 5. Testing Plan

### Independence (must always pass first)
Static check: none of the control modules contain `import`/`from` of any strategy
package (`strategies, portfolio, backtest, regime, risk, run_*`). **Verified: 0
forbidden imports.**

### Unit / behavioural (per control)
| Control | Test | Expected | Result |
|---|---|---|---|
| C1 | verify before approval | HALT (no approval) | ✅ |
| C1 | create then verify | PASS | ✅ |
| C1 | verify against a different file | HALT (hash mismatch) | ✅ |
| C2 | reconcile on current cache | HALT (26-day-stale seed), coverage 1.0, 0 unexplained divergences | ✅ |
| C3 | reconcile with held watch | HALT — caught real **BAJFINANCE** split (factor 0.10→1.00, 2025-06-16) | ✅ |
| C3 | market-wide scan | 269 symbol-change events detected from ISIN map | ✅ |
| C4 | clean book | PASS (10/10 reconcile) | ✅ |
| C4 | injected qty mismatch | HALT (quantity_mismatch on SBIN) | ✅ |
| C5 | deliver HALT+NOTIFY, no SMTP | local delivered, email dry-run to file | ✅ |
| Preflight | full gate on seed data | HALT (blocking: C2, C3, FRESHNESS); C1, C4 PASS; report written | ✅ |

(Harness: `scratchpad/test_controls.py`; promote to `tests/test_controls.py` at rollout.)

### Integration
- Preflight wraps the rehearsal output (`audit_packages/rehearsal_001/trade_list.csv`)
  and produces `preflight_<date>.json` — verified end-to-end.
- Regression to add: a **clean-path** fixture (fresh cache + approved list +
  matching broker + no CA on held names) asserting **verdict = GO**.

### Negative / fault-injection (carried into the paper program)
Per [PAPER_TRADING_PROTOCOL.md Area 9], deliberately inject: a stale cache, an
unadjusted split, a broker mismatch, and a missing approval — and confirm each
HALTs. (C1/C2/C3/C4 negative paths already demonstrated above.)

---

## 6. Rollout Plan

**Phase 0 — Shadow (now → first paper rebalance).**
Run `python -m controls.preflight <date> <trade_list> --no-email` after every
rehearsal. Controls are **advisory**: record GO/HALT but do not yet block. Goal:
calibrate thresholds (esp. C2 divergence, C3 noise) against real quarters.

**Phase 1 — Enforcing in paper (Track A/B).**
- Make preflight a **required, blocking** step in the paper runbook: no trade list
  is acted on without a `GO`.
- Wire the **real secondary source** (NSE bhavcopy loader) into
  `c2_data_source.load_secondary()` (drop-in; the consistency machinery is done).
- Operator records a genuine C1 approval each quarter; maintain the corp-action
  calendar that C3 cross-checks.
- Exercise C5 email by configuring the SMTP env vars; send a monthly test.

**Phase 2 — Live readiness gate.**
Controls must close their [OPERATIONAL_GAP_ANALYSIS.md] Critical items with logged
evidence across ≥2 live quarters before the §11 deployment conditions are met:
- C1 enforced every quarter · C2 backup exercised + reconciled · C3 ≥1 real corp
  action handled · C4 broker parity every quarter · C5 HALT + NOTIFY both fired
  and acknowledged.

**Phase 3 — Maintenance.**
Thresholds reviewed quarterly; `tests/test_controls.py` runs in CI; the
independence check is a CI gate (a strategy import in `controls/` fails the build).

**Backout:** controls are additive and read-only; disabling them is removing the
preflight step. They can never corrupt strategy state because they never write it.

---

## 7. Mapping to the Critical gaps

| Gap (Phase 3G) | Closed by | Status |
|---|---|---|
| C1 No enforced approval gate | `controls/c1_approval.py` + preflight | ✅ implemented; enforce in Phase 1 |
| C2 No backup data source | `controls/c2_data_source.py` (secondary pluggable) | ✅ machinery done; wire live bhavcopy in Phase 1 |
| C3 No corp-action reconciliation | `controls/c3_corp_actions.py` | ✅ implemented & catching real events |
| C4 No broker reconciliation | `controls/c4_broker_recon.py` | ✅ implemented |
| C5 No alert delivery channel | `controls/c5_alerts.py` (local + email) | ✅ implemented; configure SMTP in Phase 1 |

---

*Implementation note: supporting utilities were added under `controls/` only. The
champion strategy, its factors, parameters, and universe rules are unchanged and
remain frozen at `8f0482f` (`price-only-final`). The controls import no strategy
code — verified by the independence check.*
