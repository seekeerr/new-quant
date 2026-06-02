# Portfolio-Size (Concentration) Experiment

## What was tested

The champion strategy was held **completely fixed** and only the portfolio size `N`
was swept:

| Held fixed | Value |
|---|---|
| Signal | Pure 12-1 cross-sectional momentum |
| Rebalance | Quarterly |
| Weighting | Equal weight |
| Ranking buffer | 20 |
| Risk mgmt | None (no stops / DD liquidation / regime / blending) |
| Costs | Full Indian-equity delivery cost model |

**Only variable:** number of stocks held — **Top 3 / Top 5 / Top 7 / Top 10**.

Net-of-cost figures, ₹500,000 initial capital, period 2012-01-03 → 2026-05-29.

> Data note: the local cache currently resolves to 49 stocks (TATMOTORS.NS failed to
> refresh and the NIFTY 500 TRI benchmark CSV is absent), so absolute levels match the
> existing buffer experiment's universe. The *relative* ranking across sizes is the result.

## Headline result

Returns fall **monotonically as the book widens** — concentration preserves momentum alpha,
diversification dilutes it.

| Metric | Top 3 | **Top 5** | Top 7 | Top 10 |
|---|---|---|---|---|
| CAGR | **28.20%** | 26.25% | 24.11% | 20.44% |
| Max Drawdown | -40.20% | -39.85% | **-37.36%** | -38.70% |
| Sharpe | 0.87 | **0.90** | 0.87 | 0.74 |
| Calmar | **0.70** | 0.66 | 0.65 | 0.53 |
| Annual Volatility | 25.06% | 22.07% | 20.28% | **18.92%** |
| Trades | **201** | 338 | 475 | 684 |
| Txn Costs (₹) | 257,314 | 261,642 | 234,007 | **190,009** |
| Final Value (₹) | **17,886,386** | 14,354,335 | 11,216,863 | 7,276,496 |
| Time Underwater | 87.0% | **86.2%** | 86.5% | 87.0% |
| Recovery (deepest DD) | 445 d | **148 d** | 154 d | 226 d |

(Bold = best in row.)

## Interpretation

- **Top 3 wins on raw return and Calmar** (28.2% CAGR, 0.70 Calmar) but at a cost:
  highest volatility (25.1%), the deepest equity trough (value at max-DD fell to ₹1.06M
  vs ₹2.35M for Top 5), and by far the **worst recovery — 445 days** vs ~150 for Top 5/7.
  Its drawdown also struck in a different episode (2016 single-stock pain, not the 2020 COVID
  crash), a tell that 3 names is exposed to idiosyncratic, hard-to-recover hits.
- **Top 5 is the best risk-adjusted all-rounder:** highest Sharpe (0.90), shortest recovery
  (148 d), lowest time underwater, and still 26.3% CAGR. This is the current champion and the
  data supports keeping it as the default.
- **Top 7** trades a little CAGR for the shallowest max drawdown (-37.4%) and smoother ride —
  the choice if drawdown depth matters more than terminal wealth.
- **Top 10 is the clear loser:** alpha is diluted to 20.4% CAGR and Sharpe collapses to 0.74
  without buying a meaningfully shallower drawdown. More names ≠ safer here.

## Recommendation

- **Default / risk-adjusted optimum: keep Top 5.** Best Sharpe, fastest recovery, least time
  underwater — the most *robust* concentration level, and it stays the champion.
- **Maximum-growth tilt: Top 3**, only if you can stomach 25% vol and a >1-year recovery from
  the worst drawdown. Higher Calmar is driven by return, not by tamer risk.
- **Do not go to Top 10** — pure dilution of the momentum edge.

The sweet spot is **3–5 names**: concentrated enough to keep momentum alpha intact, with
Top 5 giving the better risk-adjusted profile and Top 3 the better absolute return.

## Files

| File | Contents |
|---|---|
| `report.png` | 4-size equity / drawdown / CAGR-vs-DD / Sharpe-Calmar / rolling-3Y charts |
| `report.txt` | Full console comparison report (all metrics + year-wise + verdict) |
| `comparison.csv` | Machine-readable per-size metrics |
| `yearwise_returns.csv` | Calendar-year returns per size |
| `WALKTHROUGH.md` | This file |
