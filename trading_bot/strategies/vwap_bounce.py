"""
VWAP Bounce / Reclaim Strategy.

BUY: Price dips below VWAP, then reclaims with volume > 1.2x average.
SELL: Price pops above VWAP, then fails back below with volume.

VWAP is the institutional equilibrium price. Win rate: 55-62%.
"""

from typing import Optional
import pandas as pd

from trading_bot.strategies.base import BaseStrategy
from trading_bot.core.models import Signal
from trading_bot.core.enums import SignalType


class VWAPBounceStrategy(BaseStrategy):

    @property
    def name(self) -> str:
        return "VWAP_Bounce"

    @property
    def weight(self) -> float:
        return 0.8

    def required_bars(self) -> int:
        return 20

    def analyze(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < self.required_bars():
            return None

        vwap_col = "VWAP_D"
        if vwap_col not in df.columns:
            return None

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        vwap = curr.get(vwap_col)
        prev_vwap = prev.get(vwap_col)
        rel_vol = curr.get("REL_VOL", 1.0)

        if pd.isna(vwap) or pd.isna(prev_vwap):
            return None

        # VWAP must be sloping (compare to 4 candles ago)
        if len(df) >= 5:
            vwap_4_ago = df.iloc[-5].get(vwap_col)
        else:
            vwap_4_ago = vwap

        # Bullish VWAP reclaim: was below, now closes above
        if prev["close"] < prev_vwap and curr["close"] > vwap:
            # Volume confirmation
            if rel_vol >= 1.2:
                # VWAP sloping up
                if not pd.isna(vwap_4_ago) and vwap > vwap_4_ago:
                    # RSI not overbought
                    rsi = curr.get("RSI_14", 50)
                    if pd.isna(rsi) or not (40 <= rsi <= 60):
                        return None

                    atr = curr.get("ATRr_14", abs(curr["high"] - curr["low"]))
                    stop_loss = min(curr["low"], vwap - 0.0015 * curr["close"])
                    distance = curr["close"] - stop_loss
                    take_profit = curr["close"] + 1.5 * distance

                    return Signal(
                        signal_type=SignalType.BUY,
                        symbol=symbol,
                        strategy_name=self.name,
                        confidence=0.6 + min(rel_vol - 1.2, 0.3) / 3,
                        price=curr["close"],
                        timestamp=df.index[-1],
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        metadata={
                            "vwap": vwap, "rel_vol": rel_vol,
                            "rsi": rsi, "trigger": "vwap_reclaim",
                        },
                    )

        # Bearish VWAP rejection: was above, now closes below
        if prev["close"] > prev_vwap and curr["close"] < vwap:
            if rel_vol >= 1.2:
                if not pd.isna(vwap_4_ago) and vwap < vwap_4_ago:
                    rsi = curr.get("RSI_14", 50)
                    if pd.isna(rsi) or not (40 <= rsi <= 60):
                        return None

                    stop_loss = max(curr["high"], vwap + 0.0015 * curr["close"])
                    distance = stop_loss - curr["close"]
                    take_profit = curr["close"] - 1.5 * distance

                    return Signal(
                        signal_type=SignalType.SELL,
                        symbol=symbol,
                        strategy_name=self.name,
                        confidence=0.6 + min(rel_vol - 1.2, 0.3) / 3,
                        price=curr["close"],
                        timestamp=df.index[-1],
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        metadata={
                            "vwap": vwap, "rel_vol": rel_vol,
                            "rsi": rsi, "trigger": "vwap_rejection",
                        },
                    )

        return None
