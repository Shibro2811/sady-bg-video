"""Alpaca data client -- free with paper trading account, production-grade."""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger("trading_bot")


class AlpacaClient:
    """Data client using Alpaca Markets API (free tier: 200 req/min)."""

    def __init__(self, api_key: str, secret_key: str, base_url: str = ""):
        try:
            from alpaca.data import StockHistoricalDataClient
            self._client = StockHistoricalDataClient(api_key, secret_key)
        except ImportError:
            raise ImportError("alpaca-py is required. Install: pip install alpaca-py")

    def get_bars(self, symbol: str, interval: str = "15m",
                 limit: int = 200) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV bars for a symbol using Alpaca.

        Args:
            symbol: Stock ticker
            interval: "15m" for 15-minute candles
            limit: Number of bars to fetch
        """
        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

            tf_map = {
                "1m": TimeFrame(1, TimeFrameUnit.Minute),
                "5m": TimeFrame(5, TimeFrameUnit.Minute),
                "15m": TimeFrame(15, TimeFrameUnit.Minute),
                "1h": TimeFrame(1, TimeFrameUnit.Hour),
                "1d": TimeFrame(1, TimeFrameUnit.Day),
            }

            timeframe = tf_map.get(interval, TimeFrame(15, TimeFrameUnit.Minute))

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=timeframe,
                limit=limit,
            )

            bars = self._client.get_stock_bars(request)
            df = bars.df

            if df.empty:
                logger.warning(f"No Alpaca data for {symbol}")
                return None

            # If multi-index, get just this symbol
            if isinstance(df.index, pd.MultiIndex):
                if symbol in df.index.get_level_values(0):
                    df = df.loc[symbol]
                else:
                    return None

            df.columns = [c.lower() for c in df.columns]

            required = ["open", "high", "low", "close", "volume"]
            available = [c for c in required if c in df.columns]
            df = df[available].dropna()

            if len(df) < 10:
                logger.warning(f"Insufficient Alpaca data for {symbol}: {len(df)} bars")
                return None

            return df

        except Exception as e:
            logger.error(f"Alpaca error for {symbol}: {e}")
            return None
