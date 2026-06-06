"""
target_drift.py — V6.0 portfolio target-allocation drift checker
=================================================================

The Lewis suite's Janet, adapted to STP's Signal contract. Reads:

  config/portfolio_target.json   { "AAPL": 25.0, "MSFT": 25.0, ... }   (target %)
  state["positions"]                                                     (live)

Emits a Signal when any ticker has drifted ≥5 percentage points from target.

Direction semantics for the constellation engine:
  Overweight  (current% > target%)  → SELL  (you should trim)
  Underweight (current% < target%)  → BUY   (you should add)

Confidence scales with drift magnitude. The drift checker emits at most one
signal per scan (the largest drift) to avoid flooding the alert queue.

Wire-in: in platform.py scan_signals(), after collect_all_lewis_feeds:

    from app.target_drift import compute_drift_signal
    drift_sig = compute_drift_signal(self.state)
    if drift_sig:
        signals.append(drift_sig)

That's all. No new state containers required.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

from app.models import Signal, new_id, now_iso


CONFIG_DIR = os.path.join(os.getcwd(), "config")
TARGET_FILE = os.path.join(CONFIG_DIR, "portfolio_target.json")

DRIFT_THRESHOLD_PP = 5.0  # percentage points — only flag at this magnitude or above


def _load_target() -> Dict[str, float]:
    """Read user-declared target allocation. Returns {} if missing or invalid."""
    if not os.path.exists(TARGET_FILE):
        return {}
    try:
        with open(TARGET_FILE) as fp:
            data = json.load(fp)
        # Coerce to {ticker: float_pct} with sensible bounds
        out: Dict[str, float] = {}
        for k, v in data.items():
            try:
                pct = float(v)
                if 0 <= pct <= 100:
                    out[str(k).upper()] = pct
            except (TypeError, ValueError):
                continue
        return out
    except Exception:
        return {}


def _current_allocation(state: Dict[str, Any]) -> Tuple[Dict[str, float], float]:
    """Returns ({ticker: current_pct}, total_equity_usd) from state."""
    positions = state.get("positions", {}) or {}
    cash = float((state.get("settings", {}) or {}).get("cash_balance", 0) or 0)

    market_values: Dict[str, float] = {}
    for pos in positions.values():
        if not isinstance(pos, dict):
            continue
        sym = str(pos.get("symbol", "")).upper()
        if not sym:
            continue
        try:
            qty = float(pos.get("quantity", 0) or 0)
            price = float(pos.get("market_price", 0) or 0)
        except (TypeError, ValueError):
            continue
        if qty == 0 or price == 0:
            continue
        market_values[sym] = market_values.get(sym, 0) + qty * price

    total_equity = sum(market_values.values()) + cash
    if total_equity <= 0:
        return {}, 0.0

    current_pct = {k: 100.0 * v / total_equity for k, v in market_values.items()}
    return current_pct, total_equity


def compute_drift_signal(state: Dict[str, Any]) -> Optional[Signal]:
    """Produce one drift Signal for the largest-magnitude drift breach, else None."""
    target = _load_target()
    if not target:
        return None
    current_pct, total_equity = _current_allocation(state)
    if total_equity <= 0:
        return None

    drifts = []
    for ticker, target_pct in target.items():
        cur = current_pct.get(ticker, 0.0)
        drift_pp = cur - target_pct  # +overweight, -underweight
        if abs(drift_pp) >= DRIFT_THRESHOLD_PP:
            drifts.append((ticker, target_pct, cur, drift_pp))

    if not drifts:
        return None

    # Largest absolute drift wins
    drifts.sort(key=lambda d: abs(d[3]), reverse=True)
    ticker, target_pct, cur_pct, drift_pp = drifts[0]
    direction = "SELL" if drift_pp > 0 else "BUY"
    action_hint = "trim" if drift_pp > 0 else "add"

    # Confidence climbs with drift magnitude: 5pp → 0.55, 25pp+ → 0.95
    confidence = min(0.95, 0.5 + abs(drift_pp) / 50.0)

    description = (
        f"Target {target_pct:.1f}%, current {cur_pct:.1f}% (drift {drift_pp:+.1f}pp). "
        f"Suggested action: {action_hint}."
    )

    return Signal(
        id=new_id("sig"),
        created_at=now_iso(),
        source="target_drift",
        symbol=ticker,
        direction=direction,
        confidence=round(confidence, 2),
        magnitude=abs(drift_pp),
        title=f"Portfolio drift: {ticker} {drift_pp:+.1f}pp from target",
        description=description,
        horizon="position",
        metadata={
            "feed_type": "portfolio_drift",
            "noise_level": "low",
            "narrative": "portfolio_rebalance",
            "target_pct": target_pct,
            "current_pct": cur_pct,
            "drift_pp": drift_pp,
            "action_hint": action_hint,
            "all_drifts": [
                {"ticker": t, "target": tp, "current": cp, "drift_pp": dp}
                for t, tp, cp, dp in drifts
            ],
        },
    )
