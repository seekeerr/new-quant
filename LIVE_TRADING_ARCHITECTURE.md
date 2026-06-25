# LIVE TRADING ARCHITECTURE — Phase 3C

**Strategy (frozen, unchanged):** Momentum + LowVol · Top 10 · Quarterly · Buffer 20 · Equal Weight · Equity Only · Survivorship-Free
**Frozen commit:** `8f0482f` · **Tag:** `price-only-final`
**Validated:** CAGR ≈ 17.4% · Sharpe ≈ 0.69 · Calmar ≈ 0.52 · MaxDD ≈ −33.5% · Alpha ≈ +5.4%
**Deployment context:** Indian equities · EOD data · quarterly rebalance · retail broker · initial live capital ≈ ₹5 L
**Inputs to this doc:** [PRODUCTION_READINESS_AUDIT.md](PRODUCTION_READINESS_AUDIT.md), [CAPACITY_ANALYSIS.md](CAPACITY_ANALYSIS.md), and the frozen system ([main.py](main.py), [data/downloader.py](data/downloader.py), [data/quality.py](data/quality.py), [universe/universe_builder.py](universe/universe_builder.py), [universe/filters.py](universe/filters.py), [portfolio/ranker.py](portfolio/ranker.py), [portfolio/constructor.py](portfolio/constructor.py), [risk/rebalancer.py](risk/rebalancer.py), [costs/cost_model.py](costs/cost_model.py)).
**Date:** 2026-06-23
**Scope:** Operations & deployment architecture only. No strategy/parameter/universe changes, no research, no backtests, no code.

---

## 1. Executive Summary

The frozen champion is **operationally simple by design** — it trades **once a quarter**, holds **10 names**, uses **EOD data**, and turns over **~38% per rebalance** (≈4 names traded per quarter). At ₹5 L this is a process a single disciplined operator can run with a spreadsheet, a checklist, and a retail broker terminal. The engineering goal is therefore **not** automation for its own sake — it is **operational correctness and reproducibility**: making the live portfolio provably equal to what the frozen strategy *intended*, every quarter, with a paper trail.

Three principles govern the whole architecture:

1. **The live process must obey the backtest's own assumptions.** The backtest decides on signal date `T` using data available at `T`, and executes at the **next session's open (`T+1`)** ([config.py](config.py): `execution_delay_days=1`, `execute_at="open"`). Any live deviation from this is a silent source of tracking error. The #1 way this strategy fails live is *not* bad markets — it is the operator computing signals on stale or wrongly-adjusted data, or executing on a different day than the model assumes.

2. **Every quarter is a reproducible, version-stamped event.** Given the same input data and the same frozen commit, the trade list must regenerate identically. If it doesn't, that is a bug, and trading halts.

3. **Quarterly cadence means automation has low ROI; controls have high ROI.** Four events a year do not justify a fully automated pipeline (which adds its own failure surface). They *do* justify hard validation gates, an immutable log, and a rehearsed runbook. **Generate the trade list programmatically (deterministic); execute and reconcile with a human in the loop.**

**Production readiness today: CONDITIONAL GO at ₹5 L** once the gates in §17 exist — chiefly (a) a data-freshness + corporate-action reconciliation gate, (b) an immutable rebalance log, and (c) a funded failover broker. The strategy's research lineage is sound; the gap to live is entirely operational.

---

## 2. End-to-End Workflow Diagram

```
                          ┌─────────────────────────────────────────────┐
                          │   QUARTERLY CYCLE (4× / year)                │
                          └─────────────────────────────────────────────┘

  [DAILY, light]                          [QUARTER-END, heavy]
  ───────────────                         ─────────────────────

  ┌──────────────┐
  │ 1. DATA       │   yfinance (primary) ──► parquet cache ──► local DB
  │ ACQUISITION   │   NSE bhavcopy (backup) ─┘
  └──────┬───────┘
         │ raw OHLCV
         ▼
  ┌──────────────┐   missing-data · corp-action · price-integrity · universe-integrity
  │ 2. DATA       │── FAIL ──► HALT + ALERT (do not proceed on bad data)
  │ VALIDATION    │   (main.py validate-data + reconciliation)
  └──────┬───────┘
         │ clean panel  (gate: freshness ≤ 5 trading days)
         ▼
  ┌──────────────┐   PIT universe (filters.py) ──► momentum+lowvol scores (ranker.py)
  │ 3. SIGNAL     │   on signal date T
  │ GENERATION    │── validation: rank stability, buffer logic, NaN checks
  └──────┬───────┘
         │ ranked candidates
         ▼
  ┌──────────────┐   Buffer-20 hysteresis vs current holdings ──► target 10 names
  │ 4–5. REBALANCE│   equal weight (10%) ──► whole-share rounding (constructor.py)
  │ + CONSTRUCTION│   ──► trade list = target − current (rebalancer.py)
  └──────┬───────┘
         │ trade list (BUY/SELL, symbol, shares)
         ▼   ┌──────── HUMAN REVIEW GATE ────────┐
             │ turnover sane? names sane? corp-   │── REJECT ──► investigate
             │ action clean? liquidity ok?        │
             └──────┬─────────────────────────────┘
         ▼ approved
  ┌──────────────┐   execute at T+1 open · limit orders w/ tolerance · staged
  │ 6. ORDER      │── partial fill ──► top-up next session
  │ EXECUTION     │── failed order ──► retry / failover broker
  └──────┬───────┘
         │ fills
         ▼
  ┌──────────────┐   filled vs intended weights · realized vs modeled cost
  │ RECONCILE +   │── mismatch ──► ALERT + correct
  │ LOG (immutable)│  archive: data snapshot, signals, trade list, fills, commit hash
  └──────────────┘

  [CONTINUOUS, all quarter]
  ┌──────────────────────────────────────────────────────────────────────┐
  │ 7. CORP ACTIONS  │ 8. MONITORING │ 9. LOGGING │ 10. ALERTING │ 11. RECOVERY │
  └──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Lifecycle Stage Design

Each stage below specifies **Inputs · Outputs · Failure Modes · Controls · Human Checks · Automation Opportunities**.

### Stage 1 — Data Acquisition
- **Inputs:** Symbol list (NIFTY 500 constituents, [data/nifty500_constituents.csv](data/nifty500_constituents.csv)); date range; prior cache.
- **Outputs:** Daily OHLCV appended to parquet cache (`data/cache/*.parquet`) and DB ([data/database.py](data/database.py)).
- **Source selection:**
  - **Primary:** yfinance `.NS` (already wired in [data/downloader.py](data/downloader.py)). Free, sufficient for EOD/quarterly, but *unofficial and adjustment-opaque* — it silently auto-adjusts for splits/dividends, which must be reconciled against the broker (see Stage 7).
  - **Backup:** NSE official **bhavcopy** (daily EOD CSV from the exchange) — authoritative, raw (un-adjusted) prices. Use to cross-check yfinance and to fill gaps when yfinance fails.
  - **Tertiary (manual):** broker's own historical data export for any single missing symbol.
- **Daily workflow:** End-of-day, after NSE close + settlement (~18:30 IST): pull the day's OHLCV for the universe, append to cache, run Stage 2. (Quarterly strategy, but daily pulls keep the cache fresh and surface problems early instead of on rebalance morning.)
- **Backup data source:** if the primary pull fails or diverges >0.5% from bhavcopy on spot checks, switch to bhavcopy for that day and flag.
- **Data retention policy:** Keep **full raw OHLCV history indefinitely** (it's small; it's the basis of every reproducibility claim). Snapshot the *exact* data panel used at each rebalance into an immutable, dated archive. Never overwrite history in place — append-only.
- **Failure modes:** yfinance outage/throttle; partial batch download; silently wrong adjustment; symbol delisted from feed mid-history; cache write corruption.
- **Controls:** freshness assertion (cache max date ≥ last trading day); row-count and date-continuity check per symbol; checksum on cache files; primary-vs-backup spot reconciliation.
- **Human checks:** glance at the daily acquisition log for any symbol flagged failed/diverged; weekly confirm cache completeness.
- **Automation:** fully scriptable daily pull + append + Stage-2 trigger; alert-on-failure (Stage 10). This is the *one* part worth fully automating because it runs daily.

### Stage 2 — Data Validation
- **Inputs:** Updated cache panel; prior validated panel; known corporate-action calendar.
- **Outputs:** PASS/FAIL gate + a validation report; a "clean panel" certified for signal use. (Builds on the existing `main.py validate-data` / [data/quality.py](data/quality.py).)
- **Missing-data checks:** ≥90% trading-day coverage over lookback (mirrors `min_trading_days_pct`); no gaps in the most recent 252 days for any held or candidate name (momentum needs the full 12-1 window).
- **Corporate-action checks:** flag any single-day move > ±20% as a *probable unadjusted action* until confirmed real; reconcile yfinance-adjusted vs bhavcopy-raw to detect adjustment disagreements (the highest-impact data risk per the audit).
- **Price-integrity checks:** no negative/zero prices; High ≥ Low ≥ 0; Close within [Low, High]; no stale-repeat (identical OHLC for N days = feed freeze); volume ≥ 0.
- **Universe-integrity checks:** constituent list current; no symbol with a changed ISIN/ticker silently mapped to the wrong series; survivorship-free history preserved (delisted names retained, not dropped).
- **Failure modes:** undetected unadjusted action → corrupted momentum signal; ticker remap collision; partial panel passed as complete.
- **Controls:** **hard gate — no signal generation on a FAILED validation.** Every check logged with the offending symbols.
- **Human checks:** review any >±20% move flagged as "needs confirmation" against the corporate-action calendar before clearing.
- **Automation:** all mechanical checks automated; only ambiguous corp-action confirmations need a human.

### Stage 3 — Signal Generation
- **Inputs:** Clean panel (Stage 2); signal date `T` (the chosen quarter-end decision date); frozen config + commit hash.
- **Outputs:** Cross-sectional Momentum+LowVol scores (0–100) per eligible symbol; ranked candidate list.
- **When:** On the **signal date `T`** (quarter-end), using only data available as of `T`. Execution is deferred to `T+1` open — never compute and trade same-session.
- **Required inputs:** 252-day price history per name (12-1 momentum), trailing realised-vol window for the LowVol overlay, PIT universe from filters as of `T`.
- **Validation controls:** no NaN scores in the top-30; rank stability sanity (top names shouldn't be wildly different from last quarter absent a real regime shift); confirm the same commit/config as the frozen champion produced the scores; re-run determinism check (same inputs → same scores).
- **Failure modes:** look-ahead leak (using `T+1` data at `T`); NaN propagation from a thin name; config drift from the frozen spec.
- **Controls:** PIT enforcement (only data ≤ `T`); determinism re-run; commit-hash assertion against `8f0482f` / the frozen tag.
- **Human checks:** eyeball the top-15 ranks for plausibility; confirm no obviously-broken name (e.g., a suspended ticker) ranks in.
- **Automation:** fully deterministic and scriptable — this is pure computation off the certified panel.

### Stage 4 — Quarterly Rebalance Process
- **Inputs:** Ranked candidates (Stage 3); current holdings; Buffer-20 rule; cash/NAV.
- **Outputs:** Target 10-name portfolio; approved trade list.
- **Timeline (around quarter-end):**
  - **T−5 sessions:** confirm daily data healthy; pre-stage NAV/cash; check held names for pending corp actions.
  - **T (signal date, EOD):** generate signals, apply Buffer 20, derive target portfolio + trade list.
  - **T → T+1 (overnight):** human review gate (below).
  - **T+1 (open):** execute approved trades (staged; see Stage 6).
  - **T+1 EOD → T+2:** reconcile fills, log, archive.
- **Decision points:** (a) does any held name exit only because it fell *outside* the Buffer-20 band (correct) vs noise (bug)? (b) is any new entry a thin/illiquid name needing staged execution (per [CAPACITY_ANALYSIS.md](CAPACITY_ANALYSIS.md))? (c) any corp-action pending on a name we're about to trade?
- **Human review steps:** approve the trade list only after: turnover within the expected Buffer-20 band (~38%/quarter; a spike = stop & investigate), names plausible, no corp-action/adjustment conflict, liquidity acceptable for each line.
- **Automation opportunities:** signal→target→trade-list is fully automated and deterministic; the *approval* is the deliberate human gate. Do not automate the approval.
- **Failure modes:** over-trading from misapplied buffer; trading into an unhandled corp action; executing late (prices moved).
- **Controls:** turnover-band assertion; corp-action pre-check; dry-run trade list against prior holdings before approval.

### Stage 5 — Portfolio Construction
- **Inputs:** Target 10 names; NAV; latest prices; lot/whole-share rules.
- **Outputs:** Target shares per name; trade list = target − current.
- **Holding generation:** top 10 post-Buffer-20 names.
- **Weight assignment:** **equal weight, 10% each** (frozen). Whole-share rounding via [portfolio/constructor.py](portfolio/constructor.py) — at ₹5 L (₹50k/name) a high-priced share introduces small weight error; accept it (sub-capacity, benign per capacity analysis).
- **Trade list generation:** per-name BUY/SELL with share counts, via [risk/rebalancer.py](risk/rebalancer.py) (target vs current → trades).
- **Failure modes:** rounding pushes a name materially off 10%; stale price used for share count; cash mismatch (not enough cash for buys before sells settle — T+1 settlement matters at a retail account).
- **Controls:** post-construction weight check (each name within tolerance of 10%); cash-availability check ordering sells before buys where settlement requires; deterministic regeneration.
- **Human checks:** confirm share counts against NAV; confirm no negative cash.
- **Automation:** fully automated; deterministic output is the artifact the human approves.

### Stage 6 — Order Execution
- **Inputs:** Approved trade list; broker terminal/API; T+1 open prices.
- **Outputs:** Fills (price, qty, time) per order.
- **Order types:** **limit orders with a tolerance band** (not market orders) to control slippage — the cost model assumes 0.05–0.20% slippage by tier; market orders on thin names blow past that. Execute near (not at) the open to avoid the auction's noise; avoid first/last 15 minutes and quarter-end index-rebalance days.
- **Execution workflow:** sells first (free up cash given T+1 settlement), then buys; one name at a time for thin lines; **staged over 2–3 sessions if any name exceeds ~10% of its ADTV** (per capacity analysis — not binding at ₹5 L, but the workflow must support it for scaling).
- **Partial-fill handling:** carry the unfilled remainder to the next session at a re-checked limit; never chase with a market order; if still unfilled after the rebalance window, log as a *tracking-error event* and accept the smaller position rather than forcing it.
- **Failed-order handling:** rejected/failed order → diagnose (margin, circuit, suspension); retry once; if blocked (locked circuit / suspension), skip that name this quarter and log — do not work around a halt.
- **Failure modes:** slippage spike on clustered rebalance-day fills; partial fills leaving the book unbalanced; broker outage mid-rebalance; fat-finger qty.
- **Controls:** limit-price tolerance; staged execution; post-each-order check vs intended; two-session window to correct mistakes.
- **Human checks:** operator places/approves each order (at ₹5 L, manual entry is fine and adds a sanity layer); confirm filled qty = intended before moving on.
- **Automation opportunities:** at ₹5 L keep execution **manual** (low order count, human is the safety check). Automate later via broker API only after the manual process is proven (Stage 13).

### Stage 7 — Corporate Actions
- **Inputs:** Corp-action calendar (exchange announcements); broker holdings statement; price feed.
- **Outputs:** Reconciled positions; adjusted cost basis; flags for affected names.
- **Splits / bonuses:** verify the feed (yfinance) and broker both reflect the adjustment consistently; a one-sided adjustment corrupts the momentum signal — **hard-stop trading that name until reconciled.**
- **Mergers:** held name merging → confirm share conversion in demat; treat as a forced exit/entry per the action terms; exclude from signal until resolved.
- **Delistings:** held name delisted → position becomes unsellable; write down per the audit's delisting risk; do not let it linger in "holdings" as if liquid (the ZYLOG/NET4 precedent from [CAPACITY_ANALYSIS.md](CAPACITY_ANALYSIS.md)).
- **Suspensions:** on suspension news, attempt exit at next available liquidity *ahead* of rebalance if possible; flag and freeze the name in the universe.
- **Failure modes:** missed action → signal computed on a discontinuity; unadjusted price read as a −50% "crash"; demat vs system position drift.
- **Controls:** every-rebalance reconciliation of system holdings vs broker statement; the Stage-2 >±20% move flag catches most unadjusted actions; corp-action calendar maintained for the 10 held names.
- **Human checks:** confirm each flagged action against the official announcement; clear the trading freeze only after reconciliation.
- **Automation:** calendar ingestion and the >±20% flag are automatable; the confirmation is human.

### Stage 8 — Monitoring
- **Daily (light, ~5 min):** data acquisition succeeded; NAV & drawdown vs the −33.5% reference; any held-name news/circuit/suspension; cache freshness.
- **Weekly:** cache completeness; primary-vs-backup spot reconciliation; corp-action calendar refresh for held names.
- **Quarterly (full):** end-to-end rebalance reconciliation; realized vs modeled cost/slippage; tracking error vs backtest expectation; tax-lot review; turnover sanity.
- **Inputs:** logs, NAV, broker statement, news feed. **Outputs:** monitoring log + alerts.
- **Failure modes:** silent data drift; un-noticed corp action; drawdown breaching investor pain threshold; tracking-error creep signalling a process bug.
- **Controls:** alert thresholds (Stage 10); monthly tracking-error flag (divergence = hunt for a bug, not "bad luck").
- **Human checks:** the daily glance and the quarterly reconciliation are inherently human.
- **Automation:** daily metrics dashboard + threshold alerts; human interprets.

### Stage 9 — Logging
- **Trade logs:** every order — intended qty/price, order type, fills, timestamps, broker ref.
- **Rebalance logs:** signal date, scores, ranks, buffer decisions, target vs current, turnover, commit hash, config snapshot.
- **Data logs:** daily acquisition results, validation outcomes, source used (primary/backup), divergences.
- **Exception logs:** every failed check, halt, retry, partial fill, corp-action freeze.
- **Inputs:** all stages. **Outputs:** immutable, timestamped, append-only records.
- **Failure modes:** missing/overwritten logs → loss of reproducibility/audit trail.
- **Controls:** append-only, dated, never edited in place; logs are the legal/audit record (cross-ref the existing `logs/` per-module files).
- **Human checks:** quarterly archive review.
- **Automation:** fully automated; logging is a side effect of every stage.

### Stage 10 — Alerting
- **Missing data:** daily pull failed or cache stale → alert before signal use.
- **Failed runs:** any validation FAIL, signal-determinism mismatch, or commit-hash drift → alert + halt.
- **Unexpected portfolio changes:** turnover outside the Buffer-20 band; a name entering/exiting against expectation → alert + hold for review.
- **Corporate actions:** any held name with a pending/landed action, or a >±20% unexplained move → alert.
- **Inputs:** check results from all stages. **Outputs:** push notification (email/SMS/IM) with severity.
- **Failure modes:** alert fatigue (too many low-value alerts) or missed critical alert.
- **Controls:** two severities — **HALT** (blocks the pipeline: bad data, commit drift, turnover spike) vs **NOTIFY** (review at leisure). Test the alert channel monthly.
- **Human checks:** acknowledge and action every HALT alert.
- **Automation:** alert dispatch automated; response human.

### Stage 11 — Failure Recovery
- **Data-source failure:** primary (yfinance) down → switch to NSE bhavcopy backup; if both fail, **do not rebalance on stale data** — defer execution a session (quarterly cadence tolerates a 1–2 day slip far better than trading on bad data).
- **Broker outage:** primary broker down on rebalance day → use **funded failover broker** (per audit) or defer 1 session; holdings are safe in demat regardless.
- **Execution interruption (mid-rebalance):** partial book traded → reconcile what filled, resume remaining trades next session from the *actual* current holdings (regenerate trade list from reality, not from the original plan).
- **Corrupt data:** validation catches it → restore cache from the last good immutable snapshot, re-pull the affected days, re-validate before proceeding.
- **Inputs:** failure signal + last-good snapshot/backup. **Outputs:** restored, validated state; incident log entry.
- **Failure modes:** recovering onto an inconsistent state; trading the original (now wrong) plan after interruption.
- **Controls:** always regenerate the trade list from *current actual* holdings after any interruption; restore-then-revalidate, never restore-and-trust.
- **Human checks:** operator confirms restored state matches broker statement before resuming.
- **Automation:** backups/snapshots automated; recovery decisions human.

### Stage 12 — Audit Trail
- **Reproducibility requirements:** given the archived data snapshot + frozen commit + config, the quarter's trade list must regenerate **bit-identically**. This is the core production guarantee.
- **Version tracking:** every rebalance stamped with git commit (`8f0482f`/tag), config hash, data-snapshot ID, code/library versions.
- **Research-to-production traceability:** a line from each live decision back through the frozen champion to the research that justified it ([PHASE1_FINAL_REPORT.md], [PRICE_ONLY_FINAL_CONCLUSION.md], [PRODUCTION_READINESS_AUDIT.md], [CAPACITY_ANALYSIS.md]). Any change to the live strategy requires a new commit, a new tag, and a documented rationale — **the frozen champion is never edited in place.**
- **Inputs:** all logs + snapshots. **Outputs:** an immutable per-quarter audit package.
- **Failure modes:** untracked config edit → live ≠ research; lost snapshot → unreproducible quarter.
- **Controls:** commit-hash assertion at signal time; append-only archive; config-drift detection.
- **Human checks:** quarterly sign-off that the archive is complete.
- **Automation:** stamping and archiving automated.

---

## 4. Rebalance Runbook (quarter-end)

> Execute in order. Any **HALT** condition stops the process until resolved.

**T−5 sessions**
1. Confirm daily data pulls have been green all week. *(HALT if cache stale)*
2. Pull broker holdings statement; reconcile vs system holdings. *(HALT on mismatch)*
3. Check each held name for pending corporate actions / suspensions.
4. Confirm NAV and available cash.

**T (signal date, after EOD data is in)**
5. Run Stage 2 validation. *(HALT on FAIL)*
6. Confirm commit = frozen tag, config = frozen. *(HALT on drift)*
7. Generate Momentum+LowVol scores → ranks (Stage 3). Determinism re-run.
8. Apply Buffer 20 vs current holdings → target 10 names (Stage 4).
9. Equal-weight, whole-share round → target shares; trade list = target − current (Stage 5).
10. **Assert turnover within Buffer-20 band (~38%).** *(HALT on spike → investigate)*

**T → T+1 (human review gate)**
11. Review trade list: names plausible? exits explained by buffer? any thin name needing staged execution? any corp-action conflict? *(REJECT → investigate; do not trade an unreviewed list)*
12. Approve trade list (recorded, timestamped, signed).

**T+1 (open)**
13. Place SELLs first (limit + tolerance), then BUYs. Thin names staged. Avoid first/last 15 min and index-rebalance days.
14. After each order, confirm filled qty = intended. Partial → carry remainder.

**T+1 EOD → T+2**
15. Reconcile filled vs intended weights; realized vs modeled cost/slippage. *(NOTIFY on material deviation)*
16. Archive immutable package: data snapshot, scores/ranks, trade list, fills, commit/config hash, logs.
17. Update tax-lot register. Update monitoring baseline (new holdings, new drawdown reference).

---

## 5. Operations Checklist

**Daily**
- [ ] Data pull green; cache fresh (≤ last trading day).
- [ ] Validation passed.
- [ ] NAV / drawdown vs −33.5% reference noted.
- [ ] Any held-name news / circuit / suspension?

**Weekly**
- [ ] Cache completeness check.
- [ ] Primary-vs-backup (yfinance vs bhavcopy) spot reconciliation.
- [ ] Corp-action calendar refreshed for the 10 held names.
- [ ] Alert channel responsive (monthly: send a test).

**Quarterly (in addition to the Runbook)**
- [ ] Realized vs modeled cost/slippage reviewed.
- [ ] Tracking error vs backtest expectation reviewed.
- [ ] Tax lots (STCG/LTCG) reviewed with CA.
- [ ] Audit package archived and signed off.
- [ ] Failover broker still funded/accessible.

---

## 6. Incident Response Procedures

| Incident | Immediate action | Recovery | Prevent recurrence |
|---|---|---|---|
| **Stale / missing data on rebalance day** | HALT; do not generate signals | Switch to bhavcopy backup; if both fail, defer execution 1 session | Daily pulls + freshness gate surface it before T |
| **Adjustment mismatch (feed vs broker)** | Freeze trading on that name | Reconcile against official action; correct cost basis | Stage-2 reconciliation every rebalance |
| **Turnover spike vs Buffer-20 band** | HALT; do not trade | Diagnose buffer/logic/data bug; regenerate | Determinism + turnover assertion |
| **Broker outage at open** | Pause | Failover broker, or defer 1 session | Funded second broker (audit requirement) |
| **Partial / failed fill** | Stop chasing | Carry remainder to next session at re-checked limit; regenerate plan from actual holdings | Limit orders + staged execution + 2-session window |
| **Held name suspended/delisted** | Flag, freeze | Attempt exit at next liquidity; write down if dead | Anti-manipulation filters; corp-action monitoring |
| **Corrupt cache** | HALT | Restore last-good snapshot; re-pull; re-validate | Append-only history + checksums |
| **Commit/config drift** | HALT | Reset to frozen tag; regenerate | Commit-hash assertion at signal time |

---

## 7. Production Readiness Assessment

| Capability | Status @ ₹5 L | Gap to close |
|---|---|---|
| Strategy validated & frozen | ✅ Done | — |
| Deterministic signal/trade-list generation | 🟡 Exists in engine; needs a *live* PIT path separate from backtest | Wrap a live "as-of-T" run mode (no code in this doc; flagged for build) |
| Data acquisition (primary) | ✅ yfinance wired | — |
| Data acquisition (backup) | 🔴 Not wired | Add NSE bhavcopy ingestion |
| Data validation gate | 🟡 `validate-data` exists | Add freshness gate + adjustment reconciliation as a *hard block* |
| Corp-action handling | 🔴 Manual/ad-hoc | Calendar + reconciliation procedure |
| Execution | 🟡 Manual broker terminal | Documented order-placement discipline (limit + staged) |
| Logging / audit trail | 🟡 `logs/` exists | Immutable, per-quarter, version-stamped archive |
| Alerting | 🔴 None | HALT/NOTIFY channel |
| Failover broker | 🔴 Single broker | Open + fund second account |
| Reproducibility | 🟡 Backtest reproducible | Per-quarter data snapshot + commit stamp |

**Verdict: CONDITIONAL GO at ₹5 L.** The strategy and core compute are ready; the *operational wrapper* (backup data, hard validation gates, immutable audit package, alerting, failover broker) is the work remaining. None of it touches the strategy.

---

## 8. Scaling Roadmap

Capacity is **not binding** in this range (per [CAPACITY_ANALYSIS.md](CAPACITY_ANALYSIS.md): conservative ceiling ₹50 L, hard cap ₹3 Cr). The roadmap therefore scales **operational rigor**, not the strategy.

| Capital | Operational posture | New controls introduced |
|---|---|---|
| **₹5 L** | Manual execution, manual review, scripted data + validation. One operator. | Freshness gate, immutable log, failover broker, alerting. **Prove the process for ≥4 rebalances.** |
| **₹10 L** | Same posture; rounding noise halves. | Begin formal realized-vs-modeled cost reconciliation each quarter. |
| **₹25 L** | Same; first watch on the single thinnest name (can reach ~50% of a ₹50L-ADTV name's volume). | Per-rebalance liquidity screen; flag any name < ₹2 Cr ADTV for staged execution. |
| **₹50 L** | Conservative capacity ceiling. Staged multi-session execution may be needed for one thin name. | Formal staged-execution procedure; stress-exit rehearsal. |
| **Future (>₹50 L → ₹3 Cr cap)** | Consider broker-API semi-automation *only after* the manual process is proven; mandatory liquidity screening every rebalance. | Re-run [CAPACITY_ANALYSIS.md] before each step up; tax-management discipline (LTCG threshold handling); **do not exceed ₹3 Cr without a fresh capacity audit.** |

**Scaling gate principle:** never increase AUM until the current tier has run **≥4 clean rebalances** with realized cost/slippage tracking the model and zero unresolved HALT incidents.

---

## 9. Remaining Operational Risks

1. **Single-operator / key-person risk.** No four-eyes check on approval; operator unavailability on rebalance day. *Mitigation:* runbook enables a second person; quarterly cadence tolerates a 1–2 session defer.
2. **yfinance dependency & adjustment opacity.** Unofficial feed; silent split/dividend adjustment. *Mitigation:* bhavcopy backup + every-rebalance reconciliation; this is the highest-residual data risk.
3. **Manual execution error.** Fat-finger at the terminal. *Mitigation:* programmatic trade list (operator transcribes, doesn't compute); per-order confirmation.
4. **Corp-action surprise on a held name.** Near-certain over a year across 10 names. *Mitigation:* calendar + >±20% flag + freeze-until-reconciled.
5. **Tracking error creep.** Live drifts from backtest via fills/costs/timing. *Mitigation:* monthly tracking-error flag treated as a bug hunt, not noise.
6. **No automated reconciliation of demat vs system at present.** *Mitigation:* mandatory manual reconciliation in the runbook until automated.
7. **Alerting/recovery untested under real stress.** A control that's never fired is unproven. *Mitigation:* monthly alert-channel test; rehearse one recovery drill before going live.
8. **Tax drag (from audit) is an operational reality, not just a number.** Quarterly churn realizes STCG. *Mitigation:* tax-lot register + CA + LTCG-threshold execution discretion (no strategy change).

---

*Architecture and operations design only. No code produced. Strategy, parameters, universe rules, and factors unchanged from the frozen champion (`8f0482f`). All build items flagged here are operational wrappers around the frozen system, never modifications to it.*
