"""Agent that sizes positions using Kelly Criterion and risk constraints."""

from __future__ import annotations

import math

from ..base_agent import BaseAgent
from ..types import (
    EdgeSignal,
    Message,
    MessageType,
    Side,
    SizeRecommendation,
)


class PositionSizerAgent(BaseAgent):
    name = "position_sizer"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_exposure: float = 0.0
        self._positions_count: int = 0

    # ---- proactive: nothing, purely reactive ----

    async def _run(self) -> None:
        import asyncio
        await asyncio.sleep(10)

    # ---- reactive: size positions for incoming edge signals ----

    async def _handle_message(self, message: Message) -> None:
        if message.type == MessageType.EDGE_SIGNAL:
            signal = message.payload
            if isinstance(signal, EdgeSignal):
                rec = self._compute_size(signal)
                await self.bus.publish(Message(
                    type=MessageType.ORDER_REQUEST if rec.approved else MessageType.HEARTBEAT,
                    sender=self.name,
                    payload=rec,
                ))
                if rec.approved:
                    self.logger.info(
                        "SIZED: %s %s $%.2f (%.1f shares @ $%.3f) kelly=%.3f",
                        rec.side.value, rec.token_id[:16], rec.size_usd,
                        rec.size_shares, rec.price, rec.kelly_fraction,
                    )
                else:
                    self.logger.info("REJECTED: %s — %s", signal.id, ", ".join(rec.risk_notes))

        elif message.type == MessageType.ORDER_FILL:
            # Track exposure changes from fills
            from ..types import OrderResult, OrderStatus
            result = message.payload
            if isinstance(result, OrderResult) and result.status == OrderStatus.FILLED:
                self._current_exposure += result.filled_size * result.filled_price
                self._positions_count += 1

    def _compute_size(self, signal: EdgeSignal) -> SizeRecommendation:
        tc = self.config.trading
        notes: list[str] = []
        approved = True

        # --- Kelly Criterion ---
        if signal.side == Side.BUY:
            p = signal.estimated_fair_price
            price = signal.current_price
            if price <= 0 or price >= 1:
                notes.append(f"Invalid price {price}")
                return SizeRecommendation(
                    signal_id=signal.id, token_id=signal.token_id,
                    side=signal.side, price=price, approved=False, risk_notes=notes,
                )
            b = (1.0 / price) - 1.0  # odds
            q = 1.0 - p
        else:
            p = 1.0 - signal.estimated_fair_price
            price = signal.current_price
            if price <= 0 or price >= 1:
                notes.append(f"Invalid price {price}")
                return SizeRecommendation(
                    signal_id=signal.id, token_id=signal.token_id,
                    side=signal.side, price=price, approved=False, risk_notes=notes,
                )
            b = (1.0 / (1.0 - price)) - 1.0
            q = 1.0 - p

        if b <= 0:
            notes.append("Non-positive odds")
            approved = False
        elif p * b <= q:
            notes.append(f"Negative Kelly: p*b ({p*b:.3f}) <= q ({q:.3f})")
            approved = False

        if approved:
            kelly_full = (p * b - q) / b
            kelly = kelly_full * tc.kelly_fraction  # half-Kelly
        else:
            kelly = 0.0

        # --- Position size ---
        size_usd = tc.bankroll * kelly if approved else 0.0
        max_position = tc.bankroll * tc.max_position_pct
        if size_usd > max_position:
            notes.append(f"Capped at {tc.max_position_pct*100:.0f}% of bankroll")
            size_usd = max_position

        # --- Risk checks ---
        if size_usd < tc.min_profit_usd:
            notes.append(f"Position ${size_usd:.2f} below minimum ${tc.min_profit_usd:.2f}")
            approved = False

        if self._positions_count >= tc.max_open_positions:
            notes.append(f"Max open positions reached ({tc.max_open_positions})")
            approved = False

        if self._current_exposure + size_usd > tc.bankroll:
            notes.append("Would exceed total bankroll")
            approved = False

        # --- Confidence adjustment ---
        if signal.confidence < 0.3:
            notes.append(f"Low confidence ({signal.confidence:.2f}), reducing size 50%")
            size_usd *= 0.5

        # --- Shares calculation ---
        size_shares = math.floor(size_usd / price) if price > 0 and approved else 0

        return SizeRecommendation(
            signal_id=signal.id,
            token_id=signal.token_id,
            side=signal.side,
            price=price,
            size_usd=size_usd,
            size_shares=size_shares,
            kelly_fraction=kelly,
            risk_notes=notes,
            approved=approved,
        )
