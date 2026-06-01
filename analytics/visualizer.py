"""
Visualization module for backtest results.

Generates equity curves, drawdown charts, return heatmaps,
rolling metrics, and sector allocation plots.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import RESULTS_DIR, setup_logging
from analytics.metrics import PerformanceMetrics, compute_rolling_metrics

logger = setup_logging("visualizer")

# Use matplotlib with non-interactive backend for server/script usage
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec


# ── Styling ──────────────────────────────────────────────────────────
STYLE = {
    "figure.facecolor": "#1a1a2e",
    "axes.facecolor": "#16213e",
    "axes.edgecolor": "#e94560",
    "axes.labelcolor": "#eee",
    "text.color": "#eee",
    "xtick.color": "#aaa",
    "ytick.color": "#aaa",
    "grid.color": "#333",
    "grid.alpha": 0.3,
}
COLORS = {
    "equity": "#00ff88",
    "benchmark": "#ff6b6b",
    "drawdown": "#e94560",
    "positive": "#00ff88",
    "negative": "#ff4444",
    "neutral": "#888888",
    "regime_bull": "#00ff88",
    "regime_neutral": "#ffcc00",
    "regime_bear": "#ff4444",
}


def setup_style():
    """Apply custom dark theme."""
    plt.rcParams.update(STYLE)
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 10,
        "axes.titlesize": 13,
        "axes.labelsize": 11,
    })


def plot_full_report(
    equity_curve: pd.Series,
    returns: pd.Series,
    metrics: PerformanceMetrics,
    benchmark_equity: Optional[pd.Series] = None,
    trades: Optional[List[Dict]] = None,
    regime_history: Optional[Dict] = None,
    save_path: Optional[Path] = None,
    title: str = "Backtest Report",
):
    """
    Generate a comprehensive multi-panel backtest report.

    Panels:
    1. Equity curve (strategy vs. benchmark)
    2. Drawdown chart
    3. Monthly returns heatmap
    4. Rolling Sharpe ratio
    """
    setup_style()

    fig = plt.figure(figsize=(16, 20))
    gs = GridSpec(4, 2, figure=fig, hspace=0.35, wspace=0.25)

    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.98, color="#fff")

    # ── Panel 1: Equity Curve ──
    ax1 = fig.add_subplot(gs[0, :])
    _plot_equity_curve(ax1, equity_curve, benchmark_equity, regime_history)

    # ── Panel 2: Drawdown ──
    ax2 = fig.add_subplot(gs[1, :])
    _plot_drawdown(ax2, equity_curve)

    # ── Panel 3: Monthly Returns Heatmap ──
    ax3 = fig.add_subplot(gs[2, 0])
    _plot_monthly_heatmap(ax3, returns)

    # ── Panel 4: Return Distribution ──
    ax4 = fig.add_subplot(gs[2, 1])
    _plot_return_distribution(ax4, returns)

    # ── Panel 5: Rolling Sharpe ──
    ax5 = fig.add_subplot(gs[3, 0])
    _plot_rolling_sharpe(ax5, returns)

    # ── Panel 6: Metrics Summary ──
    ax6 = fig.add_subplot(gs[3, 1])
    _plot_metrics_table(ax6, metrics)

    # Save
    save_path = save_path or (RESULTS_DIR / "backtest_report.png")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    logger.info(f"Report saved to {save_path}")
    return save_path


def _plot_equity_curve(
    ax,
    equity: pd.Series,
    benchmark: Optional[pd.Series] = None,
    regime_history: Optional[Dict] = None,
):
    """Plot equity curve with optional benchmark and regime shading."""
    ax.set_title("Equity Curve", fontweight="bold")

    # Normalise to 100 for comparison
    eq_norm = equity / equity.iloc[0] * 100
    ax.plot(eq_norm.index, eq_norm.values, color=COLORS["equity"],
            linewidth=1.5, label="Strategy", zorder=3)

    if benchmark is not None and not benchmark.empty:
        bm_norm = benchmark / benchmark.iloc[0] * 100
        # Align dates
        common = eq_norm.index.intersection(bm_norm.index)
        if len(common) > 0:
            ax.plot(common, bm_norm.reindex(common).values,
                    color=COLORS["benchmark"], linewidth=1.2,
                    label="NIFTY 500 TRI", alpha=0.8, zorder=2)

    # Regime shading
    if regime_history:
        _shade_regimes(ax, regime_history, eq_norm.min(), eq_norm.max())

    ax.set_ylabel("Value (base 100)")
    ax.legend(loc="upper left", framealpha=0.3)
    ax.grid(True, alpha=0.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_major_locator(mdates.YearLocator())


def _shade_regimes(ax, regime_history: Dict, y_min: float, y_max: float):
    """Add regime background shading."""
    dates = sorted(regime_history.keys())
    for i, date in enumerate(dates):
        end = dates[i + 1] if i + 1 < len(dates) else date + pd.Timedelta(days=30)
        regime = regime_history[date].regime
        color = COLORS.get(f"regime_{regime.lower()}", "#888")
        ax.axvspan(date, end, alpha=0.05, color=color, zorder=0)


def _plot_drawdown(ax, equity: pd.Series):
    """Plot underwater drawdown chart."""
    ax.set_title("Drawdown", fontweight="bold")

    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax * 100

    ax.fill_between(drawdown.index, drawdown.values, 0,
                    color=COLORS["drawdown"], alpha=0.4)
    ax.plot(drawdown.index, drawdown.values, color=COLORS["drawdown"],
            linewidth=0.8)

    ax.set_ylabel("Drawdown (%)")
    ax.set_ylim(drawdown.min() * 1.1, 2)
    ax.grid(True, alpha=0.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def _plot_monthly_heatmap(ax, returns: pd.Series):
    """Plot monthly returns as a heatmap."""
    ax.set_title("Monthly Returns (%)", fontweight="bold")

    # Compute monthly returns
    monthly = returns.groupby([returns.index.year, returns.index.month]).apply(
        lambda x: (1 + x).prod() - 1
    ) * 100

    if monthly.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        return

    # Reshape to year × month matrix
    years = sorted(set(idx[0] for idx in monthly.index))
    months = list(range(1, 13))
    heatmap_data = np.full((len(years), 12), np.nan)

    for (year, month), val in monthly.items():
        if year in years:
            row = years.index(year)
            heatmap_data[row, month - 1] = val

    # Plot
    im = ax.imshow(
        heatmap_data, aspect="auto", cmap="RdYlGn",
        vmin=-10, vmax=10,
    )
    ax.set_xticks(range(12))
    ax.set_xticklabels(["J", "F", "M", "A", "M", "J",
                        "J", "A", "S", "O", "N", "D"])
    ax.set_yticks(range(len(years)))
    ax.set_yticklabels(years)

    # Add text annotations
    for i in range(len(years)):
        for j in range(12):
            val = heatmap_data[i, j]
            if not np.isnan(val):
                color = "black" if abs(val) < 5 else "white"
                ax.text(j, i, f"{val:.1f}", ha="center", va="center",
                        fontsize=7, color=color)

    plt.colorbar(im, ax=ax, shrink=0.8)


def _plot_return_distribution(ax, returns: pd.Series):
    """Plot histogram of daily returns."""
    ax.set_title("Daily Return Distribution", fontweight="bold")

    daily = returns.dropna() * 100
    if daily.empty:
        return

    ax.hist(daily, bins=50, color=COLORS["equity"], alpha=0.7,
            edgecolor="none", density=True)
    ax.axvline(0, color="white", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.axvline(daily.mean(), color=COLORS["positive"], linewidth=1.2,
               linestyle="-", label=f"Mean: {daily.mean():.2f}%")

    ax.set_xlabel("Daily Return (%)")
    ax.set_ylabel("Density")
    ax.legend(framealpha=0.3)
    ax.grid(True, alpha=0.2)


def _plot_rolling_sharpe(ax, returns: pd.Series, window: int = 252):
    """Plot rolling 1-year Sharpe ratio."""
    ax.set_title(f"Rolling {window}-Day Sharpe", fontweight="bold")

    rolling = compute_rolling_metrics(returns, window)
    if rolling.empty:
        return

    sharpe = rolling["rolling_sharpe"].dropna()
    ax.plot(sharpe.index, sharpe.values, color=COLORS["equity"], linewidth=1)
    ax.axhline(0, color="white", linewidth=0.5, linestyle="--", alpha=0.3)
    ax.axhline(1, color=COLORS["positive"], linewidth=0.5, linestyle="--", alpha=0.3)
    ax.axhline(-1, color=COLORS["negative"], linewidth=0.5, linestyle="--", alpha=0.3)

    ax.fill_between(
        sharpe.index, sharpe.values, 0,
        where=sharpe.values >= 0,
        color=COLORS["positive"], alpha=0.2,
    )
    ax.fill_between(
        sharpe.index, sharpe.values, 0,
        where=sharpe.values < 0,
        color=COLORS["negative"], alpha=0.2,
    )

    ax.set_ylabel("Sharpe Ratio")
    ax.grid(True, alpha=0.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def _plot_metrics_table(ax, metrics: PerformanceMetrics):
    """Render key metrics as a styled table."""
    ax.set_title("Key Metrics", fontweight="bold")
    ax.axis("off")

    rows = [
        ("CAGR", f"{metrics.cagr:.2%}"),
        ("Sharpe Ratio", f"{metrics.sharpe_ratio:.2f}"),
        ("Sortino Ratio", f"{metrics.sortino_ratio:.2f}"),
        ("Calmar Ratio", f"{metrics.calmar_ratio:.2f}"),
        ("Max Drawdown", f"{metrics.max_drawdown:.2%}"),
        ("Max DD Duration", f"{metrics.max_drawdown_duration_days}d"),
        ("Annual Volatility", f"{metrics.annualised_volatility:.2%}"),
        ("Win Rate", f"{metrics.win_rate:.1%}"),
        ("Profit Factor", f"{metrics.profit_factor:.2f}"),
        ("Total Trades", f"{metrics.total_trades}"),
        ("Total Costs", f"₹{metrics.total_costs:,.0f}"),
        ("Alpha", f"{metrics.alpha:.2%}"),
        ("Beta", f"{metrics.beta:.2f}"),
    ]

    table = ax.table(
        cellText=[[r[1]] for r in rows],
        rowLabels=[r[0] for r in rows],
        colLabels=["Value"],
        cellLoc="center",
        rowLoc="right",
        loc="center",
    )

    table.auto_set_font_size(False)
    table.set_fontsize(9)

    # Style the table
    for key, cell in table.get_celld().items():
        cell.set_edgecolor("#333")
        cell.set_facecolor("#1a1a2e")
        cell.set_text_props(color="#eee")


def plot_comparison(
    results: Dict[str, pd.Series],
    title: str = "Strategy Comparison",
    save_path: Optional[Path] = None,
):
    """
    Plot multiple equity curves for comparison.

    Parameters
    ----------
    results : dict
        Maps label -> equity_curve (pd.Series).
    """
    setup_style()
    fig, ax = plt.subplots(figsize=(14, 6))

    colors = ["#00ff88", "#ff6b6b", "#4ecdc4", "#ffe66d", "#a28fd0",
              "#ff8c42", "#98d8c8", "#f7dc6f"]

    for i, (label, equity) in enumerate(results.items()):
        norm = equity / equity.iloc[0] * 100
        color = colors[i % len(colors)]
        ax.plot(norm.index, norm.values, label=label, color=color, linewidth=1.5)

    ax.set_title(title, fontweight="bold", fontsize=14)
    ax.set_ylabel("Value (base 100)")
    ax.legend(loc="upper left", framealpha=0.3)
    ax.grid(True, alpha=0.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    save_path = save_path or (RESULTS_DIR / "comparison.png")
    fig.savefig(save_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    logger.info(f"Comparison chart saved to {save_path}")
