"""Agent that monitors portfolio risk and enforces limits."""

from __future__ import annotations

import asyncio
import time

from ..base_agent import BaseAgent
from ..types import (
    EdgeSignal,
    MarketInfo,
    Message,
    MessageType,
    OrderResult,
    OrderStatus,
    Position,
    Side,
)


class RiskManagerAgent(BaseAgent):
    name = "risk_manager"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.positions: dict[str, Position] = {}  # token_id -> Position
        self._markets: dict[str, MarketInfo] = {}
        self._total_pnl: float = 0.0
        self._last_report: float = 0.0

    # ---- proactive: periodic portfolio check ----

    async def _run(self) -> None:
        await self._update_unrealized_pnl()
        await self._check_risk_limits()

        # Log portfolio summary every 5 minutes
        now = time.time()
        if now - self._last_report > 300:
            self._log_portfolio_summary()
            self._last_report = now

        await asyncio.sleep(15)

    async def _update_unrealized_pnl(self) -> None:
        """Update PnL for all open positions based on latest market prices."""
        for pos in self.positions.values():
            market = self._markets.get(pos.condition_id)
            if not market:
                continue
            if pos.token_id in market.token_ids:
                idx = market.token_ids.index(pos.token_id)
                if idx < len(market.outcome_prices):
                    pos.current_price = market.outcome_prices[idx]
                    if pos.side == Side.BUY:
                        pos.unrealized_pnl = (pos.current_price - pos.entry_price) * pos.size
                    else:
                        pos.unrealized_pnl = (pos.entry_price - pos.current_price) * pos.size

    async def _check_risk_limits(self) -> None:
        """Check stop-loss and take-profit levels."""
        tc = self.config.trading

        for token_id, pos in list(self.positions.items()):
            if pos.entry_price <= 0:
                continue

            pnl_pct = pos.unrealized_pnl / (pos.entry_price * pos.size) if pos.size > 0 else 0

            # Stop loss
            if pnl_pct < -tc.stop_loss_pct:
                self.logger.warning(
                    "STOP LOSS triggered for %s: %.1f%% loss (threshold: %.0f%%)",
                    pos.question[:50], pnl_pct * 100, tc.stop_loss_pct * 100,
                )
                await self.bus.publish(Message(
                    type=MessageType.RISK_ALERT,
                    sender=self.name,
                    payload={
                        "action": "close_position",
                        "token_id": token_id,
                        "reason": "stop_loss",
                        "pnl_pct": pnl_pct,
                    },
                ))

            # Take profit
            if pnl_pct > tc.take_profit_pct:
                self.logger.info(
                    "TAKE PROFIT triggered for %s: +%.1f%%",
                    pos.question[:50], pnl_pct * 100,
                )
                await self.bus.publish(Message(
                    type=MessageType.RISK_ALERT,
                    sender=self.name,
                    payload={
                        "action": "close_position",
                        "token_id": token_id,
                        "reason": "take_profit",
                        "pnl_pct": pnl_pct,
                    },
                ))

        # Portfolio-level checks
        total_exposure = sum(p.entry_price * p.size for p in self.positions.values())
        if total_exposure > tc.bankroll * 1.5:
            self.logger.warning(
                "PORTFOLIO EXPOSURE %.2f exceeds 150%% of bankroll — cancelling all",
                total_exposure,
            )
            await self.bus.publish(Message(
                type=MessageType.RISK_ALERT,
                sender=self.name,
                payload={"action": "cancel_all", "reason": "overexposed"},
            ))

    def _log_portfolio_summary(self) -> None:
        if not self.positions:
            self.logger.info("Portfolio: empty")
            return

        total_cost = sum(p.entry_price * p.size for p in self.positions.values())
        total_value = sum(p.current_price * p.size for p in self.positions.values())
        total_pnl = total_value - total_cost

        self.logger.info(
            "Portfolio: %d positions | cost=$%.2f | value=$%.2f | PnL=$%.2f (%.1f%%)",
            len(self.positions), total_cost, total_value, total_pnl,
            (total_pnl / total_cost * 100) if total_cost > 0 else 0,
        )
        for pos in self.positions.values():
            self.logger.info(
                "  %s %s: %.0f @ $%.3f -> $%.3f (PnL: $%.2f)",
                pos.side.value, pos.question[:40],
                pos.size, pos.entry_price, pos.current_price, pos.unrealized_pnl,
            )

    # ---- reactive: track fills and market updates ----

    async def _handle_message(self, message: Message) -> None:
        if message.type == MessageType.ORDER_FILL:
            result = message.payload
            if isinstance(result, OrderResult) and result.status in (
                OrderStatus.FILLED, OrderStatus.SUBMITTED
            ):
                self._record_fill(result)

        elif message.type == MessageType.MARKET_UPDATE:
            payload = message.payload
            if isinstance(payload, list):
                for m in payload:
                    if isinstance(m, MarketInfo):
                        self._markets[m.condition_id] = m
            elif isinstance(payload, MarketInfo):
                self._markets[payload.condition_id] = payload

        elif message.type == MessageType.EDGE_SIGNAL:
            # Track which markets we have signals for (for correlation)
            if isinstance(message.payload, EdgeSignal) and message.payload.market:
                self._markets[message.payload.market.condition_id] = message.payload.market

    def _record_fill(self, result: OrderResult) -> None:
        """Record a new fill as a position."""
        if result.filled_size <= 0 and result.status == OrderStatus.SUBMITTED:
            # GTC order submitted but not yet filled — track at order size
            return

        token_id = result.order_id  # simplified; real impl would look up from signal
        if token_id in self.positions:
            pos = self.positions[token_id]
            pos.size += result.filled_size
        else:
            self.positions[token_id] = Position(
                token_id=token_id,
                entry_price=result.filled_price,
                current_price=result.filled_price,
                size=result.filled_size,
                signal_id=result.signal_id,
            )
        self.logger.info("Position recorded: %s %.0f @ $%.3f", token_id[:16], result.filled_size, result.filled_price)
