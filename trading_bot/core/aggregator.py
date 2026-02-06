"""
Signal Aggregator -- Swarm Consensus System.

Collects votes from all strategies and produces a weighted consensus signal.
Only fires alerts when minimum consensus and score thresholds are met.
"""

import logging
from typing import List, Optional

from trading_bot.core.models import Signal, AggregatedSignal
from trading_bot.core.enums import SignalType, MarketRegime
from trading_bot.core.regime import detect_regime, get_regime_strategy_filter
from trading_bot.strategies.base import BaseStrategy
from trading_bot.risk.manager import calculate_position_size

logger = logging.getLogger("trading_bot")


class SignalAggregator:
    """Aggregates signals from the strategy swarm into consensus decisions."""

    def __init__(
        self,
        strategies: List[BaseStrategy],
        strong_buy_threshold: float = 1.5,
        buy_threshold: float = 0.5,
        sell_threshold: float = -0.5,
        strong_sell_threshold: float = -1.5,
        min_consensus: float = 0.4,
        min_strategies_reporting: int = 2,
    ):
        self.strategies = strategies
        self.strong_buy_threshold = strong_buy_threshold
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.strong_sell_threshold = strong_sell_threshold
        self.min_consensus = min_consensus
        self.min_strategies_reporting = min_strategies_reporting

    def aggregate(
        self,
        signals: List[Signal],
        regime: MarketRegime = MarketRegime.TRANSITIONAL,
        account_equity: float = 50000.0,
        risk_per_trade_pct: float = 0.01,
        size_multiplier: float = 1.0,
    ) -> AggregatedSignal:
        """
        Aggregate individual strategy signals into a consensus signal.

        Args:
            signals: List of Signal objects from different strategies.
            regime: Current market regime (for filtering).
            account_equity: For position sizing.
            risk_per_trade_pct: Risk per trade percentage.
            size_multiplier: From risk manager (daily/drawdown adjustments).
        """
        if not signals:
            return self._neutral_signal("")

        symbol = signals[0].symbol
        regime_filter = get_regime_strategy_filter(regime)
        allowed = regime_filter["allowed_strategies"]
        direction_bias = regime_filter["direction_bias"]
        regime_size_mult = regime_filter["size_multiplier"]

        # Filter signals by regime
        if allowed:
            filtered_signals = [s for s in signals if s.strategy_name in allowed]
        else:
            # Volatile chop: no trades
            return self._neutral_signal(symbol, regime=regime.value)

        # Apply direction bias
        if direction_bias == "long":
            filtered_signals = [s for s in filtered_signals if s.signal_type.value > 0]
        elif direction_bias == "short":
            filtered_signals = [s for s in filtered_signals if s.signal_type.value < 0]

        if len(filtered_signals) < self.min_strategies_reporting:
            return self._neutral_signal(symbol, regime=regime.value)

        # Calculate weighted score
        total_weight = 0
        weighted_score = 0

        for sig in filtered_signals:
            strategy = next(
                (s for s in self.strategies if s.name == sig.strategy_name), None
            )
            weight = strategy.weight if strategy else 1.0
            weighted_score += sig.signal_type.value * weight * sig.confidence
            total_weight += weight

        if total_weight > 0:
            weighted_score /= total_weight

        # Consensus: what fraction agree on direction?
        directions = [
            1 if s.signal_type.value > 0 else -1 if s.signal_type.value < 0 else 0
            for s in filtered_signals
        ]
        if directions:
            majority = max(set(directions), key=directions.count)
            consensus = directions.count(majority) / len(directions)
        else:
            consensus = 0

        # Determine action
        action = "NEUTRAL"
        if weighted_score >= self.strong_buy_threshold and consensus >= 0.6:
            action = "STRONG_BUY"
        elif weighted_score >= self.buy_threshold and consensus >= self.min_consensus:
            action = "BUY"
        elif weighted_score <= self.strong_sell_threshold and consensus >= 0.6:
            action = "STRONG_SELL"
        elif weighted_score <= self.sell_threshold and consensus >= self.min_consensus:
            action = "SELL"

        if action == "NEUTRAL":
            return self._neutral_signal(symbol, regime=regime.value)

        # Pick best SL/TP from individual signals (use the most conservative stop)
        is_buy = action in ("BUY", "STRONG_BUY")
        sl_signals = [s for s in filtered_signals if s.stop_loss > 0]
        tp_signals = [s for s in filtered_signals if s.take_profit > 0]

        if is_buy:
            stop_loss = max((s.stop_loss for s in sl_signals), default=0) if sl_signals else 0
            take_profit = min((s.take_profit for s in tp_signals), default=0) if tp_signals else 0
        else:
            stop_loss = min((s.stop_loss for s in sl_signals), default=0) if sl_signals else 0
            take_profit = max((s.take_profit for s in tp_signals), default=0) if tp_signals else 0

        price = filtered_signals[0].price
        risk_reward = abs(take_profit - price) / abs(price - stop_loss) if stop_loss != price else 0

        # Position sizing
        combined_mult = size_multiplier * regime_size_mult
        sizing = calculate_position_size(
            account_equity, price, stop_loss,
            risk_per_trade_pct, size_multiplier=combined_mult,
        )

        return AggregatedSignal(
            symbol=symbol,
            weighted_score=round(weighted_score, 3),
            contributing_strategies=[s.strategy_name for s in filtered_signals],
            consensus_strength=round(consensus, 3),
            action=action,
            price=round(price, 2),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            risk_reward_ratio=round(risk_reward, 2),
            position_size=sizing["shares"],
            dollar_risk=sizing["dollar_risk"],
            regime=regime.value,
            individual_signals=filtered_signals,
        )

    def _neutral_signal(self, symbol: str, regime: str = "") -> AggregatedSignal:
        return AggregatedSignal(
            symbol=symbol,
            weighted_score=0,
            contributing_strategies=[],
            consensus_strength=0,
            action="NEUTRAL",
            regime=regime,
        )
