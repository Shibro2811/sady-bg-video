# Polymarket Arbitrage Swarm

Multi-agent swarm system that monitors news, scans Polymarket markets, detects trading edges, and executes arbitrage trades autonomously.

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌────────────────┐
│ News Monitor │────>│  Edge Detector   │────>│ Position Sizer │
│  (RSS feeds) │     │ (Claude AI + sum │     │ (Kelly + risk) │
└──────────────┘     │  check arb)      │     └───────┬────────┘
                     └────────┬─────────┘             │
┌──────────────┐              │              ┌────────▼────────┐
│Market Scanner│──────────────┘              │ Order Executor  │
│ (Gamma API + │                             │ (CLOB API)      │
│  WebSocket)  │                             └────────┬────────┘
└──────────────┘                                      │
                     ┌───────────────────┐            │
                     │   Risk Manager    │<───────────┘
                     │ (stop-loss, PnL)  │
                     └───────────────────┘
```

**6 agents** communicate via an async message bus:

| Agent | Role |
|-------|------|
| **News Monitor** | Polls RSS feeds, matches keywords, emits `NewsItem` events |
| **Market Scanner** | Fetches all active markets from Gamma API, streams prices via WebSocket |
| **Edge Detector** | Uses Claude to map news to markets, also runs probability-sum arbitrage checks |
| **Position Sizer** | Kelly Criterion with half-Kelly default, enforces risk limits |
| **Order Executor** | Places GTC limit orders on Polymarket CLOB (dry-run by default) |
| **Risk Manager** | Monitors unrealized PnL, triggers stop-loss/take-profit alerts |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your keys

# 3. Run (dry-run mode by default)
python -m polymarket_swarm.main
```

## Configuration

All config is via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `POLY_PRIVATE_KEY` | — | Polygon wallet private key for trading |
| `ANTHROPIC_API_KEY` | — | Claude API key for news analysis |
| `TRADING_BANKROLL` | 1000 | Total capital in USD |
| `TRADING_KELLY_FRACTION` | 0.5 | Half-Kelly sizing |
| `TRADING_MIN_EDGE` | 0.05 | Minimum 5% edge to trade |
| `TRADING_DRY_RUN` | true | Set to `false` to place real orders |

## How It Works

1. **News Monitor** polls RSS feeds every 2 minutes, matches against keywords (AI model, election, etc.)
2. **Market Scanner** fetches all active Polymarket events from Gamma API, streams price updates via WebSocket
3. **Edge Detector** receives news + market data, uses Claude to identify which markets are affected and estimate fair prices. Also independently scans for probability-sum mispricings (outcomes summing to != 1.0)
4. **Position Sizer** applies Kelly Criterion with configurable risk limits (max position size, max exposure, confidence adjustment)
5. **Order Executor** places GTC limit orders on Polymarket's CLOB (or logs them in dry-run mode)
6. **Risk Manager** tracks all positions, computes unrealized PnL, triggers stop-loss at -50% and take-profit at +300%

## Edge Detection Patterns

The system detects five patterns from the guide:

1. **Scheduled announcements** — news about upcoming product launches/releases that markets haven't priced in
2. **Settlement lag** — events already resolved but markets still trading at wrong prices
3. **Correlated divergence** — related markets that should move together but haven't
4. **Sum mispricing** — outcome probabilities not summing to 1.0 (structural arbitrage)
5. **Calendar mispricing** — time-based conditions where probability should decay but hasn't

## Disclaimer

This software is for educational and research purposes. Trading on prediction markets involves risk of loss. Always start in dry-run mode. The authors are not responsible for any financial losses.
