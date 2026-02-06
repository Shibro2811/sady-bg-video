"""
Stock Scanner -- The main scan engine.

Scans all symbols on 15-min candles, runs the strategy swarm,
aggregates signals, and dispatches alerts.
"""

import asyncio
import logging
import time
from typing import List, Optional

import pandas as pd

from trading_bot.config import settings
from trading_bot.core.aggregator import SignalAggregator
from trading_bot.core.models import Signal, AggregatedSignal
from trading_bot.core.regime import detect_regime
from trading_bot.strategies.base import BaseStrategy
from trading_bot.strategies.registry import get_all_strategies
from trading_bot.risk.manager import DailyRiskManager, DrawdownManager
from trading_bot.utils.indicators import compute_all_indicators
from trading_bot.utils.market_hours import is_valid_entry_time

logger = logging.getLogger("trading_bot")


class StockScanner:
    """
    Main scanning engine.
    Scans symbols, runs strategies, aggregates signals, dispatches alerts.
    """

    def __init__(self, data_client, notifiers=None):
        self.data_client = data_client
        self.notifiers = notifiers or []
        self.strategies = get_all_strategies()
        self.aggregator = SignalAggregator(self.strategies)
        self.daily_risk = DailyRiskManager(
            account_equity=settings.account_equity,
            max_daily_loss_pct=settings.max_daily_loss_pct,
            max_consecutive_losses=settings.max_consecutive_losses,
            max_daily_trades=settings.max_trades_per_day,
        )
        self.drawdown = DrawdownManager(
            starting_equity=settings.account_equity,
            current_equity=settings.account_equity,
        )

    def scan_symbol(self, symbol: str) -> Optional[AggregatedSignal]:
        """Scan a single symbol through the strategy swarm."""
        try:
            # Fetch data
            df = self.data_client.get_bars(symbol, interval="15m", period="5d")
            if df is None or len(df) < 60:
                return None

            # Compute all indicators
            df = compute_all_indicators(df)

            # Detect market regime
            regime = detect_regime(df)

            # Run all strategies
            signals: List[Signal] = []
            for strategy in self.strategies:
                if len(df) >= strategy.required_bars():
                    try:
                        signal = strategy.analyze(df, symbol)
                        if signal is not None:
                            signals.append(signal)
                    except Exception as e:
                        logger.error(f"Strategy {strategy.name} error on {symbol}: {e}")

            if not signals:
                return None

            # Risk management checks
            risk_check = self.daily_risk.can_trade()
            if not risk_check["allowed"]:
                logger.info(f"Risk manager blocked trade: {risk_check['reason']}")
                return None

            dd_check = self.drawdown.get_size_multiplier()
            combined_mult = risk_check["size_multiplier"] * dd_check["multiplier"]

            if combined_mult <= 0:
                return None

            # Aggregate signals
            aggregated = self.aggregator.aggregate(
                signals,
                regime=regime,
                account_equity=settings.account_equity,
                risk_per_trade_pct=settings.risk_per_trade_pct,
                size_multiplier=combined_mult,
            )

            return aggregated if aggregated.action != "NEUTRAL" else None

        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}")
            return None

    def scan_all(self, force: bool = False) -> List[AggregatedSignal]:
        """Scan all symbols and return actionable signals."""
        if not force and not is_valid_entry_time():
            logger.info("Outside valid trading hours, skipping scan (use --force to override)")
            return []

        start_time = time.time()
        alerts: List[AggregatedSignal] = []

        logger.info(f"Starting scan of {len(settings.symbols)} symbols...")

        for symbol in settings.symbols:
            result = self.scan_symbol(symbol)
            if result is not None:
                alerts.append(result)
                logger.info(
                    f"ALERT: {result.action} {result.symbol} @ ${result.price:.2f} "
                    f"| SL: ${result.stop_loss:.2f} | TP: ${result.take_profit:.2f} "
                    f"| R:R: {result.risk_reward_ratio:.1f}:1 | Score: {result.weighted_score:.2f} "
                    f"| Consensus: {result.consensus_strength:.0%} "
                    f"| Strategies: {', '.join(result.contributing_strategies)}"
                )

        duration = time.time() - start_time
        logger.info(
            f"Scan complete: {len(settings.symbols)} symbols in {duration:.1f}s, "
            f"{len(alerts)} alerts generated"
        )

        return alerts

    async def scan_and_notify(self):
        """Run a full scan and send alerts through all notification channels."""
        alerts = self.scan_all()

        for alert in alerts:
            for notifier in self.notifiers:
                try:
                    await notifier.send_alert(alert)
                except Exception as e:
                    logger.error(f"Notification error: {e}")

        return alerts
