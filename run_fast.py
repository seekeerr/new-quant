"""
Fast backtest runner — runs only monthly rebalancing configs
with optimized settings for speed.
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Override log level BEFORE importing anything else
import logging
logging.basicConfig(level=logging.ERROR)
# Suppress all loggers
for name in logging.root.manager.loggerDict:
    logging.getLogger(name).setLevel(logging.ERROR)

import pandas as pd
import numpy as np

from config import SystemConfig, RESULTS_DIR, CACHE_DIR
from data.downloader import download_all_stocks, download_market_proxy, build_price_panel
from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns
from backtest.engine import BacktestEngine, BacktestResult
from analytics.metrics import compute_metrics, print_metrics, PerformanceMetrics
from analytics.visualizer import plot_full_report, plot_comparison


def run_fast_grid():
    config = SystemConfig()
    
    print("=" * 60)
    print("LOADING DATA (from cache)")
    print("=" * 60)
    
    t0 = time.time()
    stock_data = download_all_stocks(use_cache=True)
    if not stock_data:
        print("ERROR: No stock data. Run 'python main.py download' first.")
        return
    
    close_panel = build_price_panel(stock_data, "Close")
    open_panel = build_price_panel(stock_data, "Open")
    high_panel = build_price_panel(stock_data, "High")
    low_panel = build_price_panel(stock_data, "Low")
    volume_panel = build_price_panel(stock_data, "Volume")
    
    print(f"Loaded {len(close_panel)} dates x {len(close_panel.columns)} stocks "
          f"in {time.time()-t0:.1f}s")
    
    # Market proxy
    market = download_market_proxy()
    if market is None or market.empty:
        print("ERROR: No Nifty 50 data.")
        return
    
    market_close = market["Close"]
    market_high = market.get("High")
    market_low = market.get("Low")
    
    # Benchmark
    benchmark_returns = get_benchmark_returns(
        config.backtest.start_date, config.backtest.end_date
    )
    benchmark_equity = get_benchmark_equity_curve(
        config.backtest.start_date, config.backtest.end_date,
        config.portfolio.initial_capital,
    )
    
    # ── Run only monthly configs ──
    param_grid = [
        (5, "monthly"),
        (5, "quarterly"),
        (10, "monthly"),
        (10, "quarterly"),
    ]
    
    all_results = {}
    all_metrics = {}
    
    for n_stocks, freq in param_grid:
        label = f"{n_stocks}stocks_{freq}"
        print(f"\n{'='*60}")
        print(f"CONFIG: {n_stocks} stocks, {freq} rebalancing")
        print(f"{'='*60}")
        
        t1 = time.time()
        engine = BacktestEngine(config)
        result = engine.run(
            close_panel=close_panel,
            high_panel=high_panel,
            low_panel=low_panel,
            volume_panel=volume_panel,
            open_panel=open_panel,
            market_close=market_close,
            market_high=market_high,
            market_low=market_low,
            n_stocks=n_stocks,
            rebalance_frequency=freq,
        )
        elapsed = time.time() - t1
        
        if result.equity_curve.empty:
            print(f"  No results for {label}")
            continue
        
        # Compute metrics
        metrics = compute_metrics(
            result.equity_curve,
            result.returns,
            benchmark_returns=benchmark_returns,
            trades=result.trades_history,
            total_costs=result.costs_total,
            initial_capital=config.portfolio.initial_capital,
        )
        
        print_metrics(metrics, title=f"{n_stocks} stocks / {freq}")
        print(f"  [Completed in {elapsed:.0f}s]")
        
        all_results[label] = result.equity_curve
        all_metrics[label] = metrics
        
        # Save individual report
        plot_full_report(
            result.equity_curve,
            result.returns,
            metrics,
            benchmark_equity=benchmark_equity,
            trades=result.trades_history,
            regime_history=result.regime_history,
            save_path=RESULTS_DIR / f"report_{label}.png",
            title=f"Backtest: {n_stocks} stocks / {freq}",
        )
    
    # ── Comparison ──
    if len(all_results) > 1:
        if benchmark_equity is not None and not benchmark_equity.empty:
            all_results["NIFTY 500 TRI"] = benchmark_equity
        
        plot_comparison(
            all_results,
            title="Strategy Comparison: Option A Fixes (\u20b95L Capital)",
            save_path=RESULTS_DIR / "comparison_optionA.png",
        )
        
        # Print comparison table
        print(f"\n{'='*90}")
        print(f"{'COMPARISON TABLE':^90}")
        print(f"{'='*90}")
        print(f"{'Config':<25} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} "
              f"{'Calmar':>8} {'WinRate':>8} {'Costs':>10}")
        print(f"{'-'*90}")
        for label, m in all_metrics.items():
            print(f"{label:<25} {m.cagr:>7.1%} {m.sharpe_ratio:>8.2f} "
                  f"{m.max_drawdown:>7.1%} {m.calmar_ratio:>8.2f} "
                  f"{m.win_rate:>7.1%} Rs{m.total_costs:>9,.0f}")
        print(f"{'='*90}\n")
    
    print(f"\nAll reports saved to {RESULTS_DIR}/")
    print("Backtest complete!")


if __name__ == "__main__":
    run_fast_grid()
