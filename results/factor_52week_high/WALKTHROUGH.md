# 52-Week-High Proximity — Factor Experiment Walkthrough

_Period 2012-01-03 .. 2026-05-29. Initial capital Rs 500,000. All figures **net** of the Indian delivery cost model._

## 1. What was tested

A single new **price-only** ranking factor, the **52-Week-High Proximity**:

```
score = current_close / max(close over the last 252 trading days)
```
Range (0, 1]; a score of 1.0 means the stock is sitting at its one-year high, higher = better rank. It is a *level* (anchoring) signal rather than a path-dependent cumulative return — the property that, per George & Hwang (2004, *Journal of Finance*), carries momentum's under-reaction edge with **lower crash risk**. This is a direct attempt to address the deep momentum drawdown measured earlier on this universe.

## 2. What was held fixed (engine frozen, nothing tuned)

| Component | Setting |
|---|---|
| Backtest engine | `run_buffered_backtest` — reused unchanged |
| Universe | survivorship-free bhavcopy, top-500 by liquidity, PIT, equity-only |
| Costs | full Indian delivery cost model (net) |
| Rebalance | quarterly |
| Buffer | Buffer20 |
| Sizing | Top10, equal weight, whole-share rounding |
| Execution | identical engine mechanics |

Variants **C** and **D** are produced by the *same* validated 50/50 momentum+low-vol blend (`make_blend_scorer`); they differ **only** in the ranking leg (12-1 momentum vs 52-week-high). So D minus C isolates the factor and nothing else.

## 3. Headline results (Top10 / quarterly / Buffer20, net)

| Variant | CAGR | MaxDD | Sharpe | Calmar | Alpha | Vol | Beta | Trades | Turnover | Costs (Rs) |
|---|---|---|---|---|---|---|---|---|---|---|
| A. Pure Momentum | 18.1% | -56.3% | 0.41 | 0.32 | +12.8% | 28.2% | 0.05 | 888 | 59% | 230,259 |
| B. 52-Week High | 17.8% | -42.3% | 0.50 | 0.42 | +12.3% | 22.4% | 0.04 | 1091 | 92% | 541,754 |
| C. Mom + LowVol | 17.4% | -33.5% | 0.69 | 0.52 | +11.6% | 15.7% | 0.03 | 776 | 42% | 214,926 |
| D. 52WH + LowVol | 9.1% | -28.9% | 0.19 | 0.31 | +3.2% | 13.8% | 0.02 | 887 | 61% | 162,937 |

_Benchmark: NIFTY 500 price index CAGR 12.6% (true TRI ~ 13.9%)._

## 4. Success criterion (pre-registered)

> Variant **D** must improve **Sharpe and/or CAGR** versus Variant **C** without materially worsening drawdown (defined up front as MaxDD more than 3 pts deeper).

- C (champion): CAGR **17.4%**, Sharpe **0.69**, MaxDD **-33.5%**
- D (candidate): CAGR **9.1%**, Sharpe **0.19**, MaxDD **-28.9%**
- delta (D − C): dCAGR **-8.3%**, dSharpe **-0.50**, dMaxDD **+4.6%** (shallower)

### Verdict: **FAIL** — D does not clear the bar; the champion stands.

## 5. Split-sample validation

Realized span split at its midpoint (2019-03-14); each half measured independently. A factor that is real should not live in only one half.

| Variant | CAGR H1 | Sharpe H1 | MaxDD H1 | CAGR H2 | Sharpe H2 | MaxDD H2 |
|---|---|---|---|---|---|---|
| A. Pure Momentum | 5.3% | -0.04 | -56.3% | 32.4% | 0.91 | -38.6% |
| B. 52-Week High | 22.2% | 0.78 | -33.4% | 13.5% | 0.29 | -42.3% |
| C. Mom + LowVol | 18.1% | 0.88 | -18.8% | 16.6% | 0.57 | -33.5% |
| D. 52WH + LowVol | 9.7% | 0.26 | -22.8% | 8.6% | 0.13 | -26.4% |

D-vs-C Sharpe edge: half1 **-0.62**, half2 **-0.43** → **consistent sign** across halves.

## 6. Rolling-window validation

| Variant | Roll-3y CAGR min | median | max | Roll-1y Sharpe median |
|---|---|---|---|---|
| A. Pure Momentum | -8.5% | 21.8% | 54.2% | 0.28 |
| B. 52-Week High | -3.3% | 17.0% | 58.1% | 0.49 |
| C. Mom + LowVol | 2.4% | 22.6% | 36.3% | 0.78 |
| D. 52WH + LowVol | -3.9% | 10.3% | 23.6% | 0.08 |

D's rolling-3y CAGR ≥ C's on **0%** of overlapping windows.

## 7. Concentration analysis (robustness only)

Top3 / Top5 / Top10 for each variant. This is a **robustness read, not a tuning knob** — Top10 remains the headline and N is not optimized.

| Variant | N | CAGR | MaxDD | Sharpe | Calmar | Alpha |
|---|---|---|---|---|---|---|
| A. Pure Momentum | 3 | 3.0% | -71.9% | -0.10 | 0.04 | -2.3% |
| A. Pure Momentum | 5 | 13.9% | -61.2% | 0.24 | 0.23 | +8.6% |
| A. Pure Momentum | 10 | 18.1% | -56.3% | 0.41 | 0.32 | +12.8% |
| B. 52-Week High | 3 | 23.4% | -47.7% | 0.56 | 0.49 | +17.9% |
| B. 52-Week High | 5 | 19.4% | -43.8% | 0.51 | 0.44 | +13.9% |
| B. 52-Week High | 10 | 17.8% | -42.3% | 0.50 | 0.42 | +12.3% |
| C. Mom + LowVol | 3 | 10.3% | -42.4% | 0.19 | 0.24 | +4.5% |
| C. Mom + LowVol | 5 | 13.7% | -36.6% | 0.41 | 0.37 | +7.9% |
| C. Mom + LowVol | 10 | 17.4% | -33.5% | 0.69 | 0.52 | +11.6% |
| D. 52WH + LowVol | 3 | 3.3% | -39.1% | -0.18 | 0.08 | -2.6% |
| D. 52WH + LowVol | 5 | 6.9% | -33.3% | 0.03 | 0.21 | +1.0% |
| D. 52WH + LowVol | 10 | 9.1% | -28.9% | 0.19 | 0.31 | +3.2% |

## 8. Caveats

- **Beta/Alpha are unreliable** and shown only because they were requested. The benchmark *daily-return* series (`get_benchmark_returns`) is corrupted — annualised vol ~77% with spurious ±30–40% daily jumps caused by a date-parse ambiguity (`dayfirst`/`mixed`) in `nifty500_tri.csv`. That inflates benchmark variance, collapsing Beta toward ~0 and overstating Jensen's Alpha (≈ CAGR − rf). It is a **pre-existing** benchmark-data issue (the earlier Top10 runs show the same +12.8% alpha), and per the brief the **benchmark methodology was not modified**. The CAGR-endpoint benchmark is unaffected, so **Excess vs Bmk (CAGR)** is the trustworthy relative metric and all conclusions here rest on CAGR / Sharpe / drawdown, not on Alpha/Beta. _Recommended separate fix: repair the benchmark CSV date parsing (out of scope for this frozen-engine task)._

- 52WH here uses **daily closes** for both the current price and the 1-year high (self-contained on the close panel). Using intraday highs is a defensible alternative spec, not a tuning parameter — left for a separate robustness run.

- All conclusions are **net of costs** on the survivorship-free universe; no parameter was searched and the engine, costs, universe, rebalance, buffer, sizing, and execution are untouched.

## 9. Reproduce

```
py run_52week_high.py
```
Outputs: `results/factor_52week_high/{comparison.csv, concentration.csv, report.txt, report.png, WALKTHROUGH.md}`