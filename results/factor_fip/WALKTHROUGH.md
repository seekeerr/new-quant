# Frog-in-the-Pan (FIP) — Factor Experiment Walkthrough

_Period 2012-01-03 .. 2026-05-29. Initial capital Rs 500,000. All figures **net** of the Indian delivery cost model._

## 1. What was tested

A single new **price-only** ranking factor, **Frog-in-the-Pan (FIP)**:

```
FIP score   = percentile(12-1 momentum) + percentile(consistency)
consistency = fraction of POSITIVE daily returns over the 12-1
              formation window [T-252, T-21]
```
Per Da, Gurun & Warachka (2014, *RFS*), momentum built from **continuous** information (many small up-days) persists, while momentum from **discrete** jumps reverses. FIP keeps the existing 12-1 momentum return and adds a consistency tilt so that, among similar-momentum names, smoother accumulators rank higher. This is a momentum-*quality* refinement distinct from the earlier residual-momentum test (which adjusted for beta, not path smoothness).

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

The momentum leg of FIP **is** the existing validated 12-1 momentum. Variants **C** and **D** are produced by the *same* validated 50/50 momentum+low-vol blend (`make_blend_scorer`); they differ **only** in the ranking leg (12-1 momentum vs FIP). So D minus C isolates the factor.

> Beta/Alpha are valid here — the benchmark CSV date-parse bug found earlier was repaired in `data/benchmark.py` (benchmark daily vol back to ~16%).

## 3. Headline results (Top10 / quarterly / Buffer20, net)

| Variant | CAGR | MaxDD | Sharpe | Calmar | Alpha | Beta | Vol | Turnover | Costs (Rs) |
|---|---|---|---|---|---|---|---|---|---|
| A. Momentum | 18.1% | -56.3% | 0.41 | 0.32 | +3.1% | 1.14 | 28.2% | 59% | 230,259 |
| B. Frog-in-the-Pan | 14.4% | -56.3% | 0.33 | 0.26 | +0.0% | 1.06 | 23.8% | 55% | 198,916 |
| C. Mom + LowVol | 17.4% | -33.5% | 0.69 | 0.52 | +5.4% | 0.74 | 15.7% | 42% | 214,926 |
| D. FIP + LowVol | 15.3% | -29.4% | 0.59 | 0.52 | +3.5% | 0.71 | 14.9% | 38% | 173,527 |

_Benchmark: NIFTY 500 price index CAGR 13.6% (true TRI ~ 14.9%)._

## 4. Success criterion (pre-registered)

> Variant **D** must improve **Sharpe and/or CAGR** versus Variant **C** without materially worsening drawdown (defined up front as MaxDD more than 3 pts deeper).

- C (champion): CAGR **17.4%**, Sharpe **0.69**, MaxDD **-33.5%**
- D (candidate): CAGR **15.3%**, Sharpe **0.59**, MaxDD **-29.4%**
- delta (D − C): dCAGR **-2.1%**, dSharpe **-0.10**, dMaxDD **+4.1%** (shallower)

### Verdict: **FAIL** — D does not clear the bar; the champion stands.

## 5. Split-sample validation

Realized span split at its midpoint (2019-03-14); each half measured independently. A real factor should not live in only one half.

| Variant | CAGR H1 | Sharpe H1 | MaxDD H1 | CAGR H2 | Sharpe H2 | MaxDD H2 |
|---|---|---|---|---|---|---|
| A. Momentum | 5.3% | -0.04 | -56.3% | 32.4% | 0.91 | -38.6% |
| B. Frog-in-the-Pan | 7.5% | 0.04 | -49.7% | 21.8% | 0.61 | -45.9% |
| C. Mom + LowVol | 18.1% | 0.88 | -18.8% | 16.6% | 0.57 | -33.5% |
| D. FIP + LowVol | 18.7% | 0.94 | -19.1% | 11.9% | 0.33 | -29.4% |

D-vs-C Sharpe edge: half1 **+0.06**, half2 **-0.24** → **sign flips (fragile)** across halves.

## 6. Rolling-window validation

| Variant | Roll-3y CAGR min | median | max | Roll-1y Sharpe median |
|---|---|---|---|---|
| A. Momentum | -8.5% | 21.8% | 54.2% | 0.28 |
| B. Frog-in-the-Pan | -12.0% | 18.9% | 50.9% | 0.37 |
| C. Mom + LowVol | 2.4% | 22.6% | 36.3% | 0.78 |
| D. FIP + LowVol | 4.6% | 17.8% | 35.8% | 0.79 |

D's rolling-3y CAGR ≥ C's on **19%** of overlapping windows.

## 7. Concentration analysis (robustness only)

Top3 / Top5 / Top10 for each variant — a **robustness read, not a tuning knob**. Top10 remains the headline and N is not optimized.

| Variant | N | CAGR | MaxDD | Sharpe | Calmar | Alpha |
|---|---|---|---|---|---|---|
| A. Momentum | 3 | 3.0% | -71.9% | -0.10 | 0.04 | -12.1% |
| A. Momentum | 5 | 13.9% | -61.2% | 0.24 | 0.23 | -0.8% |
| A. Momentum | 10 | 18.1% | -56.3% | 0.41 | 0.32 | +3.1% |
| B. Frog-in-the-Pan | 3 | 11.0% | -73.8% | 0.14 | 0.15 | -3.8% |
| B. Frog-in-the-Pan | 5 | 13.6% | -71.0% | 0.26 | 0.19 | -1.1% |
| B. Frog-in-the-Pan | 10 | 14.4% | -56.3% | 0.33 | 0.26 | +0.0% |
| C. Mom + LowVol | 3 | 10.3% | -42.4% | 0.19 | 0.24 | -1.5% |
| C. Mom + LowVol | 5 | 13.7% | -36.6% | 0.41 | 0.37 | +2.0% |
| C. Mom + LowVol | 10 | 17.4% | -33.5% | 0.69 | 0.52 | +5.4% |
| D. FIP + LowVol | 3 | 11.1% | -34.1% | 0.24 | 0.32 | -0.7% |
| D. FIP + LowVol | 5 | 11.0% | -32.8% | 0.28 | 0.34 | -0.7% |
| D. FIP + LowVol | 10 | 15.3% | -29.4% | 0.59 | 0.52 | +3.5% |

## 8. Caveats

- FIP here uses **fraction of positive days** as the consistency proxy, exactly as specified. The literature's signed information-discreteness (`sign(PRET)·(%neg−%pos)`) is an alternative spec, not a tuning parameter — left for a separate robustness run.

- All conclusions are **net of costs** on the survivorship-free universe; no parameter was searched and the engine, costs, universe, rebalance, buffer, sizing, and execution are untouched.

## 9. Reproduce

```
py run_fip.py
```
Outputs: `results/factor_fip/{comparison.csv, concentration.csv, report.txt, report.png, WALKTHROUGH.md}`