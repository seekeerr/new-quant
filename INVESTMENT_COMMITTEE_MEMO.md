# INVESTMENT COMMITTEE MEMO

**Subject:** Systematic Indian-equity momentum program — final decision on capital deployment
**Strategy (frozen):** Momentum + LowVol · Top 10 · Quarterly · Buffer 20 · Equal Weight · Equity-only · Survivorship-free · Cash-only
**Frozen commit:** `8f0482f` · **Tag:** `price-only-final`
**Date:** 2026-06-24
**Status of program:** Research **complete and frozen**. Production audit, capacity analysis, live-trading architecture, paper-trading protocol, dashboard, and first dress rehearsal all complete.
**Classification:** Definitive program record + deployment decision.

**Sources:** [PHASE1_FINAL_REPORT.md], [PHASE1_DECISION.md], [RESEARCH_TIMELINE.md], [PRICE_ONLY_FINAL_CONCLUSION.md](PRICE_ONLY_FINAL_CONCLUSION.md), [PRODUCTION_READINESS_AUDIT.md](PRODUCTION_READINESS_AUDIT.md), [CAPACITY_ANALYSIS.md](CAPACITY_ANALYSIS.md), [LIVE_TRADING_ARCHITECTURE.md](LIVE_TRADING_ARCHITECTURE.md), [PAPER_TRADING_PROTOCOL.md](PAPER_TRADING_PROTOCOL.md), [DASHBOARD_VALIDATION_REPORT.md](DASHBOARD_VALIDATION_REPORT.md), [REHEARSAL_REPORT.md](REHEARSAL_REPORT.md), [OPERATIONAL_GAP_ANALYSIS.md](OPERATIONAL_GAP_ANALYSIS.md).

---

## 1. Executive Summary

The program set out to find, validate, and prepare for deployment a systematic equity strategy on the NSE / NIFTY 500. It succeeded in producing **one real, honestly-validated edge** and, just as importantly, in **disproving** a long list of plausible alternatives and **demolishing** its own early, inflated results once the data was cleaned.

**The recommendation of this committee is Option B — Deploy After Paper-Trading Program.**

The case in brief:

- **The edge is real and survives honest testing.** The champion — 12-1 momentum (offence) paired 50/50 with low realised volatility (defence) — delivers a **net 17.4% CAGR, Sharpe 0.69, −33.5% max drawdown** over 2012–2026 on a survivorship-free, cost-netted, benchmark-validated basis. It beat the NIFTY 500 (13.6% price / ~14.9% TRI) with **+5.4% Jensen alpha** and **never had a losing rolling-3-year window** (min +2.4%).
- **The headline number is not the investor number.** Net-of-tax (STCG 20% / LTCG 12.5%) the realistic figure is **~13–15% CAGR**, not 17.4%. This must anchor all expectations.
- **The danger is realization risk, not alpha decay.** The four risks worth losing sleep over — concentration (10% per name, no stop-loss), corporate actions, tax, and single-operator execution — are all "the live account ≠ the backtest" risks, not "the strategy is overfit" risks.
- **The compute is production-grade; the operational wrapper is not yet.** The first dress rehearsal regenerated a full trade list **bit-identically** across runs, and the read-only monitoring dashboard passed validation. But the controls that make *live* trading safe under stress — enforced approval, corporate-action handling, backup data, broker reconciliation, alert delivery — are **documented but not yet enforced in tooling**.
- **Capacity is comfortable at the proposed size.** Start at **≤ ₹5 L**, hard cap **₹3 Cr** under the frozen rules.

Deploying *today* with real capital would be premature; abandoning the strategy would discard a genuine, hard-won edge. The disciplined path — explicitly built into the program's own design — is to run the **paper-trading program (≥2, target 3–4 live quarterly rebalances)** to close the operational gaps and prove live cost/slippage tracks the model, then deploy real capital on a clean Go/No-Go pass.

---

## 2. Research History

A chronological program (full detail in [RESEARCH_TIMELINE.md](RESEARCH_TIMELINE.md)), summarized:

1. **Initial momentum research.** Pure 12-1 momentum (Jegadeesh-Titman) stood up on an early universe — a real but crash-prone signal showing ~30–47% CAGR.
2. **Bias discovery & migration.** A fallback-universe bug and survivorship bias were found. Migrated to the full daily NSE **bhavcopy** cross-section, corp-action adjusted → a survivorship-free universe.
3. **Honest re-validation.** Re-run on clean data, the ~30–47% CAGRs **collapsed** to ~17–18% — exposed as survivorship-bias mirages.
4. **Contamination & benchmark fixes.** ETF/fund units were purged (equity-only ISIN `INE` whitelist → 3,291 names); a benchmark date-parse bug that faked +12% alpha was repaired.
5. **Construction sweeps.** Buffer-20 adopted (turnover control, no alpha cost); Top10 chosen (concentration *hurts* on clean data).
6. **The one success — Low-Vol blend.** Pairing momentum with low volatility lifted Sharpe 0.41 → 0.69 and halved drawdown. **Became the champion.**
7. **Exhaustive failure of alternatives.** Smart/residual momentum, 52-week-high, Low-MAX, Frog-in-the-Pan, trend overlays, vol-targeting, leverage, mean reversion, and four weighting schemes were each tested and **closed**.
8. **Program close.** The price-only search space was declared exhausted; the champion was frozen (`8f0482f` / `price-only-final`). Production audit, capacity, architecture, protocol, dashboard, and rehearsal followed.

---

## 3. Major Data-Quality Discoveries

The single most important finding of the program is methodological: **its three biggest early "edges" were all data bugs.** Per [PRICE_ONLY_FINAL_CONCLUSION.md §4](PRICE_ONLY_FINAL_CONCLUSION.md) and [RESEARCH_TIMELINE.md]:

| # | Discovery | Before (corrupt) | After (honest) | Lesson |
|---|---|---|---|---|
| 1 | **Survivorship bias** — biased / fallback universes only contained survivors | ~47% (biased-500), ~26–49% (fallback) CAGR | **~17–18% CAGR** | The headline edge was a mirage; honest universe is non-negotiable. |
| 2 | **ETF / fund contamination** — bhavcopy pool held ETF/gold/liquid/index units (ISIN `INF`, `IN9`) whose structural low-vol polluted rankings | inflated low-vol edge | equity-only 3,291-name pool | Audit *instrument type*, not just price. |
| 3 | **Benchmark date-parse flip** — a `dayfirst/mixed` bug flipped 1,379 / 3,817 rows | 77% benchmark vol, beta≈0, **+12% fake alpha** | vol 16%, beta 0.74, **+5.4% real alpha**, bmk CAGR 13.6% | Alpha/beta are worthless until the benchmark parses correctly. |

**Corollary discovery: effects flip *sign* on clean data.** In the biased universe, concentration looked great and mean-reversion looked plausible; on honest data both are destructive. Direction, not just magnitude, was wrong. This is why pre-registration, split-sample, and rolling-window discipline were retained throughout.

---

## 4. Experiments Conducted

Nineteen experiments (full table in [PRICE_ONLY_FINAL_CONCLUSION.md §1](PRICE_ONLY_FINAL_CONCLUSION.md)). Verdict key: **PASS** = improved risk-adjusted return on a pre-registered bar · **FAIL** = did not · **NULL** = changed risk shape only · **FIX** = data-hygiene correction.

| Track | Experiments | Outcome |
|---|---|---|
| Data hygiene | Survivorship migration · ETF removal · benchmark repair | **3× FIX (critical)** |
| Momentum variants | Pure 12-1 (base) · residual/"smart" · 52-week-high · Low-MAX · Frog-in-the-Pan | base kept; **all refinements FAIL** |
| Volatility | **Mom + LowVol** · Low-Vol only · vol-managed (Barroso) · leverage 1.25–2× | **LowVol blend PASS → champion**; rest NULL/FAIL |
| Trend | Price-vs-EMA exposure gate | **NULL** |
| Mean reversion | Short-term reversal (Top3/5/10, monthly/quarterly) | **FAIL (catastrophic)** |
| Construction | Buffer 10/15/20 · concentration Top3/5/10 · EW/InvVol/ERC/MinVar | **Buffer20 + Top10 + EW adopted; weighting FAIL/NULL** |

**Only two PASS-shaped outcomes:** the Low-Vol blend (a real risk-adjusted win) and Buffer-20 (turnover control at no alpha cost). Everything else failed or merely re-shaped risk.

---

## 5. Champion Strategy

**Signal:** `0.5 × percentile(12-1 momentum) + 0.5 × percentile(low 252-day realised vol)`, selected Top 10, equal weight (10% each), quarterly rebalance, Buffer-20 hysteresis, equity-only, survivorship-free, **cash-only (no leverage)**.

**Validated performance** (net of the full Indian delivery cost model; 2012-01 → 2026-05; fixed benchmark — [PRICE_ONLY_FINAL_CONCLUSION.md §3](PRICE_ONLY_FINAL_CONCLUSION.md)):

| Metric | Value | Metric | Value |
|---|---|---|---|
| CAGR (net) | **17.4%** | Sharpe | **0.69** |
| CAGR (gross) | 18.2% | Sortino | 0.88 |
| Max Drawdown | **−33.5%** | Calmar | 0.52 |
| Annual Vol | 15.7% | Beta | 0.74 |
| Alpha (Jensen) | **+5.4%** | Excess vs benchmark | +3.8% |
| Turnover / rebalance | 41.9% | Cost drag | 0.79 pts |
| Time underwater | 85.4% | Txn costs (life) | ~₹2.15 L |
| **Rolling 3-yr CAGR** | **min +2.4% · median +22.6% · max +36.3% — never a losing 3-yr window** | | |

**Why it works:** it is an **offence + defence *pairing*, not a single factor.** Momentum is the return engine; low-vol is the risk reducer; the two legs are lowly correlated and do different jobs. That is precisely why every attempt to add a *second* defensive factor or a *redundant* offensive one failed (Section 6).

---

## 6. Why Alternative Strategies Failed

Per [PRICE_ONLY_FINAL_CONCLUSION.md §2](PRICE_ONLY_FINAL_CONCLUSION.md). Headline scoreboard (Top10/quarterly/Buffer20, net):

| Variant | CAGR | MaxDD | Sharpe | Why it failed |
|---|---|---|---|---|
| **Mom + LowVol (CHAMPION)** | **17.4%** | **−33.5%** | **0.69** | — (the success) |
| Pure Momentum | 18.1% | −56.3% | 0.41 | real, but crash-prone; the blend tames it |
| Residual-Mom + LowVol | 16.2% | −27.2% | 0.68 | smoother but **not higher** — no Sharpe/CAGR gain |
| FIP + LowVol | 15.3% | −29.4% | 0.59 | closest near-miss, but **split-sample sign-flipped** (fragile/regime-dependent) |
| Low-MAX + LowVol | 11.8% | −26.0% | 0.45 | **defence-on-defence** — gives up the return engine |
| 52WH + LowVol | 9.1% | −28.9% | 0.19 | **redundant** — low-vol names already sit at highs; degenerates to low-vol-only |

- **Smarter momentum is a dead end.** Residual, 52WH, Low-MAX, FIP all tried to be a better offensive leg; none beat plain 12-1.
- **Risk overlays ≠ alpha.** Trend filter, vol-targeting (Barroso), and re-weighting (InvVol/ERC/MinVar) move risk around but don't raise the engine's Sharpe; the Top10 is already low-vol-filtered, leaving nothing for risk-weighting to exploit.
- **Leverage was rejected by decision.** 1.25–2× raises CAGR but **lowers Sharpe** (0.71→0.60) and deepens drawdowns; a 30% target would need ruinous ~2.5×+. **Cash-only** is a committed constraint, capping the honest ceiling at ~17–18%.
- **Mean reversion failed catastrophically.** Naïve long-only short-term reversal loaded on falling knives / distressed high-beta micro-caps: best config Sharpe **−0.20, MaxDD −82%, alpha −13.6%**, negative even gross.

---

## 7. Risk Assessment

From [PRODUCTION_READINESS_AUDIT.md §2–4](PRODUCTION_READINESS_AUDIT.md). The strategy's edge survives the things backtests usually kill it on (low turnover, liquid book, modeled costs). The remaining risks are **realization risks**:

**Top four (lose-sleep) risks:**

1. **Concentration (HIGH/HIGH).** 10 names, 10% each, **no stop-loss by design**. A single fraud/governance blow-up or a −30% earnings gap is an instant ~3% NAV hit; a locked circuit means no exit. The −33.5% MaxDD *will* recur and may be exceeded — it is a sample minimum, not a worst case. This concentration **is the source of the alpha**; diversifying it away is a different strategy.
2. **Corporate actions (HIGH/HIGH).** Splits/bonuses/mergers across 10 names are near-certain yearly. If the feed and broker disagree on adjustment, the momentum signal is computed on a discontinuity → wrong trade. A *data-integrity* risk masquerading as market risk.
3. **Tax (CERTAIN/HIGH).** Backtest is pre-tax. STCG 20% / LTCG 12.5% → **2–4% CAGR drag** → net-to-investor **~13–15%**. Must not be marketed on the gross number.
4. **Operational / execution (HIGH/MED).** Single operator, manual-ish process: stale-data signals, fat-finger share counts, partial fills, a missed quarter. The most probable cause of a catastrophic *realized* loss is an operational mistake, not the market.

None of these are alpha-decay risks. The audit verdict was **CONDITIONAL GO**.

---

## 8. Capacity Assessment

From [CAPACITY_ANALYSIS.md](CAPACITY_ANALYSIS.md), which **rejects the audit's ₹10 Cr** ceiling and sets a stricter, evidence-based limit.

- **Binding constraint = the *thinnest* name in the book**, not the average. Equal-weight forces 10% into the least-liquid holding. The frozen ₹50 L ADTV floor is a *selection-time* test that admits genuinely thin names — and **demonstrably did**: ZYLOG and NET4 (suspended/delisted to ~zero), VAKRANGEE (−90% circuit collapse), THEBYKE, RAJTV, SBC.
- **Recommended maximum deployable capital: ₹3 Cr (hard cap), unproven until demonstrated** across ≥4 live rebalances with realized-cost reconciliation.

| Use case | Capital | Conditions |
|---|---|---|
| **Prove-out / pilot** | **≤ ₹50 L** | None. Run ≥4 live rebalances; reconcile realized cost/slippage vs model. |
| Standard | ₹50 L – ₹1 Cr | Per-rebalance liquidity screen; flag any name < ₹2 Cr ADTV. |
| Maximum | ₹1 Cr – ₹3 Cr | Staged multi-session execution; accept one hard-to-move thin name per quarter. |
| Beyond ₹3 Cr | **Not recommended** | Requires a universe-rule change (Tier-1 floor) or >10 names — both out of scope. |

The cost model's √-impact term **understates** deep-illiquidity cost (returns finite numbers at 500–2000% of ADTV where no fill exists); high-AUM net backtests are therefore optimistic. **Start at ≤ ₹5 L.**

---

## 9. Operational Readiness

From [LIVE_TRADING_ARCHITECTURE.md](LIVE_TRADING_ARCHITECTURE.md), [DASHBOARD_VALIDATION_REPORT.md](DASHBOARD_VALIDATION_REPORT.md), [REHEARSAL_REPORT.md](REHEARSAL_REPORT.md), and [OPERATIONAL_GAP_ANALYSIS.md](OPERATIONAL_GAP_ANALYSIS.md).

**Demonstrated working (this phase):**
- **Reproducibility — proven.** The first dress rehearsal (Rehearsal 001) ran the full quarterly runbook end-to-end in 4.7 s and regenerated the trade list **bit-identically** across two runs (empty checksum diff), commit-stamped to `8f0482f`. This is the core production guarantee.
- **Determinism, Buffer-20, construction, costs** all produced a correct 10-name book (weights 8.4–10.0%) and a sane 14-order, 47.8%-turnover trade list with no HALT conditions.
- **Monitoring dashboard — validated.** All 8 read-only pages load; navigation, empty-state, missing-file, alerts, charts, and the audit viewer all PASS, with no functional bugs.

**Not yet ready (the gap):** the controls that make *live* trading safe under stress are documented but **not enforced in tooling** — the 5 Critical gaps from the gap analysis:

| ID | Critical gap |
|---|---|
| C1 | No enforced human **approval gate** (sign-off is documentation only). |
| C2 | No **backup data source** (NSE bhavcopy ingestion) — single data dependency. |
| C3 | No **corporate-action calendar / reconciliation**. |
| C4 | No **broker reconciliation** step (book vs demat). |
| C5 | No alert **delivery channel** (alerts render only in-dashboard). |

These are operational wrappers; **none touch the strategy.** They are exactly the items the paper-trading program exists to convert from 🔴 to ✅.

---

## 10. Remaining Risks (accepted / unresolved)

Per [PRODUCTION_READINESS_AUDIT.md §7](PRODUCTION_READINESS_AUDIT.md):

1. **Backtest is pre-tax** — net-of-tax CAGR structurally ~2–4% lower (~13–15%). Disclose; not fixable without becoming a different (tax-managed) strategy.
2. **No stop-loss / full concentration** — structural to the alpha; accepted via IPS sign-off, not mitigated away.
3. **−33.5% MaxDD is a sample minimum, not a worst case** — true forward worst case can exceed it.
4. **Single-operator key-person risk** — failover broker + runbook reduce, do not eliminate.
5. **Capacity > ₹3 Cr unverified** under frozen rules.
6. **Live cost/slippage assumed ≈ modeled** — validated only against the model, never against live fills. **This is the single biggest unproven assumption** and the explicit purpose of the paper-trading program.
7. **Regime dependence not stress-tested live** — the 17.4% spans one 2011–2026 path; a prolonged momentum-crash regime is in-sample but its live recurrence is an accepted unknown.
8. **Discipline-through-drawdown unproven** — if no drawdown occurs during paper trading, holding-through remains a pre-commitment (IPS), not a demonstrated behaviour.

---

## 11. Conditions for Deployment

Real capital may be deployed **only after** the paper-trading program passes its Go/No-Go ([PAPER_TRADING_PROTOCOL.md §7](PAPER_TRADING_PROTOCOL.md)) **and** the following are all true (consolidated from the audit §8 and the gap analysis):

**Operational evidence (paper program):**
- [ ] ≥ 4 Track-A rehearsals **and** ≥ 2 (target 3–4) live Track-B quarterly rebalances completed.
- [ ] ≥ 1 real corporate action and ≥ 1 injected failure drill handled correctly.
- [ ] Realized slippage tracked the model for **2 consecutive** live quarters.
- [ ] Zero open hard-fails; zero acted-on operator deviations.

**Controls enforced in tooling (Critical gaps closed):**
- [ ] C1 approval gate · C2 backup data source · C3 corp-action reconciliation · C4 broker reconciliation · C5 alert delivery.
- [ ] Hard data-freshness gate (≤ 5 trading days) and commit/config-drift hard-stop at signal time.

**Governance & sizing:**
- [ ] IPS signed: −40% drawdown possible, 10-name concentration, no stop-loss, **net-of-tax ~13–15%** (not 17.4%), pre-commitment to hold through drawdowns.
- [ ] Start capital **≤ ₹5 L**; failover broker funded and tested; CA engaged for STCG/LTCG.

**No-Go if** any of the enforced-control or governance items are skipped, the investor cannot tolerate −35–40% without intervening, or the strategy is funded on its gross CAGR.

---

## 12. Conditions for Scaling

Scaling raises **operational rigor**, not the strategy ([LIVE_TRADING_ARCHITECTURE.md §8], [CAPACITY_ANALYSIS.md §6]):

| Tier | Capital | Gate to enter |
|---|---|---|
| Pilot | ≤ ₹50 L | clean paper-program Go; first live quarter on probation |
| Standard | ₹50 L – ₹1 Cr | ≥ 4 clean live rebalances; per-rebalance liquidity screen (flag < ₹2 Cr ADTV) |
| Maximum | ₹1 Cr – ₹3 Cr | realized cost/slippage tracking the model; staged multi-session execution; formal cost reconciliation each quarter |
| > ₹3 Cr | **Not permitted** | would require a universe-rule change or > 10 names — a **strategy change**; re-open research + fresh capacity audit |

**Scaling-gate principle:** never increase AUM until the current tier has run **≥ 4 clean rebalances** with realized cost tracking the model and zero unresolved HALT incidents.

---

## 13. Final Recommendation

### Decision: **B — Deploy After Paper-Trading Program**

**Justification (evidence-based):**

- **Not A (Deploy Immediately):** The edge is validated, but the controls that make live trading safe under stress (approval gate, corp-action handling, backup data, broker reconciliation, alert delivery) are **not yet enforced**, live cost/slippage is **unproven against real fills**, and the production audit explicitly required a **paper/pilot quarter first** (CONDITIONAL GO, §8). Deploying now would expose capital to known, un-closed realization risks.
- **Not C (Further Research Required):** Research is **complete and frozen by design.** Nineteen pre-registered experiments exhausted the price-only space; the only PASS was the champion. The honest ceiling (~17–18% price-only, cash) is understood and accepted. The remaining lever (an offensive fundamental factor) is a *separate, optional* future program gated on a clean point-in-time data source — **not** a prerequisite for deploying the validated champion. More price-only research has near-zero expected payoff.
- **Not D (Do Not Deploy):** The edge is **real, honest, and hard-won** — it survived survivorship correction, contamination removal, benchmark repair, cost-netting, split-sample, and rolling-window tests, and beat the benchmark with +5.4% alpha and no losing 3-year window. Discarding it would waste a genuine result over operational gaps that are straightforward to close.
- **Therefore B:** The disciplined path — and the one the program's own architecture and protocol were built to execute — is to **run the paper-trading program** (≥ 2, target 3–4 live quarterly rebalances; ~6–12 months), which closes the Critical operational gaps, exercises the controls in anger, and proves live cost/slippage tracks the model. **Deploy real capital (start ≤ ₹5 L, hard cap ₹3 Cr) only on a clean §7 Go/No-Go pass.**

**The supporting evidence for B is already on the table:** the dress rehearsal proved the process is correct and **bit-identically reproducible**; the dashboard passed validation; the gap analysis answered the operative question — *"could a rebalance run safely and reproducibly tomorrow?"* — with **"YES, WITH CONDITIONS."** Option B is the institutional formalization of exactly those conditions.

> **One-line decision:** *Deploy after the paper-trading program — the strategy is proven, the process is reproducible, and only the live operational controls remain to be demonstrated before capital is at risk.*

---

*Memo only. No new research, factors, or optimization performed. The research program is treated as complete and frozen at commit `8f0482f` (`price-only-final`). All performance figures are taken as validated from the cited program documents.*
