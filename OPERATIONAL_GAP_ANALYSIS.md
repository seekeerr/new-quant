# OPERATIONAL GAP ANALYSIS — Phase 3G

**Subject:** Readiness of the operational tooling (dashboard + rehearsal driver +
audit package) to run the frozen champion's quarterly rebalance.
**Inputs:** [DASHBOARD_VALIDATION_REPORT.md](DASHBOARD_VALIDATION_REPORT.md),
[REHEARSAL_REPORT.md](REHEARSAL_REPORT.md),
[audit_packages/rehearsal_001/](audit_packages/rehearsal_001/),
[LIVE_TRADING_ARCHITECTURE.md §7 readiness table](LIVE_TRADING_ARCHITECTURE.md),
[PAPER_TRADING_PROTOCOL.md](PAPER_TRADING_PROTOCOL.md).
**Date:** 2026-06-24
**Scope:** Gaps only. No strategy, factor, or parameter changes. Validation exercise.

---

## 1. What now works (demonstrated this phase)

- ✅ Deterministic signal → trade-list generation (bit-identical across two runs).
- ✅ Buffer-20 selection, equal-weight whole-share construction, tiered cost model.
- ✅ Immutable audit package with checksums + commit/version stamp.
- ✅ Read-only dashboard: 8 pages, navigation, empty/missing-file graceful, alerts,
  charts, audit viewer (all PASS).
- ✅ Data validation gate (price-integrity, recent-history, freshness) and a
  HALT/NOTIFY alert engine matching the architecture's model.

These cover the *compute* and *visibility* layers. The remaining gaps are almost
entirely in the **live operational wrapper** the paper-trading program exists to
close — they do **not** touch the strategy.

---

## 2. Gap register (ranked)

### 🔴 CRITICAL — block safe *live* operation (must close before Track B / go-live)

| ID | Category | Gap | Evidence | Recommended action |
|---|---|---|---|---|
| C1 | Controls | **No enforced human approval gate.** The runbook's "approve trade list (timestamped, signed)" step is documentation only; nothing records or requires it before orders are transcribed. | Rehearsal §8 deviation | Add an `approval.json` (operator, timestamp, signed trade-list hash) the audit package requires; dashboard shows "AWAITING APPROVAL" until present. |
| C2 | Data | **No backup data source (NSE bhavcopy ingestion).** Single dependency on the yfinance/cache path; an outage on rebalance morning blocks the cycle. | LIVE §7 (🔴) | Wire bhavcopy fallback + the >0.5% primary-vs-backup reconciliation. |
| C3 | Controls | **No corporate-action calendar / reconciliation.** A split/bonus/merger on a held or candidate name would corrupt the signal silently; not checked. | Rehearsal §8; LIVE §7 (🔴) | Maintain a corp-action calendar for held + top-30 names; freeze-until-reconciled procedure; the >±20% move flag as backstop. |
| C4 | Workflow | **No broker reconciliation step.** Paper book vs (future) demat is never compared; a position drift would go unseen. | Rehearsal §8 deviation | Add a reconciliation input + a HALT-on-mismatch gate (manual entry acceptable at ₹5 L). |
| C5 | Alerting | **No alert *delivery* channel.** Alerts render only inside the dashboard; an operator not looking at the screen on rebalance day is not notified. | LIVE §7 (🔴); Dashboard report | Add email/IM push for HALT alerts; monthly test. An un-fired alert is an unproven control. |

### 🟡 IMPORTANT — needed for a trustworthy paper-trading program (Track A→B)

| ID | Category | Gap | Recommended action |
|---|---|---|---|
| I1 | Workflow | **No "promote rehearsal → paper_trading/" step.** The rehearsal writes to `audit_packages/`; updating the operator's live `paper_trading/*` ledger is manual and undefined. | Add a documented (still manual/read-checked) promotion procedure + a `mode` flip EXAMPLE→PAPER. |
| I2 | Controls | **No live-PIT "as-of-T" run mode separate from the backtest.** The rehearsal driver reuses backtest internals; a dedicated, audited live-run entry point is cleaner and less error-prone. | Formalize `run_rehearsal.py` into a parameterized `generate_rebalance(as_of=T)` operational tool (no strategy change). |
| I3 | Data | **Freshness gate is advisory in the rehearsal** (90-day tolerance for replay) but must be a **hard ≤5-trading-day block** in live. | Parameterize the gate; hard-block in PAPER/LIVE mode. |
| I4 | Reconciliation | **No slippage / execution-vs-intended tracking** (Protocol Areas 7–8). The rehearsal records intended fills only. | Add fields for recorded fill price/time; compute realized-vs-modeled slippage and per-name weight deviation each quarter. |
| I5 | Docs | **No single operator runbook checklist artifact.** The runbook lives in the architecture doc; the operator needs a printable, tick-box quarter sheet that the dashboard mirrors. | Generate a per-quarter checklist (ties to PAPER_TRADING_PROTOCOL §4). |
| I6 | UX | **Dashboard has no in-app data refresh / cache-clear.** Operator must reload the browser. | Add a sidebar "Refresh data" button (clears `st.cache_data`). |
| I7 | Controls | **Commit/config-drift assertion not enforced at signal time.** Manifest stamps the commit but nothing *halts* if it ≠ frozen tag. | Add a hard assertion: signal generation refuses to run unless `HEAD == price-only-final`. |

### 🟢 NICE-TO-HAVE — polish / future scaling

| ID | Category | Gap | Recommended action |
|---|---|---|---|
| N1 | UX | `use_container_width` deprecation (cosmetic warnings). | Migrate to `width="stretch"` when pinning newer Streamlit. |
| N2 | Data hygiene | Seed price cache stale → permanent HALT badge out of the box. | Refresh cache or ship a freshness note; harmless. |
| N3 | UX | No tax-lot / STCG-LTCG register view (audit flags tax drag as real). | Add a tax-lot page once paper trading produces realized lots. |
| N4 | Reporting | No automated diff of regenerated trade list vs archived (reproducibility is run manually). | Add a one-click "verify package reproduces" action. |
| N5 | Scaling | No per-rebalance liquidity screen (not binding < ₹25 L per capacity analysis). | Defer; add before scaling AUM. |
| N6 | Convention | "Quarter-end" in docs vs "first trading day of quarter" in `get_rebalance_dates`. | Clarify wording; no code change (matches backtest). |

---

## 3. Missing items by the brief's categories

- **Missing dashboard features:** in-app data refresh (I6); approval-status display
  (C1); slippage/tracking-error view (I4); tax-lot view (N3).
- **Missing workflows:** rehearsal→paper promotion (I1); broker reconciliation (C4);
  corp-action handling (C3); approval sign-off (C1).
- **Missing documentation:** printable operator quarter-checklist (I5); rebalance-date
  convention note (N6).
- **Missing controls:** enforced approval gate (C1), commit-drift hard-stop (I7),
  hard freshness block in live (I3), corp-action freeze (C3).
- **Missing alerts:** alert *delivery* channel (C5); slippage-out-of-model alert (I4);
  commit-drift alert (I7).

---

## 4. FINAL VERDICT

> ### *"If a rebalance were required tomorrow morning, could the current system execute it safely and reproducibly?"*
>
> ## ✅ YES, WITH CONDITIONS

**Reproducibly — YES, unconditionally.** Demonstrated this phase: the trade list
regenerates **bit-identically** across runs from the archived snapshot + frozen
commit (`8f0482f`), with a checksummed, version-stamped audit package. The
deterministic compute is proven.

**Safely — YES, but only under these conditions**, because the binding gaps are in
the *human/operational wrapper*, not the strategy or the compute:

1. **Data is fresh & validated** — last close ≤ 5 trading days and the validation
   gate PASSes. (Today the shipped cache is 26 days old → this would currently
   **HALT**, correctly. Condition: refresh the cache first.)
2. **Commit = frozen tag** — confirm `HEAD == price-only-final` before generating
   signals (currently manual; C1/I7).
3. **Human approval is recorded** — the operator reviews and signs the trade list
   before any (manual) order entry (C1).
4. **Held names checked for corporate actions** — manual calendar check until C3
   is wired.
5. **Single-broker / no-backup-data risk accepted for one cycle** — tolerable for a
   one-off ₹5 L paper/live cycle with a 1–2 session defer option, but C2/C4/C5 must
   close before this becomes routine or before Track-B go-live.

**Evidence supporting YES:**
- Rehearsal 001 ran the full runbook end-to-end in 4.7 s with **0 HALT** conditions.
- Determinism re-run: **PASS (bit-identical)**; checksum `diff` empty.
- Buffer-20, equal-weight construction, whole-share rounding, and the tiered cost
  model all produced a correct 10-name book (weights 8.4–10.0%) and a sane 14-order,
  47.8%-turnover trade list.
- Dashboard validation: **all 8 pages PASS**, alerts fire correctly, no functional bugs.

**Why not an unconditional YES:** the controls that make live trading *safe under
stress* — enforced approval, corp-action handling, backup data, broker
reconciliation, and alert delivery (C1–C5) — are documented but **not yet enforced
in tooling**. They are exactly the 🔴 items the paper-trading program is designed to
convert to ✅. None require touching the frozen strategy.

**Bottom line:** the system can **safely and reproducibly generate and display** a
rebalance tomorrow, and an operator following the manual runbook conditions above
could act on it for a single ₹5 L cycle. It is **not yet** ready for *unattended* or
*routine* live operation until C1–C5 are closed.

---

*Analysis only. No strategy logic, factors, or parameters were modified in this phase.*
