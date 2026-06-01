"""
Vectorized technical indicators using NumPy/Pandas.

All functions are pure — they take pandas Series/DataFrames as input
and return pandas Series/DataFrames. No side effects.
"""

import pandas as pd
import numpy as np
from typing import Optional


# ─────────────────────────────────────────────────────────────────────
# MOVING AVERAGES
# ─────────────────────────────────────────────────────────────────────

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def wma(series: pd.Series, period: int) -> pd.Series:
    """Weighted Moving Average (linearly weighted)."""
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(window=period, min_periods=period).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )


# ─────────────────────────────────────────────────────────────────────
# TREND / SLOPE
# ─────────────────────────────────────────────────────────────────────

def slope(series: pd.Series, period: int) -> pd.Series:
    """
    Linear regression slope over a rolling window.
    Positive = rising, negative = falling.
    Normalised by the mean of the window for comparability.
    """
    def _slope(arr):
        if np.any(np.isnan(arr)):
            return np.nan
        x = np.arange(len(arr))
        m = np.polyfit(x, arr, 1)[0]
        # Normalise by mean to get "% per bar"
        mean_val = np.mean(arr)
        return m / mean_val if mean_val != 0 else 0.0

    return series.rolling(window=period, min_periods=period).apply(
        _slope, raw=True
    )


def rate_of_change(series: pd.Series, period: int) -> pd.Series:
    """Rate of Change: (current - N periods ago) / N periods ago."""
    return series.pct_change(periods=period)


# ─────────────────────────────────────────────────────────────────────
# VOLATILITY
# ─────────────────────────────────────────────────────────────────────

def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """
    Average True Range.
    TR = max(H-L, |H-Cprev|, |L-Cprev|)
    ATR = EMA(TR, period)
    """
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(span=period, adjust=False, min_periods=period).mean()


def atr_percent(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """ATR as a percentage of close price."""
    return atr(high, low, close, period) / close


def rolling_volatility(
    returns: pd.Series,
    window: int = 63,
    annualise: bool = True,
) -> pd.Series:
    """
    Rolling annualised volatility from daily returns.
    Annualisation factor: sqrt(252).
    """
    vol = returns.rolling(window=window, min_periods=max(20, window // 2)).std()
    if annualise:
        vol *= np.sqrt(252)
    return vol


def bollinger_bands(
    series: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    """
    Bollinger Bands.

    Returns DataFrame with columns: ['middle', 'upper', 'lower', 'bandwidth', 'pct_b']
    """
    middle = sma(series, period)
    std = series.rolling(window=period, min_periods=period).std()
    upper = middle + num_std * std
    lower = middle - num_std * std
    bandwidth = (upper - lower) / middle
    pct_b = (series - lower) / (upper - lower)

    return pd.DataFrame({
        "middle": middle,
        "upper": upper,
        "lower": lower,
        "bandwidth": bandwidth,
        "pct_b": pct_b,
    }, index=series.index)


# ─────────────────────────────────────────────────────────────────────
# MOMENTUM / OSCILLATORS
# ─────────────────────────────────────────────────────────────────────

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index (Wilder's smoothing).
    Returns values in [0, 100].
    """
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.DataFrame:
    """
    Average Directional Index.

    Returns DataFrame with columns: ['ADX', 'DI_plus', 'DI_minus']
    """
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    # True Range
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional movement
    plus_dm = high - prev_high
    minus_dm = prev_low - low

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    # Smoothed (Wilder's smoothing = EMA with alpha=1/period)
    alpha = 1.0 / period
    atr_smooth = true_range.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    # Directional indicators
    di_plus = 100.0 * plus_dm_smooth / atr_smooth
    di_minus = 100.0 * minus_dm_smooth / atr_smooth

    # DX and ADX
    di_diff = (di_plus - di_minus).abs()
    di_sum = di_plus + di_minus
    dx = 100.0 * di_diff / di_sum.replace(0, np.nan)
    adx_val = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    return pd.DataFrame({
        "ADX": adx_val,
        "DI_plus": di_plus,
        "DI_minus": di_minus,
    }, index=close.index)


# ─────────────────────────────────────────────────────────────────────
# CHANNELS
# ─────────────────────────────────────────────────────────────────────

def donchian_channel(
    high: pd.Series,
    low: pd.Series,
    period: int = 20,
) -> pd.DataFrame:
    """
    Donchian Channel.

    Returns DataFrame with columns: ['upper', 'lower', 'middle']
    """
    upper = high.rolling(window=period, min_periods=period).max()
    lower = low.rolling(window=period, min_periods=period).min()
    middle = (upper + lower) / 2.0

    return pd.DataFrame({
        "upper": upper,
        "lower": lower,
        "middle": middle,
    }, index=high.index)


def highest_high(high: pd.Series, period: int) -> pd.Series:
    """Rolling highest high over N periods."""
    return high.rolling(window=period, min_periods=period).max()


def lowest_low(low: pd.Series, period: int) -> pd.Series:
    """Rolling lowest low over N periods."""
    return low.rolling(window=period, min_periods=period).min()


# ─────────────────────────────────────────────────────────────────────
# RETURNS
# ─────────────────────────────────────────────────────────────────────

def log_returns(series: pd.Series) -> pd.Series:
    """Logarithmic daily returns."""
    return np.log(series / series.shift(1))


def simple_returns(series: pd.Series) -> pd.Series:
    """Simple daily returns (pct change)."""
    return series.pct_change()


def cumulative_returns(returns: pd.Series) -> pd.Series:
    """Cumulative returns from a series of simple returns."""
    return (1 + returns).cumprod() - 1


def rolling_returns(series: pd.Series, period: int) -> pd.Series:
    """Rolling N-day simple return."""
    return series / series.shift(period) - 1


# ─────────────────────────────────────────────────────────────────────
# VOLUME
# ─────────────────────────────────────────────────────────────────────

def volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    """Simple moving average of volume."""
    return sma(volume, period)


def relative_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    """Volume relative to its N-period average (RVOL)."""
    avg = volume_sma(volume, period)
    return volume / avg.replace(0, np.nan)


def on_balance_volume(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume (OBV)."""
    direction = np.sign(close.diff())
    return (volume * direction).cumsum()


# ─────────────────────────────────────────────────────────────────────
# COMPOSITE / MULTI-INDICATOR
# ─────────────────────────────────────────────────────────────────────

def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """
    MACD (Moving Average Convergence Divergence).

    Returns DataFrame with columns: ['macd', 'signal', 'histogram']
    """
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line

    return pd.DataFrame({
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }, index=series.index)
