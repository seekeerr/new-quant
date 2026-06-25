# CAPACITY ANALYSIS — Phase 3B

**Strategy (frozen, unchanged):** Momentum + LowVol · Top 10 · Quarterly · Buffer 20 · Equal Weight · Equity Only · Survivorship-Free
**Frozen commit:** `8f0482f` · **Tag:** `price-only-final`
**Inputs used:** [PRODUCTION_READINESS_AUDIT.md](PRODUCTION_READINESS_AUDIT.md), the frozen champion, the existing cost model ([cost_model.py](costs/cost_model.py)), the existing liquidity filters ([filters.py](universe/filters.py)), existing universe construction ([universe_builder.py](universe/universe_builder.py)), and the **actual realized holdings** of the strategy ([stock_pnl.csv](results/momentum_lowvol_validation/stock_pnl.csv), [holdings_breadth.csv](results/momentum_lowvol_validation/holdings_breadth.csv)).
**Analysis date:** 2026-06-23
**Scope:** Capacity only. Strategy, universe rules, factors, and parameters are **not** modified. No code produced.

---

## 0. The Central Finding (read this first)

**The audit's ₹10 Cr ceiling is not supported by the frozen ruleset and is rejected here.**

The audit reasoned about capacity *as if the book were Tier-1 large-caps*. The frozen strategy does not guarantee that. Two facts from the actual system break the assumption:

1. **The binding constraint is the *thinnest* name in the book, not the average.** Equal-weight (10% each) forces an identical rupee allocation into every holding regardless of its liquidity. One thin name caps the whole portfolio's deployable capital.

2. **The frozen universe rule admits genuinely thin names.** The selection floor in [config.py](config.py) is `min_avg_daily_turnover = ₹50 L` (Tier-3), **not** Tier-1. The strategy *did, in reality,* select illiquid names — this is not hypothetical:

| Name held | Quarters held | Reality |
|---|---|---|
| **ZYLOG** (Zylog Systems) | 2 | Defaulted / delisted — went to near-zero |
| **NET4** (Net 4 India) | 1 | Suspended / delisted |
| **VAKRANGEE** | 3 | Notorious operator/circuit collapse (−90% cascade) |
| **THEBYKE** (Byke Hospitality) | 5 | Thin micro-cap, ADTV often < ₹2 Cr |
| **RAJTV, SBC, SEINV, FIEMIND, LAXMIMACH** | 1–3 each | Thin small/micro-caps |

These passed the ₹50L liquidity and anti-manipulation filters at selection time and still turned out to be thin or fatal. **A capacity number that assumes they won't appear is wishful.** Because we may not change the universe rules (Phase 3B constraint), we must size capacity to the rules *as written* — i.e., to a book that can contain a ₹50L-ADTV name at 10% weight.

**Headline capacity numbers (Top-10, frozen rules):**

| Tier | Deployable Capital | Basis |
|---|---|---|
| **Conservative** | **₹50 L** | A 10% position is exitable in ~1 session at 10% participation even if the thinnest name sits at the ₹50L ADTV floor |
| **Reasonable** | **₹2.5–3 Cr** | Assumes the book's *thinnest* name is ≈ ₹2–3 Cr ADTV (typical, not guaranteed) and accepts a 3-session exit at 15% participation |
| **Aggressive** | **₹5 Cr** | Requires every name ≥ Tier-1-ish (₹5 Cr ADTV) and a 5-session exit at 20% participation — i.e., a *favourable* book, not a worst-case one |
| **Audit's ₹10 Cr** | **Rejected** | Only defensible if the universe rule is tightened to a Tier-1 floor — which is *out of scope* for the frozen strategy |

**Recommended Maximum Deployable Capital: ₹3 Cr** (hard cap), and **treat even that as unproven until demonstrated** across at least 4 live rebalances with realized-cost reconciliation. See §6.

---

## 1. Method & Reference Liquidity Buckets

Position size (Top 10, equal weight) = **Capital ÷ 10**. Participation rate = position value ÷ name ADTV (i.e., what fraction of one average day's turnover the position represents).

Because the frozen book mixes liquidity profiles, every capital level is scored against **three reference names that actually occur in the strategy's history**:

| Bucket | Representative real holdings | Assumed ADTV | Role |
|---|---|---|---|
| **Floor name** | the ₹50L filter minimum; realized analogues: THEBYKE, RAJTV, SBC tail | **₹50 L** | Worst *qualifying* name — the binding constraint |
| **Typical-tail name** | FIEMIND, RELAXO(early), KAJARIACER, CHOICEIN | **₹2 Cr** | The thinnest name in a *normal* book |
| **Liquid large-cap** | LT, ICICIBANK, MARUTI, TCS, ITC, HINDUNILVR, M&M, TITAN | **≥ ₹50 Cr** | The easy majority of the book |

Execution norms used as thresholds (industry-standard for delivery equity):
- **≤ 10% of ADTV/day = comfortable**, **10–20% = workable with care**, **>20% = footprint/impact territory**, **>100% = multi-day, market-moving, often un-exitable in stress.**

Cost-model reference (from [cost_model.py](costs/cost_model.py)): round-trip statutory+broker ≈ **0.18%**; slippage **0.05% / 0.10% / 0.20%** per side by tier; impact term engages above **1% of ADTV** as `value × 0.001 × √(participation/1%)`. **Note:** that √-impact term returns a finite, comforting number even at 500–2000% of ADTV — in reality those fills don't exist. The model **understates** deep-illiquidity cost and must not be trusted past ~15–20% of ADTV.

---

## 2. Per-Capital-Level Analysis

### ₹5 L — position ₹50,000
1. **Position size:** ₹50,000 / name.
2. **Liquidity utilization:** Floor name 10% of ADTV; typical-tail 0.25%; large-cap negligible.
3. **Participation rate:** ≤10% even on the worst qualifying name → 1-session exit everywhere.
4. **Slippage sensitivity:** Tier-driven only (0.05–0.20%). Already in net backtest. No marginal impact.
5. **Impact cost:** Below the 1%-of-ADTV trigger on all but the floor name; negligible.
6. **Execution practicality:** Trivial. Whole-share rounding on a ₹3,000+ share is the *only* friction (±a few % weight error on one name); fixed ₹20 + ₹15.93 DP ≈ 0.07% of trade.
7. **Exit risk in stress:** None meaningful — can liquidate the entire book in one session.
8. **Rebalance complexity:** Single-clip market/limit orders; ~38% quarterly turnover → ~4 names traded/quarter.
**Verdict: OPTIMAL.**

### ₹10 L — position ₹1,00,000
1. ₹1,00,000 / name.
2. Floor name 20% of ADTV; typical-tail 0.5%; large-cap negligible.
3. ~20% participation on a floor name → needs a 2-session split; ≤1 day everywhere else.
4. Slippage unchanged from model.
5. Impact: engages only on a floor-tier name; minor.
6. Practical; rounding noise halves vs ₹5 L.
7. Floor name would need 2 sessions to exit in stress; rest instant.
8. Low.
**Verdict: OPTIMAL (watch the single thinnest name).**

### ₹25 L — position ₹2,50,000
1. ₹2,50,000 / name.
2. Floor name **50%** of ADTV; typical-tail 1.25%; large-cap negligible.
3. 50% participation on a floor name = multi-session, visible. Typical-tail fine (~1 day).
4. Slippage as modeled for the liquid majority; the floor name will slip beyond the model.
5. Impact engages on floor and (barely) typical-tail names.
6. Practical for 9 of 10 names; the thinnest is the problem child.
7. Stress exit of a floor name: 3–5 sessions.
8. Low–moderate.
**Verdict: COMFORTABLE, provided no near-floor name is held; otherwise one position is hard to move.**

### ₹50 L — position ₹5,00,000
1. ₹5,00,000 / name.
2. Floor name **100% of ADTV** (a full day's volume); typical-tail 2.5%; large-cap negligible.
3. A floor name = one entire trading day at 100% participation → realistically 5–10 sessions to enter/exit responsibly. Typical-tail comfortable.
4. Floor-name slippage materially exceeds the 0.20% Tier-3 model assumption.
5. Impact on floor name is large and **understated** by the √-model.
6. **First level where a single holding can be genuinely hard to trade.** 9/10 names still easy.
7. **Stress exit of a floor name becomes the dominant risk** — a full-ADTV position into a falling, thinning market.
8. Moderate — may need to stage the thinnest name over multiple sessions.
**Verdict: CONSERVATIVE CEILING.** Safe *only* because at this size even a worst-case floor name is "one day's volume," still exitable (slowly) in normal markets. Breaks in stress (see §3).

### ₹1 Cr — position ₹10,00,000
1. ₹10,00,000 / name.
2. Floor name **200% of ADTV** (two full days); typical-tail **5%**; large-cap ~0.2%.
3. Floor name: ~10–20 sessions to exit at 10% participation — *not practically tradeable*. Typical-tail ~5% (1 session, fine). Large-caps trivial.
4. For a typical book (no floor name): slippage ≈ model. For a book containing a floor/near-floor name: that one line slips badly and the model lies.
5. Impact on a ₹2 Cr typical-tail name ≈ 0.22% (model); on a floor name, catastrophic and un-modellable.
6. **Tradeable only if the book happens to hold no near-floor name that quarter — which the frozen rules do not guarantee.**
7. A floor name at ₹1 Cr capital is effectively a *trapped* 10% of NAV in stress.
8. Moderate–high; requires per-name liquidity screening before each rebalance.
**Verdict: REASONABLE-CAPACITY EDGE.** Acceptable *expected-case*, but exposed to a single thin selection. This is the level where capacity stops being "fine" and becomes "fine if lucky with the book."

### ₹5 Cr — position ₹50,00,000
1. ₹50,00,000 / name.
2. Floor name **1,000% of ADTV** (ten days' volume — un-tradeable); typical-tail **25%**; large-cap ~1%.
3. Typical-tail name at 25% of ADTV = 3–5 sessions at responsible participation, with real impact. Floor name = impossible. Large-caps fine.
4. Even *typical* thin names now slip beyond model; impact term engaged on ~half the book.
5. Impact on a ₹2 Cr name: model ≈ 0.5% per side; realistically higher. On any near-floor name: total.
6. **Requires staged, multi-session execution and active liquidity screening every rebalance.** A Tier-1-only book is *assumed*, not enforced.
7. Stress exit of the thinner half of the book takes a week+ and moves prices. This is where a 2020-style event becomes a capacity *crisis* (§3).
8. **High.** No longer a one-morning task; needs an execution plan per name.
**Verdict: AGGRESSIVE CEILING.** Defensible only under a favourable (effectively Tier-1) book and disciplined multi-day execution. Not safe under the frozen rules' worst case.

### ₹10 Cr — position ₹1,00,00,000
1. ₹1,00,00,000 / name.
2. Floor name **2,000% of ADTV**; typical-tail **50%**; large-cap ~2%.
3. Typical-tail name at 50% of ADTV = 5–10 sessions, heavy footprint, front-running risk. Floor name = un-exitable. Only the large-cap core (5–7 names) is comfortable.
4. Slippage/impact materially above model across the thinner third-to-half of the book.
5. Impact on a ₹2 Cr name: model ≈ 0.71%/side (≈1.4% round trip) — and that's the *optimistic* model. Reality worse.
6. **Not practical under frozen rules.** Would require a Tier-1 ADTV floor (a universe-rule change, forbidden in scope) plus algorithmic execution.
7. In stress, half the book is illiquid simultaneously → forced-liquidation losses far exceed the −33.5% backtest MaxDD assumption (which assumed clean fills).
8. **Severe.** Institutional execution desk territory for a 10-name retail-style book.
**Verdict: REJECTED for the frozen strategy.** The audit's ₹10 Cr presumed a liquidity profile the frozen ruleset does not deliver.

---

## 3. Stress Scenarios

Capacity is a *normal-market* number; stress is where it gets tested. Each scenario is mapped to the capital level at which it becomes dangerous.

### 3.1 — 2020-style crash (March-2020 analogue)
- **Mechanism:** ADTV collapses 40–70% market-wide *exactly* when a quarterly rebalance may force selling. The ₹50L/₹2Cr ADTV figures used above were measured in calm markets; halve them.
- **Effect by level:** ≤₹50 L: still exitable. ₹1 Cr: the thinner half of the book doubles in days-to-exit. ₹5 Cr+: the book becomes partially frozen; you sell what you can (large-caps) and are stuck with the thin tail at the worst possible price.
- **Note:** the strategy's own history shows Mom+LowVol *held through* 2020 (+18% that year) rather than rebalancing into the crash — but that is luck of the rebalance calendar, not a control.
- **Capacity verdict:** halve every normal-market capacity number for crash robustness → reinforces a **₹2.5–3 Cr** practical ceiling.

### 3.2 — Low-liquidity regime (prolonged, e.g. 2018–19 small/mid-cap drought)
- **Mechanism:** Sustained ADTV compression in small/mid-caps — precisely where the LowVol tilt can fish. Names that passed the ₹50L filter at selection drift below it while held.
- **Effect:** A name can become a Tier-3/floor name *after* you own it. At ₹1 Cr+ this strands a 10% position for an entire quarter.
- **Capacity verdict:** the ₹50L floor is a *selection-time* test, not a *holding-period* guarantee → another reason the binding constraint is worst-case, not average.

### 3.3 — Gap-down event (single-name −20%+ on results/news)
- **Mechanism:** No stop-loss in the frozen design (intentional). A 10% position gapping −20–40% is an instant 2–4% NAV hit; if it locks lower-circuit, you cannot exit at any size.
- **Effect:** Capital-independent in % terms, but at higher capital the *rupee* loss and the inability to exit a large position compound.
- **Capacity verdict:** argues for AUM the investor can absorb a single −3–4% NAV shock on, repeatedly. Orthogonal to liquidity capacity but caps psychological capacity.

### 3.4 — Single-stock suspension (the ZYLOG / NET4 case — *this actually happened in the book*)
- **Mechanism:** A held name is suspended/delisted. The 10% position becomes unsellable at any price. **The strategy demonstrably selected two names (ZYLOG, NET4) that met this fate.**
- **Effect:** Capital-independent in % of NAV (always ~10% at risk), but the larger the book the larger the absolute write-off, and the harder to have diversified the residual risk.
- **Capacity verdict:** this is a *concentration/delisting* risk, but it interacts with capacity: at ₹5–10 Cr you cannot even attempt a pre-suspension exit on a thin name because the exit itself is multi-day. Smaller AUM = a fighting chance to get out on the first warning.

### 3.5 — Forced liquidation (redemption / margin / personal need)
- **Mechanism:** Must liquidate the *entire* book in a compressed window (days), not on the rebalance schedule.
- **Effect by level:** ≤₹50 L: 1–2 sessions, modest extra slippage. ₹1 Cr: 3–5 sessions if a thin name is held. ₹5 Cr: 1–2 weeks, material impact on the thin half. ₹10 Cr: the thin tail may be effectively un-liquidatable in any reasonable window → fire-sale losses.
- **Capacity verdict:** this is the **hardest** test and the one most ignored. Define deployable capacity as *"capital I could fully exit in 5 trading days without moving prices >1%"* and the answer is ~**₹2–3 Cr** under frozen rules.

---

## 4. Capacity Breakpoints

| Capital | What changes at this point |
|---|---|
| **≤ ₹50 L** | Frictionless. Even a worst-case ₹50L-ADTV name is ≤1 day's volume. **Conservative ceiling.** |
| **₹50 L → ₹1 Cr** | First level where a *single* near-floor name becomes hard to trade (100% → 200% of its ADTV). Capacity becomes "fine if the book is clean." |
| **~₹1 Cr** | **Reasonable-capacity edge.** Typical-tail names still ≤5% of ADTV; risk is isolated to the occasional thin selection. Requires per-rebalance liquidity screening. |
| **₹1 Cr → ₹3 Cr** | Typical-tail names climb to 5–15% of ADTV. Multi-session execution becomes standard. **Recommended hard cap sits at ~₹3 Cr.** |
| **~₹5 Cr** | **Aggressive ceiling.** Typical-tail at 25% of ADTV; impact engaged on half the book; only safe with a Tier-1 book + staged execution. Stress = capacity crisis. |
| **> ₹5 Cr** | Requires changing the universe rule to a Tier-1 ADTV floor (out of scope) and/or widening beyond 10 names (strategy change). Not supported. |
| **₹10 Cr** | **Rejected** for the frozen strategy. |

---

## 5. Failure Modes

1. **Thin-name trap (primary).** Equal-weight forces 10% into the book's least-liquid name; at ₹1 Cr+ that position can exceed a full day's ADTV and become un-exitable. *Evidenced by THEBYKE, RAJTV, SBC, ZYLOG, NET4 in the actual book.*
2. **Selection-time liquidity ≠ holding-period liquidity.** The ₹50L filter is checked once, at selection; a name can dry up mid-quarter (low-liquidity regime) and strand capital.
3. **Cost-model false comfort.** The √-impact term yields finite numbers at 100–2000% of ADTV where reality is "no fill / large price move." Backtested *net* returns at high AUM are therefore **optimistic**, masking the true capacity wall.
4. **Stress correlation of illiquidity.** In a 2020-style event the thin half of the book becomes illiquid *simultaneously*, so the −33.5% backtest MaxDD (which assumes clean fills) understates realized stress drawdown at scale.
5. **Suspension/delisting at scale.** A ZYLOG/NET4 event writes off ~10% of NAV; at ₹5–10 Cr you cannot pre-empt it because the exit itself is multi-day.
6. **Footprint / information leakage.** At ₹5 Cr+, repeated quarterly trading of 25–50% of a thin name's ADTV is detectable and front-runnable, degrading fills beyond any model.
7. **Whole-share rounding (low end, benign).** Below ~₹5 L, high-priced shares cause weight error — a precision issue, not a capacity wall.

---

## 6. Recommended Maximum Deployable Capital

**₹3 Cr — hard cap — and unproven until demonstrated.**

Rationale:
- It is the largest AUM at which the *worst plausible book under the frozen rules* (a thinnest name around ₹2 Cr ADTV) can still be **fully liquidated in ≈5 trading days without moving prices >1%** — the forced-liquidation test (§3.5), the strictest one.
- It keeps the typical-tail name at ≤15% of ADTV in normal markets and ≤30% in a halved-liquidity crash — inside "workable with care."
- It does **not** rely on changing the universe rule to a Tier-1 floor (forbidden in scope). It tolerates the strategy's demonstrated habit of occasionally picking thin names.

**Tiered recommendation:**

| Use case | Capital | Conditions |
|---|---|---|
| Prove-out / pilot | **≤ ₹50 L** | No conditions. Run ≥4 live rebalances; reconcile realized cost & slippage vs. model. |
| Standard deployment | **₹50 L – ₹1 Cr** | Per-rebalance liquidity screen; flag any name <₹2 Cr ADTV. |
| Maximum | **₹1 Cr – ₹3 Cr** | Staged multi-session execution; mandatory pre-trade liquidity check; accept that one thin name per quarter may be hard to move. |
| Beyond ₹3 Cr | **Not recommended** | Would require a universe-rule change (Tier-1 floor) or >10 names — both out of scope. Re-audit required. |

**Why "unproven until demonstrated":** every number here is derived from the *modeled* cost stack and *assumed* ADTV buckets. The cost model is optimistic past ~15% of ADTV, and the only honest validation is live execution. **Treat ₹3 Cr as a ceiling to approach, not a target to start at.** Begin at ≤₹50 L, measure realized slippage/impact against the model for at least four rebalances, and only scale if live costs track the model.

---

## 7. Verdict vs. the Audit

| Question | Audit (Phase 3A) | This analysis (Phase 3B) |
|---|---|---|
| Capacity ceiling | ₹10 Cr (with an *added* Tier-1 floor) | **₹3 Cr under frozen rules; ₹5 Cr only with a favourable Tier-1 book** |
| Binding constraint | Average book liquidity | **Thinnest name in the book (equal-weight × ₹50L floor)** |
| Key evidence | Reasoned from large-cap assumption | **Actual holdings: ZYLOG, NET4, VAKRANGEE, THEBYKE held** |
| ₹10 Cr status | "Soft ceiling, cap here" | **Rejected without a universe-rule change (out of scope)** |

The audit's ₹10 Cr was conditional on *"enforce a Tier-1 ADTV floor."* That condition is a **universe-rule change**, which Phase 3B forbids. Holding the strategy exactly as frozen, the honest, evidence-based ceiling is **₹3 Cr**, proven only as far as live execution demonstrates it.

---

*Analysis only. No code produced. Strategy, universe rules, factors, and parameters unchanged. ADTV buckets are reasoned estimates against real holdings; all capacity figures are modeled and must be validated live before scaling.*
