# Price-Only Research Program — Final Conclusion

> ## ⛔ PRICE-ONLY RESEARCH PROGRAM COMPLETE
>
> The following research tracks are **CLOSED**:
> **Momentum Variants · Trend Overlays · Volatility Overlays · Mean Reversion · Portfolio Construction**
>
> **Reason:** multiple independent, pre-registered experiments each failed to improve the frozen
> champion. The price-only search space is exhausted. The champion ships as the validated product.

**Scope:** all research that uses **only price/volume data** (no fundamentals).
**Period under test:** 2012-01-03 → 2026-05-29, net of the full Indian delivery cost model.
**Universe:** survivorship-free daily bhavcopy, corp-action adjusted, equity-only (ISIN `INE`),
top-500-liquid point-in-time (3,291-symbol pool). **Capital:** ₹500,000.
**Benchmark:** NIFTY 500 price index, CAGR **13.6%** (true TRI ≈ 14.9%).

Supersedes nothing; it *closes* and consolidates `PHASE1_FINAL_REPORT.md`, the Phase 2B experiments
(`results/short_term_reversal/`, `results/construction_weighting/`), and `PHASE2B_STRATEGY_LANDSCAPE.md`.

---

## 1. All experiments performed

Verdict key: **PASS** = improved risk-adjusted return on a pre-registered bar · **FAIL** = did not ·
**NULL** = changed risk shape only (no Sharpe/alpha gain) · **FIX** = data-hygiene correction.

| # | Experiment | Script / result dir | Track | Verdict |
|---|---|---|---|---|
| 1 | Pure 12-1 momentum (base factor) | `run_pure_momentum.py` | Momentum Variants | Baseline (real, crash-prone) |
| 2 | Survivorship-free bhavcopy migration | `run_survivorship_validation.py` | — (data) | **FIX** (critical) |
| 3 | ETF / fund contamination removal | equity ISIN `INE` whitelist | — (data) | **FIX** (critical) |
| 4 | Benchmark CSV date-parse repair | `data/benchmark.py` | — (data) | **FIX** (critical) |
| 5 | Universe / liquidity validation | `run_universe_validation.py` | Portfolio Construction | Infra established |
| 6 | Ranking-buffer turnover sweep (10/15/20) | `run_buffer_experiment.py` | Portfolio Construction | Buffer20 adopted |
| 7 | Portfolio size — biased universe | `run_portfolio_size_experiment.py` | Portfolio Construction | **FAIL** (bias artifact) |
| 8 | Concentration — honest universe (Top3/5/10) | `run_concentration_honest.py` | Portfolio Construction | Top10 wins (Top3 = −72% DD) |
| 9 | **Low-Volatility blend (Mom + LowVol)** | `run_momentum_lowvol.py` | **(the success)** | **PASS → champion** |
| 10 | Low-Vol only (bookend) | `run_momentum_lowvol.py` | Volatility Overlays | Weak alone (defines floor) |
| 11 | Vol-managed momentum (Barroso) | `run_momentum_lowvol.py` | Volatility Overlays | **NULL** |
| 12 | Trend-filter overlay | `run_trend_filter_experiment.py` | Trend Overlays | **NULL** |
| 13 | Residual / beta-adjusted "smart" momentum | `run_smart_momentum.py` | Momentum Variants | **FAIL** (smoother, not higher) |
| 14 | Leverage scenarios (1.25×–2×) | `run_leverage_scenarios.py` | Volatility Overlays | **FAIL** → cash-only decision |
| 15 | 52-Week-High proximity | `run_52week_high.py` | Momentum Variants | **FAIL** (redundant w/ low-vol) |
| 16 | Low-MAX / anti-lottery | `run_low_max.py` | Momentum Variants | **FAIL** (defence-on-defence) |
| 17 | Frog-in-the-Pan (FIP) | `run_fip.py` | Momentum Variants | **FAIL** (sign-flips; closest near-miss) |
| 18 | **Short-Term Reversal (mean reversion)** | `run_short_term_reversal.py` | **Mean Reversion** | **FAIL** (catastrophic) |
| 19 | **Portfolio construction (EW/InvVol/ERC/MinVar)** | `run_construction_weighting.py` | **Portfolio Construction** | **FAIL / NULL** |

Two `PASS`-shaped outcomes only: the **Low-Vol blend** (real risk-adjusted win → became the champion)
and **Buffer20** (turnover control, no alpha cost). Everything else failed or was risk-shaping noise.

---

## 2. Why each track closed (or, for low-vol, succeeded)

### ✅ The one success — Low-Volatility blend (NOT closed; it IS the champion)
Pairing 12-1 momentum (offence, the return engine) with low realised vol (defence, the risk reducer)
lifted **Sharpe 0.41 → 0.69** and cut **MaxDD −56% → −33%** while keeping ~17% CAGR. It cleared the
pre-registered bar (net alpha > 0 **and** Sharpe materially up). It works because the two legs are
**lowly correlated and do different jobs** — an offence + defence *pairing*, not a single factor.

### ⛔ CLOSED — Momentum Variants
Every attempt to build a "smarter momentum" failed to beat plain 12-1 as the offensive leg:
- **Residual/smart momentum:** smoother ride (DD −27%) but no Sharpe/CAGR gain (16.2% / 0.68).
- **52-Week-High:** *better standalone* than momentum (Sharpe 0.50 vs 0.41, −42% vs −56% crash) — but
  52WH + LowVol collapsed to Sharpe 0.19: low-vol names already sit at their highs, so the blend
  degenerated to ~low-vol-only. **Redundant** with the defensive leg.
- **Low-MAX (anti-lottery):** a *defensive* factor; Low-MAX + LowVol = defence-on-defence (0.45 Sharpe,
  lowest DD −26% but only 11.8% CAGR). Gives up the return engine.
- **Frog-in-the-Pan:** closest near-miss (FIP + LowVol 0.59) but **split-sample sign-flipped** (won
  2012–19, lost 2019–26) → fragile, regime-dependent. The validation discipline killed it.
- **Lesson:** refining the *winning* factor is a dead end; none beat plain 12-1 momentum.

### ⛔ CLOSED — Trend Overlays
The trend-filter overlay (price-vs-EMA gating of exposure) changed the *shape* of the ride but not the
engine's Sharpe → **NULL**. Risk overlays move risk around; they don't add alpha.

### ⛔ CLOSED — Volatility Overlays
- **Vol-managed momentum (Barroso):** scaling exposure to a constant-vol target → **NULL** (risk-only).
- **Leverage (1.25×–2×, ~10% borrow):** raises CAGR but **lowers Sharpe** (0.71→0.60) and deepens
  drawdowns (−40% to −59%); 30% would need ruinous ~2.5×+. → **User decision: CASH ONLY, no leverage.**
- **Lesson:** exposure/vol management buys (or sells) return with proportional risk; it is not a better
  engine. Cash-only caps the honest ceiling at ~17–18%.

### ⛔ CLOSED — Mean Reversion (Phase 2B #1)
Standalone Short-Term Reversal (buy the most recent 21-day losers), frozen shell, Top3/5/10, quarterly
and monthly. **Catastrophic FAIL** on honest data: best config (Top10) +1.0% net CAGR, **Sharpe −0.20,
MaxDD −82%, alpha −13.6%, beta ~1.1, turnover ~90%/reb**; Top3 −2.3%, Top5 −6.9%; **monthly worse**
(−9% to −27%). Negative even *gross*. Naive long-only contrarian buying loads on **falling knives and
distressed high-beta micro-caps** — the exact failure mode Phase 1's survivorship work predicted.
Verdict: *"FAIL — Momentum remains the superior style."*

### ⛔ CLOSED — Portfolio Construction (Phase 2B #2 + Phase 1 buffer/size work)
- **Concentration:** on honest data, concentrating *hurts* (Top3 = 3% CAGR / −72% DD from micro-cap
  blow-ups). **Top10 wins** — the opposite of the biased-universe result.
- **Buffer20:** adopted — cuts turnover without losing alpha (the one painless win).
- **Weighting schemes (Equal / Inverse-Vol / ERC / Min-Variance) on the champion's exact Top10:**
  selection replayed verbatim (identical-selection integrity check **PASS**); only sizing changed.
  All four landed **within noise** (Sharpe 0.67–0.70, CAGR 16.8–17.4%). Equal weight stayed best on
  the pre-registered bar. **Why:** the Top10 are *already low-vol-filtered* → similar risk → nothing
  for risk-weighting to exploit. Min-Variance only *concentrated* (HHI 0.10→0.16), the wrong direction.
- Verdict: *"FAIL — Equal Weight remains the champion's sizing."*

---

## 3. Final champion metrics

**Momentum + LowVol — Top10 / Quarterly / Buffer20 / equal weight**, net of Indian costs, fixed benchmark:

```
CAGR (net)        17.4%        Sharpe          0.69
CAGR (gross)      18.2%        Sortino         0.88
Max Drawdown     -33.5%        Calmar          0.52
Annual Vol        15.7%        Beta            0.74
Alpha (Jensen)    +5.4%        Excess vs Bmk   +3.8%
Turnover/reb      41.9%        Cost drag       0.79 pts
Time underwater   85.4%        Txn costs     ~Rs 214,926
Rolling 3-yr CAGR:  min +2.4%  |  median +22.6%  |  max +36.3%   (never a losing 3-yr window)
```

Signal: `0.5 × percentile(12-1 momentum) + 0.5 × percentile(low 252-day realised vol)`.
Smoother sibling (if drawdown matters more than the last CAGR point): **Residual-Momentum + LowVol**
≈ 16.2% CAGR, Sharpe 0.68, MaxDD −27%.

---

## 4. Lessons learned

**Statistical / methodological**
1. **Data hygiene dominates signal research.** The three biggest early "findings" (47% CAGR, the low-vol
   edge size, +12% alpha) were all *data bugs* — survivorship, ETF contamination, a benchmark date-parse
   flip. Audit survivorship, instrument type, and benchmark parsing *before* trusting any metric.
2. **Effects flip sign on clean data.** In the biased universe, concentration looked great and reversal
   looked plausible; on honest data both are destructive. Direction, not just magnitude, was wrong.
3. **Pre-registration + split-sample + rolling windows earn their keep.** They caught FIP's
   regime-dependent sign-flip and stopped reversal/weighting from being sold on a single full-sample number.
4. **Net of cost is non-negotiable.** Short-term reversal's only "edge" never existed even gross, and
   high-turnover styles must clear the full Indian cost model, not a frictionless backtest.

**Practical / economic**
5. **The edge is a *pairing*, not a factor.** Momentum (offence) + low-vol (defence) works because the
   legs are lowly correlated and play different roles. A *second defensive* factor (Low-MAX) or a
   *redundant offensive* one (52WH-within-low-vol) adds nothing.
6. **Refining the winning factor is a dead end.** Residual, 52WH, Low-MAX, FIP all tried to be a smarter
   momentum; none beat plain 12-1.
7. **Risk overlays ≠ alpha.** Trend, vol-targeting, leverage, and re-weighting move risk around but do
   not raise the engine's Sharpe. Equal weight on a pre-filtered Top10 is already near-optimal.
8. **On clean Indian data, diversify, don't concentrate.** Micro-cap blow-ups punish concentration.
9. **The honest price-only, cash ceiling is ~17–18% CAGR.** Accept it as the real number; the 30% target
   is a survivorship-bias mirage and must not be re-chased by re-introducing bias or leverage.

---

## 5. Remaining open hypotheses

**Price-only — effectively exhausted.** No untested price-only stone the evidence points to remains:
momentum refinements, defensive factors, overlays, weighting, concentration, and reversal are all closed.
Lower-priority diagnostics only (spec-robustness of failed factors, intraday-high 52WH, MAX5-vs-MAX1) —
these are *post-mortems*, not new alpha.

**The real remaining lever is an OFFENSIVE FUNDAMENTAL factor** lowly/negatively correlated with momentum
(requires a point-in-time fundamentals panel — by definition untestable in a price-only program):
- **Value (E/P, B/M)** — the canonical *negatively-correlated* offensive diversifier of momentum
  (Asness-Moskowitz-Pedersen). Strong, documented Indian value premium. **Highest expected payoff.**
- **Quality / gross profitability** (Novy-Marx; QMJ) — profitable, stable firms. Framework already built
  and paused (`PHASE2A_STATUS.md`). Risk: partly *defensive* → may be redundant with the low-vol leg
  (cf. the Low-MAX failure).
- **Multi-factor (Mom + Quality + Value + LowVol)** — the robust long-only end-state; the destination
  once Value and/or Quality validate.

**Hard constraint:** honest fundamentals require a clean PIT source (paid CMIE Prowess or an NSE/BSE XBRL
scraper). yfinance / Screener are survivors-only and **banned** — fundamentals are exactly where
survivorship/look-ahead bias hides, and this program proved how badly unaudited data corrupts results.

---

## 6. Recommendation for the next phase

**Price-only research is complete and the champion is a real, validated, shippable product.** Two things
should happen, and they are not mutually exclusive:

1. **Treat the champion as the product now.** Deploy / paper-trade Momentum + LowVol / Top10 / Quarterly /
   Buffer20, cash only (~17.4% net CAGR, Sharpe 0.69, −33% MaxDD). Do **not** keep mining price data.

2. **The only research worth funding is a bounded fundamentals pilot** — the single avenue the evidence
   actively points to. Of the fundamental factors, **Value** has the highest expected payoff and the best
   theoretical complementarity (offensive *and* negatively correlated with momentum); **Quality**'s
   framework is already built but carries a redundancy risk against the existing low-vol leg. Because
   Value and Quality share the *same* data-acquisition wall, any data effort should be scoped to test
   **both** off one clean PIT panel — without committing to a full platform before a single fundamental
   signal validates.

The detailed four-way decision (Stop / Quality pilot / Value pilot / Full PIT platform), ranked by
expected alpha, engineering effort, data requirements, and probability of success, is in
**`NEXT_PHASE_OPTIONS.md`**.
