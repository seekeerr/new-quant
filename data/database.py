"""
SQLite database manager for storing and retrieving market data.
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Optional, Dict
from contextlib import contextmanager

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DB_PATH, setup_logging

logger = setup_logging("database")


# ─────────────────────────────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS daily_prices (
    date        TEXT    NOT NULL,
    symbol      TEXT    NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      INTEGER,
    PRIMARY KEY (date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_prices_symbol ON daily_prices(symbol);
CREATE INDEX IF NOT EXISTS idx_prices_date ON daily_prices(date);

CREATE TABLE IF NOT EXISTS stock_info (
    symbol      TEXT    PRIMARY KEY,
    name        TEXT,
    sector      TEXT,
    industry    TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS benchmark (
    date        TEXT    NOT NULL,
    index_name  TEXT    NOT NULL,
    tri_value   REAL,
    daily_return REAL,
    PRIMARY KEY (date, index_name)
);
"""


# ─────────────────────────────────────────────────────────────────────
# DATABASE MANAGER
# ─────────────────────────────────────────────────────────────────────

class DatabaseManager:
    """SQLite database manager for market data storage and retrieval."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
        logger.info(f"Database initialized at {self.db_path}")

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── INSERT / UPSERT ──────────────────────────────────────────────

    def insert_stock_data(
        self,
        symbol: str,
        df: pd.DataFrame,
    ):
        """
        Insert or replace daily price data for a single stock.

        Parameters
        ----------
        symbol : str
            Stock symbol.
        df : DataFrame
            Must have DatetimeIndex and columns: Open, High, Low, Close, Volume.
        """
        if df.empty:
            return

        records = []
        for date_val, row in df.iterrows():
            date_str = pd.Timestamp(date_val).strftime("%Y-%m-%d")
            records.append((
                date_str,
                symbol,
                float(row.get("Open", np.nan)),
                float(row.get("High", np.nan)),
                float(row.get("Low", np.nan)),
                float(row.get("Close", np.nan)),
                int(row.get("Volume", 0)) if pd.notna(row.get("Volume", np.nan)) else 0,
            ))

        with self._connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO daily_prices
                   (date, symbol, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                records,
            )

        logger.debug(f"Inserted {len(records)} rows for {symbol}")

    def bulk_insert_stocks(self, stock_data: Dict[str, pd.DataFrame]):
        """Insert data for multiple stocks."""
        total = 0
        for sym, df in stock_data.items():
            self.insert_stock_data(sym, df)
            total += len(df)
        logger.info(f"Bulk inserted {total} rows for {len(stock_data)} stocks")

    def insert_benchmark_data(self, df: pd.DataFrame):
        """
        Insert benchmark TRI data.

        Parameters
        ----------
        df : DataFrame from benchmark.load_tri_csv() with columns:
             tri_value, daily_return, index_name
        """
        if df.empty:
            return

        records = []
        for date_val, row in df.iterrows():
            date_str = pd.Timestamp(date_val).strftime("%Y-%m-%d")
            records.append((
                date_str,
                row.get("index_name", "NIFTY 500"),
                float(row.get("tri_value", np.nan)),
                float(row.get("daily_return", np.nan)),
            ))

        with self._connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO benchmark
                   (date, index_name, tri_value, daily_return)
                   VALUES (?, ?, ?, ?)""",
                records,
            )

        logger.info(f"Inserted {len(records)} benchmark rows")

    # ── QUERY ────────────────────────────────────────────────────────

    def get_stock_data(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Retrieve daily OHLCV data for a single stock.

        Returns DataFrame with DatetimeIndex.
        """
        query = "SELECT date, open, high, low, close, volume FROM daily_prices WHERE symbol = ?"
        params = [symbol]

        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY date"

        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if df.empty:
            return df

        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        df.columns = ["Open", "High", "Low", "Close", "Volume"]
        return df

    def get_all_symbols(self) -> List[str]:
        """Get list of all symbols in the database."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT DISTINCT symbol FROM daily_prices ORDER BY symbol"
            )
            return [row[0] for row in cursor.fetchall()]

    def get_price_panel(
        self,
        symbols: Optional[List[str]] = None,
        field: str = "close",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get a wide-format DataFrame: dates × symbols for a given field.

        Parameters
        ----------
        symbols : list of str, optional
            If None, retrieves all symbols.
        field : str
            One of 'open', 'high', 'low', 'close', 'volume'.
        """
        query = f"SELECT date, symbol, {field} FROM daily_prices"
        conditions = []
        params = []

        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            conditions.append(f"symbol IN ({placeholders})")
            params.extend(symbols)
        if start_date:
            conditions.append("date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY date"

        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if df.empty:
            return pd.DataFrame()

        # Pivot to wide format
        df["date"] = pd.to_datetime(df["date"])
        panel = df.pivot(index="date", columns="symbol", values=field)
        return panel

    def get_volume_panel(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Convenience: get volume panel."""
        return self.get_price_panel(symbols, "volume", start_date, end_date)

    def get_benchmark_returns(
        self,
        index_name: str = "NIFTY 500",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.Series:
        """Get benchmark daily returns."""
        query = "SELECT date, daily_return FROM benchmark WHERE index_name = ?"
        params = [index_name]

        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY date"

        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if df.empty:
            return pd.Series(dtype=float)

        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        return df["daily_return"]

    def get_date_range(self) -> tuple:
        """Get min and max dates in the database."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT MIN(date), MAX(date) FROM daily_prices"
            )
            row = cursor.fetchone()
            return row[0], row[1]

    def get_stock_count(self) -> int:
        """Get number of unique stocks."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT COUNT(DISTINCT symbol) FROM daily_prices"
            )
            return cursor.fetchone()[0]

    def get_row_count(self) -> int:
        """Get total number of price rows."""
        with self._connect() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM daily_prices")
            return cursor.fetchone()[0]

    def summary(self) -> dict:
        """Get a summary of database contents."""
        date_range = self.get_date_range()
        return {
            "db_path": str(self.db_path),
            "total_rows": self.get_row_count(),
            "total_stocks": self.get_stock_count(),
            "date_range": f"{date_range[0]} to {date_range[1]}",
        }


if __name__ == "__main__":
    db = DatabaseManager()
    print("Database summary:", db.summary())
