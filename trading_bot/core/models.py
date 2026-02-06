"""Data models for signals, trades, and setups."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import pandas as pd

from .enums import SignalType, TradeDirection, MarketRegime


@dataclass
class Signal:
    """Individual signal from a single strategy."""
    signal_type: SignalType
    symbol: str
    strategy_name: str
    confidence: float  # 0.0 to 1.0
    price: float
    timestamp: pd.Timestamp
    stop_loss: float = 0.0
    take_profit: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AggregatedSignal:
    """Consensus signal from the strategy swarm."""
    symbol: str
    weighted_score: float  # -2.0 to +2.0
    contributing_strategies: List[str]
    consensus_strength: float  # 0.0 to 1.0
    action: str  # "STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"
    price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward_ratio: float = 0.0
    position_size: int = 0
    dollar_risk: float = 0.0
    regime: str = ""
    individual_signals: List[Signal] = field(default_factory=list)


@dataclass
class TradeSetup:
    """Complete trade setup with entry, stop, target, and sizing."""
    symbol: str
    direction: TradeDirection
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    stop_distance: float
    risk_reward_ratio: float
    atr_value: float
    position_size: int
    dollar_risk: float
    method: str  # which strategy triggered this


@dataclass
class Position:
    """Active position tracker."""
    symbol: str
    direction: TradeDirection
    entry_price: float
    stop_loss: float
    take_profit: float
    total_shares: int
    remaining_shares: int
    entry_time: pd.Timestamp
    realized_pnl: float = 0.0
    scale_levels_hit: List[float] = field(default_factory=list)

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def one_r(self) -> float:
        return self.risk_per_share

    def current_r_multiple(self, current_price: float) -> float:
        if self.direction == TradeDirection.LONG:
            return (current_price - self.entry_price) / self.one_r if self.one_r > 0 else 0
        else:
            return (self.entry_price - current_price) / self.one_r if self.one_r > 0 else 0
