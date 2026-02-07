"""Agent that executes orders on Polymarket's CLOB."""

from __future__ import annotations

import asyncio

import aiohttp

from ..base_agent import BaseAgent
from ..types import (
    Message,
    MessageType,
    OrderRequest,
    OrderResult,
    OrderStatus,
    Side,
    SizeRecommendation,
)


class OrderExecutorAgent(BaseAgent):
    name = "order_executor"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._clob_client = None
        self._session: aiohttp.ClientSession | None = None
        self._pending_orders: list[SizeRecommendation] = []

    def _init_clob_client(self):
        """Lazy-initialize the Polymarket CLOB client."""
        if self._clob_client is not None:
            return

        pk = self.config.polymarket.private_key
        if not pk:
            self.logger.warning("POLY_PRIVATE_KEY not set — executor in read-only mode")
            return

        try:
            from py_clob_client.client import ClobClient
            self._clob_client = ClobClient(
                host=self.config.polymarket.clob_host,
                key=pk,
                chain_id=self.config.polymarket.chain_id,
                signature_type=self.config.polymarket.signature_type,
                funder=self.config.polymarket.funder or None,
            )
            creds = self._clob_client.create_or_derive_api_creds()
            self._clob_client.set_api_creds(creds)
            self.logger.info("CLOB client initialized")
        except ImportError:
            self.logger.error("py-clob-client not installed — pip install py-clob-client")
        except Exception as exc:
            self.logger.error("CLOB client init failed: %s", exc)

    # ---- proactive: process pending orders ----

    async def _run(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()

        while self._pending_orders:
            rec = self._pending_orders.pop(0)
            result = await self._execute_order(rec)
            await self.bus.publish(Message(
                type=MessageType.ORDER_FILL,
                sender=self.name,
                payload=result,
            ))

        await asyncio.sleep(2)

    async def _execute_order(self, rec: SizeRecommendation) -> OrderResult:
        """Execute a single order, respecting dry_run mode."""

        if self.config.trading.dry_run:
            self.logger.info(
                "[DRY RUN] Would %s %.0f shares of %s @ $%.3f ($%.2f total)",
                rec.side.value, rec.size_shares, rec.token_id[:16],
                rec.price, rec.size_usd,
            )
            return OrderResult(
                signal_id=rec.signal_id,
                order_id="dry_run",
                status=OrderStatus.FILLED,
                filled_size=rec.size_shares,
                filled_price=rec.price,
            )

        self._init_clob_client()
        if self._clob_client is None:
            return OrderResult(
                signal_id=rec.signal_id,
                status=OrderStatus.FAILED,
                error="CLOB client not available",
            )

        try:
            return await self._place_limit_order(rec)
        except Exception as exc:
            self.logger.error("Order execution failed: %s", exc)
            return OrderResult(
                signal_id=rec.signal_id,
                status=OrderStatus.FAILED,
                error=str(exc),
            )

    async def _place_limit_order(self, rec: SizeRecommendation) -> OrderResult:
        """Place a GTC limit order via py-clob-client."""
        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.order_builder.constants import BUY, SELL

        side = BUY if rec.side == Side.BUY else SELL

        order_args = OrderArgs(
            token_id=rec.token_id,
            price=rec.price,
            size=rec.size_shares,
            side=side,
        )

        # Run blocking CLOB calls in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()

        signed_order = await loop.run_in_executor(
            None, self._clob_client.create_order, order_args
        )
        resp = await loop.run_in_executor(
            None, self._clob_client.post_order, signed_order, "GTC"
        )

        order_id = ""
        if isinstance(resp, dict):
            order_id = resp.get("orderID", resp.get("id", ""))
            if resp.get("success") or resp.get("status") == "matched":
                self.logger.info(
                    "ORDER PLACED: %s %s %.0f @ $%.3f — id=%s",
                    rec.side.value, rec.token_id[:16], rec.size_shares, rec.price, order_id,
                )
                return OrderResult(
                    signal_id=rec.signal_id,
                    order_id=order_id,
                    status=OrderStatus.SUBMITTED,
                    filled_size=0,
                    filled_price=rec.price,
                )
            else:
                error = resp.get("errorMsg", resp.get("error", str(resp)))
                self.logger.warning("Order rejected: %s", error)
                return OrderResult(
                    signal_id=rec.signal_id,
                    order_id=order_id,
                    status=OrderStatus.FAILED,
                    error=error,
                )

        return OrderResult(
            signal_id=rec.signal_id,
            status=OrderStatus.FAILED,
            error=f"Unexpected response: {resp}",
        )

    # ---- reactive: receive sized order requests ----

    async def _handle_message(self, message: Message) -> None:
        if message.type == MessageType.ORDER_REQUEST:
            payload = message.payload
            if isinstance(payload, SizeRecommendation) and payload.approved:
                self._pending_orders.append(payload)
                self.logger.info(
                    "Queued order: %s %s %.0f shares @ $%.3f",
                    payload.side.value, payload.token_id[:16],
                    payload.size_shares, payload.price,
                )

        elif message.type == MessageType.RISK_ALERT:
            # Risk manager says cancel everything
            if isinstance(message.payload, dict) and message.payload.get("action") == "cancel_all":
                self._pending_orders.clear()
                self.logger.warning("RISK ALERT: cleared all pending orders")
                if self._clob_client and not self.config.trading.dry_run:
                    try:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, self._clob_client.cancel_all)
                        self.logger.warning("Cancelled all open orders on CLOB")
                    except Exception as exc:
                        self.logger.error("Failed to cancel orders: %s", exc)
