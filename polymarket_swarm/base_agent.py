"""Base class for all swarm agents."""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import SwarmConfig
    from .types import Message, MessageBus


class BaseAgent(abc.ABC):
    """Every agent runs two concurrent loops: _run (proactive) and _listen (reactive)."""

    name: str = "base"

    def __init__(self, config: SwarmConfig, bus: MessageBus) -> None:
        self.config = config
        self.bus = bus
        self.inbox: asyncio.Queue[Message] = bus.subscribe(self.name)
        self.logger = logging.getLogger(f"swarm.{self.name}")
        self._running = False

    async def start(self) -> None:
        self._running = True
        self.logger.info("%s starting", self.name)
        await asyncio.gather(self._run_loop(), self._listen_loop())

    async def stop(self) -> None:
        self._running = False
        self.logger.info("%s stopping", self.name)

    # -- proactive work (polling, scanning, etc.) ---
    @abc.abstractmethod
    async def _run(self) -> None:
        ...

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._run()
            except asyncio.CancelledError:
                break
            except Exception:
                self.logger.exception("%s _run error", self.name)
                await asyncio.sleep(5)

    # -- reactive work (respond to messages) ---
    @abc.abstractmethod
    async def _handle_message(self, message: Message) -> None:
        ...

    async def _listen_loop(self) -> None:
        while self._running:
            try:
                msg = await asyncio.wait_for(self.inbox.get(), timeout=1.0)
                await self._handle_message(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                self.logger.exception("%s _handle_message error", self.name)
