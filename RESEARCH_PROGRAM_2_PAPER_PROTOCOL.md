# Program #2 — Parallel Paper-Trading Bake-Off Protocol (A+B vs A+C)

**Opened:** 2026-07-06 · **Status:** pre-registration (before any forward data). **No live capital.**
**Parent:** `RESEARCH_PROGRAM_2_FINDINGS.md` · hardening in `results/program2_ensemble_validation/`,
`results/program2_ab_hardening/`.

## 0. Purpose & scope (read first)

The A+B vs A+C production choice could not be settled by backtest: A+C(0.3) is the only ensemble
that passes all six gates but is **cost-fragile** (failed ×10 stress) and breakout-parameter-sensitive;
A+B is more robust everywhere (Sharpe 0.95, survives ×10, parameter-stable) but misses the roll-3y
gate by 0.5pt. Per the user decision (2026-07-06), **both run in parallel forward paper trading and
the live winner is decided on forward out-of-sample evidence.**

This is a **returns/robustness bake-off of two research candidates** — a *different purpose* from the
champion's `PAPER_TRADING_PROTOCOL.md`, which validates the operator/process on the frozen champion
and where returns are explicitly *not* a criterion. Keep the two programs separate. This one does not
touch `paper_trading/` or the frozen commit.

## 1. The two candidates (frozen specs)

Both: survivorship-free universe, Top-10 equal-weight per sleeve, whole-share, ₹5,00,000 paper book,
net of the full Indian cost model. Starting target portfolios generated in `results/program2_paper/`
(`AC_03_target.csv`, `AB_05_target.csv`) — as-of the latest cached date; **refresh data before live start.**

- **A+C(0.3):** 70% champion [Mom+LowVol, Top-500, quarterly] + 30% breakout [volume-confirmed
  breakout, Top-500, **monthly**]. ~20 names. Backtest: 18.9% CAGR, all six gates, but cost-fragile.
- **A+B(0.5):** 50% champion [Mom+LowVol, Top-500, quarterly] + 50% smalltail [Mom+LowVol, rank-band
  300-1000, quarterly]. ~19 names (the champion & smalltail bands overlap in rank 300-500, so a name
  there can be held by both sleeves and concentrate — an accepted property). Backtest: 19.4% CAGR,
  Sharpe 0.95, robust; misses roll-3y by 0.5pt.

## 2. Tracking method

- Each sleeve rebalances on its own cadence (champion/smalltail quarterly; breakout monthly). The
  operator records **would-be fills at live EOD/next-open prices**, applying the cost model, into a
  per-candidate append-only paper ledger (mirror the champion protocol's ledger discipline).
- Record every cycle, per candidate: realized net return, **realized slippage per side vs model**
  (per liquidity tier), turnover, drawdown, per-name execution-vs-intended tracking error, corp actions.
- Minimum window: **≥ 2 quarterly champion rebalances AND ≥ 6 monthly breakout rebalances** (~6 months)
  before any decision; target ~3-4 quarters. Returns over a short window are noisy — see §3.

## 3. PRE-REGISTERED live-decision criteria (pinned now, not rationalized later)

Forward paper trading adds exactly what backtest could not: **realized fills/slippage, real corp
actions, live discipline.** Short-window *returns* are noisy and must NOT dominate. The decision is
therefore weighted toward the thing that actually differentiates the candidates — realized cost.

1. **PRIMARY — realized cost/slippage (the A+C fragility test).** A+C's backtest weakness is cost
   sensitivity concentrated in the higher-turnover monthly breakout sleeve. Measure realized slippage
   on the breakout sleeve vs the cost model.
   - If breakout-sleeve realized slippage runs **> 1.5× model** (or materially above the champion
     sleeve's) for the window → A+C's thin edge is confirmed fragile → **choose A+B.**
   - If A+C's realized slippage tracks model (≤ 1.5×) → its all-gate backtest edge is real live → A+C stays viable.
2. **SECONDARY — drawdown behaviour** (only if a drawdown occurs in-window): compare realized DD to
   the −34% (A+C) / −30% (A+B) expectations; a materially deeper-than-expected DD on either is a mark
   against it.
3. **TERTIARY — realized net return**, but only as a tie-break and only if the gap is large relative
   to its noise (a few months of returns is a weak signal; do not overfit to it).
4. **DEFAULT / TIE-BREAK (pre-committed):** if the forward evidence is **inconclusive**, choose **A+B**
   — it is the more backtest-robust candidate (higher Sharpe, survives ×10 stress, parameter-stable);
   inconclusive forward data should not overturn that, and pre-committing the default prevents the
   decision from stalling or being reverse-engineered.

## 4. Guardrails

- **No live capital** until the decision is made per §3 and the champion's operational readiness
  (§`PAPER_TRADING_PROTOCOL.md` Go/No-Go) is separately satisfied for whichever candidate wins.
- Both strategies are **frozen** for the duration — a bad paper *return* does not prompt a strategy
  change (that would re-open closed research). Only the A+B-vs-A+C *selection* is open.
- **Data freshness:** the cache ends at the last download; regenerate target portfolios on fresh EOD
  data before the first live paper cycle.
- The losing candidate is retained as a documented backup, not deleted.

## 5. What a decision looks like

After the window: tabulate realized slippage/return/DD/TE per candidate, apply §3 in order, and record
the choice + evidence. Then the winner enters the champion-style operator-validation Go/No-Go before
any real money. Expected realistic net (post-tax, per the champion audit) is **~15-18%**, not the gross
backtest CAGR — set expectations accordingly.
