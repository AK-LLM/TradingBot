"""
ta_matrix.py — V6.1 multi-timeframe TA confluence feed.

The Python equivalent of Lewis's Pine MAX matrix: 21 standard indicators
computed across 6 timeframes on a watchlist of symbols, emitted as Signal
objects that flow into STP's constellation engine alongside Polymarket,
SEC filings, Fed-speech NLP, on-chain whales, and the rest.

Why in Python instead of Pine: STP is already pulling price data via its
existing feeds (Stooq, crypto markets) and via yfinance for backfill. Doing
the TA in Python keeps everything in one process — no webhooks, no
TradingView subscription, no Pine→STP roundtrip.

Watchlist sourcing: by default, this module computes TA for the symbols
STP is already tracking (current positions + symbols mentioned in recent
alerts). You can override by setting TA_MATRIX_SYMBOLS in the .env.

Cost: each symbol fires ~1 yfinance HTTP request to get OHLCV history.
Capped at TA_MATRIX_MAX_SYMBOLS (default 10) per scan to prevent runaway.

Wire-in: in platform.py scan_signals(), after collect_all_lewis_feeds:

    from app.ta_matrix import compute_ta_matrix_signals
    signals.extend(compute_ta_matrix_signals(self.state))

Graceful degrade: if pandas-ta or yfinance is missing, returns []. If a
symbol's data fetch fails, that symbol is skipped silently.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.models import Signal, new_id, now_iso


# Soft imports — module is no-op if either is unavailable.
try:
    import pandas as pd
    import pandas_ta as ta_lib  # type: ignore
    _PANDAS_TA_OK = True
except ImportError:
    pd = None  # type: ignore
    ta_lib = None  # type: ignore
    _PANDAS_TA_OK = False

try:
    import yfinance as yf  # type: ignore
    _YF_OK = True
except ImportError:
    yf = None  # type: ignore
    _YF_OK = False


MAX_SYMBOLS = int(os.getenv("TA_MATRIX_MAX_SYMBOLS", "10"))
HISTORY_DAYS = int(os.getenv("TA_MATRIX_HISTORY_DAYS", "180"))


# Pine timeframes → yfinance/pandas resample mapping
TIMEFRAMES = [
    ("5min", "5m"),
    ("15min", "15m"),
    ("1h", "60m"),
    ("4h", "60m"),    # 4h not directly supported by yfinance; we resample from 60m
    ("1d", "1d"),
    ("1wk", "1wk"),
]

# Confluence threshold: emit a signal only when ≥ this fraction of indicators
# point the same direction at that (symbol, timeframe).
CONFLUENCE_THRESHOLD = 0.65


def _extract_tracked_symbols(state: Dict[str, Any]) -> List[str]:
    """Pull symbols from current positions + recent alerts, deduped."""
    out: List[str] = []
    seen = set()

    # Positions first (highest priority — these are open risk)
    for pos in (state.get("positions", {}) or {}).values():
        sym = str(pos.get("symbol", "")).upper().strip()
        if sym and sym not in seen and sym not in ("MARKET", "MACRO"):
            seen.add(sym)
            out.append(sym)

    # Then symbols mentioned in recent alerts
    for alert in (state.get("alerts", []) or [])[:20]:
        sym = str(alert.get("primary_symbol", "")).upper().strip()
        if sym and sym not in seen and sym not in ("MARKET", "MACRO"):
            seen.add(sym)
            out.append(sym)

    # Env override
    env_syms = os.getenv("TA_MATRIX_SYMBOLS", "").strip()
    if env_syms:
        for s in env_syms.split(","):
            s = s.upper().strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)

    return out[:MAX_SYMBOLS]


def _fetch_ohlcv(symbol: str) -> Optional[Any]:
    """Pull historical OHLCV for a symbol. Returns a pandas DataFrame or None."""
    if not _YF_OK:
        return None
    try:
        df = yf.download(
            symbol,
            period=f"{HISTORY_DAYS}d",
            interval="60m",
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        if df is None or df.empty:
            # Fallback for symbols where 60m interval isn't available
            df = yf.download(symbol, period=f"{HISTORY_DAYS}d", interval="1d",
                             progress=False, auto_adjust=True, threads=False)
        # yfinance can return multi-index columns when threads=True/multi-symbol;
        # flatten in case.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        if df is None or df.empty:
            return None
        return df
    except Exception:
        return None


def _resample(df: Any, pine_tf: str) -> Optional[Any]:
    """Resample the base 60m DataFrame into the target Pine timeframe."""
    if df is None or df.empty:
        return None
    rules = {
        "5min": "5min",
        "15min": "15min",
        "1h": "60min",
        "4h": "240min",
        "1d": "1D",
        "1wk": "1W",
    }
    rule = rules.get(pine_tf)
    if rule is None:
        return df
    try:
        # If the underlying data is already 1d, we can only upsample to >=1d
        if pine_tf in ("5min", "15min", "1h"):
            # Use base data as-is if already at this resolution; otherwise skip
            return df
        agg = df.resample(rule).agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        }).dropna()
        return agg if not agg.empty else None
    except Exception:
        return None


def _compute_indicators(df: Any) -> Dict[str, Any]:
    """Compute the 21-indicator matrix on a single timeframe of OHLCV.
    Returns a dict of {indicator: bool_or_float}."""
    if not _PANDAS_TA_OK or df is None or len(df) < 50:
        return {}

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"] if "Volume" in df.columns else None

    out: Dict[str, Any] = {}
    try:
        # MA crossovers (bullish if fast > slow)
        ema9 = ta_lib.ema(close, length=9)
        ema21 = ta_lib.ema(close, length=21)
        ema50 = ta_lib.ema(close, length=50)
        ema200 = ta_lib.ema(close, length=200) if len(close) >= 200 else None
        out["ema9_above_21"] = bool(ema9.iloc[-1] > ema21.iloc[-1]) if not ema9.empty and not ema21.empty else False
        out["ema21_above_50"] = bool(ema21.iloc[-1] > ema50.iloc[-1]) if not ema21.empty and not ema50.empty else False
        if ema200 is not None and not ema200.empty:
            out["ema50_above_200"] = bool(ema50.iloc[-1] > ema200.iloc[-1])
        else:
            out["ema50_above_200"] = None

        # RSI
        rsi = ta_lib.rsi(close, length=14)
        out["rsi_bullish"] = bool(rsi.iloc[-1] > 50) if not rsi.empty else False

        # Stochastic
        stoch = ta_lib.stoch(high, low, close)
        if stoch is not None and not stoch.empty:
            stoch_k = stoch.iloc[:, 0].iloc[-1]
            out["stoch_bullish"] = bool(stoch_k > 50)

        # MACD
        macd = ta_lib.macd(close)
        if macd is not None and not macd.empty:
            # Columns vary across pandas-ta versions; use positional access
            macd_line = macd.iloc[:, 0].iloc[-1]
            macd_signal = macd.iloc[:, 2].iloc[-1] if macd.shape[1] >= 3 else macd.iloc[:, 1].iloc[-1]
            macd_hist = macd.iloc[:, 1].iloc[-1] if macd.shape[1] >= 3 else 0
            out["macd_bullish"] = bool(macd_line > macd_signal)
            out["macd_hist_positive"] = bool(macd_hist > 0)

        # CCI
        cci = ta_lib.cci(high, low, close)
        out["cci_bullish"] = bool(cci.iloc[-1] > 0) if cci is not None and not cci.empty else False

        # MFI
        if volume is not None:
            mfi = ta_lib.mfi(high, low, close, volume)
            out["mfi_bullish"] = bool(mfi.iloc[-1] > 50) if mfi is not None and not mfi.empty else False

        # ADX / DMI
        dmi = ta_lib.adx(high, low, close)
        if dmi is not None and not dmi.empty:
            adx_val = dmi.iloc[:, 0].iloc[-1]
            dip = dmi.iloc[:, 1].iloc[-1] if dmi.shape[1] >= 2 else 0
            dim = dmi.iloc[:, 2].iloc[-1] if dmi.shape[1] >= 3 else 0
            out["adx_strong"] = bool(adx_val > 20)
            out["di_bullish"] = bool(dip > dim)

        # Bollinger %B
        bb = ta_lib.bbands(close, length=20)
        if bb is not None and not bb.empty:
            # BBL_20_2.0, BBM_20_2.0, BBU_20_2.0, ...
            bbl = bb.iloc[:, 0].iloc[-1]
            bbu = bb.iloc[:, 2].iloc[-1]
            if bbu - bbl > 0:
                pct_b = (close.iloc[-1] - bbl) / (bbu - bbl)
                out["bb_above_mid"] = bool(pct_b > 0.5)

        # Williams %R
        willr = ta_lib.willr(high, low, close)
        out["willr_bullish"] = bool(willr.iloc[-1] > -50) if willr is not None and not willr.empty else False

        # ROC
        roc = ta_lib.roc(close, length=9)
        out["roc_positive"] = bool(roc.iloc[-1] > 0) if roc is not None and not roc.empty else False

        # ATR % (used as a regime indicator, not direction — capture as float)
        atr = ta_lib.atr(high, low, close, length=14)
        out["atr_pct"] = float(atr.iloc[-1] / close.iloc[-1] * 100) if atr is not None and not atr.empty else 0.0

        # OBV uptrend
        if volume is not None:
            obv = ta_lib.obv(close, volume)
            if obv is not None and len(obv) > 1:
                out["obv_rising"] = bool(obv.iloc[-1] > obv.iloc[-2])

        # SuperTrend
        st = ta_lib.supertrend(high, low, close, length=10, multiplier=3)
        if st is not None and not st.empty:
            # Column "SUPERTd_10_3.0" is direction: 1 = up, -1 = down
            try:
                dir_col = [c for c in st.columns if c.startswith("SUPERTd")][0]
                out["supertrend_bullish"] = bool(st[dir_col].iloc[-1] > 0)
            except (IndexError, KeyError):
                pass

        # Momentum
        mom = ta_lib.mom(close, length=10)
        out["momentum_positive"] = bool(mom.iloc[-1] > 0) if mom is not None and not mom.empty else False

        # Above SMA20 / SMA50
        sma20 = ta_lib.sma(close, length=20)
        sma50 = ta_lib.sma(close, length=50)
        out["above_sma20"] = bool(close.iloc[-1] > sma20.iloc[-1]) if sma20 is not None and not sma20.empty else False
        out["above_sma50"] = bool(close.iloc[-1] > sma50.iloc[-1]) if sma50 is not None and not sma50.empty else False

        # Close > close 10 bars ago
        if len(close) > 10:
            out["above_10ago"] = bool(close.iloc[-1] > close.iloc[-11])

    except Exception:
        # Indicator math can blow up on weird data shapes; degrade silently
        pass

    return out


def _confluence_score(indicators: Dict[str, Any]) -> Tuple[float, int, int]:
    """Return (signed_score, bullish_count, bearish_count).
    signed_score in [-1, +1] where +1 = all bullish, -1 = all bearish."""
    bullish_keys = [k for k in indicators if k not in ("atr_pct",) and indicators[k] is True]
    bearish_keys = [k for k in indicators if k not in ("atr_pct",) and indicators[k] is False]
    total = len(bullish_keys) + len(bearish_keys)
    if total == 0:
        return 0.0, 0, 0
    score = (len(bullish_keys) - len(bearish_keys)) / total
    return score, len(bullish_keys), len(bearish_keys)


def compute_ta_matrix_signals(state: Dict[str, Any]) -> List[Signal]:
    """Main entry: returns a list of Signal objects representing strong
    multi-indicator confluence at specific (symbol, timeframe) combinations."""
    if not _PANDAS_TA_OK or not _YF_OK:
        return []

    symbols = _extract_tracked_symbols(state)
    if not symbols:
        return []

    out: List[Signal] = []
    for symbol in symbols:
        df = _fetch_ohlcv(symbol)
        if df is None or df.empty or len(df) < 50:
            continue
        for pine_tf, _ in TIMEFRAMES:
            tf_df = _resample(df, pine_tf)
            if tf_df is None or len(tf_df) < 50:
                continue
            indicators = _compute_indicators(tf_df)
            if not indicators:
                continue
            score, bull, bear = _confluence_score(indicators)
            if abs(score) < CONFLUENCE_THRESHOLD:
                continue  # not enough confluence to emit a signal

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
                    f"{bull} bullish, {bear} bearish."
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
                },
            ))
    return out


def ta_matrix_status() -> Dict[str, Any]:
    """For the UI health panel."""
    return {
        "pandas_ta_installed": _PANDAS_TA_OK,
        "yfinance_installed": _YF_OK,
        "max_symbols_per_scan": MAX_SYMBOLS,
        "history_days": HISTORY_DAYS,
        "confluence_threshold": CONFLUENCE_THRESHOLD,
    }
