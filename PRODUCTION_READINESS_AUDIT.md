# PRODUCTION READINESS AUDIT — Phase 3A

**Strategy:** Momentum + LowVol · Top 10 · Quarterly Rebalance · Buffer 20 · Equal Weight · Equity Only · Survivorship-Free Universe
**Frozen commit:** `8f0482f` · **Tag:** `price-only-final`
**Backtested performance (assumed correct):** CAGR ≈ 17.4% · Sharpe ≈ 0.69 · Calmar ≈ 0.52 · MaxDD ≈ −33.5% · Alpha ≈ +5.4%
**Audit date:** 2026-06-23
**Audit scope:** Deployability of the *frozen* strategy with real capital. No new research, no factor testing, no optimization. The backtest is taken as ground truth; everything below concerns the gap between that backtest and a live brokerage account.

---

## 1. Executive Summary

The strategy is **structurally deployable** but **not yet operationally ready**. The edge survives the things backtests usually kill it on — turnover is low (quarterly + Buffer 20), the book is liquid (Top 10 from a NIFTY 500 universe filtered to ≥ ₹50L ADTV), and transaction costs are already modeled and netted. That combination is the rare case where a backtested factor strategy can actually reach a live account without the alpha evaporating at the execution layer.

The threats that remain are **not market risks — they are realization risks**:

1. **Tax is the single largest undisclosed drag.** The backtest is almost certainly pre-tax. Indian STCG is now 20% and LTCG 12.5% (post-Budget-2024). Even with low turnover, the quarterly churn will realize gains annually. Expected drag: **2–4% of CAGR**, turning a 17.4% gross-of-tax result into roughly **13–15% net-to-investor** at the higher capital tiers. This does not make the strategy bad — it makes the headline number misleading.

2. **Concentration is severe and is the price of the alpha.** Top 10 equal-weight = 10% per name. A single blow-up (fraud, sudden delisting, gap-down on results) costs ~10% of NAV instantly, with no stop-loss in the frozen design (risk module is intentionally off — see memory: stops hurt returns). The −33.5% MaxDD is real and *will* recur. An investor who cannot psychologically hold through a −33% drawdown will liquidate at the bottom and convert paper risk into permanent loss.

3. **Capacity is comfortable to ~₹5 Cr and starts to bite by ~₹10 Cr+** — not because of the large-caps in the book, but because the **LowVol tilt can pull in lower-turnover mid-caps** whose ADTV makes a ₹50L–₹1Cr position a multi-day exit.

4. **Single-operator operational risk dominates the tail.** A solo PMS-style deployment has no four-eyes check, no failover, and a single broker dependency. The most probable cause of a catastrophic *realized* loss is not the market — it is a fat-finger rebalance, a missed corporate action, or executing on stale signal data.

**Bottom line:** This is a fundamentally sound, honestly-validated strategy whose live result will be **lower than the backtest by a predictable, quantifiable margin** (tax + the costs not in the model). It is deployable **with controls and at the right capital tier**. It is **not** deployable as a fire-and-forget black box.

**Go / No-Go:** **CONDITIONAL GO** — see §13.

---

## 2. Risk Matrix

Severity = damage if it happens. Probability = likelihood over a 3-year live horizon. Impact = expected contribution to underperformance vs. backtest.

| # | Risk | Severity | Probability | Net Impact | Residual after mitigation |
|---|------|----------|-------------|------------|---------------------------|
| 1 | Capacity / scaling | Medium | Med (capital-dependent) | Med | Low (cap AUM) |
| 2 | Liquidity | Medium | Medium | Med | Low |
| 3 | Slippage | Low–Med | High (every rebalance) | Low (modeled) | Low |
| 4 | Rebalance execution | **High** | Medium | **High** | Medium |
| 5 | Concentration | **High** | **High** | **High** | Medium (structural) |
| 6 | Delisting | High | Low | Med | Low |
| 7 | Corporate actions | **High** | **High** | **High** if unhandled | Low if handled |
| 8 | Tax | Medium | **Certain** | **High** | Medium (structural) |
| 9 | Operational | **High** | Medium | **High** | Medium |
| 10 | Monitoring gaps | Medium | Medium | Med | Low |
| 11 | Live failure modes | **High** | Medium | **High** | Medium |
| 12 | Broker dependency | High | Low–Med | High (tail) | Medium |

**Top 4 risks to lose sleep over:** Concentration (#5), Corporate actions (#7), Tax (#8), Operational/execution (#4, #9). Note that **none of these are alpha-decay risks** — the strategy edge is fine. They are all "the live account does not equal the backtest" risks.

---

## 3. Capacity Assessment

Structure: **10 positions, equal weight (10% each)**. Position size = Capital ÷ 10.

| Total Capital | Per Position | Tradeable? | Constraint | Verdict |
|---|---|---|---|---|
| ₹5 L | ₹50,000 | Yes | Whole-share rounding noise on high-priced stocks (a ₹3,000 share = ±6% weight error); fixed ₹20 brokerage + ₹15.93 DP is ~0.07% of a ₹50k trade | **Optimal.** Frictionless. |
| ₹10 L | ₹1,00,000 | Yes | Rounding noise halves | **Optimal.** |
| ₹25 L | ₹2,50,000 | Yes | None meaningful | **Optimal.** |
| ₹50 L | ₹5,00,000 | Yes | Trivial vs. liquid names | **Comfortable.** |
| ₹1 Cr | ₹10,00,000 | Yes | First point where a low-ADTV LowVol mid-cap could need >1 day to exit | **Comfortable, monitor.** |
| ₹5 Cr | ₹50,00,000 | Mostly | A ₹50L position is 10% of a ₹5Cr-ADTV (Tier-1) name's *daily* turnover — needs participation-rate splitting; impact cost engages (model triggers >1% of ADTV) | **Workable with execution discipline.** |
| ₹10 Cr | ₹1,00,00,000 | Marginal on tail names | A ₹1 Cr position in a Tier-2 (₹1–5Cr ADTV) LowVol name is 20–100% of a day's volume → multi-day entry/exit, visible footprint, real impact | **Soft ceiling. Cap here or add a hard ADTV floor.** |

**Capacity ceiling (recommended): ₹10 Cr** for the frozen 10-stock design, and only if a **minimum ADTV floor of ₹5 Cr (Tier-1 only)** is enforced at selection. Above ₹10 Cr the 10-name structure forces either (a) accepting material impact cost on LowVol tail names, or (b) widening to 15–20 names — which is a **strategy change** and out of audit scope.

**Why LowVol matters here:** pure momentum tends toward liquid trending names; the LowVol overlay deliberately down-weights high-volatility (often high-turnover) stocks and can surface stable mid-caps with thinner books. Capacity is therefore *tighter than a pure-momentum Top 10 would be at the same AUM.* Do not assume large-cap liquidity for all 10 slots.

---

## 4. Detailed Risk Analysis

### Risk 1 — Capacity / Scaling
- **Severity:** Medium · **Probability:** Capital-dependent · **Impact:** Medium
- **Detail:** Edge is intact at all retail/HNI tiers; degrades only as positions approach a meaningful share of name-level ADTV (≈ ₹10 Cr+, see §3).
- **Mitigation:** Cap AUM at ₹10 Cr for the frozen design. Enforce a Tier-1 (ADTV ≥ ₹5 Cr) selection floor. Re-audit capacity before raising AUM. Track realized vs. modeled impact cost each rebalance.

### Risk 2 — Liquidity Risk
- **Severity:** Medium · **Probability:** Medium · **Impact:** Medium
- **Detail:** Universe is pre-filtered (≥ ₹50L ADTV, ≥90% trading days, circuit/spread/volume-CV anti-manipulation filters). This is genuinely good hygiene. The residual risk is *forced selling into a falling market* — in a 2020-style crash, ADTV collapses exactly when the quarterly rebalance may need to exit, and the ₹50L floor was measured in calmer conditions.
- **Mitigation:** Raise the live selection floor to Tier-1 (₹5 Cr ADTV) above ₹1 Cr AUM. Never market-sell an entire position in one clip — use participation-rate or VWAP-style splitting. Allow rebalance to span 2–3 sessions in stressed conditions.

### Risk 3 — Slippage Risk
- **Severity:** Low–Medium · **Probability:** High (every rebalance) · **Impact:** Low — *already modeled*
- **Detail:** Cost model applies 0.05% / 0.10% / 0.20% slippage by tier plus a √(participation) impact term. This is realistic-to-conservative for liquid names. The risk is that **live slippage on rebalance day clusters** — 10 names trading the same morning on the same signal, possibly alongside other momentum/smart-beta funds rebalancing on quarter-end.
- **Mitigation:** Avoid quarter-end/index-rebalance days for execution (offset by a few sessions). Use limit orders with a tolerance band, not market orders. Reconcile realized slippage vs. modeled each quarter; if realized > modeled for 2 consecutive rebalances, revisit the cost assumption (it would mean the net backtest is optimistic).

### Risk 4 — Rebalance Execution Risk
- **Severity:** HIGH · **Probability:** Medium · **Impact:** HIGH
- **Detail:** This is where backtested alpha most often dies in single-operator deployments. Concrete failure paths: executing on stale/un-updated price data; wrong share count (fat finger); partial fills leaving the book unbalanced; executing the signal a day late so prices have moved; misreading the buffer logic and churning names that should have been held. The backtest assumes T+1 open execution with perfect fills — reality has none of that for free.
- **Mitigation:** Generate the trade list programmatically (never hand-compute). Mandatory pre-trade checklist (§Deployment Checklist). Dry-run the trade list against the prior holdings and assert turnover is within the expected Buffer-20 band (a turnover spike = a bug). Post-trade reconciliation of filled vs. intended weights. Two-session window so a bad fill can be corrected, not chased.

### Risk 5 — Concentration Risk
- **Severity:** HIGH · **Probability:** HIGH · **Impact:** HIGH
- **Detail:** 10 names, 10% each, **no stop-loss** (risk module deliberately disabled). A single fraud/governance blow-up (recent Indian precedents are numerous) or a −30% earnings gap is an instant ~3% NAV hit; a locked lower circuit means you cannot even exit. The −33.5% MaxDD is a *portfolio-level* number that already embeds this — but it understates *single-name* tail risk because the worst single-name event in the sample may not be the worst possible. This concentration **is the source of the alpha** — diversifying it away is a different strategy.
- **Mitigation (without changing the strategy):** Accept it explicitly and size AUM to what the investor can hold through −35–40%. Sector cap (config already supports 30% / max 3 per sector) prevents the book becoming a single-sector bet. Hard pre-commitment to *not* intervene during drawdown (intervention is the real loss event). Document the −40% scenario in the IPS and get sign-off *before* funding.

### Risk 6 — Delisting Risk
- **Severity:** High · **Probability:** Low · **Impact:** Medium
- **Detail:** A held name gets suspended/delisted (SEBI action, NCLT, voluntary). The position becomes illiquid or worth scrap; the backtest's survivorship-free universe handles the *statistics* but a live account holds the *actual* dead stock. Quality/anti-manipulation filters reduce but do not eliminate exposure.
- **Mitigation:** The filter suite (circuit, volume-CV, spread) already screens manipulation-prone names — keep it strict. On any suspension news, exit at next liquidity rather than waiting for rebalance. Maintain a manual override to drop a name flagged for delisting/SEBI action even mid-quarter.

### Risk 7 — Corporate Action Risk
- **Severity:** HIGH · **Probability:** HIGH (multiple per year across 10 names) · **Impact:** HIGH if unhandled, Low if handled
- **Detail:** Splits, bonuses, rights, dividends, mergers, spin-offs, name/ISIN changes. If the **live price feed and the signal engine disagree on adjustment** (e.g., yfinance auto-adjusts but the broker shows raw price), the momentum signal can be computed on a discontinuity → garbage rank → wrong trade. A missed bonus/split can make a position look like it crashed 50%. This is a *data integrity* risk masquerading as a market risk and is **almost guaranteed to occur** over any year.
- **Mitigation:** Reconcile the signal data's adjustment basis against the broker's holdings statement at *every* rebalance. Maintain a corporate-action calendar for held names. Validate that no held name shows an un-explained >20% single-day move (likely an unadjusted action, not a real return) before acting on it. Treat any adjustment mismatch as a hard stop on that name's trade until resolved.

### Risk 8 — Tax Impact
- **Severity:** Medium · **Probability:** CERTAIN · **Impact:** HIGH
- **Detail:** The backtest is pre-tax. Indian equity (post Budget 2024): **STCG (holding < 12 mo) = 20%**, **LTCG (≥ 12 mo) = 12.5%** above the ₹1.25L annual exemption. Quarterly rebalance with Buffer 20 keeps turnover low, so *winners that stay in rank are held > 1 year* (good — LTCG). But every name that *rotates out* before 12 months realizes STCG at 20%. Realistic drag estimate: **2–4% off CAGR**, scaling up with AUM (the ₹1.25L exemption is fixed, so it's negligible relief at ₹1Cr+). Net-to-investor CAGR is therefore **~13–15%, not 17.4%.**
- **Mitigation:** Re-state all forward expectations as **net-of-tax**. Where Buffer-20 leaves a name marginally inside/outside the band near its 12-month mark, prefer holding past the LTCG threshold (this is execution discretion, not a strategy change). Harvest the ₹1.25L LTCG exemption annually. Engage a CA for advance-tax scheduling. **Do not market this strategy on its gross CAGR.**

### Risk 9 — Operational Risk
- **Severity:** HIGH · **Probability:** Medium · **Impact:** HIGH
- **Detail:** Single operator, single machine, manual-ish quarterly process. Failure paths: stale cached data used for a live signal (the repo *ships* cached parquet — easy to run a "live" rebalance on months-old data by accident); environment break (the documented ₹-sign cp1252 crash is a live example of fragility); lost/corrupted holdings state; operator unavailable on rebalance day; no audit trail of why a trade was made.
- **Mitigation:** Hard gate: refuse to generate a live trade list if cached data is older than N days (assert freshness). Version-control the exact config + commit hash used for each live rebalance. Immutable log of every signal, rank, and trade with timestamps. Documented runbook so a second person *could* execute. Backups of holdings/state before every rebalance.

### Risk 10 — Monitoring Requirements
- **Severity:** Medium · **Probability:** Medium · **Impact:** Medium
- **Detail:** Between quarterly rebalances the book runs unattended. Risks that develop intra-quarter: a held name gets a SEBI/fraud flag; a corporate action lands; drawdown breaches the investor's pain threshold; tracking error vs. backtest expectation diverges (a sign of a data or execution bug, not just bad luck).
- **Mitigation:** Daily lightweight check: NAV, drawdown vs. −33.5% reference, any held-name news/circuit/suspension. Monthly: tracking-error and turnover sanity vs. backtest. Quarterly: full reconciliation (holdings, costs realized vs. modeled, tax lots). Alert thresholds defined in §Required Controls.

### Risk 11 — Live Trading Failure Modes
- **Severity:** HIGH · **Probability:** Medium · **Impact:** HIGH
- **Detail:** Catalogue of "how the live account silently diverges from the backtest":
  - Signal computed on stale/unadjusted data → wrong portfolio.
  - Look-ahead leaking into live ops (using a price not yet available at decision time) — the backtest is clean (T+1 open); a sloppy manual process can cheat and then *underperform* live.
  - Partial fills → unintended weights → tracking error.
  - Buffer logic misapplied → over-trading → cost + tax drag the backtest never saw.
  - Quarter missed entirely (operator unavailable) → portfolio drifts off-model.
  - Cost/slippage worse than modeled in a stress quarter → net return below backtest.
- **Mitigation:** Every item above maps to a checklist gate or an automated assertion (§Deployment Checklist, §Required Controls). The unifying principle: **the live process must be reproducible and asserted against the backtest's own assumptions** (T+1 open, modeled costs, expected turnover band).

### Risk 12 — Broker Dependency Risk
- **Severity:** High · **Probability:** Low–Medium · **Impact:** High (tail)
- **Detail:** Single broker = single point of failure: outage on rebalance day, RMS/margin glitch, account freeze (KYC/regulatory), broker insolvency, API/terminal downtime. A rebalance day outage forces either a skipped quarter or a panicked manual scramble.
- **Mitigation:** Maintain a **second, funded, demat-linked broker account** as failover. Holdings are in demat (NSDL/CDSL) so they survive broker failure — but *trading access* does not. Prefer a broker with a stable execution API and documented uptime. Never schedule the rebalance for the first/last hour of a session (thin liquidity + outage clustering). Keep enough cash buffer to avoid margin-related RMS interference.

---

## 5. Deployment Checklist

**One-time (before first rupee):**
- [ ] Investment Policy Statement signed, explicitly stating: −40% drawdown is possible, 10-name concentration, no stop-loss, net-of-tax expected CAGR ~13–15% (not 17.4%).
- [ ] AUM capped at ≤ ₹10 Cr for the frozen 10-name design.
- [ ] Tier-1 (ADTV ≥ ₹5 Cr) selection floor enabled if AUM > ₹1 Cr.
- [ ] Primary + failover broker accounts opened, funded, demat-linked.
- [ ] Frozen commit (`8f0482f`) + exact config pinned and recorded.
- [ ] Live data feed's corporate-action adjustment basis reconciled against broker.
- [ ] CA engaged for STCG/LTCG tracking and advance tax.
- [ ] Runbook written so a second person can execute the rebalance.

**Every rebalance (quarterly):**
- [ ] Data freshness assertion passed (no stale cache).
- [ ] Signal computed on adjustment-reconciled prices.
- [ ] Trade list generated programmatically from current vs. target holdings.
- [ ] Turnover within expected Buffer-20 band (spike ⇒ stop, investigate).
- [ ] Sector cap (≤3/sector, ≤30%) respected.
- [ ] No held/target name under SEBI flag, suspension, or unexplained >20% move.
- [ ] Execution split by participation rate; limit orders with tolerance; not on quarter-end/index-rebalance day; not in first/last hour.
- [ ] Post-trade: filled weights reconciled vs. target; realized cost/slippage logged vs. modeled.
- [ ] Holdings + tax lots + signal log archived (immutable, timestamped).

---

## 6. Required Controls

| Control | Type | Threshold / Rule |
|---|---|---|
| Data freshness gate | Hard, automated | Block live trade list if cache > 5 trading days old |
| Turnover sanity | Hard, automated | Halt if rebalance turnover exceeds Buffer-20 expected band |
| Adjustment reconciliation | Hard, manual | No trade on a name whose feed/broker adjustment disagrees |
| Single-name move check | Hard, manual | Investigate any held name >20% single-day move before acting |
| AUM ceiling | Hard, policy | ≤ ₹10 Cr frozen design |
| Liquidity floor | Hard, selection | Tier-1 ADTV ≥ ₹5 Cr above ₹1 Cr AUM |
| Drawdown watch | Soft, alert | Alert at −25%, board/IPS review at −33.5% (backtest MaxDD), no forced action |
| Tracking error | Soft, monthly | Flag if live vs. expected diverges beyond noise → hunt for a bug |
| Cost realization | Soft, quarterly | Flag if realized > modeled cost 2 quarters running |
| Broker failover | Standby | Second account funded and tested |
| Execution discretion | Soft, policy | May hold a marginal name past 12-mo LTCG threshold |

**Note on drawdown control:** the frozen strategy has **no stop-loss by design** (validated: stops hurt returns). Therefore the drawdown "control" is a *governance/communication* control, **not** a liquidation trigger. Adding a stop here would be a strategy change and is out of scope — but the IPS must make crystal clear that the plan is to **hold through** drawdowns, because the single biggest realized-loss risk is an investor forcing liquidation at the bottom.

---

## 7. Open Risks (accepted / unresolved)

1. **Backtest pre-tax.** Net-of-tax CAGR is structurally ~2–4% lower. Accepted, must be disclosed; not fixable without becoming a tax-managed (different) strategy.
2. **No stop-loss / full concentration.** Structural to the alpha. Accepted via IPS sign-off, not mitigated away.
3. **−33.5% MaxDD is a sample minimum, not a worst case.** The true forward worst case can exceed it. Accepted.
4. **Single-operator model.** Failover broker and a runbook reduce but do not eliminate key-person risk.
5. **Capacity above ₹10 Cr unverified** for the frozen 10-name design. Out of scope until re-audited.
6. **Live cost/slippage assumed ≈ modeled.** Validated only against the model, not against live fills. First few live quarters are the real test of whether the *net* backtest holds.
7. **Regime dependence not stress-tested live.** The 17.4% CAGR spans a particular 2011–2026 path (incl. 2020 crash, 2022 drawdown). A prolonged momentum-crash regime (e.g., a sharp 2009-style reversal) is in-sample but its live recurrence is an accepted unknown.

---

## 8. Go / No-Go Recommendation

### Verdict: **CONDITIONAL GO**

Deploy **real money** subject to **all** of the following being true:

1. **Capital ≤ ₹10 Cr**, with a Tier-1 ADTV floor above ₹1 Cr.
2. **Net-of-tax expectations** set (~13–15% CAGR), not the gross 17.4% headline.
3. **IPS signed** acknowledging −40% drawdown potential, 10-name concentration, and no stop-loss — with a pre-commitment to hold through drawdowns.
4. **Operational controls live**: data-freshness gate, turnover sanity check, adjustment reconciliation, immutable trade log, programmatic trade-list generation.
5. **Failover broker** funded and tested.
6. **Paper/pilot quarter first**: run one full rebalance cycle at small size (≤ ₹5–10 L) to validate that *live realized cost, slippage, and execution* match the model before scaling.

### No-Go if:
- Any of controls #1, #3, #4 above are skipped, **or**
- The investor cannot tolerate a −35–40% drawdown without intervening, **or**
- The strategy is sold/funded on its gross CAGR, **or**
- AUM exceeds ₹10 Cr without a fresh capacity audit.

**Final word:** The research is honest and the edge is real — the memory record (honest ceiling ~17–18%, no survivorship mirage) is consistent with this audit. The danger is **not** that the strategy is overfit; it is that the *live account underperforms the backtest by a knowable margin* (tax + execution + the costs the model can't perfectly predict) and that a **single operational mistake or a forced drawdown exit** converts a sound long-run strategy into a realized loss. Control those, size it right, tell the investor the net number — and it is deployable.

---

*Audit only. No implementation code produced. No new research, factor tests, or optimization performed. Performance figures taken as given from frozen commit `8f0482f`.*
