"""
Support/Resistance Level Strategy.

Identifies key S/R levels from swing highs/lows and trades bounces at those levels.
Combined with candle pattern confirmation (engulfing, pin bars).

Weight: 1.1. Win rate: 55-65% at fresh levels with confirmation.
"""

from typing import Optional, List, Tuple
import pandas as pd
import numpy as np

from trading_bot.strategies.base import BaseStrategy
from trading_bot.core.models import Signal
from trading_bot.core.enums import SignalType
from trading_bot.utils.indicators import find_swing_lows, find_swing_highs


class SupportResistanceStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "Support_Resistance"

    @property
    def weight(self) -> float:
        return 1.1

    def required_bars(self) -> int:
        return 50

    def analyze(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < self.required_bars():
            return None

        # Find S/R levels from swing points
        support_levels = self._find_support_levels(df)
        resistance_levels = self._find_resistance_levels(df)

        curr = df.iloc[-1]
        proximity_pct = 0.002  # 0.2% proximity to level

        # Check for bounce at support
        for level in support_levels:
            if abs(curr["low"] - level) / level < proximity_pct:
                if self._is_bullish_reversal(df):
                    return self._build_long_signal(df, symbol, curr, level)

        # Check for rejection at resistance
        for level in resistance_levels:
            if abs(curr["high"] - level) / level < proximity_pct:
                if self._is_bearish_reversal(df):
                    return self._build_short_signal(df, symbol, curr, level)

        return None

    def _find_support_levels(self, df: pd.DataFrame) -> List[float]:
        """Find support levels from recent swing lows."""
        swing_lows = find_swing_lows(df, lookback=3)
        levels = df.loc[swing_lows, "low"].tolist() if swing_lows.any() else []
        # Return unique levels (cluster similar ones)
        return self._cluster_levels(levels, df.iloc[-1]["close"])

    def _find_resistance_levels(self, df: pd.DataFrame) -> List[float]:
        """Find resistance levels from recent swing highs."""
        swing_highs = find_swing_highs(df, lookback=3)
        levels = df.loc[swing_highs, "high"].tolist() if swing_highs.any() else []
        return self._cluster_levels(levels, df.iloc[-1]["close"])

    def _cluster_levels(self, levels: List[float], current_price: float,
                        cluster_pct: float = 0.003) -> List[float]:
        """Cluster nearby levels and return their averages."""
        if not levels:
            return []

        levels = sorted(levels)
        clusters: List[List[float]] = [[levels[0]]]

        for lvl in levels[1:]:
            if abs(lvl - clusters[-1][-1]) / clusters[-1][-1] < cluster_pct:
                clusters[-1].append(lvl)
            else:
                clusters.append([lvl])

        # Return average of each cluster, sorted by proximity to current price
        averages = [sum(c) / len(c) for c in clusters]
        averages.sort(key=lambda x: abs(x - current_price))
        return averages[:5]  # Top 5 nearest levels

    def _is_bullish_reversal(self, df: pd.DataFrame) -> bool:
        """Check for bullish reversal candle pattern."""
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        rel_vol = curr.get("REL_VOL", 1.0)

        if pd.isna(rel_vol) or rel_vol < 1.0:
            return False

        # Bullish engulfing
        if (prev["close"] < prev["open"] and
                curr["close"] > curr["open"] and
                curr["open"] <= prev["close"] and
                curr["close"] >= prev["open"]):
            return True

        # Hammer / pin bar
        body = abs(curr["close"] - curr["open"])
        lower_wick = min(curr["open"], curr["close"]) - curr["low"]
        total_range = curr["high"] - curr["low"]

        if total_range > 0 and lower_wick >= 2.0 * body and body <= 0.33 * total_range:
            if curr["close"] > curr["open"]:  # Green hammer
                return True

        return False

    def _is_bearish_reversal(self, df: pd.DataFrame) -> bool:
        """Check for bearish reversal candle pattern."""
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        rel_vol = curr.get("REL_VOL", 1.0)

        if pd.isna(rel_vol) or rel_vol < 1.0:
            return False

        # Bearish engulfing
        if (prev["close"] > prev["open"] and
                curr["close"] < curr["open"] and
                curr["open"] >= prev["close"] and
                curr["close"] <= prev["open"]):
            return True

        # Shooting star
        body = abs(curr["close"] - curr["open"])
        upper_wick = curr["high"] - max(curr["open"], curr["close"])
        total_range = curr["high"] - curr["low"]

        if total_range > 0 and upper_wick >= 2.0 * body and body <= 0.33 * total_range:
            if curr["close"] < curr["open"]:
                return True

        return False

    def _build_long_signal(self, df: pd.DataFrame, symbol: str,
                           curr: pd.Series, support_level: float) -> Signal:
        atr = curr.get("ATRr_14", abs(curr["high"] - curr["low"]))
        stop_loss = support_level - 0.25 * atr if atr > 0 else support_level * 0.998
        distance = curr["close"] - stop_loss
        take_profit = curr["close"] + 2.0 * distance

        return Signal(
            signal_type=SignalType.BUY,
            symbol=symbol,
            strategy_name=self.name,
            confidence=0.65,
            price=curr["close"],
            timestamp=df.index[-1],
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata={
                "level": support_level, "level_type": "support",
                "trigger": "bullish_reversal_at_support",
            },
        )

    def _build_short_signal(self, df: pd.DataFrame, symbol: str,
                            curr: pd.Series, resistance_level: float) -> Signal:
        atr = curr.get("ATRr_14", abs(curr["high"] - curr["low"]))
        stop_loss = resistance_level + 0.25 * atr if atr > 0 else resistance_level * 1.002
        distance = stop_loss - curr["close"]
        take_profit = curr["close"] - 2.0 * distance

        return Signal(
            signal_type=SignalType.SELL,
            symbol=symbol,
            strategy_name=self.name,
            confidence=0.65,
            price=curr["close"],
            timestamp=df.index[-1],
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata={
                "level": resistance_level, "level_type": "resistance",
                "trigger": "bearish_reversal_at_resistance",
            },
        )
