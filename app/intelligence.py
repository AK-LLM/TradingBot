from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, asdict
from typing import Any, Dict, List

ACTION_SCALE = ["STRONG_SELL", "SELL", "REDUCE", "HOLD", "BUY", "STRONG_BUY"]

@dataclass
class ActionAdvice:
    action: str
    reason: str
    confidence: float
    trend_stage: str
    confirmation_summary: str
    checks: Dict[str, bool]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TrendIntelligenceEngine:
    def __init__(self, state: Dict[str, Any]):
        self.state = state

    def advise(self, alert: Dict[str, Any]) -> ActionAdvice:
        score = float(alert.get("shark_score", 0.0))
        direction = str(alert.get("direction", "WATCH")).upper()
        metadata = alert.get("metadata", {}) if isinstance(alert.get("metadata"), dict) else {}
        sanity = metadata.get("sanity", {}) if isinstance(metadata.get("sanity"), dict) else {}
        feed_types = metadata.get("feed_types", []) or []
        sources = metadata.get("sources", []) or []
        feed_reliability = self.state.get("feed_reliability", {})
        checks = {
            "two_sources": len(set(sources)) >= int(self.state.get("settings", {}).get("min_independent_sources", 2)),
            "feed_diversity": len(set(feed_types)) >= int(self.state.get("settings", {}).get("min_feed_type_confirmations", 2)),
            "sanity_passed": bool(sanity.get("passed")),
            "feed_reliability": bool(feed_reliability.get("can_generate_trade_advice", True)),
            "score_threshold": score >= float(self.state.get("settings", {}).get("min_shark_score", 70)),
        }
        passed = all(checks.values())
        stage = self._trend_stage(alert)
        if not passed:
            action = "HOLD"
            reason = "Confirmation or sanity gate is incomplete; monitor without opening a new position."
        elif direction in {"BUY", "LONG"}:
            action = "STRONG_BUY" if score >= 84 and stage in {"EMERGING", "CONFIRMED"} else "BUY"
            reason = "Multi-feed confirmation and sanity checks support upside exposure."
        elif direction in {"SELL", "SHORT"}:
            action = "STRONG_SELL" if score >= 84 and stage in {"EMERGING", "CONFIRMED"} else "SELL"
            reason = "Multi-feed confirmation and sanity checks support downside or hedge exposure."
        else:
            action = "HOLD"
            reason = "Direction is not strong enough for a trade recommendation."
        summary = f"{len(set(sources))} source(s), {len(set(feed_types))} feed type(s): {', '.join(sorted(set(feed_types))) or 'none'}"
        return ActionAdvice(action, reason, round(min(99.0, max(0.0, score)), 1), stage, summary, checks)

    def _trend_stage(self, alert: Dict[str, Any]) -> str:
        shock = float(alert.get("shock_score", 0.0))
        fresh = float(alert.get("freshness_score", 0.0))
        confirm = float(alert.get("confirmation_score", 0.0))
        tradable = float(alert.get("tradability_score", 0.0))
        risk = float(alert.get("risk_score", 50.0))
        if fresh < 45 or risk > 78:
            return "EXHAUSTION_OR_NOISE"
        if shock >= 72 and confirm >= 62 and tradable >= 55:
            return "EMERGING"
        if confirm >= 70 and tradable >= 62:
            return "CONFIRMED"
        if confirm >= 55:
            return "FORMING"
        return "WATCH"


def summarize_alert_actions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    engine = TrendIntelligenceEngine(state)
    rows: List[Dict[str, Any]] = []
    for alert in state.get("alerts", []):
        advice = engine.advise(alert).to_dict()
        rows.append({
            "alert_id": alert.get("id"),
            "narrative": alert.get("narrative"),
            "primary_symbol": alert.get("primary_symbol"),
            "direction": alert.get("direction"),
            "shark_score": alert.get("shark_score"),
            **advice,
        })
    return rows
