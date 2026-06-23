# Phase 2B — Experiment #1: Short-Term Reversal — WALKTHROUGH

## The one question
**Can a Short-Term Reversal style compete with the frozen Momentum + LowVol champion
inside the existing framework?** Reversal is the canonical *price-only, non-momentum,
negatively-correlated* diversifier of the champion's offensive leg — the top fundamentals-free
candidate from `PHASE2B_STRATEGY_LANDSCAPE.md`.

## What is held FROZEN (nothing modified)
Engine (`run_buffered_backtest`), cost model, universe construction
(`TopNTurnoverUniverseBuilder`, equity-only top-500-liquid, survivorship-free), benchmark
methodology, and the rebalance framework (equal weight / Buffer20 / quarterly) are **all reused
verbatim**. Reversal enters ONLY as a new drop-in scorer (`compute_str_reversal`) — exactly as
every Phase-1 factor did.

## The signal (the only new code)
`compute_str_reversal`: rank by the **most recent 21-trading-day return**;
**lowest return = highest rank** (buy recent losers). No skip, no smoothing, **no parameter search**.

## Variants
- **A. Short-Term Reversal** — Top3 / Top5 / Top10, **quarterly** first.
  Because a 21-day signal is fast-decaying and turned out high-turnover
  (max quarterly turnover/reb 93.3%), a MONTHLY run was ALSO executed and the difference reported.
- **C. Champion** — Momentum + LowVol (0.5/0.5), Top10 / quarterly / Buffer20 — the bar to beat.

Reversal is **not** blended with momentum.

## Metrics reported
CAGR (net & gross) · Sharpe · Calmar · Sortino · Max Drawdown · Alpha · Beta · Volatility ·
Turnover/rebalance · Transaction costs · Cost drag · Time underwater.

## Validation (same discipline as Phase 1)
- **Split sample** — first-half vs second-half CAGR/Sharpe (the FIP sign-flip test).
- **Rolling 3-year windows** — min/median across all 3y windows.
- **Concentration** — avg # names held and name-level HHI (rebuilt from the trade log).

## Why these costs matter
Short-term reversal is the most cost-sensitive style tested: it churns the bottom of the
return distribution every rebalance. The verdict is judged **net of the full Indian delivery
cost model**, never gross — a gross-only "edge" that costs eat is not a viable style.

## Pre-registered verdict (judged on the BEST reversal config by Sharpe, all NET)
PASS — Mean Reversion merits further research, IF ALL of:
1. net CAGR > NIFTY 500 benchmark CAGR;
2. net Jensen alpha > 0;
3. Sharpe >= 0.45 (materially positive, ~2/3 of the champion);
4. survives split-sample (CAGR positive in BOTH halves; no sign-flip).
Otherwise: **FAIL — Momentum remains the superior style.**

## Run
```
py run_short_term_reversal.py
```

## Outputs (`results/short_term_reversal/`)
`report.txt` · `report.png` · `comparison.csv` · `WALKTHROUGH.md`.
