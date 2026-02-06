"""
Backtesting harness.

Runs the strategy swarm against historical data and reports performance.
Uses the same strategy logic as live scanning for consistency.
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

from trading_bot.strategies.registry import get_all_strategies
from trading_bot.core.aggregator import SignalAggregator
from trading_bot.core.regime import detect_regime
from trading_bot.utils.indicators import compute_all_indicators

logger = logging.getLogger("trading_bot")


@dataclass
class BacktestTrade:
    symbol: str
    action: str
    entry_price: float
    entry_time: pd.Timestamp
    stop_loss: float
    take_profit: float
    exit_price: float = 0.0
    exit_time: Optional[pd.Timestamp] = None
    exit_reason: str = ""
    pnl: float = 0.0
    r_multiple: float = 0.0


@dataclass
class BacktestResult:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_r_multiple: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    trades: List[BacktestTrade] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"\n{'='*60}\n"
            f"BACKTEST RESULTS\n"
            f"{'='*60}\n"
            f"Total Trades:    {self.total_trades}\n"
            f"Win Rate:        {self.win_rate:.1%}\n"
            f"Winning Trades:  {self.winning_trades}\n"
            f"Losing Trades:   {self.losing_trades}\n"
            f"Total PnL:       ${self.total_pnl:.2f}\n"
            f"Avg R-Multiple:  {self.avg_r_multiple:.2f}R\n"
            f"Max Drawdown:    {self.max_drawdown:.1%}\n"
            f"Profit Factor:   {self.profit_factor:.2f}\n"
            f"Expectancy:      {self.expectancy:.2f}R per trade\n"
            f"{'='*60}\n"
        )


def run_backtest(
    df: pd.DataFrame,
    symbol: str,
    account_equity: float = 50000.0,
    risk_per_trade_pct: float = 0.01,
    max_bars_in_trade: int = 20,
) -> BacktestResult:
    """
    Run a backtest on historical 15-min OHLCV data.

    Simulates the full strategy swarm on each candle and tracks trades.
    """
    strategies = get_all_strategies()
    aggregator = SignalAggregator(strategies)

    # Compute indicators once on full dataset
    df = compute_all_indicators(df)
    df = df.dropna(subset=["EMA_9", "EMA_21", "RSI_14"])

    if len(df) < 60:
        logger.warning(f"Insufficient data for backtest: {len(df)} bars")
        return BacktestResult()

    trades: List[BacktestTrade] = []
    position: Optional[BacktestTrade] = None
    bars_in_trade = 0

    for i in range(60, len(df)):
        window = df.iloc[:i + 1]
        curr = df.iloc[i]

        # If in a position, check exit conditions
        if position is not None:
            bars_in_trade += 1
            hit_tp = False
            hit_sl = False

            if position.action in ("BUY", "STRONG_BUY"):
                if curr["low"] <= position.stop_loss:
                    hit_sl = True
                if curr["high"] >= position.take_profit:
                    hit_tp = True
            else:
                if curr["high"] >= position.stop_loss:
                    hit_sl = True
                if curr["low"] <= position.take_profit:
                    hit_tp = True

            # Time stop
            time_stop = bars_in_trade >= max_bars_in_trade

            if hit_sl:
                position.exit_price = position.stop_loss
                position.exit_reason = "stop_loss"
            elif hit_tp:
                position.exit_price = position.take_profit
                position.exit_reason = "take_profit"
            elif time_stop:
                position.exit_price = curr["close"]
                position.exit_reason = "time_stop"

            if position.exit_price > 0:
                position.exit_time = df.index[i]
                risk = abs(position.entry_price - position.stop_loss)
                if position.action in ("BUY", "STRONG_BUY"):
                    position.pnl = position.exit_price - position.entry_price
                else:
                    position.pnl = position.entry_price - position.exit_price
                position.r_multiple = position.pnl / risk if risk > 0 else 0
                trades.append(position)
                position = None
                bars_in_trade = 0

            continue

        # No position: look for entry
        regime = detect_regime(window)
        signals = []
        for strategy in strategies:
            if len(window) >= strategy.required_bars():
                try:
                    signal = strategy.analyze(window, symbol)
                    if signal is not None:
                        signals.append(signal)
                except Exception:
                    pass

        if signals:
            aggregated = aggregator.aggregate(
                signals, regime=regime,
                account_equity=account_equity,
                risk_per_trade_pct=risk_per_trade_pct,
            )

            if aggregated.action != "NEUTRAL" and aggregated.stop_loss > 0:
                position = BacktestTrade(
                    symbol=symbol,
                    action=aggregated.action,
                    entry_price=curr["close"],
                    entry_time=df.index[i],
                    stop_loss=aggregated.stop_loss,
                    take_profit=aggregated.take_profit,
                )
                bars_in_trade = 0

    # Close any remaining position
    if position is not None:
        position.exit_price = df.iloc[-1]["close"]
        position.exit_time = df.index[-1]
        position.exit_reason = "end_of_data"
        risk = abs(position.entry_price - position.stop_loss)
        if position.action in ("BUY", "STRONG_BUY"):
            position.pnl = position.exit_price - position.entry_price
        else:
            position.pnl = position.entry_price - position.exit_price
        position.r_multiple = position.pnl / risk if risk > 0 else 0
        trades.append(position)

    # Compute results
    return _compute_results(trades)


def _compute_results(trades: List[BacktestTrade]) -> BacktestResult:
    if not trades:
        return BacktestResult()

    winning = [t for t in trades if t.pnl > 0]
    losing = [t for t in trades if t.pnl <= 0]
    r_multiples = [t.r_multiple for t in trades]

    gross_profit = sum(t.pnl for t in winning)
    gross_loss = abs(sum(t.pnl for t in losing))

    # Max drawdown (simple PnL-based)
    cumulative_pnl = np.cumsum([t.pnl for t in trades])
    peak = np.maximum.accumulate(cumulative_pnl)
    drawdown = (peak - cumulative_pnl) / (peak + 1e-10)
    max_dd = float(drawdown.max()) if len(drawdown) > 0 else 0

    return BacktestResult(
        total_trades=len(trades),
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=len(winning) / len(trades) if trades else 0,
        total_pnl=sum(t.pnl for t in trades),
        avg_r_multiple=np.mean(r_multiples) if r_multiples else 0,
        max_drawdown=max_dd,
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else float("inf"),
        expectancy=np.mean(r_multiples) if r_multiples else 0,
        trades=trades,
    )
