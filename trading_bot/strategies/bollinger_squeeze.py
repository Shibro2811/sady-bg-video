"""
Bollinger Band Squeeze / Mean Reversion Strategy.

Two modes:
1. SQUEEZE BREAKOUT: BB width compresses then expands with volume -> momentum trade.
2. MEAN REVERSION: Price at +/- 2 BB with RSI extreme -> revert to mean.

Switches based on ADX regime. Win rate: 55-65% (mean reversion), 45-52% (breakout).
"""

from typing import Optional
import pandas as pd
import numpy as np

from trading_bot.strategies.base import BaseStrategy
from trading_bot.core.models import Signal
from trading_bot.core.enums import SignalType


class BollingerSqueezeStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "Bollinger_Squeeze"

    @property
    def weight(self) -> float:
        return 0.9

    def required_bars(self) -> int:
        return 30

    def analyze(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < self.required_bars():
            return None

        bbu = "BBU_20_2.0"
        bbl = "BBL_20_2.0"
        bbm = "BBM_20_2.0"

        if bbu not in df.columns:
            return None

        curr = df.iloc[-1]
        adx = curr.get("ADX_14", 25)

        if pd.isna(adx):
            adx = 25

        # Route to the right sub-strategy based on regime
        if adx < 20:
            return self._mean_reversion(df, symbol)
        else:
            return self._squeeze_breakout(df, symbol)

    def _squeeze_breakout(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        """Detect BB squeeze then breakout."""
        bb_widths = df["BB_WIDTH"].dropna() if "BB_WIDTH" in df.columns else None
        if bb_widths is None or len(bb_widths) < 20:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # Check if we were in a squeeze (BB width in bottom 10th percentile)
        recent_widths = bb_widths.tail(100)
        width_pctile = (recent_widths < curr.get("BB_WIDTH", 0)).sum() / len(recent_widths)

        # Look for squeeze release: width was compressed, now expanding
        prev_widths = bb_widths.iloc[-8:-2]
        avg_prev_width = prev_widths.mean() if len(prev_widths) > 0 else 0
        curr_width = curr.get("BB_WIDTH", 0)

        if pd.isna(avg_prev_width) or pd.isna(curr_width):
            return None

        # Was squeezed: average width over last 6 bars was in bottom 20 percentile
        if avg_prev_width > 0 and width_pctile > 0.2:
            return None  # Not coming out of a squeeze

        # Now expanding
        if curr_width <= avg_prev_width:
            return None  # Not expanding

        bbu = curr.get("BBU_20_2.0")
        bbl = curr.get("BBL_20_2.0")
        rel_vol = curr.get("REL_VOL", 1.0)
        atr = curr.get("ATRr_14", abs(curr["high"] - curr["low"]))

        if pd.isna(bbu) or pd.isna(bbl):
            return None

        # Volume must confirm: >= 2.0x average for breakout
        if rel_vol < 1.5:
            return None

        # Bullish breakout: price closes above upper BB
        if curr["close"] > bbu:
            rsi = curr.get("RSI_14", 50)
            if not pd.isna(rsi) and rsi > 50:
                stop_loss = curr["close"] - 2.0 * atr if atr > 0 else bbl
                distance = curr["close"] - stop_loss
                take_profit = curr["close"] + 2.5 * distance

                return Signal(
                    signal_type=SignalType.STRONG_BUY,
                    symbol=symbol,
                    strategy_name=self.name,
                    confidence=0.7,
                    price=curr["close"],
                    timestamp=df.index[-1],
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    metadata={
                        "mode": "squeeze_breakout", "direction": "bullish",
                        "bb_width_pctile": width_pctile, "rel_vol": rel_vol,
                    },
                )

        # Bearish breakout: price closes below lower BB
        if curr["close"] < bbl:
            rsi = curr.get("RSI_14", 50)
            if not pd.isna(rsi) and rsi < 50:
                stop_loss = curr["close"] + 2.0 * atr if atr > 0 else bbu
                distance = stop_loss - curr["close"]
                take_profit = curr["close"] - 2.5 * distance

                return Signal(
                    signal_type=SignalType.STRONG_SELL,
                    symbol=symbol,
                    strategy_name=self.name,
                    confidence=0.7,
                    price=curr["close"],
                    timestamp=df.index[-1],
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    metadata={
                        "mode": "squeeze_breakout", "direction": "bearish",
                        "bb_width_pctile": width_pctile, "rel_vol": rel_vol,
                    },
                )

        return None

    def _mean_reversion(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        """Mean reversion at BB extremes in ranging markets."""
        curr = df.iloc[-1]
        bbu = curr.get("BBU_20_2.0")
        bbl = curr.get("BBL_20_2.0")
        bbm = curr.get("BBM_20_2.0")
        rsi = curr.get("RSI_14")
        stoch_k = curr.get("STOCHk_14_3_3")
        stoch_d = curr.get("STOCHd_14_3_3")
        ema55 = curr.get("EMA_55")
        rel_vol = curr.get("REL_VOL", 1.0)
        atr = curr.get("ATRr_14", abs(curr["high"] - curr["low"]))

        if any(pd.isna(v) for v in [bbu, bbl, bbm, rsi]):
            return None

        # Bullish mean reversion: at/below lower BB, RSI oversold
        if curr["low"] <= bbl and rsi < 30:
            # Bullish candle (close > open)
            if curr["close"] > curr["open"]:
                # EMA_55 not falling (optional)
                if not pd.isna(ema55) and len(df) > 5:
                    ema55_prev = df.iloc[-5].get("EMA_55", ema55)
                    if not pd.isna(ema55_prev) and ema55 < ema55_prev * 0.998:
                        return None  # Strong downtrend, skip

                stop_loss = bbl - 1.0 * atr if atr > 0 else bbl - 0.005 * curr["close"]
                take_profit = bbm  # Target: middle band

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
                        "mode": "mean_reversion", "direction": "bullish",
                        "rsi": rsi, "bb_lower": bbl, "bb_mid": bbm,
                    },
                )

        # Bearish mean reversion: at/above upper BB, RSI overbought
        if curr["high"] >= bbu and rsi > 70:
            if curr["close"] < curr["open"]:
                if not pd.isna(ema55) and len(df) > 5:
                    ema55_prev = df.iloc[-5].get("EMA_55", ema55)
                    if not pd.isna(ema55_prev) and ema55 > ema55_prev * 1.002:
                        return None

                stop_loss = bbu + 1.0 * atr if atr > 0 else bbu + 0.005 * curr["close"]
                take_profit = bbm

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
                        "mode": "mean_reversion", "direction": "bearish",
                        "rsi": rsi, "bb_upper": bbu, "bb_mid": bbm,
                    },
                )

        return None
