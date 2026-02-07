"""Entry point for the Polymarket Arbitrage Swarm."""

import asyncio
import sys

from .config import SwarmConfig
from .orchestrator import SwarmOrchestrator


def main() -> None:
    config = SwarmConfig()
    swarm = SwarmOrchestrator(config)

    try:
        asyncio.run(swarm.run())
    except KeyboardInterrupt:
        print("\nSwarm interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
