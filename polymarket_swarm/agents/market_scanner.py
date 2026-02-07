"""Agent that scans Polymarket for active markets and tracks prices."""

from __future__ import annotations

import asyncio
import json
import time

import aiohttp
import websockets

from ..base_agent import BaseAgent
from ..types import MarketInfo, Message, MessageType


class MarketScannerAgent(BaseAgent):
    name = "market_scanner"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.markets: dict[str, MarketInfo] = {}  # condition_id -> MarketInfo
        self._session: aiohttp.ClientSession | None = None
        self._ws_task: asyncio.Task | None = None
        self._last_full_scan: float = 0.0

    # ---- proactive: periodic full scan + WebSocket streaming ----

    async def _run(self) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()

        # Full scan every 5 minutes
        now = time.time()
        if now - self._last_full_scan > 300:
            await self._full_scan()
            self._last_full_scan = now

        # Launch WebSocket listener if not running
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(self._ws_listen())

        await asyncio.sleep(self.config.scan_interval_sec)

    async def _full_scan(self) -> None:
        """Fetch all active markets from Gamma API."""
        gamma = self.config.polymarket.gamma_host
        offset = 0
        limit = 100
        total_fetched = 0

        while True:
            url = f"{gamma}/events?active=true&limit={limit}&offset={offset}"
            try:
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        self.logger.warning("Gamma API returned %s", resp.status)
                        break
                    events = await resp.json()
            except Exception as exc:
                self.logger.warning("Gamma fetch error: %s", exc)
                break

            if not events:
                break

            for event in events:
                for mkt in event.get("markets", []):
                    info = self._parse_gamma_market(mkt, event)
                    if info and info.active:
                        old = self.markets.get(info.condition_id)
                        self.markets[info.condition_id] = info
                        if old and old.outcome_prices != info.outcome_prices:
                            await self.bus.publish(Message(
                                type=MessageType.MARKET_UPDATE,
                                sender=self.name,
                                payload=info,
                            ))
                        total_fetched += 1

            offset += limit
            if len(events) < limit:
                break

        self.logger.info("Full scan complete: %d active markets tracked", total_fetched)

        # Also publish a batch update for edge detector
        await self.bus.publish(Message(
            type=MessageType.MARKET_UPDATE,
            sender=self.name,
            payload=list(self.markets.values()),
        ))

    def _parse_gamma_market(self, mkt: dict, event: dict) -> MarketInfo | None:
        cid = mkt.get("conditionId") or mkt.get("condition_id")
        if not cid:
            return None

        outcomes = mkt.get("outcomes", [])
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except json.JSONDecodeError:
                outcomes = []

        raw_prices = mkt.get("outcomePrices", [])
        if isinstance(raw_prices, str):
            try:
                raw_prices = json.loads(raw_prices)
            except json.JSONDecodeError:
                raw_prices = []

        prices = []
        for p in raw_prices:
            try:
                prices.append(float(p))
            except (ValueError, TypeError):
                prices.append(0.0)

        token_ids_raw = mkt.get("clobTokenIds", [])
        if isinstance(token_ids_raw, str):
            try:
                token_ids_raw = json.loads(token_ids_raw)
            except json.JSONDecodeError:
                token_ids_raw = []

        tags = []
        for tag in event.get("tags", []):
            if isinstance(tag, dict):
                tags.append(tag.get("label", tag.get("slug", "")))
            elif isinstance(tag, str):
                tags.append(tag)

        return MarketInfo(
            condition_id=cid,
            question=mkt.get("question", ""),
            slug=mkt.get("slug", ""),
            outcomes=outcomes,
            outcome_prices=prices,
            token_ids=token_ids_raw,
            volume=float(mkt.get("volume", 0) or 0),
            liquidity=float(mkt.get("liquidity", 0) or 0),
            neg_risk=bool(mkt.get("negRisk", False)),
            active=bool(mkt.get("active", True)),
            end_date=mkt.get("endDate", ""),
            event_slug=event.get("slug", ""),
            tags=tags,
        )

    async def _ws_listen(self) -> None:
        """Subscribe to WebSocket for real-time price changes."""
        ws_url = self.config.polymarket.ws_url
        token_ids = []
        for m in self.markets.values():
            token_ids.extend(m.token_ids)

        if not token_ids:
            self.logger.info("No token_ids to subscribe to WebSocket")
            return

        # Subscribe in batches of 100
        batch_size = 100
        batches = [token_ids[i:i + batch_size] for i in range(0, len(token_ids), batch_size)]

        for batch in batches[:5]:  # limit to 5 batches = 500 tokens
            try:
                async with websockets.connect(ws_url, ping_interval=30) as ws:
                    sub = {"assets_ids": batch, "type": "market"}
                    await ws.send(json.dumps(sub))
                    self.logger.info("WebSocket subscribed to %d tokens", len(batch))

                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(raw)
                            await self._handle_ws_event(data)
                        except json.JSONDecodeError:
                            continue
            except Exception as exc:
                self.logger.warning("WebSocket error: %s", exc)
                await asyncio.sleep(5)

    async def _handle_ws_event(self, data: dict) -> None:
        event_type = data.get("event_type")
        if event_type == "price_change":
            for change in data.get("price_changes", []):
                asset_id = change.get("asset_id", "")
                # Find market containing this token
                for m in self.markets.values():
                    if asset_id in m.token_ids:
                        idx = m.token_ids.index(asset_id)
                        try:
                            new_price = float(change.get("price", 0))
                        except (ValueError, TypeError):
                            continue
                        if 0 < new_price < 1 and idx < len(m.outcome_prices):
                            m.outcome_prices[idx] = new_price
                            await self.bus.publish(Message(
                                type=MessageType.MARKET_UPDATE,
                                sender=self.name,
                                payload=m,
                            ))
                        break

    # ---- reactive ----

    async def _handle_message(self, message: Message) -> None:
        pass

    def get_market(self, condition_id: str) -> MarketInfo | None:
        return self.markets.get(condition_id)

    def search_markets(self, query: str) -> list[MarketInfo]:
        q = query.lower()
        return [m for m in self.markets.values() if q in m.question.lower() or q in m.event_slug.lower()]
