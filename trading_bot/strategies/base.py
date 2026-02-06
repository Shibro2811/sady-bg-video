"""Base strategy interface -- all strategies implement this."""

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

from trading_bot.core.models import Signal


class BaseStrategy(ABC):
    """Strategy interface for the swarm consensus system."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique strategy identifier."""
        pass

    @property
    @abstractmethod
    def weight(self) -> float:
        """How much this strategy's vote counts in aggregation (0.5 - 2.0)."""
        pass

    @abstractmethod
    def analyze(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        """
        Given OHLCV DataFrame with computed indicators, return a Signal or None.
        The DataFrame will already have all indicators computed.
        """
        pass

    @abstractmethod
    def required_bars(self) -> int:
        """Minimum candles needed for this strategy to produce a signal."""
        pass
