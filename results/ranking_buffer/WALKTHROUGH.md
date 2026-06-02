# Ranking-Buffer Turnover Experiment

**Question:** Does holding existing positions until their momentum rank decays past
a buffer (10 / 15 / 20) — instead of selling the instant they leave the Top 5 —
improve risk-adjusted returns by cutting turnover, without sacrificing momentum alpha?

**Script:** [`run_buffer_experiment.py`](../../run_buffer_experiment.py)
**Run:** `py run_buffer_experiment.py`

## What was held fixed (baseline, unchanged)

Pure 12-1 cross-sectional momentum · Top 5 · quarterly · equal weight · same
universe filters · same Indian-equity cost model · same dates · **no** stops,
DD-liquidation, cooldown, regime, or blending. The **only** thing that changes
between variants is the ranking buffer.

## The one change — buffered selection

At each quarterly rebalance ([`select_with_buffer`](../../run_buffer_experiment.py)):

1. Keep each currently-held stock whose momentum rank is still within the buffer
   (rank 1 = best). A name that has dropped out of the universe entirely has
   rank = ∞ and is therefore sold.
2. Fill the remaining slots (up to 5) with the best-ranked stocks not already held.

Portfolio size stays fixed at 5. `buffer = 5` reproduces the baseline exactly
("sell on leaving the Top 5"), which is how the Baseline column is generated —
no separate code path.

## Data-quality fix (important — read this)

The first run reproduced the user's quoted baseline **exactly** (CAGR 21.45%,
MaxDD **−68.10%**, final ₹82,10,060), confirming the harness is faithful. But
−68% turned out to be an **artifact**: `2026-05-28` is the only date in the
sample with <90% price coverage (31 of 49 stocks). The valuation code marked the
18 missing holdings to **zero** for that one day, fabricating a ~−68% one-day
crash that fully recovered the next session (a +367% "daily return" on the 29th).
This single day dominated every drawdown/volatility number and randomly punished
whichever variant held more of the missing names (Buffer15 printed a nonsense
−84% DD / 102% annual vol).

**Fix:** daily valuation now forward-fills a missing close (carry last price)
instead of zeroing the position. Signals and trade-execution prices still use the
raw panel, so the baseline *strategy* is untouched — only the bogus mark-to-zero
is removed. All figures below are post-fix and are the ones to trust.

All metrics are **net of costs** (the baseline the user quoted is net).

## Results

| Metric | Baseline | Buffer10 | Buffer15 | Buffer20 |
|---|---:|---:|---:|---:|
| CAGR | 21.45% | 26.51% | 25.85% | **26.25%** |
| Total Return | 1542% | 2857% | 2642% | 2771% |
| Final Value | ₹82.1L | ₹147.9L | ₹137.1L | ₹143.5L |
| Max Drawdown | −40.72% | −41.69% | −40.25% | **−39.85%** |
| Sharpe | 0.67 | 0.90 | 0.87 | **0.90** |
| Calmar | 0.53 | 0.64 | 0.64 | **0.66** |
| Annual Vol | 22.20% | 22.28% | 22.22% | 22.07% |
| Total Trades (exec) | 414 | 365 | 349 | **338** |
| Txn Costs | ₹3.69L | ₹3.91L | ₹3.44L | **₹2.62L** |
| Cost Drag (CAGR pts) | 0.77% | 0.58% | 0.46% | **0.40%** |
| Avg Turnover / rebal | 48.0% | 31.8% | 27.0% | **23.2%** |
| Recovery (deepest DD) | 268d | 236d | 256d | **148d** |

*(Deepest drawdown = COVID, trough 2020-03-23, for every variant.)*

## Read-out

- **Turnover fell as designed:** 48% → 23% per rebalance; executed trades 414 → 338
  (−18%); costs ₹3.69L → ₹2.62L (−29%) at Buffer20.
- **Alpha was not sacrificed — it improved.** Every buffer *beat* the baseline CAGR
  (+4.4 to +5.1 pts). The uplift (~+5 pts) is far larger than the cost saving
  (~0.4 pt of drag), so it is not a cost story: letting a still-strong name keep
  running rather than booking it the moment it slips to rank 6 captures more of
  momentum's persistence (avoids churning winners).
- **Risk held or improved:** volatility flat (~22%), max DD essentially unchanged
  (−40%), Sharpe 0.67 → ~0.90, Calmar 0.53 → 0.66. Buffer20 also recovered from
  COVID fastest (148 vs 268 days).
- **Diminishing returns past ~10–15.** Most of the CAGR/Sharpe gain is already
  there at Buffer10; widening to 15/20 mainly keeps buying down turnover and cost.

## Recommendation

**Buffer20** is the best all-round balance: it retains 122% of baseline CAGR
(26.25%), posts the shallowest drawdown (−39.85%), the best Calmar (0.66), the
lowest turnover (23.2%), the fewest trades (338), and the lowest costs (₹2.62L,
−29%). If you prefer the single highest return and don't mind ~50% more cost,
**Buffer10** edges CAGR (26.51%) at a slightly deeper DD.

Either way the conclusion is unambiguous: **a ranking buffer strictly dominates
selling-on-exit here** — lower turnover, lower cost, and *higher* risk-adjusted
return. No further optimisation was done; this experiment only measures the
buffer effect.

## Files

- `report.png` — equity, drawdown, trade-count, cost, rolling-3Y-CAGR panels
- `report.txt` — full 16-metric comparison + year-wise table + recommendation
- `comparison.csv` — machine-readable per-variant metrics
- `yearwise_returns.csv` — calendar-year returns per variant
