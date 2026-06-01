"""
Pure 12-1 Cross-Sectional Momentum Factor Isolation Test.

PURPOSE: Determine whether the 12-1 momentum factor itself generates
alpha in the Indian equity market, BEFORE adding any bells and whistles.

STRIPPED OUT:
  ✗ No regime detection
  ✗ No stop losses / trailing stops
  ✗ No drawdown-based liquidation
  ✗ No daily loss halts
  ✗ No breakout / mean reversion / trend signals
  ✗ No strategy blending
  ✗ No inverse volatility weighting

RETAINED:
  ✓ Universe filters (liquidity, price, anti-manipulation)
  ✓ Pure 12-1 momentum ranking (12-month return, skip last 1 month)
  ✓ Equal-weight portfolio construction
  ✓ Monthly and quarterly rebalancing

OUTPUTS:
  - Gross returns (zero costs) and Net returns (full cost model)
  - CAGR, Sharpe, Max DD, Calmar, Turnover, Trades, Costs
  - Benchmark comparison (NIFTY 500 TRI)
  - Annual returns table
  - Rolling 3-year performance chart
  - Individual report PNGs + comparison chart
"""

import sys
import time
import warnings
import io
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Fix Windows console encoding for Unicode characters (₹, emoji)
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Suppress noisy logs
import logging
logging.basicConfig(level=logging.ERROR)
for name in logging.root.manager.loggerDict:
    logging.getLogger(name).setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from tqdm import tqdm

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

from config import SystemConfig, RESULTS_DIR, CACHE_DIR
from data.downloader import download_all_stocks, download_market_proxy, build_price_panel
from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns
from universe.universe_builder import UniverseBuilder
from costs.cost_model import CostModel
from analytics.metrics import compute_metrics, print_metrics, compute_rolling_metrics
from analytics.visualizer import (
    setup_style, COLORS, plot_full_report, plot_comparison,
    _plot_equity_curve, _plot_drawdown, _plot_monthly_heatmap,
    _plot_return_distribution, _plot_rolling_sharpe, _plot_metrics_table,
)
from utils.helpers import get_rebalance_dates, round_to_lot_size


# ─────────────────────────────────────────────────────────────────────
# PURE 12-1 MOMENTUM SCORER
# ─────────────────────────────────────────────────────────────────────

def compute_12_1_momentum(
    close_panel: pd.DataFrame,
    date: pd.Timestamp,
    universe: list,
    lookback: int = 252,
    skip: int = 21,
) -> pd.Series:
    """
    Compute pure 12-1 cross-sectional momentum.
    
    Signal = (Price[T-skip] / Price[T-lookback]) - 1
    
    This is the classic Jegadeesh & Titman (1993) momentum factor:
    12-month return, skipping the most recent 1 month.
    
    No risk-adjustment, no multi-horizon blend, no acceleration filter.
    Pure, raw momentum.
    """
    cols = [s for s in universe if s in close_panel.columns]
    mask = close_panel.index <= date
    prices = close_panel.loc[mask, cols]
    
    if len(prices) < lookback + skip + 1:
        return pd.Series(dtype=float)
    
    # Price at T - skip_recent (end of momentum window)
    price_skip = prices.iloc[-(skip + 1)]
    
    # Price at T - lookback (start of momentum window)
    price_start = prices.iloc[-(lookback + 1)]
    
    # 12-1 momentum = return over [T-252, T-21]
    momentum = (price_skip / price_start) - 1
    
    # Drop NaN and zero-priced stocks
    momentum = momentum.replace([np.inf, -np.inf], np.nan).dropna()
    
    return momentum.sort_values(ascending=False)


# ─────────────────────────────────────────────────────────────────────
# PURE MOMENTUM BACKTEST ENGINE
# ─────────────────────────────────────────────────────────────────────

def run_pure_momentum_backtest(
    close_panel: pd.DataFrame,
    open_panel: pd.DataFrame,
    high_panel: pd.DataFrame,
    low_panel: pd.DataFrame,
    volume_panel: pd.DataFrame,
    n_stocks: int,
    rebalance_freq: str,
    initial_capital: float,
    config: SystemConfig,
    apply_costs: bool = True,
) -> dict:
    """
    Run a pure 12-1 momentum backtest.
    
    At each rebalance date:
      1. Build universe (point-in-time)
      2. Rank by 12-1 momentum
      3. Select top N
      4. Equal weight
      5. Hold until next rebalance (NO stops, NO risk management)
    
    Returns dict with equity_curve, returns, trades, etc.
    """
    cfg = config
    start = pd.Timestamp(cfg.backtest.start_date)
    end = pd.Timestamp(cfg.backtest.end_date)
    
    # Ensure we have warmup
    data_start = close_panel.index.min()
    data_end = close_panel.index.max()
    start = max(start, data_start + pd.Timedelta(days=365))
    end = min(end, data_end)
    
    # All trading dates
    all_dates = close_panel.index[
        (close_panel.index >= start) & (close_panel.index <= end)
    ]
    
    if all_dates.empty:
        return {"equity_curve": pd.Series(dtype=float), "returns": pd.Series(dtype=float)}
    
    # Rebalance dates
    rebal_dates = get_rebalance_dates(all_dates, rebalance_freq)
    rebal_set = set(rebal_dates)
    
    # Universe builder
    universe_builder = UniverseBuilder(
        close_panel, high_panel, low_panel, volume_panel, cfg.universe,
    )
    
    # Cost model
    cost_model = CostModel(cfg.costs)
    
    # State
    cash = initial_capital
    current_holdings = {}   # symbol -> shares
    
    equity_values = []
    trades_history = []
    holdings_snapshots = []
    total_costs = 0.0
    total_rebalances = 0
    total_turnover = 0.0
    
    label = f"{n_stocks}stocks_{rebalance_freq}"
    cost_label = "net" if apply_costs else "gross"
    desc = f"[{cost_label}] {label}"
    
    for date in tqdm(all_dates, desc=desc, unit="day"):
        today_close = close_panel.loc[date]
        
        # ── Portfolio value ──
        holdings_value = sum(
            qty * today_close.get(sym, 0)
            for sym, qty in current_holdings.items()
            if not np.isnan(today_close.get(sym, np.nan))
        )
        portfolio_value = cash + holdings_value
        
        equity_values.append({
            "date": date,
            "portfolio_value": portfolio_value,
            "cash": cash,
            "holdings_value": holdings_value,
            "n_holdings": len(current_holdings),
        })
        
        # ── Rebalance (if rebalance date) ──
        if date in rebal_set:
            total_rebalances += 1
            
            # 1. Build universe
            universe = universe_builder.build_universe(date)
            if not universe.symbols:
                continue
            
            # 2. Compute pure 12-1 momentum
            momentum_scores = compute_12_1_momentum(
                close_panel, date, universe.symbols,
            )
            
            if momentum_scores.empty or len(momentum_scores) < n_stocks:
                continue
            
            # 3. Select top N
            selected = list(momentum_scores.head(n_stocks).index)
            
            # 4. Equal weight target
            allocable = portfolio_value  # 100% allocation, no regime filter
            per_stock = allocable / n_stocks
            
            # Compute target shares
            target_shares = {}
            for sym in selected:
                price = today_close.get(sym, np.nan)
                if np.isnan(price) or price <= 0:
                    continue
                shares = int(per_stock / price)
                if shares > 0:
                    target_shares[sym] = shares
            
            # 5. Generate trades (current -> target)
            # SELL first
            sells_value = 0.0
            buys_value = 0.0
            
            # Sell everything not in target
            for sym, qty in list(current_holdings.items()):
                target_qty = target_shares.get(sym, 0)
                sell_qty = qty - target_qty
                
                if sell_qty > 0:
                    price = today_close.get(sym, 0)
                    if price <= 0:
                        continue
                    
                    sell_value = sell_qty * price
                    cost = 0.0
                    
                    if apply_costs:
                        tier = universe.liquidity_tiers.get(sym, 2)
                        cost_obj = cost_model.calculate_trade_cost(
                            sym, "SELL", sell_qty, price, liquidity_tier=tier,
                        )
                        cost = cost_obj.total_cost
                    
                    cash += sell_value - cost
                    total_costs += cost
                    sells_value += sell_value
                    
                    current_holdings[sym] = qty - sell_qty
                    if current_holdings[sym] <= 0:
                        del current_holdings[sym]
                    
                    trades_history.append({
                        "date": date, "symbol": sym, "side": "SELL",
                        "shares": sell_qty, "price": price,
                        "value": sell_value, "cost": cost,
                    })
            
            # Buy what's in target
            for sym, target_qty in target_shares.items():
                current_qty = current_holdings.get(sym, 0)
                buy_qty = target_qty - current_qty
                
                if buy_qty > 0:
                    price = today_close.get(sym, 0)
                    if price <= 0:
                        continue
                    
                    buy_value = buy_qty * price
                    cost = 0.0
                    
                    if apply_costs:
                        tier = universe.liquidity_tiers.get(sym, 2)
                        cost_obj = cost_model.calculate_trade_cost(
                            sym, "BUY", buy_qty, price, liquidity_tier=tier,
                        )
                        cost = cost_obj.total_cost
                    
                    total_buy_cost = buy_value + cost
                    
                    if total_buy_cost > cash:
                        # Reduce to affordable
                        affordable = int((cash - cost) / price) if price > 0 else 0
                        if affordable <= 0:
                            continue
                        buy_qty = affordable
                        buy_value = buy_qty * price
                        if apply_costs:
                            cost_obj = cost_model.calculate_trade_cost(
                                sym, "BUY", buy_qty, price, liquidity_tier=tier,
                            )
                            cost = cost_obj.total_cost
                        total_buy_cost = buy_value + cost
                    
                    cash -= total_buy_cost
                    total_costs += cost
                    buys_value += buy_value
                    
                    current_holdings[sym] = current_holdings.get(sym, 0) + buy_qty
                    
                    trades_history.append({
                        "date": date, "symbol": sym, "side": "BUY",
                        "shares": buy_qty, "price": price,
                        "value": buy_value, "cost": cost,
                    })
            
            # Track turnover
            rebal_turnover = max(sells_value, buys_value) / portfolio_value if portfolio_value > 0 else 0
            total_turnover += rebal_turnover
            
            holdings_snapshots.append({
                "date": date,
                "holdings": dict(current_holdings),
                "n_stocks": len(current_holdings),
                "cash": cash,
                "turnover": rebal_turnover,
                "momentum_top5": list(momentum_scores.head(5).index),
            })
    
    # ── Build results ──
    eq_df = pd.DataFrame(equity_values).set_index("date")
    equity_curve = eq_df["portfolio_value"]
    returns = equity_curve.pct_change().fillna(0)
    
    avg_turnover = total_turnover / total_rebalances if total_rebalances > 0 else 0
    
    return {
        "equity_curve": equity_curve,
        "returns": returns,
        "trades": trades_history,
        "holdings_snapshots": holdings_snapshots,
        "total_costs": total_costs,
        "total_rebalances": total_rebalances,
        "total_trades": len(trades_history),
        "avg_turnover": avg_turnover,
        "n_stocks": n_stocks,
        "rebalance_freq": rebalance_freq,
        "apply_costs": apply_costs,
    }


# ─────────────────────────────────────────────────────────────────────
# ANNUAL RETURNS TABLE
# ─────────────────────────────────────────────────────────────────────

def compute_annual_returns(equity_curve: pd.Series) -> pd.Series:
    """Compute calendar year returns from an equity curve."""
    yearly = equity_curve.groupby(equity_curve.index.year).agg(["first", "last"])
    annual_returns = (yearly["last"] / yearly["first"]) - 1
    return annual_returns


def print_annual_returns_table(all_annual: dict):
    """Print annual returns comparison table."""
    df = pd.DataFrame(all_annual)
    df.index.name = "Year"
    
    print(f"\n{'='*120}")
    print(f"{'ANNUAL RETURNS TABLE':^120}")
    print(f"{'='*120}")
    
    # Header
    cols = list(df.columns)
    header = f"{'Year':>6}"
    for col in cols:
        header += f" {col:>16}"
    print(header)
    print("-" * 120)
    
    # Rows
    for year, row in df.iterrows():
        line = f"{year:>6}"
        for col in cols:
            val = row[col]
            if pd.isna(val):
                line += f" {'N/A':>16}"
            else:
                line += f" {val:>15.1%}"
        print(line)
    
    print("-" * 120)
    
    # Averages
    avg_line = f"{'Avg':>6}"
    for col in cols:
        avg_line += f" {df[col].mean():>15.1%}"
    print(avg_line)
    
    # Median
    med_line = f"{'Med':>6}"
    for col in cols:
        med_line += f" {df[col].median():>15.1%}"
    print(med_line)
    
    print(f"{'='*120}\n")


# ─────────────────────────────────────────────────────────────────────
# ENHANCED REPORT WITH ROLLING 3-YEAR + ANNUAL TABLE
# ─────────────────────────────────────────────────────────────────────

def plot_factor_report(
    gross_equity: pd.Series,
    net_equity: pd.Series,
    gross_returns: pd.Series,
    net_returns: pd.Series,
    gross_metrics,
    net_metrics,
    benchmark_equity: pd.Series,
    n_stocks: int,
    rebalance_freq: str,
    save_path: Path,
):
    """Generate comprehensive factor isolation report with gross vs net comparison."""
    setup_style()
    
    fig = plt.figure(figsize=(18, 26))
    gs = GridSpec(5, 2, figure=fig, hspace=0.35, wspace=0.25)
    
    title = f"Pure 12-1 Momentum Factor: {n_stocks} stocks / {rebalance_freq}"
    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.98, color="#fff")
    
    # ── Panel 1: Equity Curve (Gross vs Net vs Benchmark) ──
    ax1 = fig.add_subplot(gs[0, :])
    ax1.set_title("Equity Curve: Gross vs Net vs Benchmark", fontweight="bold")
    
    gross_norm = gross_equity / gross_equity.iloc[0] * 100
    net_norm = net_equity / net_equity.iloc[0] * 100
    
    ax1.plot(gross_norm.index, gross_norm.values, color="#00ff88",
             linewidth=1.8, label="Gross (no costs)", zorder=3)
    ax1.plot(net_norm.index, net_norm.values, color="#4ecdc4",
             linewidth=1.8, label="Net (after costs)", zorder=3)
    
    if benchmark_equity is not None and not benchmark_equity.empty:
        bm_norm = benchmark_equity / benchmark_equity.iloc[0] * 100
        common = gross_norm.index.intersection(bm_norm.index)
        if len(common) > 0:
            ax1.plot(common, bm_norm.reindex(common).values,
                     color="#ff6b6b", linewidth=1.5,
                     label="NIFTY 500 TRI", alpha=0.8, zorder=2)
    
    ax1.set_ylabel("Value (base 100)")
    ax1.legend(loc="upper left", framealpha=0.3)
    ax1.grid(True, alpha=0.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    
    # ── Panel 2: Drawdown (Gross vs Net) ──
    ax2 = fig.add_subplot(gs[1, :])
    ax2.set_title("Drawdown: Gross vs Net", fontweight="bold")
    
    for eq, color, label in [
        (gross_equity, "#00ff88", "Gross"),
        (net_equity, "#4ecdc4", "Net"),
    ]:
        cummax = eq.cummax()
        dd = (eq - cummax) / cummax * 100
        ax2.fill_between(dd.index, dd.values, 0, color=color, alpha=0.2)
        ax2.plot(dd.index, dd.values, color=color, linewidth=0.8, label=label)
    
    ax2.set_ylabel("Drawdown (%)")
    ax2.legend(loc="lower left", framealpha=0.3)
    ax2.grid(True, alpha=0.2)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    
    # ── Panel 3: Monthly Returns Heatmap (Net) ──
    ax3 = fig.add_subplot(gs[2, 0])
    _plot_monthly_heatmap(ax3, net_returns)
    
    # ── Panel 4: Return Distribution (Net) ──
    ax4 = fig.add_subplot(gs[2, 1])
    _plot_return_distribution(ax4, net_returns)
    
    # ── Panel 5: Rolling 3-Year CAGR ──
    ax5 = fig.add_subplot(gs[3, :])
    ax5.set_title("Rolling 3-Year CAGR: Gross vs Net", fontweight="bold")
    
    window_3y = 252 * 3
    for rets, color, label in [
        (gross_returns, "#00ff88", "Gross"),
        (net_returns, "#4ecdc4", "Net"),
    ]:
        if len(rets) > window_3y:
            rolling_cum = (1 + rets).rolling(window_3y).apply(
                lambda x: x.prod() ** (252 / window_3y) - 1, raw=True
            )
            rolling_cum = rolling_cum.dropna()
            ax5.plot(rolling_cum.index, rolling_cum.values * 100,
                     color=color, linewidth=1.2, label=label)
    
    ax5.axhline(6.5, color="#ff6b6b", linewidth=1, linestyle="--",
                alpha=0.7, label="FD Rate (6.5%)")
    ax5.axhline(0, color="white", linewidth=0.5, linestyle="--", alpha=0.3)
    ax5.set_ylabel("Rolling 3Y CAGR (%)")
    ax5.legend(loc="upper right", framealpha=0.3)
    ax5.grid(True, alpha=0.2)
    ax5.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    
    # ── Panel 6: Metrics Table (Gross vs Net side by side) ──
    ax6 = fig.add_subplot(gs[4, :])
    ax6.set_title("Key Metrics: Gross vs Net", fontweight="bold")
    ax6.axis("off")
    
    rows = [
        ("CAGR", f"{gross_metrics.cagr:.2%}", f"{net_metrics.cagr:.2%}"),
        ("Total Return", f"{gross_metrics.total_return:.1%}", f"{net_metrics.total_return:.1%}"),
        ("Sharpe Ratio", f"{gross_metrics.sharpe_ratio:.2f}", f"{net_metrics.sharpe_ratio:.2f}"),
        ("Sortino Ratio", f"{gross_metrics.sortino_ratio:.2f}", f"{net_metrics.sortino_ratio:.2f}"),
        ("Calmar Ratio", f"{gross_metrics.calmar_ratio:.2f}", f"{net_metrics.calmar_ratio:.2f}"),
        ("Max Drawdown", f"{gross_metrics.max_drawdown:.2%}", f"{net_metrics.max_drawdown:.2%}"),
        ("Max DD Duration", f"{gross_metrics.max_drawdown_duration_days}d", f"{net_metrics.max_drawdown_duration_days}d"),
        ("Annual Volatility", f"{gross_metrics.annualised_volatility:.2%}", f"{net_metrics.annualised_volatility:.2%}"),
        ("Win Rate", f"{gross_metrics.win_rate:.1%}", f"{net_metrics.win_rate:.1%}"),
        ("Total Trades", f"{gross_metrics.total_trades}", f"{net_metrics.total_trades}"),
        ("Total Costs", "₹0", f"₹{net_metrics.total_costs:,.0f}"),
        ("Cost Drag", "0.00%", f"{net_metrics.cost_drag:.2%}"),
        ("Alpha", f"{gross_metrics.alpha:.2%}", f"{net_metrics.alpha:.2%}"),
        ("Beta", f"{gross_metrics.beta:.2f}", f"{net_metrics.beta:.2f}"),
    ]
    
    table = ax6.table(
        cellText=[[r[1], r[2]] for r in rows],
        rowLabels=[r[0] for r in rows],
        colLabels=["Gross (No Costs)", "Net (After Costs)"],
        cellLoc="center",
        rowLoc="right",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    
    for key, cell in table.get_celld().items():
        cell.set_edgecolor("#333")
        cell.set_facecolor("#1a1a2e")
        cell.set_text_props(color="#eee")
        if key[0] == 0:  # header
            cell.set_facecolor("#16213e")
            cell.set_text_props(color="#00ff88", fontweight="bold")
    
    # Save
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  Report saved: {save_path}")


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    config = SystemConfig()
    initial_capital = config.portfolio.initial_capital
    
    print("=" * 70)
    print("  PURE 12-1 MOMENTUM FACTOR ISOLATION TEST")
    print(f"  Capital: ₹{initial_capital:,.0f}")
    print("  Stripped: regime, stops, risk mgmt, multi-strategy, vol-weighting")
    print("  Retained: universe filters, 12-1 momentum, equal weight")
    print("=" * 70)
    
    # ── Load Data ──
    print("\n📦 Loading data from cache...")
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
    
    print(f"  Loaded {len(close_panel)} dates × {len(close_panel.columns)} stocks "
          f"in {time.time()-t0:.1f}s")
    
    # Benchmark
    benchmark_returns = get_benchmark_returns(
        config.backtest.start_date, config.backtest.end_date
    )
    benchmark_equity = get_benchmark_equity_curve(
        config.backtest.start_date, config.backtest.end_date,
        initial_capital,
    )
    
    # ── Test Grid ──
    param_grid = [
        (5, "monthly"),
        (5, "quarterly"),
        (10, "monthly"),
        (10, "quarterly"),
    ]
    
    all_results = {}       # label -> equity_curve (for comparison chart)
    all_metrics = {}       # label -> metrics
    all_annual = {}        # label -> annual returns Series
    
    results_dir = RESULTS_DIR / "pure_momentum"
    results_dir.mkdir(parents=True, exist_ok=True)
    
    for n_stocks, freq in param_grid:
        label = f"{n_stocks}stocks_{freq}"
        
        print(f"\n{'='*70}")
        print(f"  CONFIG: {n_stocks} stocks, {freq} rebalancing")
        print(f"{'='*70}")
        
        t1 = time.time()
        
        # ── Run GROSS (no costs) ──
        gross_result = run_pure_momentum_backtest(
            close_panel, open_panel, high_panel, low_panel, volume_panel,
            n_stocks=n_stocks,
            rebalance_freq=freq,
            initial_capital=initial_capital,
            config=config,
            apply_costs=False,
        )
        
        # ── Run NET (with costs) ──
        net_result = run_pure_momentum_backtest(
            close_panel, open_panel, high_panel, low_panel, volume_panel,
            n_stocks=n_stocks,
            rebalance_freq=freq,
            initial_capital=initial_capital,
            config=config,
            apply_costs=True,
        )
        
        elapsed = time.time() - t1
        
        if gross_result["equity_curve"].empty:
            print(f"  No results for {label}")
            continue
        
        # ── Compute Metrics ──
        gross_metrics = compute_metrics(
            gross_result["equity_curve"],
            gross_result["returns"],
            benchmark_returns=benchmark_returns,
            trades=gross_result["trades"],
            total_costs=0.0,
            initial_capital=initial_capital,
        )
        
        net_metrics = compute_metrics(
            net_result["equity_curve"],
            net_result["returns"],
            benchmark_returns=benchmark_returns,
            trades=net_result["trades"],
            total_costs=net_result["total_costs"],
            initial_capital=initial_capital,
        )
        
        # Print both
        print_metrics(gross_metrics, title=f"GROSS: {n_stocks} stocks / {freq}")
        print(f"  Avg Turnover per rebalance: {gross_result['avg_turnover']:.1%}")
        print(f"  Total rebalances: {gross_result['total_rebalances']}")
        
        print_metrics(net_metrics, title=f"NET: {n_stocks} stocks / {freq}")
        print(f"  Total costs: ₹{net_result['total_costs']:,.0f}")
        print(f"  Cost drag (% of initial): {net_result['total_costs']/initial_capital:.2%}")
        print(f"  [Completed in {elapsed:.0f}s]")
        
        # ── Cost Impact ──
        cost_impact = gross_metrics.cagr - net_metrics.cagr
        print(f"\n  📊 COST IMPACT: {cost_impact:.2%} CAGR lost to costs")
        
        if gross_metrics.cagr > 0.07:
            if net_metrics.cagr > 0.07:
                print(f"  ✅ Factor works BEFORE and AFTER costs (beats FD)")
            else:
                print(f"  ⚠️  Factor works BEFORE costs but FAILS AFTER costs → Execution problem")
        else:
            print(f"  ❌ Factor does NOT work even BEFORE costs → Factor is broken")
        
        # Store results
        all_results[f"{label}_gross"] = gross_result["equity_curve"]
        all_results[f"{label}_net"] = net_result["equity_curve"]
        all_metrics[f"{label}_gross"] = gross_metrics
        all_metrics[f"{label}_net"] = net_metrics
        
        # Annual returns
        all_annual[f"{label}_gross"] = compute_annual_returns(gross_result["equity_curve"])
        all_annual[f"{label}_net"] = compute_annual_returns(net_result["equity_curve"])
        
        # ── Generate Report ──
        plot_factor_report(
            gross_result["equity_curve"],
            net_result["equity_curve"],
            gross_result["returns"],
            net_result["returns"],
            gross_metrics,
            net_metrics,
            benchmark_equity,
            n_stocks, freq,
            save_path=results_dir / f"factor_report_{label}.png",
        )
    
    # ── Annual Returns Table ──
    if all_annual:
        if benchmark_equity is not None and not benchmark_equity.empty:
            all_annual["NIFTY500_TRI"] = compute_annual_returns(benchmark_equity)
        print_annual_returns_table(all_annual)
    
    # ── Comparison Chart ──
    if len(all_results) > 1:
        if benchmark_equity is not None and not benchmark_equity.empty:
            all_results["NIFTY 500 TRI"] = benchmark_equity
        
        plot_comparison(
            all_results,
            title="Pure 12-1 Momentum: Gross vs Net vs Benchmark",
            save_path=results_dir / "factor_comparison.png",
        )
    
    # ── Summary Comparison Table ──
    print(f"\n{'='*130}")
    print(f"{'FACTOR ISOLATION SUMMARY':^130}")
    print(f"{'='*130}")
    print(f"{'Config':<25} {'Type':<6} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} "
          f"{'Calmar':>8} {'Alpha':>8} {'Trades':>8} {'Costs':>12} {'Turnover':>10}")
    print(f"{'-'*130}")
    
    for label, m in all_metrics.items():
        cost_type = "GROSS" if "gross" in label else "NET"
        base_label = label.replace("_gross", "").replace("_net", "")
        
        # Find matching result for turnover
        matching_key = label.replace("_gross", "").replace("_net", "")
        
        print(f"{base_label:<25} {cost_type:<6} {m.cagr:>7.1%} {m.sharpe_ratio:>8.2f} "
              f"{m.max_drawdown:>7.1%} {m.calmar_ratio:>8.2f} {m.alpha:>7.2%} "
              f"{m.total_trades:>8d} ₹{m.total_costs:>10,.0f} {'':>10}")
    
    print(f"{'='*130}")
    
    # ── Final Verdict ──
    print(f"\n{'='*70}")
    print(f"{'DIAGNOSIS':^70}")
    print(f"{'='*70}")
    
    # Check best gross config
    gross_configs = {k: v for k, v in all_metrics.items() if "gross" in k}
    if gross_configs:
        best_gross = max(gross_configs.items(), key=lambda x: x[1].cagr)
        best_net_key = best_gross[0].replace("gross", "net")
        best_net = all_metrics.get(best_net_key)
        
        print(f"\n  Best config: {best_gross[0]}")
        print(f"  Gross CAGR:  {best_gross[1].cagr:.2%}")
        if best_net:
            print(f"  Net CAGR:    {best_net.cagr:.2%}")
            print(f"  Cost drag:   {best_gross[1].cagr - best_net.cagr:.2%}")
        
        print()
        if best_gross[1].cagr > 0.10:
            print("  ✅ 12-1 MOMENTUM FACTOR WORKS (>10% gross CAGR)")
            if best_net and best_net.cagr > 0.07:
                print("  ✅ SURVIVES AFTER COSTS (>7% net CAGR, beats FD)")
                print("  → Proceed with strategy refinement")
            else:
                print("  ⚠️  DOES NOT SURVIVE COSTS (<7% net)")
                print("  → Focus on reducing turnover and costs")
        elif best_gross[1].cagr > 0.065:
            print("  🟡 FACTOR IS MARGINAL (6.5-10% gross CAGR)")
            print("  → Barely beats risk-free rate before costs")
            print("  → Consider different universe or factor")
        else:
            print("  ❌ FACTOR DOES NOT WORK (<6.5% gross CAGR)")
            print("  → The 12-1 momentum factor is NOT generating alpha")
            print("  → No amount of optimisation will fix a broken factor")
    
    print(f"\n  Reports saved to: {results_dir}/")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
