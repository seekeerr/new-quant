# Phase 2B — Experiment #2: Portfolio Construction — WALKTHROUGH

## The one question
**Holding the frozen champion's EXACT Top10 selection fixed, can a better position-sizing
scheme improve risk-adjusted return?** Only portfolio construction is tested — no new
signal, no parameter tuning, no change to which names are held.

## What is held FROZEN
Universe, signals, benchmark, costs, rebalance schedule, Buffer20, execution assumptions —
and the **holdings selection itself**. The champion's Top10 names per rebalance are computed
ONCE (variant A) and **replayed verbatim** for B/C/D. Identical-SELECTION integrity check
(same names every rebalance, A vs B/C/D): **PASS**.

Note on Min-Variance: as a true optimizer it may size some of the 10 selected names to ~0
(corner solutions), so its *funded* name count is slightly below 10. That is a sizing
decision under test — not a selection change — and is captured in the concentration metrics.

The frozen engine (`run_buffered_backtest`) is not edited. Sizing is tested through a
weighting-aware sibling loop (`run_weighted_backtest`) whose trade mechanics — cost model,
forward-filled valuation, sell-then-buy ordering, affordability — are copied verbatim. The
ONLY deviation is the per-name target capital: `portfolio_value / N` (equal) becomes
`portfolio_value * weight_i`.

## The four sizing schemes (champion = Mom+LowVol / Top10 / Quarterly / Buffer20)
- **A. Equal Weight** — 1/N. The current champion. Baseline.
- **B. Inverse Volatility** — w_i ∝ 1/σ_i (lower-vol names larger).
- **C. Equal Risk Contribution (ERC)** — true ERC: each name contributes equal portfolio
  variance, solved long-only sum-to-1 (Maillard-Roncalli-Teiletche), not the inverse-vol
  approximation in `portfolio/constructor.py`.
- **D. Minimum Variance** — long-only argmin wᵀΣw, sum-to-1.

## Risk model
Daily-return covariance Σ over a fixed **252-day** lookback — the champion's own
volatility window, **inherited, not tuned**. The same Σ feeds B/C/D so the comparison is clean.
Names without enough history fall back to an equal share (kept funded so holdings stay identical).

## Metrics reported
CAGR (net & gross) · Sharpe · Calmar · Sortino · Max Drawdown · Alpha · Beta · Volatility ·
Turnover/rebalance · Transaction costs · Cost drag · Time underwater.

## Validation (same discipline as Phase 1)
- **Split sample** — first vs second half CAGR/Sharpe.
- **Rolling 3-year windows** — min/median across all 3y windows.
- **Concentration** — avg # names (10 for all, by construction) and weight-HHI / max name
  weight (these DIFFER by scheme — the whole point).

## Success criterion (pre-registered, judged NET of costs)
A variant **PASSES** if it improves **Sharpe and/or Calmar by >= 0.03** vs Equal Weight
**without** reducing CAGR by more than **1.0 pt**. Best passer by Sharpe wins;
if none pass, Equal Weight stays.

## Run
```
py run_construction_weighting.py
```

## Outputs (`results/construction_weighting/`)
`report.txt` · `report.png` · `comparison.csv` · `WALKTHROUGH.md`.
