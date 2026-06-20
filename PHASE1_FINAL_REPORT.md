# Phase 1 — Final Research Report
### Systematic momentum research on Indian equities (NSE / NIFTY 500)

**Status:** Price-only research phase complete. Champion frozen.
**Period under test:** 2012-01-03 → 2026-05-29 (after 1-year warmup), net of Indian delivery costs.
**Universe:** survivorship-free daily bhavcopy, corp-action adjusted, equity-only (ISIN `INE`), capped to the top-500 most liquid names point-in-time (3,291 equity symbols in the pool).
**Capital:** ₹500,000. **Benchmark:** NIFTY 500 price index, CAGR **13.6%** (true TRI ≈ 14.9%).

---

## 0. The frozen champion

| Strategy | **Momentum + LowVol** |
|---|---|
| Selection | Top **10**, equal weight |
| Signal | 0.5 × percentile(12-1 momentum) + 0.5 × percentile(low realised vol, 252d) |
| Rebalance | Quarterly |
| Turnover control | **Buffer20** (hold until rank decays past 20) |
| Execution | Signal at rebalance date, whole-share rounding, full Indian cost model |

**Champion metrics (net, fixed benchmark):**

| CAGR | MaxDD | Sharpe | Calmar | Vol | Alpha | Beta | Excess vs Bmk | Turnover | Worst 3-yr |
|---|---|---|---|---|---|---|---|---|---|
| **17.4%** | **−33.5%** | **0.69** | 0.52 | 15.7% | +5.4% | 0.74 | +3.8% | 42%/reb | **+2.4%** (never a losing 3-yr window) |

This is the real product. Everything below is the evidence that nothing price-only beats it.

---

## 1. Every experiment run

| # | Experiment | Script | Verdict |
|---|---|---|---|
| 1 | Pure 12-1 momentum (base factor) | `run_pure_momentum.py` | Baseline — real but crash-prone |
| 2 | Universe / liquidity validation | `run_universe_validation.py` | Infra established |
| 3 | Survivorship-free bhavcopy migration | `run_survivorship_validation.py` | **Critical fix** |
| 4 | ETF / fund contamination audit | (equity ISIN whitelist) | **Critical fix** |
| 5 | Ranking-buffer turnover sweep | `run_buffer_experiment.py` | Buffer20 adopted |
| 6 | Portfolio size — biased universe | `run_portfolio_size_experiment.py` | Exposed as bias artifact |
| 7 | Concentration — honest universe | `run_concentration_honest.py` | Top10 wins; concentration hurts |
| 8 | **Low-Volatility blend** | `run_momentum_lowvol.py` | **PASS — became champion** |
| 9 | Low-Vol only (bookend) | `run_momentum_lowvol.py` | Weak alone (defines floor) |
| 10 | Vol-managed momentum (Barroso) | `run_momentum_lowvol.py` | Null (risk overlay only) |
| 11 | Trend filter overlay | `run_trend_filter_experiment.py` | Null (risk overlay only) |
| 12 | Residual / beta-adjusted momentum | `run_smart_momentum.py` | Smoother, not higher |
| 13 | Leverage scenarios | `run_leverage_scenarios.py` | Lowers Sharpe → **cash-only decision** |
| 14 | 52-Week-High proximity | `run_52week_high.py` | **FAIL** |
| 15 | Low-MAX / anti-lottery | `run_low_max.py` | **FAIL** |
| 16 | Frog-in-the-Pan (FIP) | `run_fip.py` | **FAIL** (closest near-miss) |
| 17 | Benchmark CSV repair | `data/benchmark.py` | **Critical fix** |

---

## 2. Why each experiment passed or failed

**The single existence proof — Low-Vol blend (PASS).** Pairing 12-1 momentum (offence, the return engine) with low realised vol (defence, the risk reducer) lifted Sharpe from **0.41 → 0.69** and cut MaxDD from −56% → −33% *while keeping ~17% CAGR*. It cleared the pre-registered bar (net alpha > 0 **and** Sharpe materially up). This is the only factor that added risk-adjusted value, and it works because the two legs are **lowly correlated and play different roles**.

**Everything that only touched risk (null).** Trend filter, vol-managed exposure, and leverage all change the *shape* of the ride but not the engine's Sharpe. Leverage at 1.25× lifts CAGR to 19.2% but *lowers* Sharpe (0.71→0.66) and deepens MaxDD to −40%; 2× reaches 22.4% at −59% — buying return with proportional risk, not a better strategy. → **User decision: cash only, no leverage.**

**Everything that refined/replaced the momentum *leg* (all fail).** This is the core Phase-1 finding:

| Challenger | Standalone (B) | Blended w/ LowVol (D) | Why it failed |
|---|---|---|---|
| Residual momentum | 18.0% / 0.43 | 16.2% / 0.68 | Smoother (DD −27%) but no Sharpe/CAGR gain |
| 52-Week High | 17.8% / **0.50** | 9.1% / 0.19 | Strong *offence* alone, but low-vol names already sit at their highs → blend degenerates to ~low-vol-only |
| Low-MAX (anti-lottery) | 10.7% / 0.29 | 11.8% / 0.45 | A *defensive* factor; Low-MAX+LowVol = defence-on-defence, gives up the return engine |
| Frog-in-the-Pan | 14.4% / 0.33 | 15.3% / **0.59** | Closest, but **split-sample sign-flips** (won 2012–19, lost 2019–26) → fragile/regime-dependent |

*(standalone & blended shown as CAGR / Sharpe, Top10 net.)*

None of D beat champion C (Sharpe 0.69). The 52-Week-High result is the most useful by-product: as a **standalone** signal it is a *better* momentum than 12-1 (Sharpe 0.50 vs 0.41, −42% vs −56% crash), confirming George-Hwang crash-resistance on Indian data — but it does not combine with low-vol.

**Concentration (Top10 wins).** On honest data, concentrating *hurts*: pure-momentum Top3 = 3.0% CAGR / −72% DD (periodic micro-cap blow-ups); Top10 = 18.1% / −56%. Diversification is protective — the exact opposite of the biased-universe result that made Top3 look like a 28% path.

---

## 3. Final champion metrics

Momentum + LowVol, Top10 / quarterly / Buffer20, net of costs, fixed benchmark:

```
CAGR (net)        17.4%        Sharpe          0.69
CAGR (gross)      18.2%        Sortino         0.88
Max Drawdown     -33.5%        Calmar          0.52
Annual Vol        15.7%        Beta            0.74
Alpha (Jensen)    +5.4%        Excess vs Bmk   +3.8%
Turnover/reb      41.9%        Cost drag       0.79 pts
Txn costs       ~₹214,926      Time underwater 85.4%
Rolling 3-yr CAGR: min +2.4% | median +22.6% | max +36.3%   (never a losing 3-yr window)
```

Smoother sibling (if drawdown matters more than the last CAGR point): **Residual-Momentum + LowVol** ≈ 16.2% CAGR, Sharpe 0.68, MaxDD −27%.

---

## 4. Data-quality fixes applied

1. **Survivorship-free migration.** Moved from a current-constituents / yfinance universe to the **full daily bhavcopy** cross-section, corp-action adjusted, so delisted/suspended names are present point-in-time. (Also fixed a fallback-universe bug that silently reused a fixed name list.)
2. **ETF / fund de-contamination.** The raw bhavcopy panel included ETFs, gold/silver/liquid/index-fund units (ISIN `INF`) and DVR/special instruments (`IN9`). These are low-vol by construction and were **polluting the low-vol rankings**. Fixed with an equity-only whitelist (ISIN `INE`) → 3,291 genuine equities.
3. **Benchmark CSV repair** (see §7).
4. **Benchmark span alignment.** Benchmark CAGR is now measured over the strategy's *realized* span (post-warmup ~2012-01), not the config start — earlier mismatched windows flattered excess-return by ~2 points.
5. **Valuation NaN handling.** Forward-filled prices for daily valuation only (signals/execution still use raw closes) so a held name with a missing close on a partial-data day isn't marked to zero and faked into a one-day crash.

---

## 5. Survivorship-bias findings

Survivorship bias was the **dominant source of fake alpha** in this project.

| Source | Reported CAGR | Reality |
|---|---|---|
| Biased current-500 universe | ~47% | Mirage |
| Fallback-49 name list | ~26% | Mirage |
| Portfolio_size Top3 (biased) | ~28% | Mirage |
| **Honest universe, best config** | **~17.4%** | **Real** |

The user's **30% net-CAGR target is not reachable** on honest data; every 30%+ figure traces to bias. Crucially, the *direction* of effects flips on clean data: in the biased universe concentration looked great; on honest data it is destructive (Top3 −72% DD). **Lesson: clean the data before believing any factor result.**

---

## 6. ETF-contamination findings

The bhavcopy pool mixed non-equity instruments into the tradeable universe. Because ETFs and liquid/gold funds have **structurally low volatility and smooth returns**, they were disproportionately selected by the low-vol leg and by liquidity filters — inflating the apparent quality of any low-vol-tilted strategy. Removing them (equity ISIN `INE` whitelist) is what made the Mom+LowVol result trustworthy rather than an artifact of holding fund units. This fix is applied in every honest run via `load_equity_symbols()`.

---

## 7. Benchmark-repair findings

**Bug:** `data/benchmark.py` parsed the clean ISO `nifty500_tri.csv` with `pd.to_datetime(..., dayfirst=True, format="mixed")`, which **flipped month/day on 1,379 of 3,817 rows** (e.g. `2011-01-03` → 1 March 2011). After the chronological sort this interleaved values onto wrong dates and injected spurious ±30–40% daily "returns."

**Impact:** benchmark daily volatility blew up to **77%**, which inflated benchmark variance and **collapsed Beta toward ~0 and inflated Jensen's Alpha to ≈ CAGR − rf (~+12%)** in every run that used it (the 52-Week-High and concentration reports show the symptom).

**Fix:** a new ISO-first `_parse_dates` helper resolves explicit formats most-specific-first and never uses the day-first/mixed heuristic on unambiguous dates.

| | Before | After |
|---|---|---|
| Benchmark daily vol (ann.) | 77.6% | **16.2%** |
| Max daily move | 40.8% | 12.8% (real COVID day) |
| Diversified-basket beta | ~0.04 | **0.91** |
| Champion beta / alpha | 0.03 / +12% | **0.74 / +5.4%** |
| Benchmark CAGR | 12.6% | **13.6%** |

Beta/Alpha are valid from `run_low_max.py` / `run_fip.py` onward. Older result directories were **not** re-run and still carry the inflated alpha — read their `Excess vs Bmk (CAGR)` instead.

---

## 8. Lessons learned

1. **Data hygiene dominates signal research.** The three biggest "findings" (47% CAGR, the low-vol edge size, +12% alpha) were all data bugs. Audit survivorship, instrument type, and benchmark parsing *before* trusting any metric.
2. **The edge is a *pairing*, not a factor.** Momentum (offence) + low-vol (defence) works because the legs are lowly correlated and do different jobs. A second *defensive* factor (Low-MAX) or a *redundant* offensive one (52WH-within-low-vol) adds nothing.
3. **Refining the winning factor is a dead end here.** Residual, 52WH, Low-MAX, and FIP all tried to be a "smarter momentum" — none beat plain 12-1 momentum as the offensive leg.
4. **Validation discipline pays.** Pre-registered success bars + split-sample + rolling windows caught FIP's regime-dependent, sign-flipping edge that a single full-sample Sharpe would have sold as a win.
5. **On clean Indian data, diversify, don't concentrate.** Micro-cap blow-ups punish concentration.
6. **Risk overlays ≠ alpha.** Trend, vol-targeting, and leverage move risk around but don't raise the Sharpe of the engine.
7. **The honest ceiling on price-only, cash, is ~17–18% CAGR.** Accept it as the real number.

---

## 9. Remaining open hypotheses

**Offensive fundamental factors (the real remaining lever — require a point-in-time fundamentals panel):**
- **Value** (E/P or B/M) blended with momentum — the canonical *negatively-correlated* offensive diversifier of momentum (Asness-Moskowitz-Pedersen). Strong, well-documented Indian value premium. **Highest expected payoff.**
- **Quality / gross profitability** (Novy-Marx; QMJ) — profitable, stable firms; pairs defensively-offensively with momentum.
- **Earnings revisions / PEAD** — robust globally; highest data cost (needs estimates + announcement dates).

**Price-only leftovers (lower priority):**
- **52-Week-High as a standalone core** (Top5/Top3) — it beat momentum standalone; untested as its own product rather than a low-vol partner.
- **Short-term (1-month) reversal** — real in India but decays in weeks; needs a monthly rebalance, which conflicts with the frozen quarterly shell.
- Spec-robustness of failed factors (MAX5 vs MAX1, intraday-high 52WH, signed-ID FIP) — diagnostics, not new alpha.

---

## Recommendation

**→ B. Run a Momentum + Quality pilot.** Full justification and scope in **`PHASE1_DECISION.md`**.

In one line: price-only is exhausted and the only remaining honest lever is an *offensive fundamental* factor — but a full PIT platform (C) is unjustified until a **cheap, bounded** fundamentals pilot shows a positive, validated signal, and stopping now (A) would abandon the one avenue the evidence actively points to.
