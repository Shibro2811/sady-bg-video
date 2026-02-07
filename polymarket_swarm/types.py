"""Shared data types and inter-agent message bus."""

from __future__ import annotations

import asyncio
import enum
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Side(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class MessageType(str, enum.Enum):
    NEWS_EVENT = "news_event"
    MARKET_UPDATE = "market_update"
    EDGE_SIGNAL = "edge_signal"
    SIZE_REQUEST = "size_request"
    SIZE_RESPONSE = "size_response"
    ORDER_REQUEST = "order_request"
    ORDER_FILL = "order_fill"
    RISK_ALERT = "risk_alert"
    HEARTBEAT = "heartbeat"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MarketInfo:
    condition_id: str
    question: str
    slug: str
    outcomes: list[str]
    outcome_prices: list[float]
    token_ids: list[str]
    volume: float = 0.0
    liquidity: float = 0.0
    neg_risk: bool = False
    active: bool = True
    end_date: str = ""
    event_slug: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class NewsItem:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    summary: str = ""
    source: str = ""
    url: str = ""
    published: float = 0.0
    keywords_matched: list[str] = field(default_factory=list)
    relevance_score: float = 0.0


@dataclass
class EdgeSignal:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    market: MarketInfo | None = None
    token_id: str = ""
    side: Side = Side.BUY
    current_price: float = 0.0
    estimated_fair_price: float = 0.0
    edge: float = 0.0
    confidence: float = 0.0
    reasoning: str = ""
    news_item: NewsItem | None = None
    pattern: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class SizeRecommendation:
    signal_id: str = ""
    token_id: str = ""
    side: Side = Side.BUY
    price: float = 0.0
    size_usd: float = 0.0
    size_shares: float = 0.0
    kelly_fraction: float = 0.0
    risk_notes: list[str] = field(default_factory=list)
    approved: bool = False


@dataclass
class OrderRequest:
    signal_id: str = ""
    token_id: str = ""
    side: Side = Side.BUY
    price: float = 0.0
    size: float = 0.0
    order_type: str = "GTC"
    condition_id: str = ""


@dataclass
class OrderResult:
    signal_id: str = ""
    order_id: str = ""
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    filled_price: float = 0.0
    error: str = ""


@dataclass
class Position:
    token_id: str = ""
    condition_id: str = ""
    question: str = ""
    side: Side = Side.BUY
    entry_price: float = 0.0
    current_price: float = 0.0
    size: float = 0.0
    unrealized_pnl: float = 0.0
    signal_id: str = ""


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

@dataclass
class Message:
    type: MessageType
    sender: str
    payload: Any
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Message Bus (async fan-out)
# ---------------------------------------------------------------------------

class MessageBus:
    """Simple async pub/sub bus for inter-agent communication."""

    def __init__(self) -> None:
        self._subscribers: dict[str, asyncio.Queue[Message]] = {}

    def subscribe(self, agent_name: str) -> asyncio.Queue[Message]:
        q: asyncio.Queue[Message] = asyncio.Queue(maxsize=500)
        self._subscribers[agent_name] = q
        logger.info("MessageBus: %s subscribed", agent_name)
        return q

    async def publish(self, message: Message) -> None:
        for name, q in self._subscribers.items():
            if name == message.sender:
                continue
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("MessageBus: queue full for %s, dropping message %s", name, message.id)

    async def publish_to(self, target: str, message: Message) -> None:
        q = self._subscribers.get(target)
        if q is None:
            logger.warning("MessageBus: target %s not subscribed", target)
            return
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("MessageBus: queue full for %s", target)
