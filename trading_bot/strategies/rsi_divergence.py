"""
RSI Divergence Strategy.

Detects bullish/bearish divergences between price and RSI(14).
Price makes lower low + RSI makes higher low = bullish divergence (buy).
Price makes higher high + RSI makes lower high = bearish divergence (sell).

Win rate: 50-58% with proper filters. Best in ranging/reversal conditions.
"""

from typing import Optional
import pandas as pd
import numpy as np

from trading_bot.strategies.base import BaseStrategy
from trading_bot.core.models import Signal
from trading_bot.core.enums import SignalType


class RSIDivergenceStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "RSI_Divergence"

    @property
    def weight(self) -> float:
        return 1.2  # Higher weight -- divergences are high-conviction

    def required_bars(self) -> int:
        return 30

    def analyze(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < self.required_bars():
            return None

        rsi_col = "RSI_14"
        if rsi_col not in df.columns:
            return None

        # Look for swing points in the last 15 bars
        lookback = min(15, len(df) - 5)
        recent = df.iloc[-(lookback + 5):]

        # Find pivot lows (for bullish divergence)
        bull_signal = self._check_bullish_divergence(recent, rsi_col)
        if bull_signal:
            return self._build_signal(df, symbol, bull_signal, SignalType.BUY)

        # Find pivot highs (for bearish divergence)
        bear_signal = self._check_bearish_divergence(recent, rsi_col)
        if bear_signal:
            return self._build_signal(df, symbol, bear_signal, SignalType.SELL)

        return None

    def _check_bullish_divergence(self, df: pd.DataFrame, rsi_col: str) -> Optional[dict]:
        """Check for bullish divergence: price lower low, RSI higher low."""
        lows = df["low"].values
        rsi = df[rsi_col].values

        # Find two swing lows (simple: local minima within window)
        pivot_indices = []
        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and \
               lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
                pivot_indices.append(i)

        if len(pivot_indices) < 2:
            return None

        # Take the last two pivots
        p1_idx = pivot_indices[-2]
        p2_idx = pivot_indices[-1]

        # Must be 4-12 candles apart
        distance = p2_idx - p1_idx
        if distance < 4 or distance > 12:
            return None

        # Bullish divergence: price lower low, RSI higher low
        if lows[p2_idx] < lows[p1_idx] and rsi[p2_idx] > rsi[p1_idx]:
            # RSI should be in oversold zone (25-45)
            if 25 <= rsi[p2_idx] <= 45:
                # Confirmation: current candle is green and closes above 9 EMA
                curr = df.iloc[-1]
                ema9 = curr.get("EMA_9")
                if curr["close"] > curr["open"] and ema9 is not None and curr["close"] > ema9:
                    return {
                        "type": "bullish",
                        "pivot1_price": lows[p1_idx],
                        "pivot2_price": lows[p2_idx],
                        "pivot1_rsi": rsi[p1_idx],
                        "pivot2_rsi": rsi[p2_idx],
                        "rsi_current": rsi[-1],
                    }
        return None

    def _check_bearish_divergence(self, df: pd.DataFrame, rsi_col: str) -> Optional[dict]:
        """Check for bearish divergence: price higher high, RSI lower high."""
        highs = df["high"].values
        rsi = df[rsi_col].values

        pivot_indices = []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and \
               highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
                pivot_indices.append(i)

        if len(pivot_indices) < 2:
            return None

        p1_idx = pivot_indices[-2]
        p2_idx = pivot_indices[-1]

        distance = p2_idx - p1_idx
        if distance < 4 or distance > 12:
            return None

        if highs[p2_idx] > highs[p1_idx] and rsi[p2_idx] < rsi[p1_idx]:
            if 55 <= rsi[p2_idx] <= 75:
                curr = df.iloc[-1]
                ema9 = curr.get("EMA_9")
                if curr["close"] < curr["open"] and ema9 is not None and curr["close"] < ema9:
                    return {
                        "type": "bearish",
                        "pivot1_price": highs[p1_idx],
                        "pivot2_price": highs[p2_idx],
                        "pivot1_rsi": rsi[p1_idx],
                        "pivot2_rsi": rsi[p2_idx],
                        "rsi_current": rsi[-1],
                    }
        return None

    def _build_signal(self, df: pd.DataFrame, symbol: str,
                      divergence: dict, signal_type: SignalType) -> Signal:
        curr = df.iloc[-1]
        atr = curr.get("ATRr_14", curr["high"] - curr["low"])

        if signal_type == SignalType.BUY:
            stop_loss = divergence["pivot2_price"] - 0.001 * curr["close"]
            distance = curr["close"] - stop_loss
            take_profit = curr["close"] + 2.0 * distance
        else:
            stop_loss = divergence["pivot2_price"] + 0.001 * curr["close"]
            distance = stop_loss - curr["close"]
            take_profit = curr["close"] - 2.0 * distance

        confidence = 0.65 if abs(divergence["pivot2_rsi"] - divergence["pivot1_rsi"]) > 10 else 0.55

        return Signal(
            signal_type=signal_type,
            symbol=symbol,
            strategy_name=self.name,
            confidence=confidence,
            price=curr["close"],
            timestamp=df.index[-1],
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata=divergence,
        )
