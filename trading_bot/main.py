"""
Stock Trading Bot -- Main Entry Point.

15-Minute Chart Alert System with Swarm Strategy Consensus.
Scans stocks every 15 minutes, runs 7 strategies, aggregates signals,
and sends alerts via Discord/Telegram with SL, TP, and position sizing.

Usage:
    python -m trading_bot.main              # Run live scanner
    python -m trading_bot.main --scan-once  # Run a single scan
    python -m trading_bot.main --backtest AAPL  # Backtest on a symbol
"""

import argparse
import asyncio
import logging
import sys

from trading_bot.config import settings
from trading_bot.core.scanner import StockScanner
from trading_bot.db.models import init_db
from trading_bot.utils.logging_config import setup_logging


def build_data_client():
    """Create the data client based on config."""
    if settings.data_source == "alpaca" and settings.alpaca_api_key:
        from trading_bot.data.alpaca_client import AlpacaClient
        return AlpacaClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            settings.alpaca_base_url,
        )
    else:
        from trading_bot.data.yfinance_client import YFinanceClient
        return YFinanceClient()


def build_notifiers():
    """Create notification channels based on config."""
    notifiers = []

    if settings.discord_webhook_url:
        from trading_bot.notifications.discord import DiscordNotifier
        notifiers.append(DiscordNotifier(settings.discord_webhook_url))

    if settings.telegram_bot_token and settings.telegram_chat_id:
        from trading_bot.notifications.telegram import TelegramNotifier
        notifiers.append(TelegramNotifier(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
        ))

    return notifiers


def run_scan_once():
    """Run a single scan and print results."""
    logger = logging.getLogger("trading_bot")
    logger.info("Running single scan...")

    client = build_data_client()
    notifiers = build_notifiers()
    scanner = StockScanner(client, notifiers)

    alerts = scanner.scan_all()

    if not alerts:
        print("\nNo alerts generated. Market may be closed or no signals detected.")
        return

    print(f"\n{'='*80}")
    print(f"  TRADING ALERTS -- 15-Min Chart Swarm Consensus")
    print(f"{'='*80}\n")

    for alert in alerts:
        emoji = "🟢" if alert.action in ("BUY", "STRONG_BUY") else "🔴"
        direction = "LONG" if alert.action in ("BUY", "STRONG_BUY") else "SHORT"

        print(f"  {emoji} {alert.action}: {alert.symbol}")
        print(f"     Direction:    {direction}")
        print(f"     Price:        ${alert.price:.2f}")
        print(f"     Stop Loss:    ${alert.stop_loss:.2f}")
        print(f"     Take Profit:  ${alert.take_profit:.2f}")
        print(f"     R:R Ratio:    {alert.risk_reward_ratio:.1f}:1")
        print(f"     Score:        {alert.weighted_score:.2f}")
        print(f"     Consensus:    {alert.consensus_strength:.0%}")
        print(f"     Position:     {alert.position_size} shares (${alert.dollar_risk:.2f} risk)")
        print(f"     Regime:       {alert.regime}")
        print(f"     Strategies:   {', '.join(alert.contributing_strategies)}")
        print()

    # Send notifications
    if notifiers:
        asyncio.run(_send_alerts(notifiers, alerts))


async def _send_alerts(notifiers, alerts):
    for alert in alerts:
        for notifier in notifiers:
            try:
                await notifier.send_alert(alert)
            except Exception as e:
                logging.getLogger("trading_bot").error(f"Notification error: {e}")


def run_scheduler():
    """Run the scanner on a schedule during market hours."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    logger = logging.getLogger("trading_bot")
    scheduler = BlockingScheduler()

    def scheduled_scan():
        try:
            client = build_data_client()
            notifiers = build_notifiers()
            scanner = StockScanner(client, notifiers)
            alerts = scanner.scan_all()
            if alerts and notifiers:
                asyncio.run(_send_alerts(notifiers, alerts))
        except Exception as e:
            logger.error(f"Scheduled scan error: {e}")

    # Run every 15 minutes during market hours (Mon-Fri, 9:30 AM - 4:00 PM ET)
    scheduler.add_job(
        scheduled_scan,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="0,15,30,45",
            timezone="US/Eastern",
        ),
        id="main_scan",
        name="15-min candle scan",
    )

    logger.info("Scheduler started. Scanning every 15 minutes during market hours.")
    logger.info(f"Watching {len(settings.symbols)} symbols: {', '.join(settings.symbols[:10])}...")
    logger.info(f"Data source: {settings.data_source}")
    logger.info(f"Account equity: ${settings.account_equity:,.2f}")
    logger.info(f"Risk per trade: {settings.risk_per_trade_pct:.1%}")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown()


def run_backtest(symbol: str):
    """Run a backtest on historical data for a symbol."""
    from trading_bot.backtesting.runner import run_backtest as bt_run

    logger = logging.getLogger("trading_bot")
    logger.info(f"Running backtest for {symbol}...")

    client = build_data_client()
    df = client.get_bars(symbol, interval="15m", period="60d")

    if df is None or len(df) < 100:
        print(f"Insufficient data for backtest on {symbol}")
        return

    result = bt_run(
        df, symbol,
        account_equity=settings.account_equity,
        risk_per_trade_pct=settings.risk_per_trade_pct,
    )

    print(result.summary())

    if result.trades:
        print("\nRecent Trades:")
        for trade in result.trades[-10:]:
            emoji = "✅" if trade.pnl > 0 else "❌"
            print(
                f"  {emoji} {trade.action} @ ${trade.entry_price:.2f} -> "
                f"${trade.exit_price:.2f} | PnL: ${trade.pnl:.2f} "
                f"({trade.r_multiple:.1f}R) | {trade.exit_reason}"
            )


def main():
    setup_logging()
    init_db()

    parser = argparse.ArgumentParser(description="Stock Trading Bot - 15min Chart Alerts")
    parser.add_argument("--scan-once", action="store_true", help="Run a single scan and exit")
    parser.add_argument("--backtest", type=str, help="Run backtest on a symbol (e.g., AAPL)")
    parser.add_argument("--schedule", action="store_true", help="Run on 15-min schedule")

    args = parser.parse_args()

    if args.backtest:
        run_backtest(args.backtest)
    elif args.scan_once:
        run_scan_once()
    elif args.schedule:
        run_scheduler()
    else:
        # Default: single scan
        run_scan_once()


if __name__ == "__main__":
    main()
