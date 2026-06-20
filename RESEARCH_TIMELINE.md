# Research Timeline — Phase 1

Chronological record of the momentum research program on Indian equities (NSE / NIFTY 500).
All performance figures are net of the Indian delivery cost model. "Honest universe" =
survivorship-free daily bhavcopy, equity-only, top-500 liquid, point-in-time.

| Stage | Event | Outcome |
|---|---|---|
| 1 | **Initial momentum research** | Pure 12-1 momentum (Jegadeesh-Titman) stood up on an early yfinance / current-constituents universe. Real signal, but crash-prone. |
| 2 | **Fallback-universe bug discovered** | A silent fallback reused a fixed name list → inflated, biased results. Flagged. |
| 3 | **Bhavcopy migration** | Switched to the full daily NSE bhavcopy cross-section, corp-action adjusted → survivorship-free universe. |
| 4 | **Survivorship-free validation** | Re-ran momentum honestly. The ~30%+ CAGRs collapsed — exposed as survivorship-bias mirages (biased-500 ~47%, fallback-49 ~26%). |
| 5 | **ETF contamination discovered & removed** | Bhavcopy pool held ETFs / gold / liquid / index-fund units (ISIN `INF`, `IN9`). Their structural low-vol polluted rankings. Fixed with an equity-only (`INE`) whitelist → 3,291 equities. |
| 6 | **Benchmark alignment audit** | Benchmark CAGR re-measured over the strategy's realized post-warmup span; valuation NaN handling fixed so partial-data days don't fake one-day crashes. |
| 7 | **Buffer / turnover sweep** | Ranking buffer tested (10/15/20); **Buffer20** adopted to cut turnover without losing alpha. |
| 8 | **Concentration (honest)** | Top3/5/10 swept on clean data. Concentration **hurts** (Top3 = 3% / −72% DD); **Top10 wins** — opposite of the biased result. |
| 9 | **Low-Vol blend — PASS** | Mom + LowVol lifted Sharpe **0.41 → 0.69**, MaxDD −56% → −33%, at ~17% CAGR. **Became the champion.** Vol-managed and trend overlays tested alongside → null (risk-only). |
| 10 | **Residual / "smart" momentum** | Beta-adjusted momentum: smoother ride (DD −27%, never a losing 3-yr window) but **not higher** return/Sharpe. |
| 11 | **Leverage scenarios** | 1.25×–2× with ~10% borrow: raises CAGR but **lowers Sharpe** and deepens drawdowns; 30% needs ruinous ~2.5×+. → **User decision: CASH ONLY, no leverage.** |
| 12 | **52-Week-High proximity — FAIL** | Standalone, it *beat* plain momentum (Sharpe 0.50 vs 0.41, −42% vs −56% crash) — a better offensive leg. But 52WH + LowVol degenerated to ~low-vol-only (Sharpe 0.19). |
| 13 | **Low-MAX / anti-lottery — FAIL** | A defensive factor; Low-MAX + LowVol = defence-on-defence (Sharpe 0.45, lowest DD −26%, but only 11.8% CAGR). Gives up the return engine. |
| 14 | **Benchmark CSV repair** | Found the `dayfirst/mixed` date-parse bug flipping 1,379/3,817 rows → 77% benchmark vol, beta≈0, +12% fake alpha. Fixed ISO-first → vol 16%, beta 0.74, alpha +5.4%, benchmark CAGR 13.6%. Beta/Alpha valid thereafter. |
| 15 | **Frog-in-the-Pan — FAIL** | Closest near-miss (FIP + LowVol Sharpe 0.59 vs 0.69) but **split-sample sign-flips** (won 2012–19, lost 2019–26) → fragile, regime-dependent. Consistency tilt even hurt standalone momentum. |
| 16 | **Phase-1 close** | Price-only search exhausted. Champion frozen. Recommendation: **B — Momentum + Quality pilot** (see `PHASE1_DECISION.md`). |

---

### Headline scoreboard (Top10 / quarterly / Buffer20, net)

| Variant | CAGR | MaxDD | Sharpe | Result |
|---|---|---|---|---|
| Pure Momentum | 18.1% | −56.3% | 0.41 | Base (crash-prone) |
| **Mom + LowVol (CHAMPION)** | **17.4%** | **−33.5%** | **0.69** | **Frozen** |
| Residual-Mom + LowVol | 16.2% | −27.2% | 0.68 | Smoother sibling |
| 52WH + LowVol | 9.1% | −28.9% | 0.19 | Fail |
| Low-MAX + LowVol | 11.8% | −26.0% | 0.45 | Fail |
| FIP + LowVol | 15.3% | −29.4% | 0.59 | Fail (fragile) |

**Honest ceiling, price-only + cash: ~17–18% CAGR.** Next lever is an offensive fundamental
factor (Value / Quality) — pending the bounded pilot in `PHASE1_DECISION.md`.
