"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _list(key: str, default: str = "") -> list[str]:
    raw = os.getenv(key, default)
    return [s.strip() for s in raw.split(",") if s.strip()]


@dataclass(frozen=True)
class PolymarketConfig:
    clob_host: str = os.getenv("POLY_CLOB_HOST", "https://clob.polymarket.com")
    gamma_host: str = os.getenv("POLY_GAMMA_HOST", "https://gamma-api.polymarket.com")
    ws_url: str = os.getenv("POLY_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market")
    ws_user_url: str = os.getenv("POLY_WS_USER_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/user")
    private_key: str = os.getenv("POLY_PRIVATE_KEY", "")
    chain_id: int = _int("POLY_CHAIN_ID", 137)
    signature_type: int = _int("POLY_SIGNATURE_TYPE", 0)
    funder: str = os.getenv("POLY_FUNDER", "")


@dataclass(frozen=True)
class TradingConfig:
    bankroll: float = _float("TRADING_BANKROLL", 1000.0)
    max_position_pct: float = _float("TRADING_MAX_POSITION_PCT", 0.20)
    kelly_fraction: float = _float("TRADING_KELLY_FRACTION", 0.5)  # half-Kelly
    min_edge: float = _float("TRADING_MIN_EDGE", 0.05)
    min_profit_usd: float = _float("TRADING_MIN_PROFIT_USD", 2.0)
    max_open_positions: int = _int("TRADING_MAX_OPEN_POSITIONS", 10)
    max_single_market_exposure: float = _float("TRADING_MAX_SINGLE_MARKET_EXPOSURE", 0.30)
    stop_loss_pct: float = _float("TRADING_STOP_LOSS_PCT", 0.50)
    take_profit_pct: float = _float("TRADING_TAKE_PROFIT_PCT", 3.0)
    dry_run: bool = os.getenv("TRADING_DRY_RUN", "true").lower() == "true"


@dataclass(frozen=True)
class NewsConfig:
    rss_feeds: list[str] = field(default_factory=lambda: _list("NEWS_RSS_FEEDS",
        "https://feeds.arstechnica.com/arstechnica/technology-lab,"
        "https://www.reddit.com/r/MachineLearning/.rss,"
        "https://hnrss.org/frontpage"
    ))
    poll_interval_sec: int = _int("NEWS_POLL_INTERVAL_SEC", 120)
    keywords: list[str] = field(default_factory=lambda: _list("NEWS_KEYWORDS",
        "polymarket,prediction market,AI model,benchmark,election,poll,"
        "resign,impeach,indictment,sanctions,ceasefire,rate cut,rate hike,"
        "FDA approval,Supreme Court,executive order,launched,released,announced"
    ))
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")


@dataclass(frozen=True)
class SwarmConfig:
    polymarket: PolymarketConfig = field(default_factory=PolymarketConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
    scan_interval_sec: int = _int("SWARM_SCAN_INTERVAL_SEC", 30)
    log_level: str = os.getenv("SWARM_LOG_LEVEL", "INFO")
