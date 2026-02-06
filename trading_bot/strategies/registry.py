"""Strategy registry: loads all strategies for the swarm."""

from typing import List

from trading_bot.strategies.base import BaseStrategy
from trading_bot.strategies.ema_cross import EMACrossStrategy
from trading_bot.strategies.rsi_divergence import RSIDivergenceStrategy
from trading_bot.strategies.vwap_bounce import VWAPBounceStrategy
from trading_bot.strategies.macd_histogram import MACDHistogramStrategy
from trading_bot.strategies.bollinger_squeeze import BollingerSqueezeStrategy
from trading_bot.strategies.volume_spike import VolumeSpikeStrategy
from trading_bot.strategies.support_resistance import SupportResistanceStrategy


def get_all_strategies() -> List[BaseStrategy]:
    """Return all strategies for the swarm consensus system."""
    return [
        EMACrossStrategy(),          # Trend: EMA 9/21 cross
        RSIDivergenceStrategy(),     # Momentum: RSI divergence
        VWAPBounceStrategy(),        # Volume: VWAP reclaim/rejection
        MACDHistogramStrategy(),     # Momentum: MACD histogram cross
        BollingerSqueezeStrategy(),  # Volatility: BB squeeze + mean reversion
        VolumeSpikeStrategy(),       # Volume: unusual activity detection
        SupportResistanceStrategy(), # Structure: S/R level bounces
    ]
