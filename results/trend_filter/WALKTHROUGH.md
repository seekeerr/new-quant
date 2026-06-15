# Experiment 1 — Market Trend Filter (risk overlay)

**Question:** Can a market-trend filter on the NIFTY 500 *significantly reduce drawdown
and improve the Sharpe ratio without destroying long-term returns?*

**Short answer:** A **monthly SMA filter cuts the drawdown by ~12 points** (−62.5% → −50.2%)
while keeping **88–93% of the CAGR** — that part works. But it does **not** materially
move Sharpe, and Jensen alpha stays (barely) negative. A **daily 200-DMA filter is the
worst of the lot** — it whipsaws, halves the return, and makes the drawdown *deeper*.
So: drawdown — yes; risk-adjusted edge — no. The strict success criteria are **not met**.

## Setup (everything but the gate is the survivorship-free baseline)

- Universe: survivorship-free bhavcopy cross-section, point-in-time top-500-by-turnover.
- Signal/portfolio: pure 12-1 momentum, Top5, equal weight, quarterly, **Buffer20** — unchanged.
- Costs/dates/benchmark: identical Indian-equity cost model, 2012-01 → 2026-05, NIFTY 500 price index.
- **Only change:** a 0/1 exposure gate on the NIFTY 500 price index. Risk-off ⇒ 100% cash
  (0% interest); risk-on ⇒ redeploy the *same* most-recent quarterly momentum book.
  1-trading-day lag (decision uses the prior close — no lookahead). Switching trades pay full costs.
- The momentum **selection still rebalances every quarter regardless of the gate**, so
  "Top5 / Buffer20 / quarterly / 12-1" is genuinely intact — the gate only scales exposure.

**Engine validation:** the *No Filter* variant reproduces the survivorship-free baseline to
the rupee (CAGR 12.75%, MaxDD −62.46%, Sharpe 0.20, Alpha −1.96%, final ₹28.15 L, 436 trades).
The overlay is therefore a clean superset of the baseline engine.

## Results

| Metric | No Filter (baseline) | 200 DMA (daily) | 10-Mo SMA | 12-Mo SMA |
|---|---|---|---|---|
| **CAGR** | 12.75% | 5.78% | 11.17% | **11.89%** |
| **Max Drawdown** | −62.46% | −67.65% | **−50.20%** | −50.23% |
| **Sharpe** | 0.20 | −0.03 | 0.18 | 0.20 |
| **Sortino** | 0.28 | −0.04 | 0.24 | 0.26 |
| **Calmar** | 0.20 | 0.09 | 0.22 | **0.24** |
| **Annual Vol** | 31.5% | 25.6% | 26.3% | 27.3% |
| **Jensen Alpha** | −1.96% | −5.43% | −0.28% | **−0.09%** |
| **Excess vs bmk (CAGR)** | +1.35% | −5.62% | −0.22% | +0.49% |
| **Final Value (₹5L)** | ₹28.2 L | ₹11.2 L | ₹23.0 L | ₹25.2 L |
| **Time in cash** | 0% | 25% | 26% | 22% |
| **Gate switches** | 0 | 99 | 31 | 21 |
| **Trades / Turnover** | 436 / 58% | 778 / 207% | 456 / 92% | 431 / 79% |
| **Txn costs** | ₹1.66 L | ₹2.01 L | ₹1.60 L | ₹1.92 L |

Success test per variant (DD↓ materially **and** Sharpe↑ **and** Calmar↑ **and** Alpha>0):
**none fully met** — DD and Calmar improve, but Sharpe is flat and alpha never turns positive.

## Why each filter behaves the way it does

- **200 DMA (daily) — fails.** Too twitchy for a −60%-vol mid/small-cap book. 99 switches,
  207% turnover, ₹2 L of costs, and it still *deepened* the max drawdown to −67.7%. A daily
  index average flips the whole book in and out around every wiggle, selling bottoms and
  buying back higher. This is the classic whipsaw failure mode. **Do not use.**
- **10-Month / 12-Month SMA (monthly) — partial win.** Monthly sampling damps the whipsaw
  (21–31 switches vs 99). Both chop the deepest drawdown by ~12 points and keep ~90% of the
  CAGR. The 12-month is the best single overlay: 11.89% CAGR (−0.86 vs baseline), −50.2% DD
  (+12.2 shallower), Calmar 0.24 vs 0.20, alpha essentially zero (−0.09%) vs −1.96%.
- **But Sharpe doesn't move** (0.20 → 0.20). The filter removes some of the *worst* tail
  (drawdown, Calmar, Sortino all nudge up) yet trims roughly as much upside as downside in
  Sharpe terms — see 2018 (+19.8% → +12.6%) and 2020 (+98.5% → +75.8%), where the gate sat
  in cash through part of a *rally*. Lower vol, lower return, same ratio.

## Honest verdict

The trend filter is a **drawdown tool, not an alpha tool.** On this bias-free universe:

- ✅ **Drawdown improves materially** (−62% → −50%, ~12 pts) — the monthly variants deliver this.
- ✅ **Calmar improves** (0.20 → 0.24) and CAGR is largely preserved (retains 93%).
- ❌ **Sharpe does not materially improve** (0.20 → 0.20).
- ❌ **Alpha does not turn positive** (−1.96% → −0.09%; better, but still ≤ 0).
- ❌ **The daily 200-DMA is actively harmful** (whipsaw).

Against the user's stated success bar (*DD↓ AND Sharpe↑ AND Calmar↑ AND Alpha>0*), the
experiment **does not fully succeed** — it clears two of four. The most defensible takeaway:
the underlying Top-5 momentum book has **no genuine risk-adjusted edge** to rescue (Sharpe
0.20, alpha ≈ 0), so an overlay can reshape the return *path* (shallower drawdowns, faster
psychological recovery) but cannot manufacture the Sharpe/alpha that isn't there. If a
single overlay must be chosen for *drawdown control with minimal CAGR give-up*, it is the
**12-Month SMA**.

## Caveats

- Risk-off earns **0% in cash** (no T-bill/FD yield). A realistic ~6% cash yield would lift
  the filtered variants' CAGR by roughly the cash-weighted fraction (~22–26% of the time),
  i.e. order +1.3–1.6%/yr — enough to push the 10/12-month CAGR *above* baseline and alpha
  clearly positive. Worth a follow-up before dismissing the monthly filter.
- Benchmark is **price**, not TRI (≈ +1.3%/yr understated) — the excess-return columns
  flatter the strategy by that much.
- Gate is on the **price index**; using the TRI level would barely change the MA crossings.
- This is a single historical path; the 200-DMA whipsaw conclusion is robust, but the
  10-vs-12-month ranking is within noise.

## Files
- `report.png` — equity / drawdown / CAGR-vs-DD / Sharpe-Sortino-Calmar / rolling-3Y / year-wise
- `report.txt`, `comparison.csv`, `yearwise_returns.csv`
- Reproduce: `py run_trend_filter_experiment.py` (gate logic in `run_trend_filter_experiment.py`,
  baseline engine reused from `run_buffer_experiment.py` + `run_survivorship_validation.py`).
