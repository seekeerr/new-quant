# Low-MAX / Anti-Lottery — Factor Experiment Walkthrough

_Period 2012-01-03 .. 2026-05-29. Initial capital Rs 500,000. All figures **net** of the Indian delivery cost model._

## 1. What was tested

A single new **price-only** ranking factor, **Low-MAX (anti-lottery)**:

```
MAX   = maximum single-day return over the last 21 trading days
score = -MAX            (lower MAX = better rank)
```
Per Bali, Cakici & Whitelaw (2011, *JFE*, "Maxing Out"), investors overpay for lottery-like stocks that just printed an extreme up-day; those names subsequently underperform. Avoiding them earns a premium documented to be distinct from plain volatility, and plausibly **stronger in retail-heavy India**.

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

Variants **C** and **D** are produced by the *same* validated 50/50 momentum+low-vol blend (`make_blend_scorer`); they differ **only** in the ranking leg (12-1 momentum vs Low-MAX). So D minus C isolates the factor.

> Note: the benchmark CSV date-parse bug found in the prior experiment was repaired this session (`data/benchmark.py`), so **Beta and Jensen's Alpha below are valid** (benchmark daily vol back to ~16%).

## 3. Headline results (Top10 / quarterly / Buffer20, net)

| Variant | CAGR | MaxDD | Sharpe | Calmar | Alpha | Vol | Beta | Trades | Turnover | Costs (Rs) |
|---|---|---|---|---|---|---|---|---|---|---|
| A. Momentum | 18.1% | -56.3% | 0.41 | 0.32 | +3.1% | 28.2% | 1.14 | 888 | 59% | 230,259 |
| B. Low-MAX | 10.7% | -38.2% | 0.29 | 0.28 | -0.9% | 14.8% | 0.68 | 1044 | 84% | 224,494 |
| C. Mom + LowVol | 17.4% | -33.5% | 0.69 | 0.52 | +5.4% | 15.7% | 0.74 | 776 | 42% | 214,926 |
| D. Low-MAX + LowVol | 11.8% | -26.0% | 0.45 | 0.46 | +1.2% | 11.9% | 0.55 | 851 | 55% | 175,500 |

_Benchmark: NIFTY 500 price index CAGR 13.6% (true TRI ~ 14.9%)._

## 4. Success criterion (pre-registered)

> Variant **D** must improve **Sharpe and/or CAGR** versus Variant **C** without materially worsening drawdown (defined up front as MaxDD more than 3 pts deeper).

- C (champion): CAGR **17.4%**, Sharpe **0.69**, MaxDD **-33.5%**
- D (candidate): CAGR **11.8%**, Sharpe **0.45**, MaxDD **-26.0%**
- delta (D − C): dCAGR **-5.5%**, dSharpe **-0.24**, dMaxDD **+7.5%** (shallower)

### Verdict: **FAIL** — D does not clear the bar; the champion stands.

## 5. Split-sample validation

Realized span split at its midpoint (2019-03-14); each half measured independently. A real factor should not live in only one half.

| Variant | CAGR H1 | Sharpe H1 | MaxDD H1 | CAGR H2 | Sharpe H2 | MaxDD H2 |
|---|---|---|---|---|---|---|
| A. Momentum | 5.3% | -0.04 | -56.3% | 32.4% | 0.91 | -38.6% |
| B. Low-MAX | 8.9% | 0.20 | -24.9% | 12.5% | 0.36 | -32.2% |
| C. Mom + LowVol | 18.1% | 0.88 | -18.8% | 16.6% | 0.57 | -33.5% |
| D. Low-MAX + LowVol | 13.5% | 0.69 | -12.4% | 10.2% | 0.28 | -26.0% |

D-vs-C Sharpe edge: half1 **-0.19**, half2 **-0.29** → **consistent sign** across halves.

## 6. Rolling-window validation

| Variant | Roll-3y CAGR min | median | max | Roll-1y Sharpe median |
|---|---|---|---|---|
| A. Momentum | -8.5% | 21.8% | 54.2% | 0.28 |
| B. Low-MAX | -6.3% | 12.7% | 29.0% | 0.40 |
| C. Mom + LowVol | 2.4% | 22.6% | 36.3% | 0.78 |
| D. Low-MAX + LowVol | 4.1% | 15.5% | 25.2% | 0.63 |

D's rolling-3y CAGR ≥ C's on **26%** of overlapping windows.

## 7. Concentration analysis (robustness only)

Top3 / Top5 / Top10 for each variant — a **robustness read, not a tuning knob**. Top10 remains the headline and N is not optimized.

| Variant | N | CAGR | MaxDD | Sharpe | Calmar | Alpha |
|---|---|---|---|---|---|---|
| A. Momentum | 3 | 3.0% | -71.9% | -0.10 | 0.04 | -12.1% |
| A. Momentum | 5 | 13.9% | -61.2% | 0.24 | 0.23 | -0.8% |
| A. Momentum | 10 | 18.1% | -56.3% | 0.41 | 0.32 | +3.1% |
| B. Low-MAX | 3 | 5.7% | -38.2% | -0.05 | 0.15 | -4.8% |
| B. Low-MAX | 5 | 8.2% | -33.3% | 0.10 | 0.25 | -3.1% |
| B. Low-MAX | 10 | 10.7% | -38.2% | 0.29 | 0.28 | -0.9% |
| C. Mom + LowVol | 3 | 10.3% | -42.4% | 0.19 | 0.24 | -1.5% |
| C. Mom + LowVol | 5 | 13.7% | -36.6% | 0.41 | 0.37 | +2.0% |
| C. Mom + LowVol | 10 | 17.4% | -33.5% | 0.69 | 0.52 | +5.4% |
| D. Low-MAX + LowVol | 3 | 6.7% | -43.9% | 0.01 | 0.15 | -3.3% |
| D. Low-MAX + LowVol | 5 | 9.1% | -33.0% | 0.20 | 0.28 | -1.3% |
| D. Low-MAX + LowVol | 10 | 11.8% | -26.0% | 0.45 | 0.46 | +1.2% |

## 8. Caveats

- Low-MAX uses the **single** maximum daily return over the last 21 days, exactly as specified. The literature's MAX5 (mean of the 5 largest up-days) is an alternative spec, not a tuning parameter — left for a separate robustness run.

- All conclusions are **net of costs** on the survivorship-free universe; no parameter was searched and the engine, costs, universe, rebalance, buffer, sizing, and execution are untouched.

## 9. Reproduce

```
py run_low_max.py
```
Outputs: `results/factor_low_max/{comparison.csv, concentration.csv, report.txt, report.png, WALKTHROUGH.md}`