"""Enums used across the trading system."""

from enum import Enum


class SignalType(Enum):
    STRONG_BUY = 2
    BUY = 1
    NEUTRAL = 0
    SELL = -1
    STRONG_SELL = -2


class MarketRegime(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE_CHOP = "volatile_chop"
    LOW_VOL_DRIFT = "low_vol_drift"
    TRANSITIONAL = "transitional"


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"
