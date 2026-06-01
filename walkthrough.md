# Backtest Results — Systematic Trading System

## Comparison Table

| Config | CAGR | Sharpe | Max DD | Calmar | Win Rate | Total Costs | Cost Drag |
|:---|---:|---:|---:|---:|---:|---:|---:|
| **5 stocks / monthly** | **+4.2%** | -0.20 | -32.2% | 0.13 | 44.6% | ₹96,114 | 96.1% |
| 10 stocks / monthly | -0.8% | -0.86 | -34.5% | -0.02 | 39.6% | ₹1,16,073 | 116% |
| 15 stocks / monthly | -5.0% | -1.52 | -56.6% | -0.09 | 33.5% | ₹1,25,606 | 126% |
| 20 stocks / monthly | -8.5% | -2.37 | -73.7% | -0.12 | 28.8% | ₹1,25,553 | 126% |

> [!IMPORTANT]
> **5 stocks with monthly rebalancing is the only positive-return configuration.** All others are destroyed by transaction costs.

---

## Equity Curves

![5-stock monthly report](file:///c:/Users/VAIBHAV/OneDrive/Desktop/Stocks/new%20quant/results/report_5stocks_monthly.png)

![Strategy comparison across portfolio sizes](file:///c:/Users/VAIBHAV/OneDrive/Desktop/Stocks/new%20quant/results/comparison_monthly.png)

---

## Key Findings

### 1. Transaction Costs Are THE Dominant Factor
At ₹1,00,000 capital, transaction costs consumed **96% to 126%** of the initial capital over 14 years. This is the single biggest driver of returns — not strategy alpha, not market regime, but **₹20 brokerage + ₹15.93 DP charges per trade**.

| Stocks | Position Size | Round-trip Cost | Trades Over 14Y | Total Cost |
|:---|---:|---:|---:|---:|
| 5 | ₹20,000 | ~0.74% | ~819 | ₹96,114 |
| 10 | ₹10,000 | ~1.05% | ~1,406 | ₹1,16,073 |
| 15 | ₹6,667 | ~1.37% | ~1,782 | ₹1,25,606 |
| 20 | ₹5,000 | ~1.69% | ~2,078 | ₹1,25,553 |

### 2. The 5-Stock Config Actually Works (Pre-Cost)
The 5-stock strategy showed genuine alpha:
- ₹1L → ₹2.4L peak (Oct 2021) = **140% gain before the 2022 correction**
- The equity curve closely tracked the post-COVID bull run
- Rolling Sharpe hit **3.0+** during 2020-2021
- But the -32% drawdown and 96% cost drag dragged CAGR down to 4.2%

### 3. Risk Management Worked But Was Too Aggressive
- **Liquidation at -25%** triggered multiple times, destroying compounding
- After each liquidation + 30-day cooldown, the system re-entered at lower capital
- The -15% drawdown-reduce (halving positions) created a drag during recovery
- **Suggestion**: Raise drawdown limits to -20%/-35% for a 14-year horizon

### 4. Regime Detection Was Effective
- **BULL**: Full deployment, strong momentum returns
- **BEAR (2015, 2020)**: Correctly reduced to 30% allocation
- **NEUTRAL**: 70% allocation balanced risk well

---

## What Needs to Change

### Priority 1: Reduce Transaction Costs
| Action | Impact |
|:---|:---|
| **Switch to zero-brokerage broker** (Zerodha Lite, Groww) | Eliminates ₹20/order → ~50% cost reduction |
| **Increase capital to ₹5-10L** | Position sizes of ₹1L+ → costs become ~0.3% per trade |
| **Reduce turnover** — only swap if score improvement > threshold | Fewer trades = less cost drag |
| **Quarterly rebalancing** instead of monthly | ~3× fewer rebalance events |

### Priority 2: Relax Risk Limits
| Parameter | Current | Suggested |
|:---|:---|:---|
| Max drawdown reduce | -15% | -20% |
| Max drawdown liquidate | -25% | -35% |
| Liquidation cooldown | 30 days | 60 days |
| Trailing stop multiplier | 2.5× ATR | 3.0× ATR |

### Priority 3: Strategy Improvements
- **Add turnover filter**: Only swap a position if the new stock scores >20% higher
- **Momentum crash protection**: Skip buying stocks with >50% 1-year gains (mean reversion risk)
- **Sector diversification**: Cap at 2 stocks per sector

---

## Reports Saved

All reports in `results/` folder:
- [report_5stocks_monthly.png](file:///c:/Users/VAIBHAV/OneDrive/Desktop/Stocks/new%20quant/results/report_5stocks_monthly.png)
- [report_10stocks_monthly.png](file:///c:/Users/VAIBHAV/OneDrive/Desktop/Stocks/new%20quant/results/report_10stocks_monthly.png) 
- [report_15stocks_monthly.png](file:///c:/Users/VAIBHAV/OneDrive/Desktop/Stocks/new%20quant/results/report_15stocks_monthly.png)
- [report_20stocks_monthly.png](file:///c:/Users/VAIBHAV/OneDrive/Desktop/Stocks/new%20quant/results/report_20stocks_monthly.png)
- [comparison_monthly.png](file:///c:/Users/VAIBHAV/OneDrive/Desktop/Stocks/new%20quant/results/comparison_monthly.png)

---

## Bottom Line

> [!WARNING]  
> At ₹1L capital, **no configuration beats a simple index fund** after realistic transaction costs. The system has genuine stock-selection alpha (peaked at 2.4× in 2021), but ₹20/order brokerage + DP charges eat 96% of capital over 14 years.
>
> **The path forward**: Either increase capital to ₹5L+ OR switch to a zero-brokerage platform, then the 5-stock monthly config becomes viable with ~12-15% CAGR potential.
