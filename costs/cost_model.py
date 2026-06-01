"""
Transaction cost model for Indian equity delivery trades.

Models all cost components: STT, stamp duty, exchange charges,
SEBI fee, GST, brokerage (₹20/order), DP charges, and slippage.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CostConfig, setup_logging

logger = setup_logging("cost_model")


@dataclass
class TradeCost:
    """Cost breakdown for a single trade."""
    symbol: str
    side: str                  # "BUY" or "SELL"
    value: float              # trade value in ₹
    shares: int
    price: float

    # Cost components
    stt: float = 0.0
    stamp_duty: float = 0.0
    exchange_charges: float = 0.0
    sebi_fee: float = 0.0
    gst: float = 0.0
    brokerage: float = 0.0
    dp_charges: float = 0.0
    slippage: float = 0.0
    impact_cost: float = 0.0

    @property
    def total_cost(self) -> float:
        return (
            self.stt + self.stamp_duty + self.exchange_charges +
            self.sebi_fee + self.gst + self.brokerage +
            self.dp_charges + self.slippage + self.impact_cost
        )

    @property
    def cost_pct(self) -> float:
        return self.total_cost / self.value if self.value > 0 else 0


class CostModel:
    """
    Comprehensive transaction cost model for Indian equity delivery.

    Calculates all statutory charges, broker fees, and estimated slippage
    for each trade.
    """

    def __init__(self, config: Optional[CostConfig] = None):
        self.config = config or CostConfig()

    def calculate_trade_cost(
        self,
        symbol: str,
        side: str,
        shares: int,
        price: float,
        avg_daily_volume: float = 0,
        avg_daily_value: float = 0,
        liquidity_tier: int = 2,
    ) -> TradeCost:
        """
        Calculate total cost for a single trade.

        Parameters
        ----------
        symbol : str
        side : str
            "BUY" or "SELL"
        shares : int
        price : float
            Execution price per share.
        avg_daily_volume : float
            Stock's average daily volume (for impact cost).
        avg_daily_value : float
            Stock's average daily turnover (for tier classification).
        liquidity_tier : int
            1, 2, or 3. Used for slippage estimation.
        """
        cfg = self.config
        value = shares * price
        side = side.upper()

        cost = TradeCost(
            symbol=symbol, side=side, value=value,
            shares=shares, price=price,
        )

        if value <= 0:
            return cost

        # ── STT (Securities Transaction Tax) ──
        cost.stt = value * cfg.stt_rate

        # ── Stamp Duty (buy side only) ──
        if side == "BUY":
            cost.stamp_duty = value * cfg.stamp_duty_buy

        # ── Exchange charges (NSE) ──
        cost.exchange_charges = value * cfg.exchange_charges

        # ── SEBI fee ──
        cost.sebi_fee = value * cfg.sebi_fee

        # ── Brokerage (₹20 flat per order) ──
        cost.brokerage = min(cfg.brokerage_per_order, value * 0.025)  # capped at 2.5%

        # ── GST on (brokerage + exchange charges) ──
        cost.gst = (cost.brokerage + cost.exchange_charges) * cfg.gst_rate

        # ── DP charges (sell side only) ──
        if side == "SELL":
            cost.dp_charges = cfg.dp_charges_per_scrip

        # ── Slippage (based on liquidity tier) ──
        if liquidity_tier == 1:
            slippage_rate = cfg.slippage_tier1
        elif liquidity_tier == 2:
            slippage_rate = cfg.slippage_tier2
        else:
            slippage_rate = cfg.slippage_tier3
        cost.slippage = value * slippage_rate

        # ── Impact cost (for large positions) ──
        if avg_daily_value > 0:
            position_pct = value / avg_daily_value
            if position_pct > cfg.impact_cost_threshold:
                cost.impact_cost = value * cfg.impact_cost_base * np.sqrt(
                    position_pct / cfg.impact_cost_threshold
                )

        return cost

    def calculate_rebalance_costs(
        self,
        trades: List[Dict],
        liquidity_tiers: Optional[Dict[str, int]] = None,
    ) -> Tuple[float, List[TradeCost]]:
        """
        Calculate total costs for a set of rebalancing trades.

        Parameters
        ----------
        trades : list of dict
            Each dict has: symbol, side, shares, price, avg_daily_value (optional)
        liquidity_tiers : dict, optional
            symbol -> tier

        Returns
        -------
        Tuple of (total_cost, list of TradeCost).
        """
        liquidity_tiers = liquidity_tiers or {}
        costs = []
        total = 0.0

        for trade in trades:
            tier = liquidity_tiers.get(trade["symbol"], 2)
            cost = self.calculate_trade_cost(
                symbol=trade["symbol"],
                side=trade["side"],
                shares=trade["shares"],
                price=trade["price"],
                avg_daily_value=trade.get("avg_daily_value", 0),
                liquidity_tier=tier,
            )
            costs.append(cost)
            total += cost.total_cost

        return total, costs

    def estimate_round_trip_cost_pct(
        self,
        order_value: float,
        liquidity_tier: int = 2,
    ) -> float:
        """
        Estimate total round-trip cost as a percentage.
        Useful for quick cost estimates.
        """
        cfg = self.config

        # Buy side
        buy_cost = (
            cfg.stt_rate +
            cfg.stamp_duty_buy +
            cfg.exchange_charges +
            cfg.sebi_fee
        )
        buy_brokerage = min(cfg.brokerage_per_order / order_value, 0.025)
        buy_cost += buy_brokerage
        buy_cost += (buy_brokerage + cfg.exchange_charges) * cfg.gst_rate

        # Sell side
        sell_cost = (
            cfg.stt_rate +
            cfg.exchange_charges +
            cfg.sebi_fee
        )
        sell_brokerage = min(cfg.brokerage_per_order / order_value, 0.025)
        sell_cost += sell_brokerage
        sell_cost += (sell_brokerage + cfg.exchange_charges) * cfg.gst_rate
        sell_cost += cfg.dp_charges_per_scrip / order_value

        # Slippage
        if liquidity_tier == 1:
            slippage = cfg.slippage_tier1
        elif liquidity_tier == 2:
            slippage = cfg.slippage_tier2
        else:
            slippage = cfg.slippage_tier3

        round_trip = buy_cost + sell_cost + 2 * slippage
        return round_trip


if __name__ == "__main__":
    model = CostModel()

    # Example: ₹1L capital, 15 stocks, ₹6,667 per position
    print("Round-trip cost estimates for different position sizes:")
    print(f"{'Position Size':>15} {'Tier 1':>10} {'Tier 2':>10} {'Tier 3':>10}")
    for pos_size in [5000, 6667, 10000, 20000, 50000]:
        t1 = model.estimate_round_trip_cost_pct(pos_size, 1)
        t2 = model.estimate_round_trip_cost_pct(pos_size, 2)
        t3 = model.estimate_round_trip_cost_pct(pos_size, 3)
        print(f"₹{pos_size:>13,} {t1:>9.2%} {t2:>9.2%} {t3:>9.2%}")
