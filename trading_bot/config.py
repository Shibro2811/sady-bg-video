"""Type-safe configuration using pydantic-settings."""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Data source
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    data_source: str = "yfinance"  # "yfinance" or "alpaca"

    # Scanning
    scan_interval_minutes: int = 15
    symbols: List[str] = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "AMD",
        "NFLX", "SPY", "QQQ", "BABA", "DIS", "BA", "JPM", "V", "MA",
        "PYPL", "SQ", "COIN", "SOFI", "PLTR", "NIO", "RIVN", "UBER",
    ]
    max_concurrent_requests: int = 10
    max_requests_per_minute: int = 100

    # Alerts
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Trading Parameters
    account_equity: float = 50000.0
    risk_per_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.03
    max_open_positions: int = 3
    max_trades_per_day: int = 6
    max_consecutive_losses: int = 3

    # Database
    database_url: str = "sqlite:///trading_bot.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
