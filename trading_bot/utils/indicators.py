"""Technical indicator calculations using pandas-ta."""

import pandas as pd
import numpy as np

try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all indicators needed by the strategy swarm.
    Expects OHLCV DataFrame with columns: open, high, low, close, volume.
    """
    df = df.copy()

    if HAS_PANDAS_TA:
        return _compute_with_pandas_ta(df)
    else:
        return _compute_manual(df)


def _compute_with_pandas_ta(df: pd.DataFrame) -> pd.DataFrame:
    """Compute indicators using pandas-ta library."""
    # EMAs
    df.ta.ema(length=9, append=True)
    df.ta.ema(length=21, append=True)
    df.ta.ema(length=55, append=True)

    # RSI
    df.ta.rsi(length=14, append=True)

    # MACD
    df.ta.macd(fast=12, slow=26, signal=9, append=True)

    # Bollinger Bands
    df.ta.bbands(length=20, std=2.0, append=True)

    # ATR
    df.ta.atr(length=14, append=True)

    # Stochastic
    df.ta.stoch(k=14, d=3, smooth_k=3, append=True)

    # ADX
    df.ta.adx(length=14, append=True)

    # VWAP (if datetime index)
    try:
        df.ta.vwap(append=True)
    except Exception:
        df["VWAP_D"] = _manual_vwap(df)

    # Volume SMA
    df["VOL_SMA_20"] = df["volume"].rolling(window=20).mean()

    # Relative Volume
    df["REL_VOL"] = df["volume"] / df["VOL_SMA_20"]

    # Bollinger Band Width
    if "BBU_20_2.0" in df.columns and "BBL_20_2.0" in df.columns and "BBM_20_2.0" in df.columns:
        df["BB_WIDTH"] = (df["BBU_20_2.0"] - df["BBL_20_2.0"]) / df["BBM_20_2.0"]

    return df


def _compute_manual(df: pd.DataFrame) -> pd.DataFrame:
    """Fallback: compute indicators manually with numpy/pandas."""
    # EMAs
    df["EMA_9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["EMA_21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["EMA_55"] = df["close"].ewm(span=55, adjust=False).mean()

    # RSI
    df["RSI_14"] = _manual_rsi(df["close"], 14)

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD_12_26_9"] = ema12 - ema26
    df["MACDs_12_26_9"] = df["MACD_12_26_9"].ewm(span=9, adjust=False).mean()
    df["MACDh_12_26_9"] = df["MACD_12_26_9"] - df["MACDs_12_26_9"]

    # Bollinger Bands
    df["BBM_20_2.0"] = df["close"].rolling(window=20).mean()
    bb_std = df["close"].rolling(window=20).std()
    df["BBU_20_2.0"] = df["BBM_20_2.0"] + 2.0 * bb_std
    df["BBL_20_2.0"] = df["BBM_20_2.0"] - 2.0 * bb_std
    df["BB_WIDTH"] = (df["BBU_20_2.0"] - df["BBL_20_2.0"]) / df["BBM_20_2.0"]

    # ATR
    df["ATRr_14"] = _manual_atr(df, 14)

    # Stochastic
    low14 = df["low"].rolling(window=14).min()
    high14 = df["high"].rolling(window=14).max()
    df["STOCHk_14_3_3"] = 100 * (df["close"] - low14) / (high14 - low14 + 1e-10)
    df["STOCHk_14_3_3"] = df["STOCHk_14_3_3"].rolling(window=3).mean()
    df["STOCHd_14_3_3"] = df["STOCHk_14_3_3"].rolling(window=3).mean()

    # ADX
    df["ADX_14"] = _manual_adx(df, 14)

    # VWAP
    df["VWAP_D"] = _manual_vwap(df)

    # Volume
    df["VOL_SMA_20"] = df["volume"].rolling(window=20).mean()
    df["REL_VOL"] = df["volume"] / df["VOL_SMA_20"]

    return df


def _manual_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))


def _manual_atr(df: pd.DataFrame, period: int) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def _manual_adx(df: pd.DataFrame, period: int) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr = _manual_atr(df, period)

    plus_di = 100 * (plus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / (atr + 1e-10))
    minus_di = 100 * (minus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / (atr + 1e-10))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    return adx


def _manual_vwap(df: pd.DataFrame) -> pd.Series:
    """Calculate intraday VWAP. Resets each day if datetime index."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_vol = df["volume"].cumsum()
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    return cum_tp_vol / (cum_vol + 1e-10)


def find_swing_lows(df: pd.DataFrame, lookback: int = 3) -> pd.Series:
    """Identify swing lows: candles whose low is lower than N candles on both sides."""
    is_swing = pd.Series(False, index=df.index)
    lows = df["low"]
    for i in range(lookback, len(df) - lookback):
        window_left = lows.iloc[i - lookback:i]
        window_right = lows.iloc[i + 1:i + 1 + lookback]
        if lows.iloc[i] < window_left.min() and lows.iloc[i] < window_right.min():
            is_swing.iloc[i] = True
    return is_swing


def find_swing_highs(df: pd.DataFrame, lookback: int = 3) -> pd.Series:
    """Identify swing highs: candles whose high is higher than N candles on both sides."""
    is_swing = pd.Series(False, index=df.index)
    highs = df["high"]
    for i in range(lookback, len(df) - lookback):
        window_left = highs.iloc[i - lookback:i]
        window_right = highs.iloc[i + 1:i + 1 + lookback]
        if highs.iloc[i] > window_left.max() and highs.iloc[i] > window_right.max():
            is_swing.iloc[i] = True
    return is_swing
