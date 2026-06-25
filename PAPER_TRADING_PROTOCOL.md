# PAPER TRADING VALIDATION PROTOCOL — Phase 3D

**Strategy (frozen, unchanged):** Momentum + LowVol · Top 10 · Quarterly · Buffer 20 · Equal Weight · Equity Only · Survivorship-Free
**Frozen commit:** `8f0482f` · **Tag:** `price-only-final`
**Deployment context:** Indian equities · quarterly rebalance · initial target capital ≈ ₹5 L · retail broker · **manual execution**
**Inputs:** [PRICE_ONLY_FINAL_CONCLUSION.md](PRICE_ONLY_FINAL_CONCLUSION.md), [PRODUCTION_READINESS_AUDIT.md](PRODUCTION_READINESS_AUDIT.md), [CAPACITY_ANALYSIS.md](CAPACITY_ANALYSIS.md), [LIVE_TRADING_ARCHITECTURE.md](LIVE_TRADING_ARCHITECTURE.md).
**Date:** 2026-06-23
**Scope:** Operational validation protocol only. **This program validates the *operator and the process*, not the strategy.** No strategy/parameter/universe/execution-assumption changes. No research. No code.

---

## 0. The Central Design Tension (read first)

**This is a quarterly strategy. Operational learning is therefore rate-limited to 4 events per year.** A naive "paper trade for a year and see" wastes 9–12 months to observe only 3–4 rebalances — and still fails to rehearse the rare events (corp action, partial fill, broker outage) that the operator most needs to survive.

This protocol resolves that with a **two-track program**:

- **Track A — Historical Dress Rehearsal (compresses learning):** replay the *most recent* completed quarters using the frozen system, running the full manual runbook against archived data *as if live*. This rehearses the entire operational chain — data → validation → signal → trade list → (simulated) execution → reconciliation → audit — many times in weeks, not years. It cannot test live fills, but it proves the *process is correct and reproducible* and trains the operator's hands.
- **Track B — Live Forward Paper Trading (proves reality):** run the real cadence with **live EOD data and live broker prices**, recording would-be fills at actual market prices, for a **minimum of 2 and target of 3–4 live quarterly rebalances**. This is the only track that tests real slippage, real timing, real corp actions, and real discipline.

**You may not skip Track B.** Track A earns the right to start Track B; Track B earns the right to deploy capital. Returns/alpha are explicitly *not* a success criterion here — the strategy is already frozen and validated; paper-trading "good returns" proves nothing about operational readiness and a "bad" paper quarter is not a reason to change the strategy.

---

## 1. Executive Summary

The frozen champion is research-validated and the live architecture is designed. The remaining unknown is **whether the operator can execute the process correctly, repeatably, and with discipline** using a retail broker and a manual workflow. Paper trading is the controlled environment to prove that *before* real money is exposed.

The program's job is to convert every 🔴/🟡 in the [LIVE_TRADING_ARCHITECTURE.md §7 readiness table](LIVE_TRADING_ARCHITECTURE.md) into a demonstrated ✅ — backup data source exercised, validation gates fired in anger, immutable audit package produced for real, alerting tested, failover broker dry-run, and **the operator shown to follow the trade list without improvisation**.

**Success is operational, measured on five axes:**
1. **Process correctness** — every runbook step executed, every HALT respected.
2. **Reproducibility** — trade lists regenerate bit-identically from archived snapshots.
3. **Execution fidelity** — paper fills match the *intended* portfolio within tolerance; slippage tracks the cost model.
4. **Exception handling** — at least one corp action and one injected failure handled correctly.
5. **Discipline** — zero unauthorized deviations; documented, rule-consistent behavior through a drawdown.

**Duration:** ~4–6 weeks Track A (dress rehearsal) → **minimum 2, target 3–4 live quarterly rebalances** Track B (~6–12 months). **Go-live only on a clean pass of the §17 Go/No-Go framework.**

---

## 2. Validation Timeline

```
 WEEK 0 ─────────── WEEKS 1–6 ──────────────── Q1 ───── Q2 ───── Q3 ───── Q4 ──────► GO/NO-GO
 │                  │                          │        │        │        │
 │ Setup &          │ TRACK A                  │        TRACK B (live forward paper)  │
 │ baseline         │ Historical dress         │  ◄── minimum 2 / target 3–4 ──►      │
 │                  │ rehearsal (replay)       │  live quarterly rebalances           │
 │                  │                          │                                      │
 ▼                  ▼                          ▼        ▼        ▼        ▼            ▼
 - Open paper       - Replay last 4–6 quarters - Real EOD data each quarter           - Tally all
   ledger             through full runbook     - Record would-be fills @ live prices    pass/fail
 - Fund failover    - Practice every step      - Track slippage vs model                gates
   broker (real)    - Inject failure drills    - Measure execution-vs-intended TE      - Decide
 - Set alert        - Prove reproducibility    - Handle real corp actions                go-live
   channel          - Operator competency sign-off  - Discipline log every quarter
```

| Phase | Calendar | Rebalances observed | Proves |
|---|---|---|---|
| Setup | Week 0 | — | Infrastructure, ledger, failover, alerts ready |
| Track A (rehearsal) | Weeks 1–6 | 4–6 (replayed) | Process correctness, reproducibility, operator competency, failure drills |
| Track B (live paper) | ~6–12 months | 2–4 (live) | Real slippage, timing, corp actions, discipline |
| Decision | After Track B | — | Go/No-Go |

---

## 3. Validation Area Design

Each area: **Purpose · Process · Metrics · Pass/Fail Rules.**

### Area 1 — Paper Trading Duration
- **Purpose:** Observe enough *real* rebalances to trust the process, without waiting indefinitely for a quarterly cadence.
- **Process:** Track A compresses repetitions on historical data; Track B runs the live cadence. Count Track B rebalances as the binding measure of "real" experience.
- **Metrics:** # Track A rehearsals; # Track B live rebalances; # exception scenarios exercised.
- **Pass/Fail:** **PASS** ≥ 4 Track A rehearsals **AND** ≥ 2 live Track B rebalances (target 3–4) **AND** ≥ 1 real corp action + ≥ 1 injected failure handled. **FAIL** if fewer than 2 live rebalances regardless of how clean — real timing/slippage cannot be inferred from rehearsal alone.

### Area 2 — Validation Objectives
- **Purpose:** Make explicit that we are proving *operations*, not the strategy.
- **Process:** Map each objective to a [LIVE_TRADING_ARCHITECTURE.md §7] readiness gap and require evidence it closed.
- **Metrics:** % of readiness-table 🔴/🟡 items demonstrated ✅ with logged evidence.
- **Pass/Fail:** **PASS** = 100% of readiness items demonstrated at least once live. Any un-exercised critical control (validation gate, audit package, failover, alerting) = **FAIL**.

### Area 3 — Success Criteria
- **Purpose:** Define what "operationally ready" objectively means.
- **Process:** Tally the five axes (process correctness, reproducibility, execution fidelity, exception handling, discipline) across Track B.
- **Metrics:** runbook-step completion %, reproducibility match %, execution-vs-intended tracking error, slippage-vs-model ratio, # unauthorized deviations.
- **Pass/Fail (all must hold):**
  - Runbook steps executed: **100%** every live quarter.
  - HALT conditions respected: **100%** (zero overrides of a HALT).
  - Reproducibility: **100%** bit-identical trade-list regeneration.
  - Execution fidelity: each name within **±1.0% absolute weight** of its 10% target after rounding (see Area 8).
  - Slippage: realized ≤ **1.5×** modeled per side, and ≤ **0.30%** absolute per side on the liquid book (see Area 7).
  - Discipline: **zero** unauthorized deviations (see Area 11).

### Area 4 — Failure Criteria
- **Purpose:** Pre-commit to what kills the go-live decision, so it isn't rationalized away later.
- **Process:** Any single hard-fail trips a mandatory remediation + re-run of the affected live quarter.
- **Metrics:** count of hard-fail events.
- **Pass/Fail — any ONE of these is a HARD FAIL (no go-live until remediated and re-proven over a fresh live quarter):**
  - Any HALT condition overridden / ignored.
  - Any rebalance that does **not** reproduce from its snapshot.
  - Any operator deviation from the approved trade list without a documented, rule-based reason.
  - A corp action missed and traded through.
  - Trade list computed on stale/unvalidated data.
  - Audit package incomplete for any live quarter.

### Area 5 — Rebalance Simulation Process
- **Purpose:** Run the live runbook end-to-end without real capital.
- **Process:** Execute the [LIVE_TRADING_ARCHITECTURE.md §4 Runbook] verbatim. Track A: against archived data with simulated fills at recorded historical open. Track B: against live EOD data; at T+1 open, record **would-be fills at the actual prevailing market price** (mid/L1 quote at the time the order *would* have been placed), applying the cost model's statutory + slippage components.
- **Metrics:** runbook completion; turnover vs the ~38% Buffer-20 expectation; time-to-complete per rebalance.
- **Pass/Fail:** **PASS** = every step done in order, turnover within band, no skipped gate. **FAIL** = any skipped step or unexplained turnover spike.

### Area 6 — Trade Recording Process
- **Purpose:** Capture an honest, tamper-evident record of every paper trade as if real.
- **Process:** A **paper ledger** (append-only) records, per order: signal date, intended symbol/side/shares, target weight, would-be limit price, recorded fill price & time, computed costs, resulting position, and the commit/snapshot ID. Sells before buys (T+1 settlement realism). No back-editing — corrections are new dated entries.
- **Metrics:** ledger completeness (% of fields populated), timestamp presence, append-only integrity.
- **Pass/Fail:** **PASS** = 100% of orders fully recorded with timestamps, append-only intact. **FAIL** = any missing/edited entry.

### Area 7 — Slippage Tracking
- **Purpose:** Test whether the cost model's slippage assumptions hold for *this* operator at *this* broker on *this* book — the assumption underpinning the net 17.4% CAGR.
- **Process:** For each paper fill, compute realized slippage = (recorded fill price − decision reference price) / reference, per side; compare to the modeled rate for the name's liquidity tier (0.05% / 0.10% / 0.20% from [costs/cost_model.py](costs/cost_model.py)). Aggregate per quarter and per liquidity tier.
- **Metrics:** realized slippage per side (bps), realized/modeled ratio, per-tier breakdown, worst-name slippage.
- **Pass/Fail:** **PASS** = mean realized ≤ 1.5× modeled per side **and** ≤ 0.30% absolute per side across the liquid book, for **2 consecutive live quarters**. **FAIL / INVESTIGATE** = realized > modeled for 2 consecutive quarters → the net backtest is optimistic; halt go-live and re-examine cost assumptions (without changing the strategy — this is a *deployment* decision, e.g., cap AUM lower, not a strategy edit).

### Area 8 — Tracking Error Measurement
- **Purpose:** Measure **operational** tracking error — the gap between the portfolio the strategy *intended* and the one the operator actually built. (This is NOT benchmark tracking error and NOT a strategy-return check.)
- **Process:** After each rebalance, compare realized paper holdings (post-fill, post-rounding) to the deterministic target portfolio. Compute per-name absolute weight deviation and the sum of absolute deviations (turnover-style TE). Attribute any deviation to a cause: whole-share rounding (expected/benign), partial fill, slippage, or error (not benign).
- **Metrics:** per-name |Δweight|; Σ|Δweight|; deviation attributed to error vs rounding.
- **Pass/Fail:** **PASS** = each name within ±1.0% absolute of its 10% target, Σ|Δweight| ≤ 3%, and **zero** deviation attributable to operator error (rounding/partial-fill deviation is acceptable). **FAIL** = any error-attributable deviation, or weights outside tolerance without a rounding/partial-fill explanation.

### Area 9 — Data Validation Process
- **Purpose:** Prove the data gates actually catch problems before they reach a trade list.
- **Process:** Run [data/quality.py](data/quality.py)/`validate-data` + the freshness and adjustment-reconciliation gates from the architecture every cycle. Deliberately **inject** at least one bad-data scenario in Track A (stale cache; an unadjusted split; a NaN gap) and confirm the gate HALTs.
- **Metrics:** # validation runs, # true issues caught, # false negatives (issues that slipped through), corp-action >±20% flags correctly classified.
- **Pass/Fail:** **PASS** = zero false negatives across the program; every injected fault HALTs correctly; 100% of >±20% moves correctly classified (real vs unadjusted). **FAIL** = any bad data reaching signal generation.

### Area 10 — Audit Trail Requirements
- **Purpose:** Prove each quarter is reproducible and fully traceable.
- **Process:** Produce the immutable per-quarter audit package ([LIVE_TRADING_ARCHITECTURE.md §3 Stage 12]): data snapshot, scores/ranks, trade list, fills, commit + config hash, logs. Independently regenerate the trade list from the snapshot + frozen commit and diff.
- **Metrics:** regeneration diff (must be empty); package completeness %.
- **Pass/Fail:** **PASS** = bit-identical regeneration and complete package every live quarter. **FAIL** = any diff or missing artifact.

### Area 11 — Psychological Discipline Checks
- **Purpose:** Prove the operator follows the system — especially the hard parts: no stop-loss, 10% single-name concentration, and holding through drawdown (the audit's #1 *realized*-loss risk).
- **Process:** Maintain a **discipline log**: every quarter the operator records any *urge* to deviate (sell a falling name early, skip a "scary" entry, oversize a "sure thing") and confirms the rule-based action taken instead. If a drawdown occurs during the program, the response is logged and reviewed. Pre-commit, in writing, to the IPS terms (−35–40% drawdown tolerance, no intervention).
- **Metrics:** # urges-to-deviate logged; # actual deviations; drawdown-response consistency.
- **Pass/Fail:** **PASS** = every trade matches the approved list; any urge-to-deviate was logged and *not acted on*; drawdown (if any) handled per rule. **FAIL** = any acted-on deviation, or evidence the operator would not hold through the modeled drawdown. (Logging an urge is *healthy*; acting on it is the failure.)

### Area 12 — Transition Criteria to Live Capital
- **Purpose:** Define the gate from paper to real money, with no ambiguity.
- **Process:** All Areas 1–11 PASS; the §16 Transition Checklist complete; §17 Go/No-Go = GO.
- **Metrics:** consolidated pass/fail across all areas.
- **Pass/Fail:** **GO** only if every area passes and no hard-fail is open. Otherwise **NO-GO** + remediation. See §17.

---

## 4. Quarterly Rebalance Checklist (paper)

> Mirrors the live runbook so the paper process *is* the live process. Differences from live are **bolded**.

**T−5 sessions**
- [ ] Daily data pulls green all week; cache fresh. *(HALT if stale)*
- [ ] **Paper holdings ledger reconciled vs prior quarter's recorded positions.** *(HALT on mismatch)*
- [ ] Check held names for pending corp actions.
- [ ] Confirm paper NAV & notional cash.

**T (signal date, after EOD)**
- [ ] Validation PASS. *(HALT on FAIL)*
- [ ] Commit = frozen tag, config = frozen. *(HALT on drift)*
- [ ] Generate scores → ranks; determinism re-run.
- [ ] Apply Buffer 20 → target 10 names.
- [ ] Equal-weight, whole-share round → target shares; trade list.
- [ ] Turnover within ~38% band. *(HALT on spike)*

**T → T+1 (review gate)**
- [ ] Review trade list (names, buffer exits, thin-name staging, corp-action conflicts).
- [ ] Approve (recorded, timestamped, signed).

**T+1 (open)**
- [ ] **Record would-be fills at live market price** — sells first, then buys; limit + tolerance discipline; thin names staged; avoid first/last 15 min & index-rebalance days.
- [ ] Confirm each recorded fill qty = intended; partial → carry remainder.

**T+1 EOD → T+2**
- [ ] Compute slippage vs model (Area 7).
- [ ] Compute execution-vs-intended tracking error (Area 8).
- [ ] Archive immutable audit package; regenerate & diff (Area 10).
- [ ] Update discipline log (Area 11).
- [ ] Update paper tax-lot register (rehearsal only; informs go-live tax expectations).

---

## 5. Operational Validation Framework

| Axis | What it proves | Primary metric | Pass bar |
|---|---|---|---|
| Process correctness | Operator runs the runbook | runbook completion % | 100% every live quarter |
| HALT integrity | Operator respects gates | # HALT overrides | 0 |
| Reproducibility | Quarter regenerates from snapshot | regen diff | empty, every quarter |
| Execution fidelity | Built = intended portfolio | per-name |Δweight| | ≤ ±1.0%, Σ ≤ 3%, 0 error-attributed |
| Slippage realism | Cost model holds live | realized/modeled per side | ≤ 1.5× and ≤ 0.30% abs, 2 quarters |
| Data integrity | Gates catch bad data | false negatives | 0; all injected faults HALT |
| Exception handling | Survives the rare event | corp actions + drills handled | ≥1 corp action + ≥1 drill, correct |
| Discipline | Operator follows the system | acted-on deviations | 0 |
| Audit completeness | Full traceability | package completeness | 100% |

---

## 6. Transition-To-Live Checklist

**Operational evidence**
- [ ] ≥ 4 Track A rehearsals + ≥ 2 (target 3–4) live Track B rebalances completed.
- [ ] All nine validation-framework axes PASS.
- [ ] All [LIVE_TRADING_ARCHITECTURE.md §7] readiness items demonstrated ✅ live.
- [ ] ≥ 1 real corporate action handled correctly end-to-end.
- [ ] ≥ 1 injected failure drill (data, broker, partial fill) handled correctly.
- [ ] Slippage tracked the model for 2 consecutive live quarters.
- [ ] Zero open hard-fails (§Area 4).

**Infrastructure**
- [ ] Backup data source (NSE bhavcopy) exercised at least once.
- [ ] Failover broker funded and a dry-run order placed.
- [ ] Alert channel tested (HALT + NOTIFY both fired and acknowledged).
- [ ] Immutable audit archive in place and proven reproducible.

**Governance & discipline**
- [ ] IPS signed: −35–40% drawdown tolerance, 10% concentration, no stop-loss, hold-through commitment.
- [ ] Net-of-tax expectations acknowledged (~13–15%, not 17.4% gross — per audit).
- [ ] Discipline log shows zero acted-on deviations.
- [ ] CA engaged for STCG/LTCG handling.
- [ ] Start capital confirmed ≤ ₹5 L (capacity non-binding; scaling gated per [CAPACITY_ANALYSIS.md]).

---

## 7. Go / No-Go Decision Framework

Evaluate after Track B. Decision is **binary and pre-committed** — no "mostly ready."

```
                          ┌────────────────────────────────────┐
                          │ Any open HARD FAIL (§Area 4)?       │
                          └───────────────┬────────────────────┘
                                  YES ─────┘        └───── NO
                                   │                        │
                                   ▼                        ▼
                              NO-GO                ┌──────────────────────────┐
                         remediate + re-run        │ All 9 framework axes PASS?│
                         a fresh live quarter      └──────────┬───────────────┘
                                              NO ─────────────┘     └──── YES
                                               │                          │
                                               ▼                          ▼
                                          NO-GO                ┌────────────────────────────┐
                                     fix the failing axis,      │ ≥2 live rebalances + ≥1 corp │
                                     re-prove it live           │ action + ≥1 drill handled?   │
                                                                └──────────┬───────────────────┘
                                                          NO ──────────────┘    └──── YES
                                                           │                          │
                                                           ▼                          ▼
                                                      NO-GO                 ┌──────────────────────┐
                                                 run more live quarters      │ Transition checklist  │
                                                                             │ (§16) 100% complete?  │
                                                                             └──────────┬────────────┘
                                                                       NO ──────────────┘   └──── YES
                                                                        │                        │
                                                                        ▼                        ▼
                                                                   NO-GO                  ★ GO LIVE ₹5 L ★
                                                              finish the checklist        (capacity non-binding;
                                                                                           scale per CAPACITY_ANALYSIS)
```

**GO** = real ₹5 L deployment, following the live architecture verbatim. First live quarter is treated as continued probation (extra reconciliation scrutiny).

**NO-GO** outcomes are *specific*, not vague: each routes to a concrete remediation and a re-proof over a fresh live quarter. A NO-GO is a normal, expected result of a serious program — not a failure of the strategy.

---

## 8. Remaining Notes & Honest Limitations

1. **Paper fills are optimistic by construction.** Recording a would-be fill at the prevailing quote omits market impact and queue position. Treat recorded slippage as a *floor*; add margin before trusting it. This is *the* limitation of any paper program and is the reason the first live quarter stays on probation.
2. **Quarterly cadence limits live sample size.** Even a target 4 live rebalances is a small sample for slippage statistics — hence the 2-consecutive-quarter rule and the AUM-scaling gate in [CAPACITY_ANALYSIS.md] (≥4 *live* rebalances before any AUM step-up).
3. **No drawdown is guaranteed during the program.** If none occurs, discipline-through-drawdown remains *unproven* — the IPS pre-commitment and the logged urges-to-deviate are the best available proxy. Flag this explicitly in the go-live decision.
4. **This program cannot fail the strategy.** A poor paper *return* is not a NO-GO trigger and must never prompt a strategy change — that would be re-opening frozen research, which is out of scope. Only operational failures gate go-live.

---

*Protocol only. No code produced. Strategy, parameters, universe, and execution assumptions unchanged from the frozen champion (`8f0482f`). This program validates the operator and the process; the strategy is already frozen and validated.*
