"""
Data downloader using yfinance (V1).

Downloads adjusted OHLCV data for NIFTY 500 constituents and market
proxy (Nifty 50) from Yahoo Finance.
"""

import time
import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
from typing import List, Optional, Dict
from tqdm import tqdm

import sys, os
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    DownloadConfig,
    CACHE_DIR,
    CONSTITUENTS_CSV_PATH,
    setup_logging,
)

logger = setup_logging("downloader")


# ─────────────────────────────────────────────────────────────────────
# NIFTY 500 CONSTITUENT LIST
# ─────────────────────────────────────────────────────────────────────

def load_nifty500_symbols(csv_path: Optional[Path] = None) -> List[str]:
    """
    Load NIFTY 500 constituent symbols from CSV.

    The CSV should have a column named 'Symbol' (case-insensitive).
    If no CSV is found, falls back to a hardcoded sample list.

    Returns
    -------
    List of NSE symbols (without .NS suffix).
    """
    csv_path = csv_path or CONSTITUENTS_CSV_PATH

    if csv_path.exists():
        df = pd.read_csv(csv_path)
        # Try common column names
        for col_name in ["Symbol", "symbol", "SYMBOL", "Ticker", "ticker"]:
            if col_name in df.columns:
                symbols = df[col_name].dropna().str.strip().tolist()
                logger.info(f"Loaded {len(symbols)} symbols from {csv_path}")
                return symbols

        # If no known column, use first column
        symbols = df.iloc[:, 0].dropna().str.strip().tolist()
        logger.warning(
            f"No 'Symbol' column found, using first column. Got {len(symbols)} symbols."
        )
        return symbols

    logger.warning(
        f"Constituents CSV not found at {csv_path}. "
        f"Using sample list of 50 stocks for testing."
    )
    return _get_sample_symbols()


def _get_sample_symbols() -> List[str]:
    """Fallback: top 50 NSE stocks by market cap for testing."""
    return [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
        "LT", "HCLTECH", "AXISBANK", "ASIANPAINT", "MARUTI",
        "SUNPHARMA", "TITAN", "BAJFINANCE", "DMART", "ULTRACEMCO",
        "NESTLEIND", "WIPRO", "M&M", "POWERGRID", "NTPC",
        "ONGC", "JSWSTEEL", "TATMOTORS", "ADANIENT", "ADANIPORTS",
        "COALINDIA", "TECHM", "TATASTEEL", "INDUSINDBK", "BAJAJFINSV",
        "HINDALCO", "GRASIM", "CIPLA", "DRREDDY", "EICHERMOT",
        "DIVISLAB", "BPCL", "BRITANNIA", "HEROMOTOCO", "APOLLOHOSP",
        "TATACONSUM", "UPL", "SHREECEM", "SBILIFE", "HDFCLIFE",
    ]


# ─────────────────────────────────────────────────────────────────────
# yfinance DOWNLOADER
# ─────────────────────────────────────────────────────────────────────

def download_single_stock(
    symbol: str,
    start_date: str,
    end_date: str,
    suffix: str = ".NS",
    max_retries: int = 3,
    retry_delay: int = 5,
) -> Optional[pd.DataFrame]:
    """
    Download OHLCV data for a single stock from yfinance.

    Returns
    -------
    DataFrame with columns [Open, High, Low, Close, Volume] indexed by date,
    or None if download fails.
    """
    ticker = f"{symbol}{suffix}"

    for attempt in range(1, max_retries + 1):
        try:
            data = yf.download(
                ticker,
                start=start_date,
                end=end_date,
                auto_adjust=True,    # gives adjusted OHLCV
                progress=False,
                timeout=30,
            )

            if data is None or data.empty:
                logger.warning(f"{ticker}: No data returned (attempt {attempt})")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                continue

            # Flatten MultiIndex columns if present (yfinance sometimes returns these)
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            # Keep only needed columns
            expected_cols = ["Open", "High", "Low", "Close", "Volume"]
            available = [c for c in expected_cols if c in data.columns]
            if len(available) < 4:  # need at least OHLC
                logger.warning(f"{ticker}: Missing columns. Got: {list(data.columns)}")
                return None

            data = data[available].copy()
            data.index = pd.to_datetime(data.index)
            data.index.name = "Date"

            # Drop rows with all NaN
            data.dropna(how="all", inplace=True)

            if len(data) < 10:
                logger.warning(f"{ticker}: Only {len(data)} rows, skipping.")
                return None

            # Add symbol column
            data["Symbol"] = symbol

            logger.debug(f"{ticker}: Downloaded {len(data)} rows")
            return data

        except Exception as e:
            logger.warning(f"{ticker}: Error on attempt {attempt}: {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)

    logger.error(f"{ticker}: Failed after {max_retries} attempts")
    return None


def download_batch(
    symbols: List[str],
    start_date: str,
    end_date: str,
    suffix: str = ".NS",
) -> Dict[str, pd.DataFrame]:
    """
    Download data for multiple symbols using yfinance batch download.

    Uses yf.download with multiple tickers for efficiency.

    Returns
    -------
    Dict mapping symbol -> DataFrame.
    """
    tickers = [f"{s}{suffix}" for s in symbols]
    ticker_str = " ".join(tickers)

    try:
        data = yf.download(
            ticker_str,
            start=start_date,
            end=end_date,
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
            timeout=60,
        )
    except Exception as e:
        logger.error(f"Batch download failed: {e}")
        return {}

    result = {}
    for sym, ticker in zip(symbols, tickers):
        try:
            if len(symbols) == 1:
                stock_data = data.copy()
            else:
                if ticker in data.columns.get_level_values(0):
                    stock_data = data[ticker].copy()
                else:
                    continue

            stock_data = stock_data.dropna(how="all")
            if len(stock_data) < 10:
                continue

            stock_data["Symbol"] = sym
            result[sym] = stock_data

        except Exception as e:
            logger.debug(f"{sym}: Error extracting batch data: {e}")

    return result


def download_all_stocks(
    config: Optional[DownloadConfig] = None,
    symbols: Optional[List[str]] = None,
    use_cache: bool = True,
) -> Dict[str, pd.DataFrame]:
    """
    Download data for all stocks in the universe.

    Uses cached data if available and use_cache=True.
    Downloads missing stocks individually with progress bar.

    Returns
    -------
    Dict mapping symbol -> DataFrame with OHLCV data.
    """
    config = config or DownloadConfig()
    symbols = symbols or load_nifty500_symbols()

    all_data = {}
    symbols_to_download = []

    # Check cache
    if use_cache:
        for sym in symbols:
            cache_file = CACHE_DIR / f"{sym}.parquet"
            if cache_file.exists():
                try:
                    df = pd.read_parquet(cache_file)
                    # Check if cache is reasonably fresh (within 7 days of end_date)
                    last_date = df.index.max()
                    end = pd.Timestamp(config.end_date)
                    if (end - last_date).days <= 7:
                        all_data[sym] = df
                        continue
                except Exception:
                    pass  # corrupted cache, re-download
            symbols_to_download.append(sym)
    else:
        symbols_to_download = list(symbols)

    if not symbols_to_download:
        logger.info(f"All {len(all_data)} stocks loaded from cache.")
        return all_data

    logger.info(
        f"Downloading {len(symbols_to_download)} stocks "
        f"({len(all_data)} from cache)..."
    )

    # Download in batches
    batch_size = config.batch_size
    for i in tqdm(
        range(0, len(symbols_to_download), batch_size),
        desc="Downloading batches",
        unit="batch",
    ):
        batch_symbols = symbols_to_download[i : i + batch_size]
        batch_data = download_batch(
            batch_symbols,
            config.start_date,
            config.end_date,
            config.yfinance_suffix,
        )

        # For symbols that failed in batch, try individually
        failed = [s for s in batch_symbols if s not in batch_data]
        for sym in failed:
            df = download_single_stock(
                sym,
                config.start_date,
                config.end_date,
                config.yfinance_suffix,
                config.max_retries,
                config.retry_delay_seconds,
            )
            if df is not None:
                batch_data[sym] = df

        # Save to cache
        for sym, df in batch_data.items():
            cache_file = CACHE_DIR / f"{sym}.parquet"
            try:
                df.to_parquet(cache_file)
            except Exception as e:
                logger.warning(f"Failed to cache {sym}: {e}")

        all_data.update(batch_data)

        # Rate limiting between batches
        if i + batch_size < len(symbols_to_download):
            time.sleep(2)

    logger.info(
        f"Download complete: {len(all_data)}/{len(symbols)} stocks "
        f"({len(symbols) - len(all_data)} failed)"
    )

    return all_data


def download_market_proxy(
    symbol: str = "^NSEI",
    start_date: str = "2011-01-01",
    end_date: str = "2026-05-30",
) -> Optional[pd.DataFrame]:
    """
    Download Nifty 50 index data for regime detection.

    Returns
    -------
    DataFrame with OHLCV data for the Nifty 50.
    """
    cache_file = CACHE_DIR / "NIFTY50.parquet"

    if cache_file.exists():
        try:
            df = pd.read_parquet(cache_file)
            last_date = df.index.max()
            if (pd.Timestamp(end_date) - last_date).days <= 7:
                logger.info("Nifty 50 loaded from cache.")
                return df
        except Exception:
            pass

    logger.info(f"Downloading Nifty 50 ({symbol})...")
    df = download_single_stock(
        symbol.replace(".NS", ""),
        start_date,
        end_date,
        suffix="" if symbol.startswith("^") else ".NS",
    )

    if df is not None:
        try:
            df.to_parquet(cache_file)
        except Exception:
            pass

    return df


# ─────────────────────────────────────────────────────────────────────
# BUILD WIDE-FORMAT DATAFRAMES
# ─────────────────────────────────────────────────────────────────────

def build_price_panel(
    stock_data: Dict[str, pd.DataFrame],
    field: str = "Close",
) -> pd.DataFrame:
    """
    Build a wide-format DataFrame: dates × symbols for a given field.

    Parameters
    ----------
    stock_data : dict of {symbol: DataFrame}
    field : str, one of 'Open', 'High', 'Low', 'Close', 'Volume'

    Returns
    -------
    DataFrame with DatetimeIndex and one column per symbol.
    """
    panels = {}
    for sym, df in stock_data.items():
        if field in df.columns:
            panels[sym] = df[field]

    panel = pd.DataFrame(panels)
    panel.index = pd.to_datetime(panel.index)
    panel.sort_index(inplace=True)
    return panel


if __name__ == "__main__":
    # Quick test: download a few stocks
    config = DownloadConfig()
    test_symbols = ["RELIANCE", "TCS", "INFY"]
    data = download_all_stocks(config, symbols=test_symbols, use_cache=False)

    for sym, df in data.items():
        print(f"{sym}: {len(df)} rows, {df.index.min().date()} to {df.index.max().date()}")
