"""Discord webhook notifications with rich embeds."""

import logging
from typing import Optional

import aiohttp

from trading_bot.core.models import AggregatedSignal

logger = logging.getLogger("trading_bot")


class DiscordNotifier:
    """Send trading alerts via Discord webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send_alert(self, signal: AggregatedSignal):
        """Send a rich embed alert to Discord."""
        if not self.webhook_url:
            logger.debug("Discord webhook URL not configured, skipping")
            return

        is_buy = signal.action in ("BUY", "STRONG_BUY")
        color = 0x00FF00 if is_buy else 0xFF0000
        emoji = "🟢" if is_buy else "🔴"
        direction = "LONG" if is_buy else "SHORT"

        strategies_text = ", ".join(signal.contributing_strategies[:5])
        rr_text = f"{signal.risk_reward_ratio:.1f}:1" if signal.risk_reward_ratio > 0 else "N/A"

        embed = {
            "embeds": [{
                "title": f"{emoji} {signal.action}: {signal.symbol}",
                "color": color,
                "fields": [
                    {"name": "Direction", "value": direction, "inline": True},
                    {"name": "Price", "value": f"${signal.price:.2f}", "inline": True},
                    {"name": "Score", "value": f"{signal.weighted_score:.2f}", "inline": True},
                    {"name": "Stop Loss", "value": f"${signal.stop_loss:.2f}", "inline": True},
                    {"name": "Take Profit", "value": f"${signal.take_profit:.2f}", "inline": True},
                    {"name": "R:R", "value": rr_text, "inline": True},
                    {"name": "Consensus", "value": f"{signal.consensus_strength:.0%}", "inline": True},
                    {"name": "Position Size", "value": f"{signal.position_size} shares", "inline": True},
                    {"name": "Risk", "value": f"${signal.dollar_risk:.2f}", "inline": True},
                    {"name": "Strategies", "value": strategies_text, "inline": False},
                    {"name": "Regime", "value": signal.regime or "N/A", "inline": True},
                ],
                "footer": {"text": "Trading Bot | 15-Min Chart | Not Financial Advice"},
            }]
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=embed) as resp:
                    if resp.status != 204:
                        body = await resp.text()
                        logger.error(f"Discord webhook error {resp.status}: {body}")
                    else:
                        logger.info(f"Discord alert sent: {signal.action} {signal.symbol}")
        except Exception as e:
            logger.error(f"Discord notification failed: {e}")

    async def send_message(self, content: str):
        """Send a plain text message."""
        if not self.webhook_url:
            return
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(self.webhook_url, json={"content": content})
        except Exception as e:
            logger.error(f"Discord message failed: {e}")
