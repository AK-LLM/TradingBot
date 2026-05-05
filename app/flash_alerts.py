from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Set
from app.models import new_id, now_iso

ACTION_RANK = {
    "STRONG_SELL": 5,
    "SELL": 4,
    "REDUCE": 4,    # V5.6: REDUCE is now a real, directional action — eligible for flash alerts
    "HOLD": 0,
    "BUY": 4,
    "STRONG_BUY": 5,
}

@dataclass
class FlashAlert:
    id: str
    created_at: str
    alert_id: str
    narrative: str
    action: str
    confidence: float
    shark_score: float
    primary_symbol: str
    direction: str
    trend_stage: str
    reasons: List[str]
    acknowledged: bool = False
    acknowledged_at: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


class FlashAlertEngine:
    """Promotes only high-grade, confirmed anomalies into interruptive alerts.

    This module deliberately does not create trades. It only surfaces alerts that
    already passed confirmation, feed-diversity, sanity, freshness and score gates.
    """
    def __init__(self, state: Dict[str, Any]):
        self.state = state
        self.settings = state.get("settings", {})

    def evaluate(self) -> List[Dict[str, Any]]:
        active = self._current_active()
        active_by_alert: Set[str] = {a.get("alert_id", "") for a in active if not a.get("acknowledged")}
        recent_keys = self._recent_keys()
        new_items: List[Dict[str, Any]] = []
        for alert in self.state.get("alerts", []):
            candidate = self._candidate(alert)
            if not candidate["ok"]:
                continue
            alert_id = alert.get("id")
            key = f"{alert.get('narrative')}|{alert.get('primary_symbol')}|{candidate['action']}"
            if alert_id in active_by_alert or key in recent_keys:
                continue
            item = FlashAlert(
                id=new_id("flash"),
                created_at=now_iso(),
                alert_id=alert_id,
                narrative=str(alert.get("narrative", "Unknown")),
                action=candidate["action"],
                confidence=float(candidate["confidence"]),
                shark_score=float(alert.get("shark_score", 0.0)),
                primary_symbol=str(alert.get("primary_symbol", "")),
                direction=str(alert.get("direction", "")),
                trend_stage=candidate["trend_stage"],
                reasons=candidate["reasons"],
            ).to_dict()
            item["dedupe_key"] = key
            new_items.append(item)
        if new_items:
            self.state.setdefault("active_flash_alerts", []).extend(new_items)
            self.state.setdefault("flash_history", []).extend(new_items)
            self.state.setdefault("journal", []).append({
                "ts": now_iso(),
                "event": "flash_alert_created",
                "count": len(new_items),
                "alerts": [x["narrative"] for x in new_items],
            })
        # Keep active list bounded and remove old acknowledged items.
        self.state["active_flash_alerts"] = self._trim_active(self.state.get("active_flash_alerts", []))
        self.state["flash_history"] = self.state.get("flash_history", [])[-500:]
        return new_items

    def acknowledge(self, flash_id: str) -> bool:
        changed = False
        for row in self.state.get("active_flash_alerts", []):
            if row.get("id") == flash_id:
                row["acknowledged"] = True
                row["acknowledged_at"] = now_iso()
                changed = True
        if changed:
            self.state.setdefault("journal", []).append({"ts": now_iso(), "event": "flash_alert_acknowledged", "flash_id": flash_id})
        return changed

    def _candidate(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        meta = alert.get("metadata", {}) if isinstance(alert.get("metadata"), dict) else {}
        advice = meta.get("advice", {}) if isinstance(meta.get("advice"), dict) else {}
        sanity = meta.get("sanity", {}) if isinstance(meta.get("sanity"), dict) else {}
        feed_reliability = self.state.get("feed_reliability", {})
        action = str(advice.get("action") or alert.get("action") or "HOLD").upper()
        trend_stage = str(advice.get("trend_stage", "WATCH")).upper()
        score = float(alert.get("shark_score", 0.0))
        confidence = float(advice.get("confidence", score))
        min_score = float(self.settings.get("flash_min_score", 82))
        min_conf = float(self.settings.get("flash_min_confidence", 78))
        allowed_stages = set(self.settings.get("flash_allowed_trend_stages", ["EMERGING", "CONFIRMED"]))
        reasons: List[str] = []
        checks = {
            "status_shark": alert.get("status") == "SHARK",
            "action_is_directional": ACTION_RANK.get(action, 0) >= 4,
            "score": score >= min_score,
            "confidence": confidence >= min_conf,
            "sanity": bool(sanity.get("passed")),
            "feed_reliability": bool(feed_reliability.get("can_generate_trade_advice", True)),
            "stage": trend_stage in allowed_stages,
        }
        if checks["status_shark"]: reasons.append("SHARK-grade anomaly")
        if checks["action_is_directional"]: reasons.append(f"Action is {action}")
        if checks["score"]: reasons.append(f"Score {score:.1f} >= {min_score:.1f}")
        if checks["confidence"]: reasons.append(f"Confidence {confidence:.1f} >= {min_conf:.1f}")
        if checks["sanity"]: reasons.append("Sanity checks passed")
        if checks["feed_reliability"]: reasons.append("Feed reliability permits advice")
        if checks["stage"]: reasons.append(f"Trend stage {trend_stage}")
        return {"ok": all(checks.values()), "checks": checks, "action": action, "confidence": confidence, "trend_stage": trend_stage, "reasons": reasons}

    def _current_active(self) -> List[Dict[str, Any]]:
        return list(self.state.get("active_flash_alerts", []))

    def _recent_keys(self) -> Set[str]:
        cooldown = int(self.settings.get("flash_cooldown_minutes", 20))
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown)
        keys: Set[str] = set()
        for row in self.state.get("flash_history", []):
            ts = _parse_iso(row.get("created_at"))
            if ts and ts >= cutoff:
                keys.add(row.get("dedupe_key") or f"{row.get('narrative')}|{row.get('primary_symbol')}|{row.get('action')}")
        return keys

    def _trim_active(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ttl = int(self.settings.get("flash_active_ttl_minutes", 180))
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl)
        kept = []
        for row in rows[-100:]:
            ts = _parse_iso(row.get("created_at"))
            if row.get("acknowledged") and ts and ts < cutoff:
                continue
            kept.append(row)
        return kept
