"""
Main entry point for the Systematic Trading System.

Usage:
    python main.py download          - Download/update price data via yfinance
    python main.py backtest          - Run full backtest (all parameter combos)
    python main.py backtest-quick    - Run backtest with default params only
    python main.py scan              - Run strategies on latest data
    python main.py report            - Generate performance report
    python main.py validate-data     - Run data quality checks
    python main.py costs             - Show transaction cost estimates
"""

import sys
import argparse
from pathlib import Path
from typing import Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    SystemConfig, DEFAULT_CONFIG, setup_logging,
    CACHE_DIR, DB_PATH, RESULTS_DIR,
)

logger = setup_logging("main")


def cmd_download(args):
    """Download market data via yfinance."""
    from data.downloader import (
        download_all_stocks, download_market_proxy,
        build_price_panel, load_nifty500_symbols,
    )
    from data.benchmark import load_tri_csv
    from data.database import DatabaseManager

    config = DEFAULT_CONFIG.download

    logger.info("=" * 60)
    logger.info("STEP 1: Downloading stock data via yfinance")
    logger.info("=" * 60)

    symbols = load_nifty500_symbols()
    stock_data = download_all_stocks(config, symbols=symbols, use_cache=not args.fresh)

    logger.info(f"Downloaded {len(stock_data)} stocks successfully")

    logger.info("\nSTEP 2: Downloading Nifty 50 (market proxy)")
    market = download_market_proxy(
        start_date=config.start_date,
        end_date=config.end_date,
    )
    if market is not None:
        logger.info(f"Nifty 50: {len(market)} rows")

    logger.info("\nSTEP 3: Loading benchmark TRI data")
    tri = load_tri_csv()
    if not tri.empty:
        logger.info(f"NIFTY 500 TRI: {len(tri)} rows")
    else:
        logger.warning(
            "No TRI data found. Please download from "
            "https://www.niftyindices.com/reports/historical-data"
        )

    logger.info("\nSTEP 4: Saving to database")
    db = DatabaseManager()
    db.bulk_insert_stocks(stock_data)
    if not tri.empty:
        db.insert_benchmark_data(tri)

    summary = db.summary()
    logger.info(f"Database summary: {summary}")
    logger.info("\nDownload complete! ✓")


def cmd_backtest(args):
    """Run backtest with parameter grid."""
    from data.downloader import download_all_stocks, download_market_proxy, build_price_panel
    from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns
    from backtest.engine import BacktestEngine
    from analytics.metrics import compute_metrics, print_metrics
    from analytics.visualizer import plot_full_report, plot_comparison

    config = DEFAULT_CONFIG

    logger.info("=" * 60)
    logger.info("LOADING DATA")
    logger.info("=" * 60)

    # Load data
    stock_data = download_all_stocks(use_cache=True)
    if not stock_data:
        logger.error("No stock data available. Run 'python main.py download' first.")
        return

    # Build panels
    close_panel = build_price_panel(stock_data, "Close")
    open_panel = build_price_panel(stock_data, "Open")
    high_panel = build_price_panel(stock_data, "High")
    low_panel = build_price_panel(stock_data, "Low")
    volume_panel = build_price_panel(stock_data, "Volume")

    logger.info(f"Data: {len(close_panel)} dates × {len(close_panel.columns)} stocks")

    # Market proxy
    market = download_market_proxy()
    if market is None or market.empty:
        logger.error("No Nifty 50 data available.")
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

    # ── Run backtests ──
    if args.quick:
        # Quick mode: default params only
        param_grid = [(config.portfolio.max_stocks, "monthly")]
    else:
        # Full grid: all portfolio sizes × rebalancing frequencies
        param_grid = [
            (n, freq)
            for n in config.portfolio.portfolio_sizes_to_test
            for freq in config.portfolio.rebalance_frequencies_to_test
        ]

    logger.info(f"\nRunning {len(param_grid)} backtest configurations...")

    all_results = {}
    all_metrics = {}

    for n_stocks, freq in param_grid:
        label = f"{n_stocks}stocks_{freq}"
        logger.info(f"\n{'='*60}")
        logger.info(f"CONFIG: {n_stocks} stocks, {freq} rebalancing")
        logger.info(f"{'='*60}")

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

        if result.equity_curve.empty:
            logger.warning(f"No results for {label}")
            continue

        # Compute metrics
        metrics = compute_metrics(
            result.equity_curve,
            result.returns,
            benchmark_returns=benchmark_returns,
            total_costs=result.costs_total,
            initial_capital=config.portfolio.initial_capital,
        )

        print_metrics(metrics, title=f"{n_stocks} stocks / {freq}")

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
        # Add benchmark
        if benchmark_equity is not None and not benchmark_equity.empty:
            all_results["NIFTY 500 TRI"] = benchmark_equity

        plot_comparison(
            all_results,
            title="Strategy Comparison Across Parameters",
            save_path=RESULTS_DIR / "comparison_all.png",
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
                  f"{m.win_rate:>7.1%} ₹{m.total_costs:>9,.0f}")
        print(f"{'='*90}\n")

    logger.info(f"\nAll reports saved to {RESULTS_DIR}/")
    logger.info("Backtest complete! ✓")


def cmd_scan(args):
    """Run strategies on latest data and show current signals."""
    from data.downloader import download_all_stocks, download_market_proxy, build_price_panel
    from universe.universe_builder import UniverseBuilder
    from strategies.momentum import MomentumStrategy
    from strategies.trend_following import TrendFollowingStrategy
    from strategies.breakout import BreakoutStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    from regime.regime_filter import RegimeFilter
    from portfolio.ranker import compute_composite_scores, select_top_stocks

    config = DEFAULT_CONFIG

    logger.info("Loading data...")
    stock_data = download_all_stocks(use_cache=True)
    if not stock_data:
        logger.error("No data. Run 'python main.py download' first.")
        return

    close_panel = build_price_panel(stock_data, "Close")
    high_panel = build_price_panel(stock_data, "High")
    low_panel = build_price_panel(stock_data, "Low")
    volume_panel = build_price_panel(stock_data, "Volume")

    latest_date = close_panel.index[-1]
    logger.info(f"Latest data date: {latest_date.date()}")

    # Build universe
    ub = UniverseBuilder(close_panel, high_panel, low_panel, volume_panel, config.universe)
    universe = ub.build_universe(latest_date)
    logger.info(f"Tradeable universe: {len(universe.symbols)} stocks")

    # Regime
    market = download_market_proxy()
    regime_filter = RegimeFilter(config.regime)
    regime = regime_filter.detect_regime(
        market["Close"], market.get("High"), market.get("Low"), latest_date
    )
    print(f"\nMarket Regime: {regime.regime}")
    print(f"Capital Allocation: {regime.capital_allocation:.0%}")
    print(f"Strategy Weights: {regime.strategy_weights}")

    # Strategy scores
    strategies = {
        "momentum": MomentumStrategy(config.momentum),
        "trend_following": TrendFollowingStrategy(config.trend),
        "breakout": BreakoutStrategy(config.breakout),
        "mean_reversion": MeanReversionStrategy(config.mean_reversion),
    }

    strategy_scores = {}
    for name, strategy in strategies.items():
        scores = strategy.compute_scores(
            close_panel, high_panel, low_panel, volume_panel,
            latest_date, universe.symbols,
        )
        strategy_scores[name] = scores

    # Composite ranking
    composite = compute_composite_scores(strategy_scores, regime)
    selected = select_top_stocks(composite, n_stocks=config.portfolio.max_stocks)

    # Display
    print(f"\n{'='*80}")
    print(f"TOP {len(selected)} STOCKS — {latest_date.date()}")
    print(f"{'='*80}")
    print(f"{'Rank':<6} {'Symbol':<15} {'Score':>8} {'Mom':>8} "
          f"{'Trend':>8} {'Break':>8} {'MR':>8} {'Price':>10}")
    print(f"{'-'*80}")

    for rank, sym in enumerate(selected, 1):
        price = close_panel[sym].iloc[-1] if sym in close_panel.columns else 0
        mom = strategy_scores.get("momentum", {}).get(sym, 0)
        if hasattr(mom, '__float__'):
            mom = float(mom)
        trend = strategy_scores.get("trend_following", {}).get(sym, 0)
        if hasattr(trend, '__float__'):
            trend = float(trend)
        brk = strategy_scores.get("breakout", {}).get(sym, 0)
        if hasattr(brk, '__float__'):
            brk = float(brk)
        mr = strategy_scores.get("mean_reversion", {}).get(sym, 0)
        if hasattr(mr, '__float__'):
            mr = float(mr)
        comp = composite.get(sym, 0)

        print(f"{rank:<6} {sym:<15} {comp:>7.1f} {mom:>7.1f} "
              f"{trend:>7.1f} {brk:>7.1f} {mr:>7.1f} ₹{price:>9,.2f}")

    print(f"{'='*80}\n")


def cmd_validate(args):
    """Run data quality checks."""
    from data.downloader import download_all_stocks, build_price_panel
    from data.quality import check_all_stocks, print_quality_summary

    logger.info("Loading data...")
    stock_data = download_all_stocks(use_cache=True)
    if not stock_data:
        logger.error("No data. Run 'python main.py download' first.")
        return

    reports, usable = check_all_stocks(stock_data)
    print_quality_summary(reports)


def cmd_costs(args):
    """Show transaction cost estimates."""
    from costs.cost_model import CostModel

    model = CostModel()
    config = DEFAULT_CONFIG.portfolio

    print(f"\n{'='*60}")
    print(f"{'TRANSACTION COST ESTIMATES':^60}")
    print(f"{'='*60}")
    print(f"Capital: ₹{config.initial_capital:,.0f}")
    print()

    for n_stocks in config.portfolio_sizes_to_test:
        pos_size = config.initial_capital / n_stocks
        print(f"\n--- {n_stocks} stocks (₹{pos_size:,.0f} per position) ---")
        for tier, label in [(1, "Large-cap"), (2, "Mid-cap"), (3, "Small-cap")]:
            cost_pct = model.estimate_round_trip_cost_pct(pos_size, tier)
            cost_abs = pos_size * cost_pct
            print(f"  {label:<12}: {cost_pct:.2%} round-trip (₹{cost_abs:.0f})")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Systematic Trading System for Indian Equities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # download
    dl = subparsers.add_parser("download", help="Download market data")
    dl.add_argument("--fresh", action="store_true", help="Ignore cache, re-download all")

    # backtest
    bt = subparsers.add_parser("backtest", help="Run full backtest")
    bt.add_argument("--quick", action="store_true",
                    help="Quick mode: default params only")

    # backtest-quick
    btq = subparsers.add_parser("backtest-quick", help="Run quick backtest")

    # scan
    subparsers.add_parser("scan", help="Show current signals")

    # validate-data
    subparsers.add_parser("validate-data", help="Run data quality checks")

    # costs
    subparsers.add_parser("costs", help="Show cost estimates")

    # report
    subparsers.add_parser("report", help="Generate report from last backtest")

    args = parser.parse_args()

    if args.command == "download":
        cmd_download(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "backtest-quick":
        args.quick = True
        cmd_backtest(args)
    elif args.command == "scan":
        cmd_scan(args)
    elif args.command == "validate-data":
        cmd_validate(args)
    elif args.command == "costs":
        cmd_costs(args)
    elif args.command == "report":
        logger.info("Report generation from saved results — coming soon")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
