"""
Market-Timing Filter Test on Pure 12-1 Momentum.

The 12-1 momentum strategy is UNCHANGED. We only add a market regime
overlay that moves the WHOLE portfolio to cash when the NIFTY index is
below a moving average, and re-enters the momentum portfolio when it
recovers.

Filters tested (one at a time):
  1. NIFTY above 200 DMA          (200-day SMA of daily closes)
  2. NIFTY above 10-month SMA     (SMA of last 10 monthly closes)
  3. NIFTY above 12-month SMA     (SMA of last 12 monthly closes)

Overlay rules:
  - Exit to cash IMMEDIATELY (daily check) when filter turns OFF  -> drawdown protection
  - Re-enter the top-N momentum portfolio when filter turns back ON
  - NO stop losses, NO drawdown liquidation, NO cooldowns, NO blending

Look-ahead control: the filter at date D uses only NIFTY closes up to and
including D, matching the existing close-execution convention of the
baseline so the comparison is apples-to-apples.

Objective: cut Max Drawdown and Time Underwater while keeping >= 80% of
the baseline (no-filter) CAGR.
"""

import sys
import io
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import logging
logging.basicConfig(level=logging.ERROR)
for name in logging.root.manager.loggerDict:
    logging.getLogger(name).setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from tqdm import tqdm

from config import SystemConfig
from data.downloader import (
    download_all_stocks, download_market_proxy, build_price_panel,
)
from universe.universe_builder import UniverseBuilder
from costs.cost_model import CostModel
from utils.helpers import get_rebalance_dates
from run_pure_momentum import compute_12_1_momentum


# ─────────────────────────────────────────────────────────────────────
# MARKET FILTER SERIES
# ─────────────────────────────────────────────────────────────────────

def build_filter_series(nifty_close: pd.Series, kind: str) -> pd.Series:
    """
    Return a daily boolean Series: True = market ON (invest), False = cash.

    kind:
      '200dma' -> daily 200-day SMA
      '10mo'   -> SMA of last 10 monthly closes (forward-filled to daily)
      '12mo'   -> SMA of last 12 monthly closes (forward-filled to daily)

    No look-ahead: SMA at date D uses only closes up to D.
    """
    nifty_close = nifty_close.sort_index()

    if kind == "200dma":
        sma = nifty_close.rolling(200).mean()
        on = nifty_close > sma

    elif kind in ("10mo", "12mo"):
        window = 10 if kind == "10mo" else 12
        # Month-end closes (last trading day of each month)
        monthly = nifty_close.resample("ME").last()
        monthly_sma = monthly.rolling(window).mean()
        # Forward-fill the month-end SMA to the daily index. On a daily date D,
        # this uses the SMA computed through the most recently COMPLETED month-end
        # at or before D -> no look-ahead.
        sma = monthly_sma.reindex(nifty_close.index, method="ffill")
        on = nifty_close > sma

    else:
        raise ValueError(f"Unknown filter kind: {kind}")

    # During warmup (SMA is NaN) default to ON so we don't sit in cash by accident.
    on = on.where(sma.notna(), other=True)
    return on.astype(bool)


# ─────────────────────────────────────────────────────────────────────
# FILTERED MOMENTUM BACKTEST
# ─────────────────────────────────────────────────────────────────────

def run_filtered_momentum_backtest(
    close_panel, high_panel, low_panel, volume_panel,
    n_stocks, rebalance_freq, initial_capital, config,
    filter_series=None, apply_costs=True, show_progress=True,
):
    """
    Pure 12-1 momentum with an optional market-timing overlay.

    filter_series : daily bool Series (True=invest, False=cash). None = baseline.
    """
    cfg = config
    start = pd.Timestamp(cfg.backtest.start_date)
    end = pd.Timestamp(cfg.backtest.end_date)

    data_start = close_panel.index.min()
    data_end = close_panel.index.max()
    start = max(start, data_start + pd.Timedelta(days=365))
    end = min(end, data_end)

    all_dates = close_panel.index[
        (close_panel.index >= start) & (close_panel.index <= end)
    ]
    if all_dates.empty:
        return {"equity_curve": pd.Series(dtype=float)}

    rebal_dates = get_rebalance_dates(all_dates, rebalance_freq)
    rebal_set = set(rebal_dates)

    universe_builder = UniverseBuilder(
        close_panel, high_panel, low_panel, volume_panel, cfg.universe,
    )
    cost_model = CostModel(cfg.costs)

    cash = initial_capital
    current_holdings = {}
    in_cash_due_to_filter = False

    equity_values = []
    total_costs = 0.0
    days_in_cash = 0
    n_forced_exits = 0
    n_reentries = 0

    def market_on(date):
        if filter_series is None:
            return True
        return bool(filter_series.get(date, True))

    def sell_all(date, today_close, liquidity_tiers):
        nonlocal cash, total_costs
        for sym, qty in list(current_holdings.items()):
            price = today_close.get(sym, 0)
            if price <= 0 or np.isnan(price):
                continue
            value = qty * price
            cost = 0.0
            if apply_costs:
                tier = liquidity_tiers.get(sym, 2)
                cost = cost_model.calculate_trade_cost(
                    sym, "SELL", qty, price, liquidity_tier=tier,
                ).total_cost
            cash += value - cost
            total_costs += cost
            del current_holdings[sym]

    def rebalance(date, today_close, portfolio_value):
        nonlocal cash, total_costs
        universe = universe_builder.build_universe(date)
        if not universe.symbols:
            return
        momentum_scores = compute_12_1_momentum(close_panel, date, universe.symbols)
        if momentum_scores.empty or len(momentum_scores) < n_stocks:
            return
        selected = list(momentum_scores.head(n_stocks).index)
        per_stock = portfolio_value / n_stocks

        target_shares = {}
        for sym in selected:
            price = today_close.get(sym, np.nan)
            if np.isnan(price) or price <= 0:
                continue
            shares = int(per_stock / price)
            if shares > 0:
                target_shares[sym] = shares

        # SELL non-targets / over-weights
        for sym, qty in list(current_holdings.items()):
            target_qty = target_shares.get(sym, 0)
            sell_qty = qty - target_qty
            if sell_qty > 0:
                price = today_close.get(sym, 0)
                if price <= 0 or np.isnan(price):
                    continue
                value = sell_qty * price
                cost = 0.0
                if apply_costs:
                    tier = universe.liquidity_tiers.get(sym, 2)
                    cost = cost_model.calculate_trade_cost(
                        sym, "SELL", sell_qty, price, liquidity_tier=tier,
                    ).total_cost
                cash += value - cost
                total_costs += cost
                current_holdings[sym] = qty - sell_qty
                if current_holdings[sym] <= 0:
                    del current_holdings[sym]

        # BUY targets
        for sym, target_qty in target_shares.items():
            buy_qty = target_qty - current_holdings.get(sym, 0)
            if buy_qty <= 0:
                continue
            price = today_close.get(sym, 0)
            if price <= 0 or np.isnan(price):
                continue
            tier = universe.liquidity_tiers.get(sym, 2)
            buy_value = buy_qty * price
            cost = 0.0
            if apply_costs:
                cost = cost_model.calculate_trade_cost(
                    sym, "BUY", buy_qty, price, liquidity_tier=tier,
                ).total_cost
            total_buy_cost = buy_value + cost
            if total_buy_cost > cash:
                affordable = int((cash - cost) / price) if price > 0 else 0
                if affordable <= 0:
                    continue
                buy_qty = affordable
                buy_value = buy_qty * price
                if apply_costs:
                    cost = cost_model.calculate_trade_cost(
                        sym, "BUY", buy_qty, price, liquidity_tier=tier,
                    ).total_cost
                total_buy_cost = buy_value + cost
            cash -= total_buy_cost
            total_costs += cost
            current_holdings[sym] = current_holdings.get(sym, 0) + buy_qty

    iterator = tqdm(all_dates, desc=f"{n_stocks}st/{rebalance_freq}", unit="day") \
        if show_progress else all_dates

    for date in iterator:
        today_close = close_panel.loc[date]

        holdings_value = sum(
            qty * today_close.get(sym, 0)
            for sym, qty in current_holdings.items()
            if not np.isnan(today_close.get(sym, np.nan))
        )
        portfolio_value = cash + holdings_value
        equity_values.append({"date": date, "portfolio_value": portfolio_value})

        on = market_on(date)

        if filter_series is not None and not on:
            # Market OFF -> ensure fully in cash
            if current_holdings:
                # Forced liquidation uses default tier-2 cost (conservative).
                sell_all(date, today_close, {})
                n_forced_exits += 1
            in_cash_due_to_filter = True
            days_in_cash += 1
            continue

        # Market ON (or baseline)
        is_rebal = date in rebal_set
        do_rebalance = is_rebal
        if filter_series is not None and in_cash_due_to_filter:
            # Re-enter immediately on the first ON day after a forced exit
            do_rebalance = True
            in_cash_due_to_filter = False
            n_reentries += 1

        if do_rebalance:
            # recompute portfolio value (cash may have changed nothing here)
            rebalance(date, today_close, portfolio_value)

    eq_df = pd.DataFrame(equity_values).set_index("date")
    equity_curve = eq_df["portfolio_value"]

    return {
        "equity_curve": equity_curve,
        "total_costs": total_costs,
        "days_in_cash": days_in_cash,
        "total_days": len(all_dates),
        "n_forced_exits": n_forced_exits,
        "n_reentries": n_reentries,
    }


# ─────────────────────────────────────────────────────────────────────
# STATISTICS
# ─────────────────────────────────────────────────────────────────────

def compute_stats(equity: pd.Series, initial_capital: float):
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max

    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1

    trough_idx = dd.idxmin()
    max_dd = dd[trough_idx]
    peak_idx = equity[:trough_idx].idxmax()
    peak_value = equity[peak_idx]

    # recovery after the max-DD trough
    post = equity[trough_idx:]
    recovered = post[post >= peak_value]
    if recovered.empty:
        recovery_days = None
    else:
        recovery_days = (recovered.index[0] - trough_idx).days

    pct_time_underwater = (dd < 0).sum() / len(dd) * 100
    # Time spent in *deep* drawdowns — the pain that actually matters.
    pct_time_dd_10 = (dd < -0.10).sum() / len(dd) * 100
    pct_time_dd_20 = (dd < -0.20).sum() / len(dd) * 100
    # Ulcer-style severity: RMS of the drawdown curve.
    ulcer = np.sqrt((dd ** 2).mean()) * 100

    return {
        "cagr": cagr,
        "max_dd": max_dd,
        "pct_underwater": pct_time_underwater,
        "pct_dd_10": pct_time_dd_10,
        "pct_dd_20": pct_time_dd_20,
        "ulcer": ulcer,
        "recovery_days": recovery_days,
        "peak_date": peak_idx,
        "trough_date": trough_idx,
        "final_value": equity.iloc[-1],
        "peak_value": peak_value,
    }


def main():
    config = SystemConfig()
    initial_capital = config.portfolio.initial_capital

    print("=" * 78)
    print("  MARKET-TIMING FILTERS ON PURE 12-1 MOMENTUM (NET of costs)")
    print(f"  Initial Capital: Rs {initial_capital:,.0f}")
    print(f"  Period: {config.backtest.start_date} to {config.backtest.end_date}")
    print("  Overlay: 100% cash when NIFTY < MA; re-enter momentum when NIFTY > MA")
    print("=" * 78)

    print("\nLoading stock data...")
    stock_data = download_all_stocks(use_cache=True)
    if not stock_data:
        print("ERROR: No stock data.")
        return
    close_panel  = build_price_panel(stock_data, "Close")
    high_panel   = build_price_panel(stock_data, "High")
    low_panel    = build_price_panel(stock_data, "Low")
    volume_panel = build_price_panel(stock_data, "Volume")

    print("Loading NIFTY market proxy...")
    nifty_df = download_market_proxy(
        start_date=config.backtest.start_date,
        end_date=config.backtest.end_date,
    )
    if nifty_df is None or nifty_df.empty:
        print("ERROR: Could not load NIFTY proxy (^NSEI).")
        return
    nifty_close = nifty_df["Close"].sort_index()
    print(f"  NIFTY proxy: {len(nifty_close)} days "
          f"({nifty_close.index.min().date()} to {nifty_close.index.max().date()})")

    filters = {
        "Baseline (no filter)": None,
        "NIFTY > 200 DMA":      build_filter_series(nifty_close, "200dma"),
        "NIFTY > 10-month SMA": build_filter_series(nifty_close, "10mo"),
        "NIFTY > 12-month SMA": build_filter_series(nifty_close, "12mo"),
    }

    param_grid = [
        (5,  "monthly"),
        (5,  "quarterly"),
        (10, "monthly"),
        (10, "quarterly"),
    ]

    for n_stocks, freq in param_grid:
        print(f"\n\n{'#'*78}")
        print(f"#  CONFIG: {n_stocks} stocks / {freq} rebalancing")
        print(f"{'#'*78}")

        results = {}
        for fname, fseries in filters.items():
            res = run_filtered_momentum_backtest(
                close_panel, high_panel, low_panel, volume_panel,
                n_stocks=n_stocks, rebalance_freq=freq,
                initial_capital=initial_capital, config=config,
                filter_series=fseries, apply_costs=True, show_progress=False,
            )
            stats = compute_stats(res["equity_curve"], initial_capital)
            stats["days_in_cash"] = res.get("days_in_cash", 0)
            stats["total_days"] = res.get("total_days", 1)
            stats["n_forced_exits"] = res.get("n_forced_exits", 0)
            stats["n_reentries"] = res.get("n_reentries", 0)
            stats["total_costs"] = res.get("total_costs", 0.0)
            results[fname] = stats

        base = results["Baseline (no filter)"]

        # Table
        print(f"\n{'Filter':<24} {'CAGR':>7} {'%Base':>6} {'MaxDD':>7} "
              f"{'UW':>6} {'<-10%':>6} {'<-20%':>6} {'Ulcer':>6} {'Recov':>8} {'FinalValue':>15}")
        print("-" * 100)
        for fname, s in results.items():
            cagr_pct_of_base = (s["cagr"] / base["cagr"] * 100) if base["cagr"] != 0 else 0
            rec = f"{s['recovery_days']}d" if s["recovery_days"] is not None else "NOTREC"
            print(f"{fname:<24} {s['cagr']:>6.1%} {cagr_pct_of_base:>5.0f}% "
                  f"{s['max_dd']:>6.1%} {s['pct_underwater']:>5.0f}% {s['pct_dd_10']:>5.0f}% "
                  f"{s['pct_dd_20']:>5.0f}% {s['ulcer']:>5.1f} {rec:>8} "
                  f"Rs{s['final_value']:>12,.0f}")
        print("  UW=% days underwater | <-10%/<-20%=% days in DD beyond that depth | "
              "Ulcer=RMS drawdown")

        # Filter activity detail
        print(f"\n  Filter activity (time parked in cash / exits / re-entries):")
        for fname, s in results.items():
            if fname == "Baseline (no filter)":
                continue
            cash_pct = s["days_in_cash"] / s["total_days"] * 100
            print(f"    {fname:<24} {cash_pct:>5.1f}% in cash | "
                  f"{s['n_forced_exits']:>3} exits | {s['n_reentries']:>3} re-entries | "
                  f"costs Rs{s['total_costs']:,.0f}")

        # Objective check
        print(f"\n  Objective check (keep >=80% CAGR, cut DD & underwater):")
        for fname, s in results.items():
            if fname == "Baseline (no filter)":
                continue
            cagr_ret = s["cagr"] / base["cagr"] * 100 if base["cagr"] else 0
            dd_better = s["max_dd"] > base["max_dd"]  # less negative = better
            uw_better = s["pct_underwater"] < base["pct_underwater"]
            passes = (cagr_ret >= 80) and dd_better and uw_better
            verdict = "PASS" if passes else "FAIL"
            print(f"    [{verdict}] {fname:<24} "
                  f"CAGR {cagr_ret:.0f}% of base | "
                  f"DD {'improved' if dd_better else 'worse':>8} "
                  f"({base['max_dd']:.0%}->{s['max_dd']:.0%}) | "
                  f"Underwater {'improved' if uw_better else 'worse':>8} "
                  f"({base['pct_underwater']:.0f}%->{s['pct_underwater']:.0f}%)")

    print(f"\n{'='*78}\n")


if __name__ == "__main__":
    main()
