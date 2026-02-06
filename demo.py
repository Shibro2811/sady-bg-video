"""
Demo: Run the full trading bot pipeline with synthetic market data.
Proves the entire system works end-to-end when external APIs are unavailable.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from trading_bot.utils.logging_config import setup_logging
from trading_bot.utils.indicators import compute_all_indicators
from trading_bot.core.regime import detect_regime, _efficiency_ratio
from trading_bot.core.aggregator import SignalAggregator
from trading_bot.core.enums import MarketRegime
from trading_bot.strategies.registry import get_all_strategies
from trading_bot.risk.manager import (
    DailyRiskManager, DrawdownManager,
    calculate_position_size, calculate_take_profits,
)


def generate_synthetic_data(bars: int = 500, seed: int = 42) -> pd.DataFrame:
    """Generate realistic 15-min OHLCV data with strong crossovers and reversals."""
    np.random.seed(seed)
    base_price = 185.0
    prices = [base_price]

    for i in range(1, bars):
        phase = i / bars
        if phase < 0.12:
            drift = 0.004     # strong uptrend
        elif phase < 0.22:
            drift = 0.001     # mild up
        elif phase < 0.28:
            drift = -0.004    # sharp selloff (creates crossovers)
        elif phase < 0.38:
            drift = 0.003     # bounce back (creates bullish crossover)
        elif phase < 0.48:
            drift = -0.001    # drift down
        elif phase < 0.55:
            drift = -0.005    # crash (triggers mean reversion)
        elif phase < 0.62:
            drift = 0.005     # V-recovery (strong crossovers)
        elif phase < 0.72:
            drift = 0.001     # consolidation
        elif phase < 0.80:
            drift = -0.003    # pullback
        else:
            drift = 0.003     # final rally

        noise = np.random.normal(drift, 0.005)
        prices.append(prices[-1] * (1 + noise))

    prices = np.array(prices)

    dates = pd.date_range(start=datetime(2026, 1, 15, 9, 30), periods=bars, freq="15min")

    high = prices * (1 + np.abs(np.random.normal(0.0015, 0.003, bars)))
    low = prices * (1 - np.abs(np.random.normal(0.0015, 0.003, bars)))
    opens = low + (high - low) * np.random.uniform(0.2, 0.8, bars)

    volume = np.random.randint(1000000, 5000000, bars).astype(float)
    # Big volume spikes at transitions
    for pct in [0.12, 0.22, 0.28, 0.38, 0.48, 0.55, 0.62, 0.72, 0.80]:
        idx = int(bars * pct)
        volume[max(0, idx - 2):min(bars, idx + 6)] *= 4

    df = pd.DataFrame({
        "open": opens, "high": high, "low": low,
        "close": prices, "volume": volume,
    }, index=dates)
    return df


def main():
    setup_logging("WARNING")  # quiet logging

    print("=" * 80)
    print("  STOCK TRADING BOT -- Full Pipeline Demo")
    print("  15-Min Chart | 7-Strategy Swarm | Weighted Consensus")
    print("=" * 80)

    # ── 1. Generate data ────────────────────────────────────────────
    df = generate_synthetic_data(bars=500, seed=7)
    df_ind = compute_all_indicators(df)
    df_ind = df_ind.dropna(subset=["EMA_9", "EMA_21", "RSI_14"])

    last = df_ind.iloc[-1]
    print(f"\n  Data: 500 bars of 15-min synthetic OHLCV")
    print(f"  Range: {df_ind.index[0]} -> {df_ind.index[-1]}")
    print(f"\n  Latest Indicators:")
    print(f"    Close: ${last['close']:.2f} | EMA9: ${last.get('EMA_9',0):.2f} | "
          f"EMA21: ${last.get('EMA_21',0):.2f} | EMA55: ${last.get('EMA_55',0):.2f}")
    print(f"    RSI: {last.get('RSI_14',0):.1f} | ADX: {last.get('ADX_14',0):.1f} | "
          f"ATR: ${last.get('ATRr_14',0):.3f} | RelVol: {last.get('REL_VOL',0):.2f}x")

    # ── 2. Scan every bar for signals (full backtest-style) ─────────
    print(f"\n{'─'*80}")
    print("  SCANNING ALL BARS -- Strategy Signals Across Full Dataset")
    print(f"{'─'*80}\n")

    strategies = get_all_strategies()
    aggregator = SignalAggregator(strategies, min_strategies_reporting=1,
                                  buy_threshold=0.3, sell_threshold=-0.3)

    all_signals = []
    all_alerts = []

    for i in range(60, len(df_ind)):
        window = df_ind.iloc[:i + 1]
        regime = detect_regime(window)

        bar_signals = []
        for strategy in strategies:
            if len(window) >= strategy.required_bars():
                sig = strategy.analyze(window, "AAPL")
                if sig is not None:
                    bar_signals.append(sig)
                    all_signals.append((i, sig))

        if bar_signals:
            agg = aggregator.aggregate(
                bar_signals, regime=regime,
                account_equity=50000, risk_per_trade_pct=0.01,
            )
            if agg.action != "NEUTRAL":
                all_alerts.append((i, agg))

    # Print signal summary
    print(f"  Total individual strategy signals: {len(all_signals)}")
    print(f"  Total consensus alerts (tradeable): {len(all_alerts)}")

    # Signal breakdown by strategy
    print(f"\n  Signals by Strategy:")
    from collections import Counter
    strat_counts = Counter(s.strategy_name for _, s in all_signals)
    for name, count in strat_counts.most_common():
        print(f"    {name:30s}  {count} signals")

    # Print all consensus alerts
    if all_alerts:
        print(f"\n{'─'*80}")
        print("  TRADING ALERTS")
        print(f"{'─'*80}\n")

        for bar_idx, alert in all_alerts:
            timestamp = df_ind.index[bar_idx]
            is_buy = alert.action in ("BUY", "STRONG_BUY")
            emoji = "+" if is_buy else "-"
            direction = "LONG " if is_buy else "SHORT"

            print(f"  {emoji} {alert.action:12s} AAPL @ ${alert.price:.2f}  |  "
                  f"SL: ${alert.stop_loss:.2f}  TP: ${alert.take_profit:.2f}  "
                  f"R:R {alert.risk_reward_ratio:.1f}:1  |  "
                  f"Score: {alert.weighted_score:+.2f}  "
                  f"Consensus: {alert.consensus_strength:.0%}  |  "
                  f"{', '.join(alert.contributing_strategies)}  |  "
                  f"Regime: {alert.regime}")
    else:
        print("\n  No consensus alerts generated.")

    # ── 3. Simulate trades from alerts ──────────────────────────────
    if all_alerts:
        print(f"\n{'─'*80}")
        print("  SIMULATED TRADE RESULTS")
        print(f"{'─'*80}\n")

        trades = []
        for bar_idx, alert in all_alerts:
            entry = alert.price
            sl = alert.stop_loss
            tp = alert.take_profit
            is_buy = alert.action in ("BUY", "STRONG_BUY")

            # Simulate: look forward up to 20 bars
            exit_price = None
            exit_reason = "time_stop"
            for j in range(bar_idx + 1, min(bar_idx + 21, len(df_ind))):
                bar = df_ind.iloc[j]
                if is_buy:
                    if bar["low"] <= sl:
                        exit_price = sl
                        exit_reason = "stop_loss"
                        break
                    if bar["high"] >= tp:
                        exit_price = tp
                        exit_reason = "take_profit"
                        break
                else:
                    if bar["high"] >= sl:
                        exit_price = sl
                        exit_reason = "stop_loss"
                        break
                    if bar["low"] <= tp:
                        exit_price = tp
                        exit_reason = "take_profit"
                        break

            if exit_price is None:
                exit_idx = min(bar_idx + 20, len(df_ind) - 1)
                exit_price = df_ind.iloc[exit_idx]["close"]

            if is_buy:
                pnl = exit_price - entry
            else:
                pnl = entry - exit_price

            risk = abs(entry - sl)
            r_mult = pnl / risk if risk > 0 else 0
            trades.append((alert, exit_price, pnl, r_mult, exit_reason))

        wins = sum(1 for _, _, pnl, _, _ in trades if pnl > 0)
        losses = sum(1 for _, _, pnl, _, _ in trades if pnl <= 0)
        total_pnl = sum(pnl for _, _, pnl, _, _ in trades)
        avg_r = np.mean([r for _, _, _, r, _ in trades]) if trades else 0

        for alert, exit_price, pnl, r_mult, reason in trades:
            emoji = "+" if pnl > 0 else "-"
            print(f"    {emoji} {alert.action:12s} @ ${alert.price:.2f} -> ${exit_price:.2f}  "
                  f"PnL: ${pnl:+.2f} ({r_mult:+.1f}R)  [{reason}]")

        print(f"\n  {'─'*50}")
        print(f"  SUMMARY:")
        print(f"    Total Trades:   {len(trades)}")
        print(f"    Wins / Losses:  {wins} / {losses}")
        print(f"    Win Rate:       {wins/len(trades):.0%}" if trades else "    Win Rate:       N/A")
        print(f"    Total PnL:      ${total_pnl:+.2f}")
        print(f"    Avg R-Multiple: {avg_r:+.2f}R")

    # ── 4. Risk management showcase ─────────────────────────────────
    print(f"\n{'─'*80}")
    print("  RISK MANAGEMENT SYSTEM")
    print(f"{'─'*80}\n")

    sizing = calculate_position_size(
        account_equity=50000, entry_price=185.0,
        stop_loss=183.50, risk_per_trade_pct=0.01,
    )
    tps = calculate_take_profits(185.0, 183.50, "long")
    print(f"  Position Sizing (AAPL @ $185.00, SL @ $183.50, 1% risk):")
    print(f"    Shares:     {sizing['shares']}")
    print(f"    Risk:       ${sizing['dollar_risk']:.2f} ({sizing['pct_of_account']:.1f}% of account)")
    print(f"    TP1 (1.5R): ${tps['tp1']:.2f} -- close 50%")
    print(f"    TP2 (3.0R): ${tps['tp2']:.2f} -- close remainder")
    print(f"    Trail:      ${tps['trail_offset']:.2f} offset")

    daily = DailyRiskManager(account_equity=50000)
    print(f"\n  Daily Limits: Max Loss ${daily.max_daily_loss_dollars:.0f} | "
          f"Max Trades {daily.max_daily_trades} | "
          f"Max Consec Losses {daily.max_consecutive_losses}")

    dd = DrawdownManager(starting_equity=50000, current_equity=47000)
    info = dd.get_size_multiplier()
    print(f"  Drawdown: {info['drawdown_pct']:.1f}% -> Tier {info['tier']} -> "
          f"{info['multiplier']:.0%} size | {info['action']}")

    print(f"\n{'='*80}")
    print("  DEMO COMPLETE -- All systems operational")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
