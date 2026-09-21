# Research Program #2 — High-CAGR Discovery: Consolidated Findings

**Status:** price-testable search space EXHAUSTED (2026-07-06). Architecture-comparison stage unlocked.
**Charter:** `RESEARCH_PROGRAM_2_CHARTER.md` · **Track-2 design:** `RESEARCH_PROGRAM_2_TRACK2_DESIGN.md`

Objective: can a long-only, no-leverage, no-hindsight, no-curve-fit strategy on the full NSE/BSE
universe earn materially higher **robust** CAGR than the frozen ~17.4% Mom+LowVol champion?
Every experiment judged on six pre-registered gates (CAGR>17.4%, Sharpe≥0.69, MaxDD≥−38.5%, no
split-sample sign-flip, survives ×5/×10 slippage stress, rolling-3y-min CAGR>0), survivorship-free
bhavcopy, net of the full Indian cost model. Benchmarks were held constant; nothing was tuned to pass.

---

## 1. The family map (genuinely independent return drivers)

"Independent" = a distinct, lowly-correlated return mechanism — not a variant, sizing rule, or
universe tilt. Despite ~25 experiments across both programs, only a handful of true families exist.

| Family | Status | Best result | Verdict |
|---|---|---|---|
| **Momentum** (12-1, cross-sectional) | tested | champion offense | Works — the return engine |
| **Low-volatility / BAB** | tested | Sharpe 0.69 blend | Works — the defense leg |
| Trend-following (time-series) | tested | null overlay | Correlated cousin of momentum; no alpha |
| **Short-term reversal / pullback (2C)** | tested | gross +26.8% / net −38.6% | Real GROSS edge, **cost-killed** net |
| **Event-driven / PEAD proxy (2E)** | tested | −0.10 Sharpe | Negative; price proxy ≠ earnings surprise |
| **Seasonality / calendar (2F)** | tested | TOM raw spread +39% | Timing family; can't beat CAGR long-only |
| **Volatility-expansion / squeeze (2D)** | tested | −0.14 Sharpe | Negative; fixed-hold exit hurts |
| Value (E/P, B/M) | **data-gated** | — | Highest evidence; needs PIT fundamentals |
| Quality / profitability | **data-gated** | — | Framework built; needs PIT fundamentals |
| True PEAD (earnings dates) | **data-gated** | — | Needs announcement dates |
| Pairs / statistical-arbitrage | out of scope | — | Market-neutral, not long-only |

**Bottom line:** *no genuinely-independent non-momentum price family beats the champion net of Indian
costs.* High CAGR only comes from the momentum family. The only unexplored region is the data-gated
fundamentals track (Value/Quality) — a data-acquisition project, not a price experiment.

## 2. The high-CAGR candidates actually found

Two independent momentum-family expressions reach ~22%, both failing the strict gates *only on risk*:

| Candidate | Net CAGR | Sharpe | MaxDD | Gate status |
|---|---|---|---|---|
| Champion — Mom+LowVol Top-500 qtrly | 17.4% | 0.69 | −33% | **passes all six** |
| Small-cap-tail Mom+LowVol (Exp 1) | **21.8%** | **1.02** | −34.8% | 5/6 — fails roll-3y-min (−6.3%) |
| Breakout monthly, Top-500 (2B) | **22.8%** | 0.66 | −40.6% | fails Sharpe, DD, roll-3y-min |

~22% is reachable from *two independent mechanisms* → it's a real, repeatable ceiling, not a mirage.
Each pays for it with more cyclicality than the champion. **50–60% is nowhere in the data** (charter
prediction confirmed).

## 3. Cross-cutting lessons

1. **Volume surges mark exhaustion, not conviction** — confirmed twice (2B volume filter *hurt* −2.6%;
   2E gap+volume gave negative alpha). Do not build "volume-confirmation" long entries on this market.
2. **Fixed-hold event execution < rank-rebalance** — the same momentum-cousin signal earned +22.8%
   in the rank engine (2B) but −1.4% in the 40-day-clock event engine (2D). The exit rule dominated.
3. **The pullback population fix worked** — buying dips in *winners* (2C) has strong gross alpha,
   unlike raw reversal (negative even gross). Costs, not signal, killed it.
4. **Turn-of-month is huge** — ~19% of days carry ~50% annualized vs ~8–12% the rest; not harvestable
   standalone, but a real risk-timing fact.
5. **The impact-aware capacity test matters** — the frozen engine silently disables impact cost; the
   small-cap tail only proved scalable (₹1L→₹50L) once impact was actually modeled.

## 4. The architecture comparison — RESULT (`run_program2_ensemble.py`)

Sleeve daily-return correlations: A/B 0.62, A/C 0.59, B/C 0.58 — only **moderate** (all momentum
family), so blending smooths risk but cannot fully diversify a shared driver.

| Architecture | CAGR | Sharpe | MaxDD | roll-3y-min | Gate status |
|---|---|---|---|---|---|
| A champion (Top-10 shell) | 16.5% | 0.66 | −33.0% | **+1.8%** | fails CAGR/Sharpe (this shell) |
| B smalltail | 21.8% | 1.02 | −34.8% | −6.3% | fails roll-3y-min only |
| C breakout-monthly | 22.8% | 0.66 | −40.6% | −3.7% | fails Sharpe/DD/roll-3y-min |
| **B+C 50/50** | **22.9%** | 0.92 | −37.0% | −4.6% | fails roll-3y-min only |
| **A+C 50/50** | 20.2% | 0.77 | −33.8% | **−0.6%** | fails roll-3y-min only |
| A+B 50/50 | 19.4% | **0.95** | −30.4% | −2.0% | fails roll-3y-min only |
| A+B+C ⅓ | 21.0% | 0.92 | −33.2% | −2.3% | fails roll-3y-min only |

**The whole program reduces to one binding constraint.** Every architecture above ~17% fails *only*
the "never a losing 3-year window" gate. Blending clearly *improves* it (B −6.3% → A+C −0.6%) but
cannot cross zero at ~0.6 correlation. The frozen champion (~17.4% in its Top-5 shell, roll-3y-min
+2.4%) is the sole all-gate product. **The ensemble does not "win" outright, but it is a genuine risk
smoother** — A+C reaches 20.2% at a −0.6% worst-3-year window (vs the champion's +2.4%).

## 5. Conclusion & the production-architecture decision

The market offers **~20–23% CAGR from the momentum family, but always with at least one mildly-negative
3-year stretch.** Requiring zero losing 3-year windows caps the honest number at **~17%**. This is a
**risk-preference decision**, now made on evidence:

| Choice | Product | Profile |
|---|---|---|
| Never a losing 3-yr window | **Champion** (Mom+LowVol Top-5 qtrly) | ~17.4%, Sharpe 0.69, all six gates |
| Best return/robustness balance | **A+C** (champion + breakout-monthly) | 20.2%, Sharpe 0.77, worst-3yr −0.6% |
| Highest Sharpe | **A+B** (champion + small-cap-tail) | 19.4%, Sharpe 0.95, worst-3yr −2.0% |
| Highest CAGR | **B+C** (small-cap-tail + breakout) | 22.9%, Sharpe 0.92, worst-3yr −4.6% |

**The only remaining source of a genuinely new, independent edge is the data-gated fundamentals track
(Value/Quality)** — a separate data-acquisition project, the single avenue that could lift the ceiling
without accepting more cyclicality.

**SCOPE CORRECTION (peer-review audit, 2026-07-06).** An earlier phrasing — "50–60% was a mirage" — is
an OVERSTATEMENT and is **withdrawn**. The evidence supports only: *within the strategy families tested,
no robust 50–60% CAGR strategy was found.* All experiments used a **single data source** (daily
price/volume), covering ~5 distinct mechanisms — roughly **20–25% of the long-only design space.** The
highest-evidence families (fundamentals: value, quality), true event-driven strategies with real
announcement data, alternative datasets, and intraday microstructure were **not tested.** The ≈17–22%
figure is the ceiling **of the price/volume-derivable families on this market/sample (2012–2026)**, not a
proven bound on the whole long-only space. What *is* evidenced: the specific 50%+ backtest numbers seen
earlier were artifacts of survivorship/fillability bias. Confidence: ~85% in the tested-family ceiling;
only ~30% that ≈22% bounds the overall long-only space (we did not test the regions most likely to exceed
it). See `RESEARCH_PROGRAM_2_PAPER_PROTOCOL.md` and the Part-2 audit. Program #2's *price-derivable*
question is CLOSED; the broader-data question is OPEN and out of scope.
