# Research Program #2 — High-CAGR Discovery (Charter / Pre-Registration)

**Opened:** 2026-06-29
**Status:** OPEN — pre-registration only. No verdicts yet.

---

## 0. Objective (verbatim mandate)

> Determine, through rigorous research, whether a **long-only** systematic strategy on the
> **full NSE/BSE universe** can realistically achieve materially higher CAGR than the validated
> champion (Mom+LowVol, ~17.4% net).
>
> **Success criterion is NOT "find 50%."** It is: *find the highest **robust** CAGR the market
> genuinely offers under these constraints.* Do not assume 17–22% is the ceiling. Do not assume
> 50–60% is achievable.

### Hard constraints (non-negotiable — a violation = automatic FAIL)
- **No leverage.** Cash only. (Leverage already tested → lowers Sharpe; closed.)
- **No hindsight / look-ahead.** Point-in-time universe & signals only.
- **No curve-fitting.** No tuning a knob to the full sample; every claim survives split-sample + rolling windows.
- **No weakened validation.** Same bar that killed FIP (sign-flip) and reversal (catastrophic) applies here.
- **Net of the full Indian delivery cost model**, always. Higher-turnover styles must *clear costs*, not ignore them.

### Explicitly in scope (the new design region)
- Completely different **trading styles** (breakout, event-driven, swing).
- **Higher-turnover** systems.
- **Different holding periods** (daily → weekly → monthly, not just quarterly).
- **Event-driven** approaches (earnings/volume/gap/breakout events).
- **Aggressive rejection** — kill ideas fast on the pre-registered bar.

---

## 1. What is already CLOSED (do not re-run)

Source: `PRICE_ONLY_FINAL_CONCLUSION.md`. Every item below failed a pre-registered bar on
survivorship-free data, net of costs.

| Family | Verdict | Why it stays closed |
|---|---|---|
| Momentum refinements (residual, 52WH, Low-MAX, FIP) | FAIL | None beat plain 12-1; FIP sign-flipped split-sample. |
| Mean reversion / short-term reversal (21-day losers) | FAIL (catastrophic) | Negative even **gross**; loads on falling knives. Monthly worse than quarterly. |
| Trend overlays / vol-targeting (Barroso) | NULL | Move risk, add no alpha. |
| Leverage 1.25×–2× | FAIL | Raises CAGR, **lowers Sharpe**, deepens DD. Constraint forbids anyway. |
| Concentration (Top3/5) | FAIL | Micro-cap blow-ups; Top10 optimal on honest data. |
| Weighting (InvVol/ERC/MinVar) | FAIL/NULL | Within noise; EW best on pre-filtered Top10. |
| Universe breadth — unfiltered ≥₹1/₹5 | MIRAGE | Filters load-bearing; PureMom 26% is un-fillable micro-cap fills; ShortRev → −100% ruin. |

**Implication:** Program #2 must NOT be a re-parameterization of momentum, a new overlay, or another
weighting scheme. Those corners are exhausted. The only honest moves left are **(a) validate a
standing lead that already exceeds the champion**, and **(b) test genuinely different *styles*.**

---

## 2. The design space that remains OPEN

Two tracks. Track 1 is the cheap, high-probability test of "is the ceiling really 17–18%?".
Track 2 is the exploratory hunt for a higher ceiling via new styles.

### TRACK 1 — Validate the standing small-cap-tail lead (highest probability)
`results/smallcap_universe/` already produced, net of costs, on survivorship-free data:

| Signal | Slice | Net CAGR | Sharpe | MaxDD |
|---|---|---|---|---|
| Mom+LowVol | **SmallCap 300–1000** | **21.8%** | **1.02** | −34.8% |
| Mom+LowVol | Liquid Top-500 (champion) | 16.5% | 0.66 | −33.0% |
| PureMom | SmallCap 300–1000 | 17.0% | 0.38 | −69.6% |

The 21.8% / Sharpe 1.02 cell is **+5.3 pts CAGR over the champion at a *better* Sharpe and
comparable drawdown** — and it is exactly "full universe, long-only, no leverage." Memory flags it
**unvalidated**. If it survives the same discipline that killed FIP, the 17–18% ceiling is *already*
disproven and the new honest number is ~22%. If it dies (regime-dependent, sign-flip, capacity
mirage at ₹1L only), we learn the tail is not robust — cheaply.

**This is the single highest expected-value first experiment.** It uses work already done and
answers the program's core question (is the ceiling firm?) before spending compute on new styles.

### TRACK 2 — New styles for a higher ceiling (exploratory)
Ranked by *expected robust payoff after the Indian cost model* (the cost model is the killer here —
high turnover is brutal under STT + stamp + slippage). Survivorship risk is handled by the bias-free
bhavcopy panel already in use.

| # | Style | Economic basis | Free/PIT data? | Cost-sensitivity | Prior-art risk |
|---|---|---|---|---|---|
| 2A | **Holding-period / horizon grid** for momentum & breakout (weekly/biweekly/monthly × short formation) | Faster trend capture; the one axis the closed work never swept cleanly | Yes (price) | **High** (turnover ↑) | Reversal died fast — but trend≠reversal |
| 2B | **Breakout / Donchian event system** (52-wk-high *breakout as event*, volume-confirmed) | `strategies/breakout.py` exists, never tested net; breakout ≠ 52WH-proximity factor (which failed) | Yes (price+vol) | Medium-High | 52WH *proximity* failed; *breakout event* is different |
| 2C | **Post-event drift / volume-gap events** (price-gap + volume-surge as a proxy for earnings surprise / PEAD) | PEAD is among the most robust anomalies globally | Partial (true PEAD needs earnings dates; gap/volume is a price-only proxy) | Medium | Untested |
| 2D | **Sector / thematic rotation** (cross-sectional momentum on sector baskets) | Lower turnover, diversification; untested | Yes (price + sector map) | Low-Medium | Untested |

**Pre-registered prior (honest):** Track 2 styles face a steep cost headwind, and the closed reversal
result is a warning that high-turnover long-only contrarian dies in India. Trend/breakout/event styles
are *directional*, not contrarian, so they are not pre-doomed — but the expectation is that **most will
NOT clear the champion net of costs.** The job is to prove which, if any, does, and reject the rest fast.

---

## 3. The cost-realism gate (the program's main killer)

Any higher-turnover style is judged net of the **full Indian delivery cost model** (STT, stamp, GST,
brokerage, per-liquidity-tier slippage, impact). Additionally, for any style whose edge concentrates
in small/illiquid names, a **×5 slippage/impact stress pass** (as in `run_full_universe.py`) is
mandatory: if the edge dies under stress, it is an un-fillable artifact, not a strategy. Stated up
front, not as an after-the-fact excuse.

---

## 4. Pre-registered bar & kill criteria (applied to EVERY experiment)

An experiment **PASSES** only if ALL hold:
1. **Net CAGR > champion's 17.4%** (the program's whole point), AND
2. **Sharpe ≥ champion's 0.69** (no buying CAGR with ruinous risk), AND
3. **MaxDD not worse than champion by >5 pts** (i.e. ≥ −38.5%), AND
4. **No split-sample sign-flip** (2012–19 vs 2019–26 both positive alpha), AND
5. **Survives the ×5 cost-stress** if the edge is small/illiquid-concentrated, AND
6. **Rolling 3-yr min CAGR > 0** (never a losing 3-yr window — the champion clears this).

Fail any → **REJECT** and document why (post-mortem in the study's WALKTHROUGH). No second chances by
re-tuning; a rejected style is closed unless a *new economic reason* reopens it.

---

## 5. Frozen shell (identical to all prior studies unless the experiment explicitly varies it)

- Engine: `run_buffered_backtest` (verbatim).
- Data: survivorship-free bhavcopy panels (`data/cache_bhav/`), corp-action adjusted, equity-only (ISIN `INE`), point-in-time.
- Default product shell: Top-10 / equal weight / whole-share rounding / Buffer20.
- Capital: ₹500,000 for the research base; ₹100,000 for any tiny-book-capacity claim (small-cap tail).
- Benchmark: NIFTY 500 price index (CAGR 13.6% over span; TRI ≈ 14.9%).

---

## 6. Sequencing (recommended)

1. **Experiment 1 — Track 1 validation** of the 21.8% SmallCap-300–1000 Mom+LowVol lead
   (walk-forward + split-sample + rolling windows + ×5 cost stress + ₹1L-only capacity check).
   *Decisive on the core question; cheapest; uses standing work.*
2. **If Track 1 PASSES** → the honest ceiling is ~22%, and Track 2 hunts above it.
   **If Track 1 FAILS** → the tail is a mirage; Track 2 becomes the only path and the champion stands.
3. **Track 2** in ranked order 2A → 2B → 2C → 2D, each gated by §4, rejecting aggressively.

---

## 7. Pre-registered honest expectation (so we can't move the goalposts later)

- **Likely outcome:** the robust ceiling lands in the **~18–24%** band, with the SmallCap-tail
  Mom+LowVol (if it validates) as the most probable new champion, and most Track 2 styles rejected on costs.
- **50–60% is not an expected outcome** and will only appear if a bias re-enters — which the gates exist to catch.
- This expectation is recorded *before* the experiments so a disappointing-but-honest result is a
  SUCCESS (we found the real ceiling), not a failure to be re-chased with looser rules.
