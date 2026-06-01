"""
Central configuration for the Systematic Trading System.
All hyperparameters, paths, and constants in one place.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import date

# ─────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "market_data.db"
BENCHMARK_CSV_PATH = DATA_DIR / "nifty500_tri.csv"
CONSTITUENTS_CSV_PATH = DATA_DIR / "nifty500_constituents.csv"
RESULTS_DIR = PROJECT_ROOT / "results"
LOG_DIR = PROJECT_ROOT / "logs"

# Ensure directories exist
for d in [DATA_DIR, CACHE_DIR, RESULTS_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────
# DATA DOWNLOAD
# ─────────────────────────────────────────────────────────────────────
@dataclass
class DownloadConfig:
    """Configuration for yfinance data downloading."""
    start_date: str = "2011-01-01"
    end_date: str = "2026-05-30"
    yfinance_suffix: str = ".NS"                   # NSE suffix
    batch_size: int = 50                            # stocks per yfinance batch
    max_retries: int = 3
    retry_delay_seconds: int = 5
    cache_format: str = "parquet"                   # parquet or csv
    min_history_days: int = 252                     # ~1 year minimum data


# ─────────────────────────────────────────────────────────────────────
# TRANSACTION COSTS  (Indian equity delivery trades, 2024-2026)
# ─────────────────────────────────────────────────────────────────────
@dataclass
class CostConfig:
    """All-in transaction cost parameters for Indian equity delivery."""
    # Statutory charges
    stt_rate: float = 0.001              # 0.1% on both buy and sell
    stamp_duty_buy: float = 0.00015      # 0.015% on buy side only
    exchange_charges: float = 0.0000345  # ~0.00345% NSE both sides
    sebi_fee: float = 0.000001           # 0.0001% both sides
    gst_rate: float = 0.18               # 18% on (brokerage + exchange charges)

    # Broker charges
    brokerage_per_order: float = 20.0    # ₹20 flat per executed order
    dp_charges_per_scrip: float = 15.93  # ₹15.93 per scrip on sell (CDSL)

    # Slippage estimates by liquidity tier (per side)
    slippage_tier1: float = 0.0005       # ADTV > ₹5Cr: 0.05%
    slippage_tier2: float = 0.001        # ADTV ₹1-5Cr: 0.10%
    slippage_tier3: float = 0.002        # ADTV ₹50L-1Cr: 0.20%

    # Impact cost exponent
    impact_cost_base: float = 0.001      # 0.1% base
    impact_cost_threshold: float = 0.01  # trigger when position > 1% of daily vol


# ─────────────────────────────────────────────────────────────────────
# PORTFOLIO & CAPITAL
# ─────────────────────────────────────────────────────────────────────
@dataclass
class PortfolioConfig:
    """Portfolio construction parameters."""
    initial_capital: float = 500_000.0        # ₹5 lakh
    risk_free_rate: float = 0.065             # 6.5% (Indian 10Y govt bond yield)

    # Position constraints
    max_stocks: int = 5                       # default; backtest grid: [5, 10]
    max_single_stock_weight: float = 0.20     # 20% cap (higher for small portfolios)
    max_sector_weight: float = 0.30           # 30% sector cap
    min_stock_weight: float = 0.02            # 2% min (below this, not worth the cost)

    # Weighting method: "equal", "inverse_volatility", "risk_parity"
    weighting_method: str = "inverse_volatility"

    # Backtest grid
    portfolio_sizes_to_test: List[int] = field(
        default_factory=lambda: [5, 10]
    )
    rebalance_frequencies_to_test: List[str] = field(
        default_factory=lambda: ["monthly", "quarterly"]
    )


# ─────────────────────────────────────────────────────────────────────
# UNIVERSE FILTERS
# ─────────────────────────────────────────────────────────────────────
@dataclass
class UniverseConfig:
    """Filters for constructing the tradeable universe."""
    # Liquidity
    min_avg_daily_turnover: float = 50_00_000    # ₹50 lakh (₹5M)
    min_trading_days_pct: float = 0.90            # 90% of trading days in lookback
    trading_days_lookback: int = 60               # days
    turnover_lookback: int = 20                   # days for ADTV calculation

    # Price
    min_price: float = 10.0                       # exclude penny stocks
    max_price: float = 50_000.0                   # practical upper limit

    # Anti-manipulation
    max_circuit_hit_pct: float = 0.05             # max 5% of days hitting circuits
    circuit_lookback: int = 20                    # days
    max_spread_pct: float = 0.10                  # (H-L)/C < 10%
    spread_lookback: int = 20
    max_volume_cv: float = 3.0                    # StdDev(Vol)/Mean(Vol) < 3.0
    volume_cv_lookback: int = 60

    # Market cap proxy
    min_market_cap_proxy: float = 100_00_00_000   # ₹100 Cr (₹1B)


# ─────────────────────────────────────────────────────────────────────
# STRATEGY PARAMETERS
# ─────────────────────────────────────────────────────────────────────
@dataclass
class MomentumConfig:
    """Cross-sectional momentum parameters."""
    lookback_long: int = 252       # 12-month return window
    skip_recent: int = 21          # skip most recent 1 month
    lookback_medium: int = 126     # 6-month
    lookback_short: int = 63       # 3-month
    vol_lookback: int = 63         # for risk-adjusted momentum
    # Blending weights for multi-horizon
    weight_12m: float = 0.50
    weight_6m: float = 0.30
    weight_3m: float = 0.20


@dataclass
class TrendConfig:
    """Trend following parameters."""
    ema_short: int = 50
    ema_long: int = 100
    ema_slope_window: int = 10
    adx_period: int = 14
    adx_threshold: float = 20.0
    # Signal weights
    weight_price_above_ema: float = 0.40
    weight_ema_slope: float = 0.30
    weight_adx: float = 0.30


@dataclass
class BreakoutConfig:
    """Volatility breakout parameters."""
    donchian_period: int = 55          # N-day high breakout
    volume_sma_period: int = 20
    volume_surge_multiplier: float = 1.5
    atr_period: int = 20
    consolidation_threshold: float = 0.03  # ATR/Close < 3%


@dataclass
class MeanReversionConfig:
    """Mean reversion parameters."""
    trend_sma_period: int = 200
    trend_slope_window: int = 20
    short_sma_period: int = 20
    rsi_period: int = 5
    rsi_oversold: float = 30.0
    atr_period: int = 20
    atr_distance_multiplier: float = 2.0
    max_hold_days: int = 10            # short holding period


# ─────────────────────────────────────────────────────────────────────
# REGIME DETECTION
# ─────────────────────────────────────────────────────────────────────
@dataclass
class RegimeConfig:
    """Market regime detection parameters."""
    market_proxy_symbol: str = "^NSEI"   # Nifty 50
    sma_fast: int = 50
    sma_slow: int = 200
    adx_period: int = 14
    adx_trending_threshold: float = 20.0

    # Regime-dependent strategy weights: {regime: {strategy: weight}}
    regime_weights: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "BULL": {
            "momentum": 0.45, "trend": 0.35, "breakout": 0.20,
            "mean_reversion": 0.00,
        },
        "NEUTRAL": {
            "momentum": 0.20, "trend": 0.40, "breakout": 0.10,
            "mean_reversion": 0.30,
        },
        "BEAR": {
            "momentum": 0.00, "trend": 0.00, "breakout": 0.00,
            "mean_reversion": 0.00,
        },
    })

    # Capital allocation by regime (rest goes to cash)
    regime_capital_allocation: Dict[str, float] = field(default_factory=lambda: {
        "BULL": 1.00,
        "NEUTRAL": 0.80,
        "BEAR": 0.00,
    })

    # Breadth thresholds
    breadth_bullish: float = 0.60    # >60% stocks above 200 SMA
    breadth_bearish: float = 0.30    # <30%


# ─────────────────────────────────────────────────────────────────────
# RISK MANAGEMENT
# ─────────────────────────────────────────────────────────────────────
@dataclass
class RiskConfig:
    """Risk management parameters."""
    # Individual stock
    trailing_stop_atr_multiplier: float = 4.0
    atr_period: int = 20
    max_hold_days_momentum: int = 120
    max_hold_days_mean_reversion: int = 10
    profit_target_atr_multiplier: float = 3.0   # for mean reversion

    # Portfolio level
    max_drawdown_reduce: float = -0.25    # -25% → reduce 50%
    max_drawdown_liquidate: float = -0.40 # -40% → liquidate all
    max_daily_loss: float = -0.06         # -6% → halt 3 days
    halt_days: int = 3

    # Sector concentration
    max_stocks_per_sector: int = 3


# ─────────────────────────────────────────────────────────────────────
# BACKTEST
# ─────────────────────────────────────────────────────────────────────
@dataclass
class BacktestConfig:
    """Backtesting engine parameters."""
    start_date: str = "2011-06-01"     # after warmup period
    end_date: str = "2026-05-30"
    execution_delay_days: int = 1       # signal on T, execute on T+1
    execute_at: str = "open"            # execute at next day's open

    # Walk-forward
    train_window_years: int = 3
    test_window_years: int = 1
    walk_forward_step_months: int = 6

    # Anti-overfit
    parameter_variation_pct: float = 0.20   # ±20%
    min_backtest_years: int = 5


# ─────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────
import logging

LOG_LEVEL = logging.WARNING
LOG_FORMAT = "%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(name: str = "quant") -> logging.Logger:
    """Configure and return a logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(LOG_LEVEL)

        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(LOG_LEVEL)
        ch.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
        logger.addHandler(ch)

        # File handler
        fh = logging.FileHandler(LOG_DIR / f"{name}.log")
        fh.setLevel(LOG_LEVEL)
        fh.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
        logger.addHandler(fh)

    return logger


# ─────────────────────────────────────────────────────────────────────
# MASTER CONFIG — single object to pass around
# ─────────────────────────────────────────────────────────────────────
@dataclass
class SystemConfig:
    """Top-level config aggregating all sub-configs."""
    download: DownloadConfig = field(default_factory=DownloadConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    momentum: MomentumConfig = field(default_factory=MomentumConfig)
    trend: TrendConfig = field(default_factory=TrendConfig)
    breakout: BreakoutConfig = field(default_factory=BreakoutConfig)
    mean_reversion: MeanReversionConfig = field(default_factory=MeanReversionConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)


# Default global config instance
DEFAULT_CONFIG = SystemConfig()
