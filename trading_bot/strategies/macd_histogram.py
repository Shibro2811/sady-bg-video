"""
MACD Histogram Reversal Strategy.

BUY: MACD histogram crosses from negative to positive with accelerating momentum.
SELL: MACD histogram crosses from positive to negative.

Confirms momentum shifts. Weight: 1.0. Win rate: ~50% with 1.8:1 R:R.
"""

from typing import Optional
import pandas as pd

from trading_bot.strategies.base import BaseStrategy
from trading_bot.core.models import Signal
from trading_bot.core.enums import SignalType


class MACDHistogramStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "MACD_Histogram"

    @property
    def weight(self) -> float:
        return 1.0

    def required_bars(self) -> int:
        return 35

    def analyze(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < self.required_bars():
            return None

        hist_col = "MACDh_12_26_9"
        macd_col = "MACD_12_26_9"
        signal_col = "MACDs_12_26_9"

        if hist_col not in df.columns:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]

        hist = curr.get(hist_col)
        prev_hist = prev.get(hist_col)
        prev2_hist = prev2.get(hist_col)
        macd_line = curr.get(macd_col)
        macd_signal = curr.get(signal_col)

        if any(pd.isna(v) for v in [hist, prev_hist, prev2_hist, macd_line, macd_signal]):
            return None

        rel_vol = curr.get("REL_VOL", 1.0)
        rsi = curr.get("RSI_14", 50)
        atr = curr.get("ATRr_14", abs(curr["high"] - curr["low"]))

        # Bullish: histogram crosses zero from below AND accelerating
        if prev_hist <= 0 and hist > 0 and hist > prev_hist:
            # MACD line crossing signal line
            prev_macd = prev.get(macd_col, 0)
            prev_signal = prev.get(signal_col, 0)
            if not pd.isna(prev_macd) and not pd.isna(prev_signal):
                if prev_macd <= prev_signal and macd_line > macd_signal:
                    # RSI confirmation: between 40-65 (room to run)
                    if not pd.isna(rsi) and 40 <= rsi <= 65:
                        # Volume confirmation
                        if rel_vol >= 1.0:
                            stop_loss = curr["close"] - 1.5 * atr if atr > 0 else curr["low"]
                            distance = curr["close"] - stop_loss
                            take_profit = curr["close"] + 2.0 * distance

                            return Signal(
                                signal_type=SignalType.BUY,
                                symbol=symbol,
                                strategy_name=self.name,
                                confidence=0.55 + min(abs(hist) / (atr + 1e-10) * 0.1, 0.3),
                                price=curr["close"],
                                timestamp=df.index[-1],
                                stop_loss=stop_loss,
                                take_profit=take_profit,
                                metadata={
                                    "macd_hist": hist, "macd_line": macd_line,
                                    "macd_signal": macd_signal, "rsi": rsi,
                                    "trigger": "bullish_histogram_cross",
                                },
                            )

        # Bearish: histogram crosses zero from above AND decelerating
        if prev_hist >= 0 and hist < 0 and hist < prev_hist:
            prev_macd = prev.get(macd_col, 0)
            prev_signal = prev.get(signal_col, 0)
            if not pd.isna(prev_macd) and not pd.isna(prev_signal):
                if prev_macd >= prev_signal and macd_line < macd_signal:
                    if not pd.isna(rsi) and 35 <= rsi <= 60:
                        if rel_vol >= 1.0:
                            stop_loss = curr["close"] + 1.5 * atr if atr > 0 else curr["high"]
                            distance = stop_loss - curr["close"]
                            take_profit = curr["close"] - 2.0 * distance

                            return Signal(
                                signal_type=SignalType.SELL,
                                symbol=symbol,
                                strategy_name=self.name,
                                confidence=0.55 + min(abs(hist) / (atr + 1e-10) * 0.1, 0.3),
                                price=curr["close"],
                                timestamp=df.index[-1],
                                stop_loss=stop_loss,
                                take_profit=take_profit,
                                metadata={
                                    "macd_hist": hist, "macd_line": macd_line,
                                    "macd_signal": macd_signal, "rsi": rsi,
                                    "trigger": "bearish_histogram_cross",
                                },
                            )

        return None
