# PAPER-TRADING REHEARSAL REPORT — Phase 3G (Rehearsal 001)

**Track:** A — Historical dress rehearsal (replay archived quarters through the
full runbook *as if live*). No live data, no broker, no capital.
**Strategy (frozen, unchanged):** Momentum + LowVol (50/50) · Top 10 · Quarterly ·
Buffer 20 · Equal Weight · Equity-only · Survivorship-free.
**Frozen commit:** `8f0482f` · **Tag:** `price-only-final`
**Generator:** [`run_rehearsal.py`](run_rehearsal.py) — deterministic, read-only,
calls only frozen scoring/universe/buffer/cost functions.
**Date:** 2026-06-24
**Audit package:** [`audit_packages/rehearsal_001/`](audit_packages/rehearsal_001/)

---

## 1. Objective

Execute **one complete quarterly rebalance cycle** end-to-end against archived
data, following the [LIVE_TRADING_ARCHITECTURE.md §4 runbook](LIVE_TRADING_ARCHITECTURE.md)
and the [PAPER_TRADING_PROTOCOL.md §4 checklist](PAPER_TRADING_PROTOCOL.md), to
prove the *process* is correct and reproducible — not to evaluate returns.

To genuinely exercise **Buffer-20 hysteresis and turnover** (which a single
inception rebalance cannot), the rehearsal replays the **two most recent
quarter-end signal dates** in the cache: `T_prev` establishes an inception book;
`T` is the steady-state rebalance under test.

---

## 2. Inputs used

| Input | Value / source |
|---|---|
| Price/volume panels | `data/cache_bhav/{adj_close,adj_high,adj_low,raw_volume,raw_turnover}.parquet` |
| Panel shape | 3,799 dates × 3,291 **equity-only** symbols (ETF/fund ISINs purged) |
| Data last close | 2026-05-29 |
| Signal date `T_prev` (inception) | **2026-01-01** |
| Signal date `T` (under test) | **2026-04-01** |
| Universe rule | PIT filters → top-500 by 20-day avg turnover (`TopNTurnoverUniverseBuilder`) |
| Signal | 12-1 momentum ⊕ 252-day low-vol, 50/50 percentile blend (frozen scorer) |
| Selection | `select_with_buffer(scores, holdings, n=10, buffer=20)` (frozen) |
| Sizing | equal weight 10%, whole-share rounding |
| Costs | `CostModel` (STT, stamp, GST, brokerage, slippage by liquidity tier) |
| Initial capital | ₹5,00,000 |

---

## 3. Runbook execution (step-by-step)

| Runbook stage | Action | Result |
|---|---|---|
| **T−5 · Stage 1** Data acquisition | Load archived equity-only panels | ✅ 3,799×3,291; last close 2026-05-29 |
| **T · Stage 2** Data validation gate | price-integrity / recent-history / freshness | ✅ PASS / PASS / PASS (26d ≤ quarterly tolerance) |
| **T · Stage 3** Signal generation | Mom+LowVol blend over 500-name universe | ✅ scores computed |
| — determinism re-run | recompute scores, compare | ✅ **bit-identical** |
| — NaN guard | no NaN in top-30 | ✅ PASS |
| **T · Stage 4-5** Buffer20 + construction | select 10, equal-weight, whole-share | ✅ 10-name book |
| **T · Stage 4** turnover gate | assert within Buffer-20 band | ✅ 47.8% (in band; centre ~38%) |
| **T→T+1 · Stage 6** Trade list | target − current, SELLs first | ✅ 14 orders (9 SELL, 5 BUY) |
| **T+1 EOD · Stage 12** Audit package | write immutable artifacts + checksums | ✅ 9 files |

---

## 4. Holdings generated (post-rebalance book at `T`)

| Rank | Symbol | Qty | Price | Weight | Source |
|---|---|---|---|---|---|
| 1 | SBIN | 39 | ₹1,017.80 | 9.8% | new entry |
| 2 | MFSL | 27 | ₹1,477.40 | 9.8% | retained |
| 3 | SBC | 1342 | ₹30.24 | 10.0% | new entry |
| 4 | EICHERMOT | 5 | ₹6,825.50 | 8.4% | retained |
| 5 | TVSMOTOR | 11 | ₹3,425.80 | 9.3% | retained |
| 6 | TORNTPHARM | 9 | ₹4,111.30 | 9.1% | new entry |
| 7 | TITAN | 9 | ₹4,065.50 | 9.0% | new entry |
| 8 | SBILIFE | 22 | ₹1,790.50 | 9.7% | retained |
| 16 | HEROMOTOCO | 7 | ₹5,122.00 | 8.8% | **buffer-retained** |
| 19 | MARUTI | 3 | ₹12,509.00 | 9.2% | **buffer-retained** |

Weights land in 8.4–10.0% — whole-share rounding noise only (benign at ₹5 L, per
[CAPACITY_ANALYSIS.md](CAPACITY_ANALYSIS.md)). The two names below the Top-10 by
rank (HEROMOTOCO #16, MARUTI #19) are present **because the Buffer-20 rule retains
held names still inside the top-20 band** — the intended turnover-reducing hysteresis.

---

## 5. Trade list generated (14 orders, SELLs first)

| Action | Names |
|---|---|
| **SELL** (9) | SBILIFE, MFSL, EICHERMOT, BHARTIARTL, ASIANPAINT, RELIANCE, HEROMOTOCO, NYKAA, TVSMOTOR (mix of full exits + buffer trims) |
| **BUY** (5) | SBIN (new), SBC (new), TORNTPHARM (new), TITAN (new), MARUTI (top-up) |

- **Exited entirely:** ASIANPAINT, BHARTIARTL, NYKAA, RELIANCE (dropped out of the top-20 band).
- **Turnover:** 47.8% of ₹4,05,907 book.
- **Modelled costs:** ₹1,054 (statutory + tiered slippage).

---

## 6. Reproducibility

`run_rehearsal.py` was executed **twice**. The SHA-256 of every data artifact was
**identical** across runs:

```
7ae9457494bdfa88  alerts.csv
f066275832ee8a80  holdings.csv
ecfc33a51fb6f239  ranks_T.csv
b0e5d81ad6b5f5b1  trade_list.csv
b0e5d81ad6b5f5b1  trades.csv
```

`diff` of the two checksum sets was empty → **bit-identical regeneration PASS**,
satisfying the core production guarantee ([LIVE_TRADING_ARCHITECTURE.md §3 Stage 12]).
The git commit is stamped in `manifest.json` (`8f0482f`).

---

## 7. Operational issues encountered

| # | Issue | Impact | Disposition |
|---|---|---|---|
| 1 | Quarter-end signal dates resolve to the **first trading day of the quarter** (2026-01-01 / 2026-04-01) via `get_rebalance_dates`, not the calendar quarter-*end*. | None for correctness (consistent with the backtest), but the naming "quarter-end" in docs vs "first trading day" in code could confuse an operator. | Document the convention; no code change (matches frozen backtest). |
| 2 | Inception book rolled from ₹5.00 L → ₹4.06 L over Q1 (−19%). | Cosmetic — it is real market movement of the inception names, not an error. | Expected; returns are explicitly *not* a success criterion here. |
| 3 | Turnover 47.8% sits **above** the ~38% centre. | Within a sane band; the first transition off an arbitrary inception book is naturally higher than steady-state. | Monitor across future rehearsals; flagged NOTIFY-worthy if it persists. |
| 4 | `trades.csv` and `trade_list.csv` are duplicates. | Minor redundancy. | Intentional — one is the ledger, one the operator transcription sheet. |

**No HALT conditions fired.** The only alert was a NOTIFY ("Archived-data replay"),
which is expected and correct for a Track-A dress rehearsal.

---

## 8. Runbook deviations

| Deviation from the live runbook | Why | Acceptable for Track A? |
|---|---|---|
| Data is **archived**, not a live EOD pull | Track A replays history by design | ✅ yes (Track B requires live data) |
| No broker holdings **reconciliation** (T−5 step 2) | no broker account in a paper rehearsal | ✅ yes — flagged as a Track-B / live gap |
| No **corp-action calendar** check | not wired yet (known 🔴 gap) | ✅ logged in gap analysis |
| Fills assumed at `T`-close, no `T+1` open slippage realism | rehearsal records intended book, not live fills | ✅ yes — Track B records would-be fills at live prices |
| **Approval gate** (human sign-off) not enforced programmatically | single-operator rehearsal | ⚠️ must be a manual step in live; see gap analysis |

None of these are strategy deviations — the signal, universe, buffer, sizing and
costs are the frozen champion's, unchanged.

---

## 9. Time required

| Phase | Time |
|---|---|
| End-to-end automated cycle (load → signal → selection → trade list → audit package) | **~4.7 s** |
| Determinism re-run + checksum diff | < 10 s |
| (Live equivalent) human review + manual order entry for ~14 orders at ₹5 L | est. 30–45 min (per architecture; not part of this automated run) |

The deterministic compute is trivially fast; the binding time cost in live
operation is the **human review/approval and manual broker entry**, not the maths.

---

## 10. Lessons learned

1. **The deterministic core is solid.** Signal → trade list regenerates bit-for-bit;
   the reproducibility guarantee is real and now demonstrated, not just asserted.
2. **Buffer-20 visibly works.** 6 of 10 names retained (2 of them below the Top-10
   by rank), holding turnover to ~48% on a cold-start transition — exactly the
   churn suppression the rule exists for.
3. **The audit package is the right shape.** `holdings / trades / alerts / summary`
   + manifest + checksums is enough to reconstruct and verify a quarter. This format
   should be frozen as the standard for every future rebalance.
4. **The human controls are the gap, not the code.** Every deviation in §8 is an
   *operational wrapper* (broker reconciliation, corp-action calendar, approval
   sign-off, live-fill recording) — none touch the strategy. These are exactly the
   🔴/🟡 items the paper-trading program exists to close.
5. **Rehearsal cadence is cheap.** A full cycle runs in seconds, so Track A can
   replay many quarters quickly to build operator muscle memory before Track B.

---

*Rehearsal only. No live trading, no broker execution, no capital. Strategy,
parameters, universe and costs unchanged from the frozen champion (`8f0482f`).*
