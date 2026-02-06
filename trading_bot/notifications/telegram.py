"""Telegram bot notifications."""

import logging

import aiohttp

from trading_bot.core.models import AggregatedSignal

logger = logging.getLogger("trading_bot")


class TelegramNotifier:
    """Send trading alerts via Telegram bot."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    async def send_alert(self, signal: AggregatedSignal):
        """Send a formatted alert to Telegram."""
        if not self.bot_token or not self.chat_id:
            logger.debug("Telegram not configured, skipping")
            return

        is_buy = signal.action in ("BUY", "STRONG_BUY")
        emoji = "🟢" if is_buy else "🔴"
        direction = "LONG" if is_buy else "SHORT"
        strategies = ", ".join(signal.contributing_strategies[:5])
        rr = f"{signal.risk_reward_ratio:.1f}:1" if signal.risk_reward_ratio > 0 else "N/A"

        message = (
            f"{emoji} <b>{signal.action}: {signal.symbol}</b>\n\n"
            f"Direction: {direction}\n"
            f"Price: ${signal.price:.2f}\n"
            f"Stop Loss: ${signal.stop_loss:.2f}\n"
            f"Take Profit: ${signal.take_profit:.2f}\n"
            f"R:R: {rr}\n"
            f"Score: {signal.weighted_score:.2f}\n"
            f"Consensus: {signal.consensus_strength:.0%}\n"
            f"Size: {signal.position_size} shares (${signal.dollar_risk:.2f} risk)\n"
            f"Strategies: {strategies}\n"
            f"Regime: {signal.regime or 'N/A'}\n\n"
            f"<i>15-Min Chart | Not Financial Advice</i>"
        )

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/sendMessage"
                payload = {
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                }
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"Telegram error {resp.status}: {body}")
                    else:
                        logger.info(f"Telegram alert sent: {signal.action} {signal.symbol}")
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")

    async def send_message(self, text: str):
        """Send a plain text message."""
        if not self.bot_token or not self.chat_id:
            return
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/sendMessage"
                await session.post(url, json={
                    "chat_id": self.chat_id, "text": text, "parse_mode": "HTML"
                })
        except Exception as e:
            logger.error(f"Telegram message failed: {e}")
