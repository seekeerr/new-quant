# PAPER TRADING CYCLE 001 — REMEDIATION PLAN

**Scope:** Convert the Cycle 001 (2026Q2) preflight **HALT** into a valid **GO**.
**Source:** [PAPER_TRADING_CYCLE_001.md](PAPER_TRADING_CYCLE_001.md) · [paper_trading/2026Q2/preflight_report.json](paper_trading/2026Q2/preflight_report.json)
**Constraints:** Analysis only — no implementation, no strategy changes, no control changes.
**Strategy:** frozen at commit `8f0482f` / tag `price-only-final`.
**Date:** 2026-06-24

---

## Summary of the HALT

Preflight verdict **HALT**; blocking = **C2, C3, FRESHNESS**. Passing = **C1 (approval), C4 (broker)**.

| Blocker | Control | One-line cause |
|---|---|---|
| Data freshness | preflight freshness gate | cache last close 2026-05-29 = 26 days old vs 5-trading-day limit |
| C2 Backup Data Source | C2 | same staleness; coverage 100%, **0 unexplained divergences** |
| C3 Corp-Action | C3 | RELIANCE 1:1 bonus (factor 0.50→1.00, 2024-10-28) flagged on a held name |

**Note on overlap:** the *freshness gate* and *C2* fire on the **same root cause** (a
stale cache) via two independent mechanisms — the preflight's freshness alert and C2's
own freshness assertion. They are listed separately because each is an independent gate
that must clear, but **one data refresh resolves both.**

---

## Blocker 1 — Data Freshness gate

- **Root Cause:** The survivorship-free EOD cache (`data/cache_bhav/adj_close.parquet`)
  ends **2026-05-29**; the system clock is **2026-06-24** → 26 calendar days (well past
  the 5-trading-day / ~7-calendar-day limit). No EOD ingestion has run since 2026-05-29;
  in this environment no live feed is wired to advance the cache. This is a
  **data-operations gap, not a strategy or signal defect.**
- **Required Fix:** Run the daily EOD acquisition to bring the cache to within 5 trading
  days of the intended rebalance date (primary feed; backfill any gap days), then re-run
  the cycle on a **current** quarter-end. The frozen strategy decides on signal date `T`
  using data ≤ `T` and executes at `T+1` open — so a real-capital cycle must be run on a
  fresh `T`, not on the quarter-old 2026-04-01 signal.
- **Verification Method:** Re-run `python -m controls.preflight <T> <trade_list>`; confirm
  the preflight freshness alert is absent and `primary_age_days ≤ 5` in the C2 details.
  Independently assert `cache.index[-1] ≥ last_trading_day − 5`.
- **Estimated Effort:** **Low** (minutes of compute for one incremental pull) — *if* a feed
  is reachable. **Medium** as a one-time setup if the daily acquisition job is not yet
  scheduled (closing gap C2 from the gap analysis: backup-source wiring + a cron/daily run).
- **Risk if Ignored:** **High.** Trading real capital on a 26-day-old signal means acting
  on a portfolio the strategy no longer intends; momentum ranks drift materially over a
  quarter. This is precisely the "stale-data signal" failure the audit names as the #1 way
  the live account silently diverges from the backtest.

---

## Blocker 2 — C2 Backup Data Source

- **Root Cause:** C2 HALTed on the **freshness** branch only (`Primary stale (26d old)`).
  Its consistency checks were otherwise **clean**: secondary coverage 100%, **0
  unexplained per-name divergences** beyond 0.5% (corp-action names correctly excluded via
  the shared adjustment factor). Secondary note: C2's secondary source is currently the
  in-repo `raw_close.parquet` stand-in; the live NSE-bhavcopy loader is not yet wired
  (Phase-1 rollout item), so C2 is presently a single-feed freshness check rather than a
  true two-source cross-validation.
- **Required Fix:** (a) Resolve Blocker 1 (the staleness that tripped C2). (b) Before the
  *next* live cycle, wire `c2_data_source.load_secondary()` to the independent NSE bhavcopy
  feed so the 0.5% divergence + 98% coverage checks run against a genuinely separate source.
  No control-code change is required to clear *this* cycle — only the data refresh.
- **Verification Method:** Re-run C2 (`python -m controls.c2_data_source`); expect PASS with
  `primary_age_days ≤ 5`, `symbol_coverage ≥ 0.98`, `n_discrepancies = 0` (or any flagged
  names triaged in the discrepancy report).
- **Estimated Effort:** **Low** to clear this cycle (rides on Blocker 1). **Medium** for the
  one-time live-bhavcopy wiring (drop-in loader; the consistency machinery already exists).
- **Risk if Ignored:** **Medium–High.** Without a true secondary, a silent primary-feed
  error (bad adjustment, partial batch, wrong series) has no independent cross-check — the
  highest-residual data risk per the production audit. Clearing only the freshness symptom
  while leaving the single-feed gap open weakens the control to a freshness timer.

---

## Blocker 3 — C3 Corporate Action Reconciliation

- **Root Cause:** C3 detected a real adjustment-factor step on **RELIANCE** (adj/raw
  0.50→1.00 on **2024-10-28** — a 1:1 bonus) and, because RELIANCE is in the **held (prior)
  book**, escalated to HALT ("freeze until reconciled"). The control is behaving correctly:
  it cannot tell *on its own* that the action is historical and already price-adjusted, so
  it conservatively blocks. There is no reconciliation record telling it the event is
  already accounted for.
- **Required Fix:** Operator reconciliation (no code, no override): confirm the RELIANCE
  bonus against the official NSE corporate-action record, verify the panel is already
  adjusted consistently (the factor settling to 1.00 indicates it is), and record the
  confirmation in the corp-action calendar/log that the runbook maintains. The freeze is
  then **cleared by evidence, not overridden.** Materially, RELIANCE is an **exit** this
  quarter (it left the top-20 band), so it leaves the book regardless — but the gate must
  still be cleared per process, never bypassed.
- **Verification Method:** Re-run C3 with the held watch
  (`python -m controls.c3_corp_actions <held symbols>`); confirm no *unreconciled* action
  touches a held/target name. Cross-check the RELIANCE event against the maintained
  corp-action calendar entry. On the refreshed cycle, confirm no *new* unreconciled action
  appears on the new book.
- **Estimated Effort:** **Low** (single name, historical event, one confirmation against the
  public record + a calendar entry).
- **Risk if Ignored:** **Medium.** For RELIANCE specifically the live impact is limited (it
  is exiting and already adjusted), but **ignoring or overriding** a C3 HALT sets the
  precedent the controls exist to prevent: an *unadjusted* action on a *held, retained* name
  computed into the signal produces a discontinuity and a wrong trade. The discipline cost
  of overriding is higher than the one-off reconciliation.

---

## Cross-cutting note: refresh regenerates the signal

Resolving Blocker 1 by advancing to a **current** quarter-end will cause the frozen
strategy to generate a **new** trade list (different `T`, possibly different names). That
new list must clear the full preflight in its own right, which means:

- **C1 (approval) must be re-issued** for the new trade list — the existing approval is
  hash-bound to the 2026Q2 list and will (correctly) fail to match. This is not a new
  blocker; it is the approval gate working as designed.
- **C4 (broker)** re-reconciles against the then-current book (passed cleanly this cycle).
- **C3** must show no unreconciled action on the new book.

---

## Remediation checklist (order of operations)

1. Run EOD acquisition → cache within 5 trading days of the chosen rebalance date. *(Blocker 1+2)*
2. (Before next live cycle) wire live NSE bhavcopy as C2's secondary source. *(Blocker 2, hardening)*
3. Reconcile RELIANCE bonus against official record; log in corp-action calendar; clear freeze. *(Blocker 3)*
4. Re-generate the rebalance on the current quarter-end (frozen strategy, unchanged).
5. Re-issue C1 approval for the new trade list.
6. Re-run preflight → expect all gates green.

---

## Expected outcome after remediation:

**GO**

**Justification:** Two of four gates already PASS (C1 approval, C4 broker reconciliation),
and C2's only failure was the freshness branch — its consistency checks (coverage,
divergence) were already clean. Both data blockers (freshness + C2) share a single root
cause that a routine EOD refresh resolves, and the lone C3 blocker is a single historical,
already-adjusted corporate action on an **exiting** name that an operator can reconcile and
clear by evidence (not override) in minutes. None of the blockers stem from the strategy,
the parameters, or the controls — they are data-readiness and reconciliation preconditions.
Once data is refreshed to a current quarter-end, the RELIANCE event is logged as reconciled,
and a fresh C1 approval is issued for the newly generated trade list, the preflight has no
remaining blocking condition and returns **GO**. (Conditional only on the refreshed data
itself passing validation and surfacing no *new* unreconciled corporate action on the new
book — the normal, expected per-quarter checks.)
