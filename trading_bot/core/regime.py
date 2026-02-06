"""
Market Regime Detection.

Classifies market into: TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE_CHOP,
LOW_VOL_DRIFT, TRANSITIONAL.

Uses ADX, Efficiency Ratio, BB Width, and ATR expansion to determine regime.
Strategy routing table changes based on regime.
"""

import pandas as pd
import numpy as np

from trading_bot.core.enums import MarketRegime


def detect_regime(df: pd.DataFrame) -> MarketRegime:
    """
    Detect current market regime from 15-min OHLCV data with indicators.

    Args:
        df: DataFrame with computed indicators (ADX, BB_WIDTH, EMAs, etc.)

    Returns:
        MarketRegime enum value.
    """
    if len(df) < 20:
        return MarketRegime.TRANSITIONAL

    curr = df.iloc[-1]

    # Factor 1: ADX (trend strength)
    adx = curr.get("ADX_14", 25)
    if pd.isna(adx):
        adx = 25

    # Factor 2: Efficiency Ratio (directional efficiency)
    er = _efficiency_ratio(df["close"], period=10)

    # Factor 3: BB Width percentile
    bb_widths = df.get("BB_WIDTH")
    if bb_widths is not None and not bb_widths.dropna().empty:
        recent = bb_widths.dropna().tail(100)
        curr_width = curr.get("BB_WIDTH", 0)
        if pd.isna(curr_width):
            curr_width = 0
        width_pctile = (recent < curr_width).sum() / max(len(recent), 1)
    else:
        width_pctile = 0.5

    # Factor 4: ATR expansion/contraction
    atr_col = "ATRr_14"
    if atr_col in df.columns:
        atr_fast = df[atr_col].tail(5).mean()
        atr_slow = df[atr_col].tail(20).mean()
        atr_ratio = atr_fast / atr_slow if atr_slow > 0 else 1.0
        if pd.isna(atr_ratio):
            atr_ratio = 1.0
    else:
        atr_ratio = 1.0

    # Factor 5: EMA alignment for trend direction
    ema9 = curr.get("EMA_9")
    ema21 = curr.get("EMA_21")
    ema55 = curr.get("EMA_55")
    vwap = curr.get("VWAP_D")
    price = curr["close"]

    ema_bullish = (not pd.isna(ema9) and not pd.isna(ema21) and not pd.isna(ema55)
                   and ema9 > ema21 > ema55)
    ema_bearish = (not pd.isna(ema9) and not pd.isna(ema21) and not pd.isna(ema55)
                   and ema9 < ema21 < ema55)
    above_vwap = not pd.isna(vwap) and price > vwap

    # Classification
    if adx > 30 and er > 0.6 and atr_ratio > 1.0:
        if ema_bullish and above_vwap:
            return MarketRegime.TRENDING_UP
        elif ema_bearish and not above_vwap:
            return MarketRegime.TRENDING_DOWN
        else:
            return MarketRegime.TRENDING_UP if above_vwap else MarketRegime.TRENDING_DOWN

    if adx < 18 and er < 0.3 and width_pctile < 0.30:
        return MarketRegime.LOW_VOL_DRIFT

    if adx < 22 and er < 0.4:
        return MarketRegime.RANGING

    if atr_ratio > 1.3 and adx < 25:
        return MarketRegime.VOLATILE_CHOP

    return MarketRegime.TRANSITIONAL


def _efficiency_ratio(prices: pd.Series, period: int = 10) -> float:
    """
    Kaufman's Efficiency Ratio: net direction / total path length.
    1.0 = perfectly trending, 0.0 = perfectly choppy.
    """
    if len(prices) < period + 1:
        return 0.5

    net_change = abs(prices.iloc[-1] - prices.iloc[-period - 1])
    total_path = sum(abs(prices.iloc[i] - prices.iloc[i - 1])
                     for i in range(-period, 0))

    if total_path == 0:
        return 0.5

    return min(net_change / total_path, 1.0)


def get_regime_strategy_filter(regime: MarketRegime) -> dict:
    """
    Returns which strategy categories to activate for the current regime,
    and position size multiplier.
    """
    filters = {
        MarketRegime.TRENDING_UP: {
            "allowed_strategies": ["EMA_Cross_9_21", "VWAP_Bounce", "MACD_Histogram",
                                    "Volume_Spike", "Support_Resistance"],
            "direction_bias": "long",
            "size_multiplier": 1.0,
        },
        MarketRegime.TRENDING_DOWN: {
            "allowed_strategies": ["EMA_Cross_9_21", "VWAP_Bounce", "MACD_Histogram",
                                    "Volume_Spike", "Support_Resistance"],
            "direction_bias": "short",
            "size_multiplier": 1.0,
        },
        MarketRegime.RANGING: {
            "allowed_strategies": ["Bollinger_Squeeze", "RSI_Divergence", "VWAP_Bounce",
                                    "Support_Resistance"],
            "direction_bias": None,
            "size_multiplier": 1.0,
        },
        MarketRegime.LOW_VOL_DRIFT: {
            "allowed_strategies": ["Bollinger_Squeeze", "RSI_Divergence"],
            "direction_bias": None,
            "size_multiplier": 0.5,
        },
        MarketRegime.VOLATILE_CHOP: {
            "allowed_strategies": [],  # No trading
            "direction_bias": None,
            "size_multiplier": 0.0,
        },
        MarketRegime.TRANSITIONAL: {
            "allowed_strategies": ["EMA_Cross_9_21", "VWAP_Bounce", "Support_Resistance"],
            "direction_bias": None,
            "size_multiplier": 0.5,
        },
    }
    return filters.get(regime, filters[MarketRegime.TRANSITIONAL])
