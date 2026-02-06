"""
Risk Management System.

Handles:
- ATR-based dynamic stop losses (1.5x ATR default)
- Position sizing (1% risk per trade)
- Take profit with partial scaling (50% at 1R, trail rest)
- Daily loss limits (3% max)
- Drawdown tiers (reduce size at 5%, stop at 10%)
- Max trades per day, consecutive loss limits
- Time-based stops
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
import logging

logger = logging.getLogger("trading_bot")


@dataclass
class DailyRiskManager:
    """Tracks daily PnL and enforces daily risk limits."""
    account_equity: float
    max_daily_loss_pct: float = 0.03
    max_consecutive_losses: int = 3
    max_daily_trades: int = 6
    cooldown_candles: int = 2

    daily_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    is_locked_out: bool = False
    lockout_reason: str = ""
    size_multiplier: float = 1.0
    cooldown_remaining: int = 0

    @property
    def max_daily_loss_dollars(self) -> float:
        return self.account_equity * self.max_daily_loss_pct

    def record_trade(self, pnl: float):
        """Record a completed trade and update risk state."""
        self.daily_pnl += pnl
        self.trades_today += 1

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
            self.size_multiplier = 1.0

        self._check_limits()

    def _check_limits(self):
        if self.daily_pnl <= -self.max_daily_loss_dollars:
            self.is_locked_out = True
            self.lockout_reason = (
                f"Daily loss limit hit: ${self.daily_pnl:.2f} "
                f"(limit: -${self.max_daily_loss_dollars:.2f})"
            )
            logger.warning(self.lockout_reason)
            return

        if self.consecutive_losses >= self.max_consecutive_losses:
            self.is_locked_out = True
            self.lockout_reason = f"{self.consecutive_losses} consecutive losses"
            self.cooldown_remaining = self.cooldown_candles
            logger.warning(self.lockout_reason)
            return

        if self.trades_today >= self.max_daily_trades:
            self.is_locked_out = True
            self.lockout_reason = f"Max daily trades reached: {self.trades_today}"
            logger.info(self.lockout_reason)
            return

        # Reduce size after 2 consecutive losses
        if self.consecutive_losses >= 2:
            self.size_multiplier = 0.5

    def can_trade(self) -> Dict:
        if self.is_locked_out:
            return {"allowed": False, "reason": self.lockout_reason, "size_multiplier": 0.0}
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
            return {"allowed": False, "reason": f"Cooling down ({self.cooldown_remaining} left)", "size_multiplier": 0.0}
        return {"allowed": True, "reason": "OK", "size_multiplier": self.size_multiplier}

    def reset_daily(self, new_equity: float):
        self.account_equity = new_equity
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.consecutive_losses = 0
        self.is_locked_out = False
        self.lockout_reason = ""
        self.size_multiplier = 1.0
        self.cooldown_remaining = 0


@dataclass
class DrawdownManager:
    """Multi-day drawdown management with tiered position reduction."""
    starting_equity: float
    current_equity: float
    tier1_pct: float = 0.05   # 5% -> 50% size
    tier2_pct: float = 0.075  # 7.5% -> 25% size
    tier3_pct: float = 0.10   # 10% -> stop trading

    @property
    def current_drawdown_pct(self) -> float:
        if self.starting_equity <= 0:
            return 0.0
        return max(0, (self.starting_equity - self.current_equity) / self.starting_equity)

    def update_equity(self, new_equity: float):
        self.current_equity = new_equity
        if new_equity > self.starting_equity:
            self.starting_equity = new_equity

    def get_size_multiplier(self) -> Dict:
        dd = self.current_drawdown_pct
        if dd >= self.tier3_pct:
            return {"multiplier": 0.0, "tier": 3, "action": "STOP TRADING. Review strategy.", "drawdown_pct": round(dd * 100, 2)}
        elif dd >= self.tier2_pct:
            return {"multiplier": 0.25, "tier": 2, "action": "Trade at 25% size. A+ setups only.", "drawdown_pct": round(dd * 100, 2)}
        elif dd >= self.tier1_pct:
            return {"multiplier": 0.5, "tier": 1, "action": "Trade at 50% size. Be selective.", "drawdown_pct": round(dd * 100, 2)}
        else:
            return {"multiplier": 1.0, "tier": 0, "action": "Normal trading.", "drawdown_pct": round(dd * 100, 2)}


def calculate_position_size(
    account_equity: float,
    entry_price: float,
    stop_loss: float,
    risk_per_trade_pct: float = 0.01,
    max_position_pct: float = 0.25,
    size_multiplier: float = 1.0,
) -> Dict:
    """
    Calculate position size using fixed fractional risk.
    Risk 1% of account per trade by default.
    """
    risk_pct = risk_per_trade_pct * size_multiplier
    dollar_risk = account_equity * risk_pct
    risk_per_share = abs(entry_price - stop_loss)

    if risk_per_share <= 0:
        return {"shares": 0, "dollar_risk": 0, "position_value": 0}

    shares = int(dollar_risk / risk_per_share)

    # Cap by max position percentage
    max_shares = int((account_equity * max_position_pct) / entry_price) if entry_price > 0 else 0
    shares = min(shares, max_shares)

    actual_risk = shares * risk_per_share
    position_value = shares * entry_price

    return {
        "shares": shares,
        "dollar_risk": round(actual_risk, 2),
        "position_value": round(position_value, 2),
        "risk_per_share": round(risk_per_share, 4),
        "pct_of_account": round(position_value / account_equity * 100, 2) if account_equity > 0 else 0,
    }


def calculate_stop_loss(entry_price: float, atr: float, direction: str,
                        multiplier: float = 1.5) -> float:
    """ATR-based stop loss."""
    distance = atr * multiplier
    if direction == "long":
        return entry_price - distance
    else:
        return entry_price + distance


def calculate_take_profits(entry_price: float, stop_loss: float,
                           direction: str) -> Dict:
    """Calculate tiered take profit levels."""
    risk = abs(entry_price - stop_loss)

    if direction == "long":
        return {
            "tp1": round(entry_price + 1.5 * risk, 4),  # 1.5R - close 50%
            "tp2": round(entry_price + 3.0 * risk, 4),  # 3.0R - close remaining
            "trail_offset": round(1.5 * risk, 4),         # 1.5R trailing stop
        }
    else:
        return {
            "tp1": round(entry_price - 1.5 * risk, 4),
            "tp2": round(entry_price - 3.0 * risk, 4),
            "trail_offset": round(1.5 * risk, 4),
        }
