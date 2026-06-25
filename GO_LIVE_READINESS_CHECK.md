# GO-LIVE READINESS CHECK — Phase 3K

**Objective:** Determine the shortest path from the current **HALT** (Cycle 001) to a valid **GO**.
**Sources:** [PAPER_TRADING_CYCLE_001.md](PAPER_TRADING_CYCLE_001.md) · [PAPER_TRADING_CYCLE_001_REMEDIATION.md](PAPER_TRADING_CYCLE_001_REMEDIATION.md) · [OPERATIONAL_GAP_ANALYSIS.md](OPERATIONAL_GAP_ANALYSIS.md)
**Constraints:** No strategy changes · no control changes · no research · no new architecture · analysis only.
**Strategy:** frozen at `8f0482f` / `price-only-final`.
**Date:** 2026-06-24

---

## 1. Every remaining blocker to GO

Current preflight: **HALT** — blocking `{C2, C3, FRESHNESS}`; passing `{C1, C4}`.

| # | Blocker | Gate | State |
|---|---|---|---|
| B1 | Cache stale (last close 2026-05-29 = 26 days old vs ≤5-trading-day limit) | Freshness gate | **OPEN** |
| B2 | C2 freshness branch (same stale cache) — consistency checks already clean (100% coverage, 0 unexplained divergence) | C2 | **OPEN** (rides on B1) |
| B3 | RELIANCE corporate action (1:1 bonus, factor 0.50→1.00 on 2024-10-28) flagged on a held name | C3 | **OPEN** |
| B4 | C1 approval is hash-bound to the *old* 2026Q2 trade list; a refreshed cycle regenerates the list → old approval no longer matches | C1 | **WILL OPEN on re-run** (by design) |

> B1 and B2 share **one** root cause and are cleared by **one** data refresh.
> B4 is not a defect — it is the approval gate correctly refusing a stale/mismatched approval.

---

## 2. Blocker classification

### Mandatory **before the next paper cycle** (to reach a GO)
| ID | Item | Clears |
|---|---|---|
| M1 | Refresh EOD cache to ≤5 trading days of a current quarter-end | B1, B2 |
| M2 | Reconcile held-name corporate action(s) on the new book (RELIANCE + any new) and log them | B3 |
| M3 | Re-generate the rebalance with the frozen strategy on the current quarter-end | (produces new list) |
| M4 | Re-issue C1 approval for the new trade list | B4 |
| M5 | Re-run preflight → confirm GO | verifies all |

### Mandatory **before live capital** (from the gap analysis / audit / protocol — not required for paper)
| ID | Item | Source |
|---|---|---|
| L1 | Wire the **live NSE bhavcopy** as C2's true secondary source (replace the in-repo stand-in) | Gap C2 |
| L2 | Configure + monthly-test the **email/IM alert delivery** channel (SMTP) | Gap C5 |
| L3 | Open + **fund the failover broker**; place a dry-run order | Audit §8 |
| L4 | **IPS signed** (−40% DD, 10-name concentration, no stop-loss, net-of-tax ~13–15%) | Audit §8 |
| L5 | Complete the **paper program**: ≥4 Track-A rehearsals + ≥2 live Track-B rebalances; ≥1 real corp action + ≥1 injected failure drill; slippage tracks model 2 consecutive quarters | Protocol §6 |
| L6 | Maintain a **corp-action calendar** for held names (standing process behind C3) | Gap C3 |
| L7 | CA engaged for **STCG/LTCG**; advance-tax scheduling | Audit §8 |

### Optional **hardening** (improve robustness; block nothing)
| ID | Item | Source |
|---|---|---|
| H1 | Schedule the **daily EOD pull + freshness alert** (so staleness never recurs silently) | Gap I3/N1 |
| H2 | **Commit/config-drift hard-stop** asserted at signal time (beyond C1's check) | Gap I7 |
| H3 | Promote the cycle orchestrator + a `tests/test_controls.py` into the repo; independence check in CI | Controls testing plan |
| H4 | One-click **reproducibility diff** (regenerate package, assert bit-identical) | Gap N4 |
| H5 | Slippage / execution-vs-intended **tracking-error** capture fields | Gap I4 |

---

## 3. Execution sequence (to the next valid paper GO)

| Step | Action | Effort | Depends on |
|---|---|---|---|
| 1 | **Refresh EOD data** to ≤5 trading days of the target signal date (run the existing acquisition/bhavcopy build; backfill gap days; pass `validate-data`) | Low (compute) — gated by feed availability + arrival of the 2026-07-01 quarter-end | — |
| 2 | **Re-generate** the rebalance package on the current quarter-end with the frozen strategy | Low (~seconds, deterministic) | Step 1 |
| 3 | **Reconcile corporate actions** on the new held/target names (confirm RELIANCE-type events against the official record; log in the calendar; clear the freeze by evidence, never override) | Low (per name) | Step 2 |
| 4 | **Re-issue C1 approval** for the new trade list (approver, timestamp, commit, config fingerprint, trade-list hash) | Low (minutes) | Step 2 |
| 5 | **Re-run preflight** → expect `GO`; archive the audit package | Low (~seconds) | Steps 1–4 |

**Critical path:** Step 1 (data) is the binding constraint; Steps 2–5 are fast and
deterministic once data is fresh. Because the strategy is quarterly, the *natural* next
signal date is **2026-07-01 (2026Q3)** — so the practical earliest GO is on/after that date,
when fresh EOD data through the signal date can be pulled.

---

## 4. Task type (human / existing tooling / new implementation)

| Task | Human action | Existing tooling | New implementation |
|---|---|---|---|
| M1 Refresh EOD data | trigger / confirm | ✅ `download` / bhavcopy build / `validate-data` | — |
| M2 Reconcile corp action | ✅ confirm vs NSE record + log | ✅ `controls.c3_corp_actions` | — |
| M3 Re-generate rebalance | review | ✅ frozen generator (`run_rehearsal`) | — |
| M4 Re-issue C1 approval | ✅ sign-off | ✅ `controls.c1_approval` | — |
| M5 Re-run preflight | review verdict | ✅ `controls.preflight` | — |
| L1 Live bhavcopy secondary | — | partial (loader hook exists) | ✅ wire live feed |
| L2 Email alert channel | ✅ configure + test | ✅ `controls.c5_alerts` (SMTP ready) | config only |
| L3 Failover broker | ✅ open/fund/dry-run | — | — |
| L4 IPS signed | ✅ governance | — | — |
| L5 Paper program (≥2 live Q) | ✅ run cadence | ✅ full controls stack | — |
| L6 Corp-action calendar | ✅ maintain | ✅ C3 cross-checks it | — |
| L7 Tax / CA | ✅ engage CA | — | — |

**Key finding:** **the next paper cycle requires ZERO new implementation.** Every M-step
is human action + existing tooling. New implementation (L1) and config (L2) are reserved
for *before live capital*, not the next paper GO.

---

## 5. Minimum set to execute the next valid paper-trading cycle

> **If the only goal is the next valid paper cycle as quickly as possible:**
>
> 1. **Refresh the EOD cache** to ≤5 trading days of the signal date (existing tooling + human trigger). *Clears freshness + C2.*
> 2. **Reconcile the held-name corporate action(s)** and log them (human + existing C3). *Clears C3.*
> 3. **Re-generate** the rebalance (existing frozen generator) and **re-issue the C1 approval** for the new trade list (human + existing C1).
> 4. **Re-run preflight** (existing) → GO.
>
> That is the whole minimum set: **one data refresh, one corp-action reconciliation, one
> re-generation + re-approval, one preflight re-run.** No new code, no architecture, no
> strategy or control changes. C4 (broker) already passes and re-reconciles automatically.
> The binding constraint is data availability at the next quarter-end (2026-07-01).

---

## Current Status:

**NOT READY FOR NEXT PAPER CYCLE**

**Justification:** As of 2026-06-24 the preflight still returns HALT — the two data
preconditions (freshness / C2) and the C3 corporate-action freeze remain **open**; nothing
has been remediated yet (the prior phase was analysis only), and fresh EOD data past
2026-05-29 is not yet available (the next quarter-end, 2026-07-01, has not occurred). The
state is therefore *not ready today*. However, the path to ready is short and fully scoped:
**no new implementation, no architecture, and no strategy/control changes are required** —
only a data refresh, a single corporate-action reconciliation, a re-generation with a fresh
C1 approval, and a preflight re-run, all on existing tooling. Once the next quarter-end data
is pulled and those steps complete, the preflight is expected to return **GO**.
