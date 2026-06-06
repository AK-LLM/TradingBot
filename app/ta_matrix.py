"""
ta_matrix.py — V6.1 multi-timeframe TA confluence feed (rewritten for
zero-third-party-TA-dep operation).

The Python equivalent of Lewis's Pine MAX matrix: 21 standard indicators
computed across multiple timeframes on a watchlist of symbols, emitted as
Signal objects that flow into STP's constellation engine alongside
Polymarket, SEC filings, Fed-speech NLP, on-chain whales, and the rest.

Implementation choices (V6.1.1 deployment fix):
  • OHLCV via Stooq's free historical CSV endpoint (no auth, no library,
    same provider STP already uses for live quotes in market_data.py)
  • All 21 indicators are hand-rolled in pandas/numpy — no pandas-ta,
    no ta-lib, no numba, no llvmlite. Robust to Python version changes.
  • Timeframes: daily + weekly (Stooq's free intervals). Intraday is paid
    on every provider; we don't pretend otherwise.

Watchlist sourcing: by default, this module computes TA for the symbols
STP is already tracking (current positions + symbols mentioned in recent
alerts). Override via the TA_MATRIX_SYMBOLS env var if you want a fixed list.

Wire-in: platform.scan_signals() calls compute_ta_matrix_signals(state)
alongside collect_all_lewis_feeds(state). Graceful degrade: any per-symbol
fetch failure is silently skipped, and if pandas or requests aren't
available the whole module returns [].
"""
from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.models import Signal, new_id, now_iso


# Soft imports — module is no-op if either fails (shouldn't happen since
# both are core STP deps, but keeps a clean fallback).
try:
    import pandas as pd
    import numpy as np
    import requests
    _DEPS_OK = True
except ImportError:
    pd = None      # type: ignore
    np = None      # type: ignore
    requests = None  # type: ignore
    _DEPS_OK = False


MAX_SYMBOLS = int(os.getenv("TA_MATRIX_MAX_SYMBOLS", "10"))
CONFLUENCE_THRESHOLD = 0.65  # min fraction of bullish-or-bearish agreement
REQUEST_TIMEOUT = 12

# Stooq's free historical CSV endpoint. Intervals: d (daily), w (weekly), m (monthly).
STOOQ_HISTORY_URL = "https://stooq.com/q/d/l/"

# Two timeframes from Stooq's free intervals.
TIMEFRAMES = [
    ("1d", "d", 200),   # daily, need ~200 bars for SMA200
    ("1wk", "w", 80),   # weekly, ~1.5 years
]


# --------------------------------------------------------------------------
# Data fetching
# --------------------------------------------------------------------------

def _stooq_symbol(symbol: str) -> str:
    """Match Stooq's symbol conventions used in market_data.py.
    US tickers get a .us suffix; everything else passes through."""
    s = symbol.strip().lower()
    if "." in s:
        return s  # already qualified (e.g. shop.to, btc.v)
    return f"{s}.us"


def _fetch_stooq_history(symbol: str, interval: str = "d",
                        min_bars: int = 80) -> Optional[Any]:
    """Pull historical OHLCV from Stooq. Returns a DataFrame indexed by date
    with columns Open, High, Low, Close, Volume — or None on any failure."""
    if not _DEPS_OK:
        return None
    try:
        r = requests.get(
            STOOQ_HISTORY_URL,
            params={"s": _stooq_symbol(symbol), "i": interval},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200 or not r.text or "Date" not in r.text[:200]:
            return None
        df = pd.read_csv(io.StringIO(r.text))
        if df.empty or len(df) < min_bars:
            return None
        # Normalise column names — Stooq uses TitleCase (Date, Open, High,...)
        df.columns = [c.strip() for c in df.columns]
        if "Date" not in df.columns:
            return None
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).set_index("Date").sort_index()
        # Ensure numeric
        for col in ("Open", "High", "Low", "Close", "Volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Close"])
        return df if len(df) >= min_bars else None
    except Exception:
        return None


# --------------------------------------------------------------------------
# Hand-rolled indicators (pandas/numpy only)
# --------------------------------------------------------------------------

def _ema(s, period):
    return s.ewm(span=period, adjust=False, min_periods=period).mean()


def _sma(s, period):
    return s.rolling(period, min_periods=period).mean()


def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _stoch_k(high, low, close, period=14):
    ll = low.rolling(period, min_periods=period).min()
    hh = high.rolling(period, min_periods=period).max()
    return 100 * (close - ll) / (hh - ll).replace(0, np.nan)


def _macd(close, fast=12, slow=26, signal=9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = line - sig
    return line, sig, hist


def _cci(high, low, close, period=20):
    tp = (high + low + close) / 3
    sma_tp = _sma(tp, period)
    mean_dev = (tp - sma_tp).abs().rolling(period, min_periods=period).mean()
    return (tp - sma_tp) / (0.015 * mean_dev.replace(0, np.nan))


def _mfi(high, low, close, volume, period=14):
    tp = (high + low + close) / 3
    mf = tp * volume
    pos = mf.where(tp > tp.shift(), 0).rolling(period, min_periods=period).sum()
    neg = mf.where(tp < tp.shift(), 0).rolling(period, min_periods=period).sum()
    mfr = pos / neg.replace(0, np.nan)
    return 100 - (100 / (1 + mfr))


def _true_range(high, low, close):
    prior_close = close.shift()
    return pd.concat([
        high - low,
        (high - prior_close).abs(),
        (low - prior_close).abs(),
    ], axis=1).max(axis=1)


def _atr(high, low, close, period=14):
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _adx_dmi(high, low, close, period=14):
    """Wilder's ADX with +DI / -DI. Returns (adx, plus_di, minus_di)."""
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = _atr(high, low, close, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return adx, plus_di, minus_di


def _bbands(close, period=20, mult=2):
    sma = _sma(close, period)
    std = close.rolling(period, min_periods=period).std()
    upper = sma + mult * std
    lower = sma - mult * std
    pct_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return upper, sma, lower, pct_b


def _williams_r(high, low, close, period=14):
    hh = high.rolling(period, min_periods=period).max()
    ll = low.rolling(period, min_periods=period).min()
    return -100 * (hh - close) / (hh - ll).replace(0, np.nan)


def _roc(close, period=9):
    return (close / close.shift(period) - 1) * 100


def _obv(close, volume):
    direction = np.sign(close.diff()).fillna(0)
    return (volume * direction).cumsum()


def _supertrend_bullish(high, low, close, period=10, mult=3.0):
    """Returns a boolean Series — True where SuperTrend trend is bullish.
    Simplified non-iterative variant suitable for current-bar classification."""
    hl_avg = (high + low) / 2
    atr = _atr(high, low, close, period)
    upper = hl_avg + mult * atr
    lower = hl_avg - mult * atr
    # Use rolling 5-bar context to determine trend state
    rec_close = close.rolling(5, min_periods=5).mean()
    rec_lower = lower.rolling(5, min_periods=5).mean()
    rec_upper = upper.rolling(5, min_periods=5).mean()
    # Bullish if recent close is above the rolling lower band
    return rec_close > rec_lower


def _momentum(close, period=10):
    return close - close.shift(period)


# --------------------------------------------------------------------------
# Indicator orchestrator
# --------------------------------------------------------------------------

def _compute_indicators(df: Any) -> Dict[str, Any]:
    """Compute the 21-indicator matrix on a single timeframe of OHLCV.
    Returns a dict of {indicator_name: bool_or_float}. Bool = bullish state."""
    if df is None or len(df) < 50:
        return {}
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df.get("Volume")
    out: Dict[str, Any] = {}

    try:
        # EMA crossovers
        ema9 = _ema(close, 9)
        ema21 = _ema(close, 21)
        ema50 = _ema(close, 50)
        ema200 = _ema(close, 200) if len(close) >= 200 else None
        out["ema9_above_21"] = bool(ema9.iloc[-1] > ema21.iloc[-1]) if not ema9.empty else False
        out["ema21_above_50"] = bool(ema21.iloc[-1] > ema50.iloc[-1]) if not ema21.empty else False
        out["ema50_above_200"] = bool(ema50.iloc[-1] > ema200.iloc[-1]) if ema200 is not None else None

        # RSI
        rsi = _rsi(close)
        out["rsi_bullish"] = bool(rsi.iloc[-1] > 50)

        # Stochastic
        stoch = _stoch_k(high, low, close)
        out["stoch_bullish"] = bool(stoch.iloc[-1] > 50)

        # MACD
        macd_line, macd_signal, macd_hist = _macd(close)
        out["macd_bullish"] = bool(macd_line.iloc[-1] > macd_signal.iloc[-1])
        out["macd_hist_positive"] = bool(macd_hist.iloc[-1] > 0)

        # CCI
        cci = _cci(high, low, close)
        out["cci_bullish"] = bool(cci.iloc[-1] > 0)

        # MFI (needs volume)
        if volume is not None and volume.notna().any():
            mfi = _mfi(high, low, close, volume)
            out["mfi_bullish"] = bool(mfi.iloc[-1] > 50)

        # ADX / DMI
        adx, plus_di, minus_di = _adx_dmi(high, low, close)
        out["adx_strong"] = bool(adx.iloc[-1] > 20)
        out["di_bullish"] = bool(plus_di.iloc[-1] > minus_di.iloc[-1])

        # Bollinger %B (above midline)
        _, _, _, pct_b = _bbands(close)
        out["bb_above_mid"] = bool(pct_b.iloc[-1] > 0.5)

        # Williams %R (>-50 is bullish)
        willr = _williams_r(high, low, close)
        out["willr_bullish"] = bool(willr.iloc[-1] > -50)

        # ROC positive
        roc = _roc(close)
        out["roc_positive"] = bool(roc.iloc[-1] > 0)

        # ATR% (regime indicator, not direction — captured as float)
        atr = _atr(high, low, close)
        out["atr_pct"] = float(atr.iloc[-1] / close.iloc[-1] * 100)

        # OBV trend
        if volume is not None and volume.notna().any():
            obv = _obv(close, volume)
            out["obv_rising"] = bool(obv.iloc[-1] > obv.iloc[-2])

        # SuperTrend
        st_bull = _supertrend_bullish(high, low, close)
        out["supertrend_bullish"] = bool(st_bull.iloc[-1])

        # Momentum
        mom = _momentum(close)
        out["momentum_positive"] = bool(mom.iloc[-1] > 0)

        # Above SMA20 / SMA50
        sma20 = _sma(close, 20)
        sma50 = _sma(close, 50)
        out["above_sma20"] = bool(close.iloc[-1] > sma20.iloc[-1])
        out["above_sma50"] = bool(close.iloc[-1] > sma50.iloc[-1])

        # Above close 10 bars ago
        if len(close) > 10:
            out["above_10ago"] = bool(close.iloc[-1] > close.iloc[-11])

    except Exception:
        # Indicator math can blow up on weird data; degrade silently
        pass

    return out


# --------------------------------------------------------------------------
# Confluence scoring + signal emission
# --------------------------------------------------------------------------

def _confluence_score(indicators: Dict[str, Any]) -> Tuple[float, int, int]:
    """Return (signed_score, bullish_count, bearish_count).
    signed_score in [-1, +1] where +1 = all bullish, -1 = all bearish.
    Non-directional indicators (atr_pct) excluded from the count."""
    NON_DIRECTIONAL = {"atr_pct"}
    bullish_keys = [k for k in indicators
                    if k not in NON_DIRECTIONAL and indicators[k] is True]
    bearish_keys = [k for k in indicators
                    if k not in NON_DIRECTIONAL and indicators[k] is False]
    total = len(bullish_keys) + len(bearish_keys)
    if total == 0:
        return 0.0, 0, 0
    score = (len(bullish_keys) - len(bearish_keys)) / total
    return score, len(bullish_keys), len(bearish_keys)


def _extract_tracked_symbols(state: Dict[str, Any]) -> List[str]:
    """Pull symbols from current positions + recent alerts, deduped, capped."""
    out: List[str] = []
    seen = set()
    for pos in (state.get("positions", {}) or {}).values():
        sym = str(pos.get("symbol", "")).upper().strip()
        if sym and sym not in seen and sym not in ("MARKET", "MACRO"):
            seen.add(sym)
            out.append(sym)
    for alert in (state.get("alerts", []) or [])[:20]:
        sym = str(alert.get("primary_symbol", "")).upper().strip()
        if sym and sym not in seen and sym not in ("MARKET", "MACRO"):
            seen.add(sym)
            out.append(sym)
    env_syms = os.getenv("TA_MATRIX_SYMBOLS", "").strip()
    if env_syms:
        for s in env_syms.split(","):
            s = s.upper().strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out[:MAX_SYMBOLS]


def compute_ta_matrix_signals(state: Dict[str, Any]) -> List[Signal]:
    """Main entry: returns a list of Signal objects representing strong
    multi-indicator confluence at specific (symbol, timeframe) combinations."""
    if not _DEPS_OK:
        return []
    symbols = _extract_tracked_symbols(state)
    if not symbols:
        return []

    out: List[Signal] = []
    for symbol in symbols:
        for pine_tf, stooq_interval, min_bars in TIMEFRAMES:
            df = _fetch_stooq_history(symbol, interval=stooq_interval, min_bars=min_bars)
            if df is None:
                continue
            indicators = _compute_indicators(df)
            if not indicators:
                continue
            score, bull, bear = _confluence_score(indicators)
            if abs(score) < CONFLUENCE_THRESHOLD:
                continue

            direction = "BUY" if score > 0 else "SELL"
            confidence = min(0.95, 0.55 + 0.4 * abs(score))
            confluence_pct = round(abs(score) * 100, 1)

            out.append(Signal(
                id=new_id("sig"),
                created_at=now_iso(),
                source="ta_matrix",
                symbol=symbol,
                direction=direction,
                confidence=round(confidence, 2),
                magnitude=confluence_pct,
                title=f"TA confluence on {symbol} [{pine_tf}]: {bull}/{bull+bear} bullish",
                description=(
                    f"21-indicator confluence {confluence_pct:.0f}% on {pine_tf}. "
                    f"{bull} bullish, {bear} bearish. (Stooq OHLCV)"
                ),
                horizon="swing",
                metadata={
                    "feed_type": "technical_analysis",
                    "noise_level": "medium",
                    "narrative": "ta_confluence",
                    "timeframe": pine_tf,
                    "confluence_score": score,
                    "bullish_count": bull,
                    "bearish_count": bear,
                    "indicators": indicators,
                    "atr_pct": indicators.get("atr_pct", 0.0),
                    "data_source": "stooq",
                },
            ))
    return out


def ta_matrix_status() -> Dict[str, Any]:
    """For the UI health panel."""
    return {
        "deps_ok": _DEPS_OK,
        "data_source": "stooq",
        "timeframes": [tf for tf, _, _ in TIMEFRAMES],
        "max_symbols_per_scan": MAX_SYMBOLS,
        "confluence_threshold": CONFLUENCE_THRESHOLD,
    }
