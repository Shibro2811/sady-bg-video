"""Yahoo Finance data client -- free, no API key required.

Uses the Yahoo Finance v8 chart API directly via aiohttp when the yfinance
package is not available (build issues with 'multitasking' on some systems).
"""

import logging
import time
from typing import Optional
from io import StringIO

import pandas as pd
import numpy as np
import aiohttp

logger = logging.getLogger("trading_bot")

# Map user-friendly intervals/periods to Yahoo API params
_INTERVAL_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "1d": "1d"}
_PERIOD_MAP = {
    "1d": "1d", "5d": "5d", "1mo": "1mo", "3mo": "3mo",
    "60d": "60d", "6mo": "6mo", "1y": "1y",
}


class YFinanceClient:
    """Data client that fetches OHLCV from Yahoo Finance (no dependencies)."""

    def __init__(self):
        # Try yfinance first; fall back to direct HTTP
        self._yf = None
        try:
            import yfinance as yf
            self._yf = yf
            logger.info("Using yfinance library for data")
        except ImportError:
            logger.info("yfinance not installed, using direct Yahoo Finance API")

    # ── public API (sync, used by scanner) ──────────────────────────

    def get_bars(
        self,
        symbol: str,
        interval: str = "15m",
        period: str = "5d",
    ) -> Optional[pd.DataFrame]:
        """Fetch OHLCV bars for *symbol*."""
        if self._yf is not None:
            return self._get_via_yfinance(symbol, interval, period)
        return self._get_via_http(symbol, interval, period)

    def get_bars_batch(self, symbols: list, interval: str = "15m",
                       period: str = "5d") -> dict:
        results = {}
        for sym in symbols:
            df = self.get_bars(sym, interval, period)
            if df is not None:
                results[sym] = df
        return results

    # ── yfinance path ───────────────────────────────────────────────

    def _get_via_yfinance(self, symbol, interval, period) -> Optional[pd.DataFrame]:
        try:
            ticker = self._yf.Ticker(symbol)
            df = ticker.history(interval=interval, period=period)
            return self._normalise(df, symbol)
        except Exception as e:
            logger.error(f"yfinance error for {symbol}: {e}")
            return None

    # ── direct HTTP path (fallback) ─────────────────────────────────

    def _get_via_http(self, symbol, interval, period) -> Optional[pd.DataFrame]:
        """Download via Yahoo Finance v8 chart endpoint (synchronous)."""
        import urllib.request, urllib.error, json

        yf_interval = _INTERVAL_MAP.get(interval, interval)
        yf_range = _PERIOD_MAP.get(period, period)

        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            f"?interval={yf_interval}&range={yf_range}"
        )

        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            logger.error(f"Yahoo HTTP error for {symbol}: {e}")
            return None

        try:
            result = data["chart"]["result"][0]
            timestamps = result["timestamp"]
            quote = result["indicators"]["quote"][0]

            df = pd.DataFrame({
                "open": quote["open"],
                "high": quote["high"],
                "low": quote["low"],
                "close": quote["close"],
                "volume": quote["volume"],
            }, index=pd.to_datetime(timestamps, unit="s", utc=True))

            df.index = df.index.tz_convert("US/Eastern")
            return self._normalise(df, symbol)
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Yahoo parse error for {symbol}: {e}")
            return None

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _normalise(df: pd.DataFrame, symbol: str) -> Optional[pd.DataFrame]:
        if df is None or df.empty:
            logger.warning(f"No data returned for {symbol}")
            return None

        df.columns = [c.lower() for c in df.columns]
        required = ["open", "high", "low", "close", "volume"]
        available = [c for c in required if c in df.columns]
        df = df[available].dropna()

        if len(df) < 10:
            logger.warning(f"Insufficient data for {symbol}: {len(df)} bars")
            return None
        return df
