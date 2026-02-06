"""yfinance data client -- free, no API key required."""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger("trading_bot")


class YFinanceClient:
    """Data client using yfinance (free Yahoo Finance data)."""

    def __init__(self):
        try:
            import yfinance as yf
            self._yf = yf
        except ImportError:
            raise ImportError("yfinance is required. Install: pip install yfinance")

    def get_bars(self, symbol: str, interval: str = "15m",
                 period: str = "5d") -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV bars for a symbol.

        Args:
            symbol: Stock ticker (e.g., "AAPL")
            interval: Candle interval ("15m" for 15-minute)
            period: How far back to look ("5d" = 5 days)

        Returns:
            DataFrame with columns: open, high, low, close, volume
        """
        try:
            ticker = self._yf.Ticker(symbol)
            df = ticker.history(interval=interval, period=period)

            if df.empty:
                logger.warning(f"No data returned for {symbol}")
                return None

            # Normalize column names to lowercase
            df.columns = [c.lower() for c in df.columns]

            # Keep only OHLCV columns
            required = ["open", "high", "low", "close", "volume"]
            available = [c for c in required if c in df.columns]
            df = df[available]

            # Drop rows with NaN
            df = df.dropna()

            if len(df) < 10:
                logger.warning(f"Insufficient data for {symbol}: {len(df)} bars")
                return None

            return df

        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            return None

    def get_bars_batch(self, symbols: list, interval: str = "15m",
                       period: str = "5d") -> dict:
        """Fetch bars for multiple symbols."""
        results = {}
        for symbol in symbols:
            df = self.get_bars(symbol, interval, period)
            if df is not None:
                results[symbol] = df
        return results
