"""
Vectorized backtesting engine.

Simulates portfolio performance over historical data with:
- Point-in-time universe construction
- Strategy signal generation
- Regime-dependent allocation
- Realistic transaction costs
- Stop loss management
- T+1 execution (signal on T, execute on T+1 at Open)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from tqdm import tqdm

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    SystemConfig, DEFAULT_CONFIG, setup_logging,
)
from universe.universe_builder import UniverseBuilder
from strategies.momentum import MomentumStrategy
from strategies.trend_following import TrendFollowingStrategy
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from regime.regime_filter import RegimeFilter
from portfolio.ranker import compute_composite_scores, select_top_stocks
from portfolio.constructor import construct_portfolio
from risk.risk_manager import RiskManager
from risk.rebalancer import generate_rebalance_trades, Trade
from costs.cost_model import CostModel
from utils.helpers import get_rebalance_dates
from utils.indicators import atr

logger = setup_logging("backtest")


@dataclass
class BacktestResult:
    """Complete backtest results."""
    equity_curve: pd.Series               # daily portfolio value
    returns: pd.Series                    # daily returns
    holdings_history: List[Dict]          # per-rebalance holdings snapshot
    trades_history: List[Dict]            # all trades executed
    regime_history: Dict                  # regime at each rebalance
    costs_total: float = 0.0             # total transaction costs paid
    config_summary: Dict = field(default_factory=dict)

    # Metadata
    n_stocks: int = 0
    rebalance_frequency: str = ""
    start_date: str = ""
    end_date: str = ""
    total_rebalances: int = 0


class BacktestEngine:
    """
    Portfolio backtest engine.

    Core loop:
    1. For each rebalance date:
       a. Build universe (point-in-time)
       b. Compute strategy scores
       c. Detect regime
       d. Rank and select stocks
       e. Construct portfolio (weights, shares)
       f. Generate rebalance trades
       g. Apply transaction costs
    2. Between rebalance dates:
       a. Update portfolio value daily
       b. Check stop losses
       c. Monitor drawdown
    """

    def __init__(self, config: Optional[SystemConfig] = None):
        self.config = config or DEFAULT_CONFIG

        # Initialize components
        self.strategies = {
            "momentum": MomentumStrategy(self.config.momentum),
            "trend_following": TrendFollowingStrategy(self.config.trend),
            "breakout": BreakoutStrategy(self.config.breakout),
            "mean_reversion": MeanReversionStrategy(self.config.mean_reversion),
        }
        self.regime_filter = RegimeFilter(self.config.regime)
        self.risk_manager = RiskManager(self.config.risk)
        self.cost_model = CostModel(self.config.costs)

    def run(
        self,
        close_panel: pd.DataFrame,
        high_panel: pd.DataFrame,
        low_panel: pd.DataFrame,
        volume_panel: pd.DataFrame,
        open_panel: pd.DataFrame,
        market_close: pd.Series,
        market_high: Optional[pd.Series] = None,
        market_low: Optional[pd.Series] = None,
        n_stocks: int = 15,
        rebalance_frequency: str = "monthly",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> BacktestResult:
        """
        Run a complete backtest.

        Parameters
        ----------
        close_panel, high_panel, low_panel, volume_panel, open_panel : DataFrame
            Wide-format price panels (dates × symbols).
        market_close : Series
            Market proxy (Nifty 50) close prices.
        market_high, market_low : Series, optional
            Market proxy H/L for ADX.
        n_stocks : int
            Number of stocks in portfolio.
        rebalance_frequency : str
            'weekly', 'biweekly', or 'monthly'.
        start_date, end_date : str, optional
            Backtest window.
        """
        cfg = self.config
        start = pd.Timestamp(start_date or cfg.backtest.start_date)
        end = pd.Timestamp(end_date or cfg.backtest.end_date)

        # Validate date range
        data_start = close_panel.index.min()
        data_end = close_panel.index.max()
        start = max(start, data_start + pd.Timedelta(days=365))  # need warmup
        end = min(end, data_end)

        logger.info(
            f"Starting backtest: {start.date()} to {end.date()}, "
            f"{n_stocks} stocks, {rebalance_frequency} rebalancing"
        )

        # All trading dates in the backtest window
        all_dates = close_panel.index[
            (close_panel.index >= start) & (close_panel.index <= end)
        ]

        if all_dates.empty:
            logger.error("No trading dates in backtest window")
            return BacktestResult(
                equity_curve=pd.Series(dtype=float),
                returns=pd.Series(dtype=float),
                holdings_history=[],
                trades_history=[],
                regime_history={},
            )

        # Rebalance dates
        rebal_dates = get_rebalance_dates(all_dates, rebalance_frequency)
        rebal_set = set(rebal_dates)

        # Build universe builder
        universe_builder = UniverseBuilder(
            close_panel, high_panel, low_panel, volume_panel,
            cfg.universe,
        )

        # State
        capital = cfg.portfolio.initial_capital
        current_holdings: Dict[str, int] = {}    # symbol -> shares
        cash = capital
        portfolio_value = capital
        peak_value = capital
        liquidation_cooldown_until: Optional[pd.Timestamp] = None  # cooldown after liquidation

        equity_values = []
        holdings_history = []
        trades_history = []
        regime_history = {}
        total_costs = 0.0
        total_rebalances = 0

        # ── Main backtest loop ──
        for date in tqdm(all_dates, desc="Backtesting", unit="day"):

            # Get today's prices
            today_close = close_panel.loc[date]
            today_open = open_panel.loc[date] if date in open_panel.index else today_close

            # ── Execute pending trades (from yesterday's signal) ──
            # Trades generated at previous rebalance execute at today's open
            # (This is handled by using T+1 rebalance logic below)

            # ── Calculate portfolio value ──
            holdings_value = sum(
                qty * today_close.get(sym, 0)
                for sym, qty in current_holdings.items()
                if not np.isnan(today_close.get(sym, np.nan))
            )
            portfolio_value = cash + holdings_value
            peak_value = max(peak_value, portfolio_value)

            equity_values.append({
                "date": date,
                "portfolio_value": portfolio_value,
                "cash": cash,
                "holdings_value": holdings_value,
                "n_holdings": len(current_holdings),
            })

            # ── Check stop losses (daily) ──
            if current_holdings:
                price_dict = {
                    sym: today_close.get(sym, np.nan)
                    for sym in current_holdings
                }
                stop_exits = self.risk_manager.update_stops(
                    price_dict, date
                )

                # Execute stop loss sells at today's close (simplified)
                for sym in stop_exits:
                    if sym in current_holdings:
                        qty = current_holdings[sym]
                        price = today_close.get(sym, 0)
                        if price > 0 and qty > 0:
                            sell_value = qty * price
                            cost_obj = self.cost_model.calculate_trade_cost(
                                sym, "SELL", qty, price,
                            )
                            sell_proceeds = sell_value - cost_obj.total_cost
                            cash += sell_proceeds
                            total_costs += cost_obj.total_cost

                            trades_history.append({
                                "date": date,
                                "symbol": sym,
                                "side": "SELL",
                                "shares": qty,
                                "price": price,
                                "value": sell_value,
                                "cost": cost_obj.total_cost,
                                "reason": "stop_loss",
                            })

                            del current_holdings[sym]

            # ── Check portfolio-level risk ──
            # Skip risk check if in liquidation cooldown or no holdings
            if liquidation_cooldown_until and date < liquidation_cooldown_until:
                # In cooldown — only allow rebalancing (re-entry)
                risk_check = {"action": "none", "reason": "cooldown", "scale_factor": 0.5}
            elif not current_holdings:
                # All cash — no risk to manage, allow re-entry
                risk_check = {"action": "none", "reason": "all_cash", "scale_factor": 1.0}
            else:
                daily_ret = (
                    (portfolio_value / equity_values[-2]["portfolio_value"] - 1)
                    if len(equity_values) > 1 else 0
                )
                risk_check = self.risk_manager.check_portfolio_risk(
                    portfolio_value, peak_value, daily_ret, date
                )

            if risk_check["action"] == "liquidate" and current_holdings:
                # Sell everything
                for sym, qty in list(current_holdings.items()):
                    price = today_close.get(sym, 0)
                    if price > 0:
                        cost_obj = self.cost_model.calculate_trade_cost(
                            sym, "SELL", qty, price,
                        )
                        cash += qty * price - cost_obj.total_cost
                        total_costs += cost_obj.total_cost
                        trades_history.append({
                            "date": date, "symbol": sym, "side": "SELL",
                            "shares": qty, "price": price,
                            "value": qty * price,
                            "cost": cost_obj.total_cost,
                            "reason": "drawdown_liquidation",
                        })
                current_holdings.clear()
                self.risk_manager.clear_stops()
                # Reset peak to current value so we don't keep triggering
                peak_value = portfolio_value
                # Set cooldown: wait 30 days before re-entering
                liquidation_cooldown_until = date + pd.Timedelta(days=30)
                logger.info(f"Liquidated on {date.date()}. Cooldown until {liquidation_cooldown_until.date()}")
                continue

            # ── Rebalance (if it's a rebalance date) ──
            if date in rebal_set and risk_check["action"] != "halt":
                total_rebalances += 1

                # 1. Build universe
                universe = universe_builder.build_universe(date)

                if not universe.symbols:
                    continue

                # 2. Compute strategy scores
                strategy_scores = {}
                for name, strategy in self.strategies.items():
                    scores = strategy.compute_scores(
                        close_panel, high_panel, low_panel, volume_panel,
                        date, universe.symbols,
                    )
                    if not scores.empty:
                        strategy_scores[name] = scores

                if not strategy_scores:
                    continue

                # 3. Detect regime
                regime = self.regime_filter.detect_regime(
                    market_close, market_high, market_low, date,
                )
                regime_history[date] = regime

                # Adjust for portfolio-level risk scaling
                capital_alloc = regime.capital_allocation * risk_check["scale_factor"]

                # 4. Rank and select stocks
                composite = compute_composite_scores(strategy_scores, regime)
                selected = select_top_stocks(
                    composite,
                    n_stocks=n_stocks,
                    existing_portfolio=list(current_holdings.keys()),
                )

                if not selected:
                    continue

                # 5. Construct target portfolio
                current_portfolio_value = cash + holdings_value
                target = construct_portfolio(
                    selected,
                    close_panel,
                    date,
                    capital=current_portfolio_value,
                    capital_allocation=capital_alloc,
                    config=cfg.portfolio,
                    cost_config=cfg.costs,
                )

                # 6. Generate rebalance trades
                current_prices = {
                    sym: today_close.get(sym, 0)
                    for sym in set(list(current_holdings.keys()) + selected)
                }
                rebal_result = generate_rebalance_trades(
                    current_holdings,
                    target,
                    current_prices,
                    date,
                )

                # 7. Execute trades with costs
                # SELL first (free up cash)
                for trade in sorted(rebal_result.trades, key=lambda t: t.side != "SELL"):
                    price = trade.price
                    if price <= 0:
                        continue

                    tier = universe.liquidity_tiers.get(trade.symbol, 2)
                    cost_obj = self.cost_model.calculate_trade_cost(
                        trade.symbol, trade.side, trade.shares, price,
                        liquidity_tier=tier,
                    )

                    if trade.side == "SELL":
                        sell_proceeds = trade.value - cost_obj.total_cost
                        cash += sell_proceeds
                        current_holdings[trade.symbol] = (
                            current_holdings.get(trade.symbol, 0) - trade.shares
                        )
                        if current_holdings.get(trade.symbol, 0) <= 0:
                            current_holdings.pop(trade.symbol, None)
                            self.risk_manager._stop_levels.pop(trade.symbol, None)

                    elif trade.side == "BUY":
                        buy_cost = trade.value + cost_obj.total_cost
                        if buy_cost > cash:
                            # Not enough cash, reduce shares
                            affordable = int((cash - cost_obj.total_cost) / price)
                            if affordable <= 0:
                                continue
                            trade = Trade(
                                symbol=trade.symbol,
                                side="BUY",
                                shares=affordable,
                                price=price,
                                reason=trade.reason,
                            )
                            cost_obj = self.cost_model.calculate_trade_cost(
                                trade.symbol, "BUY", affordable, price,
                                liquidity_tier=tier,
                            )
                            buy_cost = trade.value + cost_obj.total_cost

                        cash -= buy_cost
                        current_holdings[trade.symbol] = (
                            current_holdings.get(trade.symbol, 0) + trade.shares
                        )

                        # Set stop loss for new/increased positions
                        if trade.reason == "new_entry":
                            # Compute ATR for stop
                            sym = trade.symbol
                            if sym in high_panel.columns and sym in low_panel.columns:
                                h = high_panel.loc[:date, sym].tail(30)
                                l = low_panel.loc[:date, sym].tail(30)
                                c_s = close_panel.loc[:date, sym].tail(30)
                                atr_val = atr(h, l, c_s, 20)
                                if not atr_val.empty and not np.isnan(atr_val.iloc[-1]):
                                    self.risk_manager.initialize_stop(
                                        sym, price, date, atr_val.iloc[-1]
                                    )

                    total_costs += cost_obj.total_cost

                    trades_history.append({
                        "date": date,
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "shares": trade.shares,
                        "price": price,
                        "value": trade.value,
                        "cost": cost_obj.total_cost,
                        "reason": trade.reason,
                    })

                # Record holdings snapshot
                holdings_history.append({
                    "date": date,
                    "holdings": dict(current_holdings),
                    "cash": cash,
                    "portfolio_value": portfolio_value,
                    "regime": regime.regime,
                    "n_stocks": len(current_holdings),
                })

        # ── Build result ──
        eq_df = pd.DataFrame(equity_values).set_index("date")
        equity_curve = eq_df["portfolio_value"]
        returns = equity_curve.pct_change().fillna(0)

        result = BacktestResult(
            equity_curve=equity_curve,
            returns=returns,
            holdings_history=holdings_history,
            trades_history=trades_history,
            regime_history=regime_history,
            costs_total=total_costs,
            config_summary={
                "n_stocks": n_stocks,
                "rebalance_frequency": rebalance_frequency,
                "initial_capital": cfg.portfolio.initial_capital,
                "weighting_method": cfg.portfolio.weighting_method,
            },
            n_stocks=n_stocks,
            rebalance_frequency=rebalance_frequency,
            start_date=str(start.date()),
            end_date=str(end.date()),
            total_rebalances=total_rebalances,
        )

        logger.info(
            f"Backtest complete: {start.date()} to {end.date()}, "
            f"{total_rebalances} rebalances, "
            f"₹{total_costs:,.0f} total costs, "
            f"final value: ₹{portfolio_value:,.0f}"
        )

        return result
