from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Set

LIVE_STATUSES = {"live"}
# These statuses are visible in Feed Health but are not treated as hard failures.
# They should not poison readiness when the suite has enough other live categories.
DEGRADED_STATUSES = {"empty", "credential_pending", "access_limited", "geo_blocked", "not_supported"}
BLOCKING_STATUSES = {"error"}

FEED_TYPE_FALLBACKS: Dict[str, List[str]] = {
    "prediction_market": ["polymarket", "kalshi", "predictit", "manifold"],
    "forecasting": ["metaculus"],
    "news": ["news_rss"],
    "market_data": ["stooq_market"],
    "crypto_market_data": ["crypto_market", "binance_crypto"],
    "filings": ["sec_filings"],
    "positioning": ["cftc_cot"],
    "options": ["options_flow"],
}

@dataclass
class FeedReliabilityReport:
    system_status: str
    active_feeds: int
    active_feed_types: int
    required_active_feeds: int
    required_feed_types: int
    reliability_score: float
    can_generate_trade_advice: bool
    messages: List[str]
    feed_type_status: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def feed_key_from_health_name(feed_name: str) -> str:
    normalized = feed_name.lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "polymarket": "polymarket",
        "predictit": "predictit",
        "manifold": "manifold",
        "metaculus": "metaculus",
        "kalshi": "kalshi",
        "sec_filings": "sec_filings",
        "cftc_cot": "cftc_cot",
        "news_rss": "news_rss",
        "stooq_market_pulse": "stooq_market",
        "binance_crypto_pulse": "binance_crypto",
        "crypto_market_pulse": "crypto_market",
        "options_flow": "options_flow",
    }
    return aliases.get(normalized, normalized)


class FeedReliabilityEngine:
    def __init__(self, state: Dict[str, Any]):
        self.state = state

    def evaluate(self) -> FeedReliabilityReport:
        settings = self.state.get("settings", {})
        required_active = int(settings.get("minimum_live_feeds_required", 4))
        required_types = int(settings.get("minimum_feed_types_required", 3))
        health = self.state.get("feed_health", [])
        active = [h for h in health if h.get("status") in LIVE_STATUSES]
        degraded = [h for h in health if h.get("status") in DEGRADED_STATUSES]
        failed = [h for h in health if h.get("status") in BLOCKING_STATUSES]
        active_keys: Set[str] = {feed_key_from_health_name(str(h.get("feed", ""))) for h in active}
        active_types: Set[str] = set()
        feed_type_status: Dict[str, str] = {}
        for feed_type, keys in FEED_TYPE_FALLBACKS.items():
            has_live = any(k in active_keys for k in keys)
            has_any = any(feed_key_from_health_name(str(h.get("feed", ""))) in keys for h in health)
            if has_live:
                feed_type_status[feed_type] = "live"
                active_types.add(feed_type)
            elif has_any:
                feed_type_status[feed_type] = "unavailable"
            else:
                feed_type_status[feed_type] = "not_checked"
        total_checked = max(1, len(health))
        reliability = max(0.0, min(100.0, (len(active) * 100.0 + len(degraded) * 45.0) / total_checked))
        messages: List[str] = []
        if len(active) < required_active:
            messages.append(f"Only {len(active)} live feeds available; minimum is {required_active}.")
        if len(active_types) < required_types:
            messages.append(f"Only {len(active_types)} live feed types available; minimum is {required_types}.")
        if failed:
            messages.append(f"{len(failed)} feed(s) failed with runtime errors.")
        non_live = [h for h in health if h.get("status") in DEGRADED_STATUSES]
        if non_live:
            messages.append(f"{len(non_live)} feed(s) are non-live but non-blocking: credential/access/geo/empty.")
        can_advise = len(active) >= required_active and len(active_types) >= required_types
        status = "LIVE_READY" if can_advise and reliability >= 70 else "SAFE_MODE"
        report = FeedReliabilityReport(status, len(active), len(active_types), required_active, required_types, round(reliability, 1), can_advise, messages, feed_type_status)
        self.state["feed_reliability"] = report.to_dict() | {"ts": _now()}
        return report

    def filter_usable_signals(self, signals: List[Any]) -> List[Any]:
        report = self.evaluate()
        if report.can_generate_trade_advice:
            return signals
        # Safe mode still allows monitoring alerts, but no trade candidate status will be emitted.
        return signals
