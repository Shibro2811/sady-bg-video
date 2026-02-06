"""Market hours detection and session utilities."""

from datetime import datetime, time, date
import pytz

EASTERN = pytz.timezone("US/Eastern")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
TRADING_START = time(9, 45)  # Skip first 15 min
TRADING_END = time(15, 30)  # No new entries last 30 min
EOD_FLATTEN = time(15, 45)  # Close all positions

# 2026 US market holidays
HOLIDAYS_2026 = {
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 7, 3),    # Independence Day (observed)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
}


def now_eastern() -> datetime:
    """Get current time in Eastern timezone."""
    return datetime.now(EASTERN)


def is_market_open() -> bool:
    """Check if US stock market is currently open."""
    now = now_eastern()
    if now.weekday() >= 5:
        return False
    if now.date() in HOLIDAYS_2026:
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def is_valid_entry_time() -> bool:
    """Check if it's a valid time for new trade entries."""
    now = now_eastern()
    if not is_market_open():
        return False
    current = now.time()
    if current < TRADING_START:
        return False
    if current >= TRADING_END:
        return False
    return True


def is_lunch_hour() -> bool:
    """Check if it's the low-liquidity lunch hour (11:30-1:30 ET)."""
    now = now_eastern()
    return time(11, 30) <= now.time() <= time(13, 30)


def should_flatten_positions() -> bool:
    """Check if it's time to close all positions."""
    now = now_eastern()
    return now.time() >= EOD_FLATTEN
