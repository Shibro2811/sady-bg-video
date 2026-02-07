"""Swarm Orchestrator — spins up all agents and coordinates the message bus."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .agents import (
    EdgeDetectorAgent,
    MarketScannerAgent,
    NewsMonitorAgent,
    OrderExecutorAgent,
    PositionSizerAgent,
    RiskManagerAgent,
)
from .config import SwarmConfig
from .types import MessageBus

logger = logging.getLogger("swarm.orchestrator")


class SwarmOrchestrator:
    """Launches and manages the full agent swarm."""

    def __init__(self, config: SwarmConfig | None = None) -> None:
        self.config = config or SwarmConfig()
        self.bus = MessageBus()
        self.agents = [
            NewsMonitorAgent(self.config, self.bus),
            MarketScannerAgent(self.config, self.bus),
            EdgeDetectorAgent(self.config, self.bus),
            PositionSizerAgent(self.config, self.bus),
            OrderExecutorAgent(self.config, self.bus),
            RiskManagerAgent(self.config, self.bus),
        ]
        self._tasks: list[asyncio.Task] = []

    async def run(self) -> None:
        """Start all agents concurrently."""
        self._setup_logging()
        self._print_banner()
        self._validate_config()

        loop = asyncio.get_event_loop()
        for sig_name in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig_name, lambda: asyncio.create_task(self.shutdown()))

        logger.info("Starting %d agents...", len(self.agents))

        self._tasks = [asyncio.create_task(agent.start()) for agent in self.agents]

        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("Swarm cancelled")

    async def shutdown(self) -> None:
        """Gracefully stop all agents."""
        logger.info("Shutting down swarm...")
        for agent in self.agents:
            await agent.stop()
        for task in self._tasks:
            task.cancel()
        logger.info("Swarm stopped")

    def _setup_logging(self) -> None:
        level = getattr(logging, self.config.log_level.upper(), logging.INFO)
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stdout,
        )

    def _print_banner(self) -> None:
        dry = "DRY RUN" if self.config.trading.dry_run else "LIVE TRADING"
        print(f"""
╔══════════════════════════════════════════════════╗
║         POLYMARKET ARBITRAGE SWARM               ║
║                                                  ║
║  Agents: {len(self.agents)}                                       ║
║  Mode:   {dry:<40s} ║
║  Bankroll: ${self.config.trading.bankroll:>10,.2f}                       ║
║  Kelly:  {self.config.trading.kelly_fraction:.0%} (half-Kelly)                       ║
║  Min edge: {self.config.trading.min_edge:.0%}                                  ║
╚══════════════════════════════════════════════════╝
""")
        print("Agents:")
        for agent in self.agents:
            print(f"  -> {agent.name}")
        print()

    def _validate_config(self) -> None:
        warnings = []

        if not self.config.news.anthropic_api_key:
            warnings.append("ANTHROPIC_API_KEY not set — edge detector will not analyze news")

        if not self.config.polymarket.private_key:
            warnings.append("POLY_PRIVATE_KEY not set — orders cannot be placed (read-only mode)")

        if self.config.trading.dry_run:
            warnings.append("TRADING_DRY_RUN=true — no real orders will be placed")

        if not self.config.news.rss_feeds:
            warnings.append("No RSS feeds configured")

        for w in warnings:
            logger.warning("CONFIG: %s", w)
