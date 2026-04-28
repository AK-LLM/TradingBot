from __future__ import annotations
from typing import List, Dict, Any, Set
from collections import defaultdict, Counter
import statistics
from app.models import Signal, Alert, new_id, now_iso
from app.instrument_map import classify_narrative, map_instruments
from app.market_data import MarketDataService, MarketDataError
from app.feed_reliability import FeedReliabilityEngine
from app.intelligence import TrendIntelligenceEngine

class SharkEngine:
    def __init__(self, state: Dict[str, Any]):
        self.state = state
        self.market = MarketDataService(state)
        self.feed_reliability = FeedReliabilityEngine(state)
        self.intelligence = TrendIntelligenceEngine(state)

    def build_alerts(self, signals: List[Signal]) -> List[Alert]:
        reliability = self.feed_reliability.evaluate()
        buckets: Dict[str, List[Signal]] = defaultdict(list)
        for s in signals:
            narrative = s.metadata.get("narrative") or classify_narrative(f"{s.title} {s.description}", s.symbol)
            buckets[narrative].append(s)
        alerts: List[Alert] = []
        for narrative, rows in buckets.items():
            if not rows:
                continue
            dirs = Counter([r.direction.upper() for r in rows if r.direction.upper() != "WATCH"] or [r.direction.upper() for r in rows])
            direction = dirs.most_common(1)[0][0]
            primary = Counter([r.symbol.upper() for r in rows]).most_common(1)[0][0]
            sources = set(r.source for r in rows)
            feed_types = set(r.metadata.get("feed_type", "unknown") for r in rows)
            confs = [float(r.confidence) for r in rows]
            moves = [float(r.metadata.get("probability_change_pct", r.magnitude or 0.0)) for r in rows]
            vols = [float(r.metadata.get("volume_zscore", 1.0)) for r in rows]
            fresh = [float(r.metadata.get("freshness_minutes", 999.0)) for r in rows]
            shock = min(100.0, statistics.mean(moves) * 4.0 + statistics.mean(vols) * 10.0 + max(confs) * 25.0)
            confirmation = min(100.0, len(sources) * 15.0 + len(feed_types) * 13.0 + statistics.mean(confs) * 32.0)
            freshness = max(0.0, 100.0 - min(fresh) * 0.75)
            instruments = map_instruments(narrative, primary, direction)
            tradability_scores: List[float] = []
            tradability_warnings: List[str] = []
            for inst in instruments[:4]:
                try:
                    ctx = self.market.context_score(inst["symbol"], inst.get("direction", direction))
                    tradability_scores.append(float(ctx["score"]))
                except MarketDataError as e:
                    tradability_warnings.append(str(e))
            tradability = statistics.mean(tradability_scores) if tradability_scores else 0.0
            risk = max(10.0, min(100.0, 45.0 + statistics.pstdev(confs) * 90.0 - confirmation * 0.12 + (24.0 if len(sources) < 2 else 0.0)))
            sanity = self._sanity(rows, sources, feed_types, tradability, freshness)
            shark = max(0.0, min(100.0, shock * 0.34 + confirmation * 0.26 + freshness * 0.18 + tradability * 0.22 - risk * 0.12 + sanity["bonus"]))
            warnings = []
            if len(sources) < int(self.state.get("settings", {}).get("min_independent_sources", 2)):
                warnings.append("Needs second independent source")
            if len(feed_types) < int(self.state.get("settings", {}).get("min_feed_type_confirmations", 2)):
                warnings.append("Needs feed-type diversity")
            if freshness < float(self.state.get("settings", {}).get("min_freshness_score", 55)):
                warnings.append("Signal may be stale")
            if tradability < float(self.state.get("settings", {}).get("min_tradability_score", 55)):
                warnings.append("Market context is weak or unavailable")
            if risk > 65:
                warnings.append("High noise/risk score")
            if not reliability.can_generate_trade_advice:
                warnings.extend(reliability.messages)
            warnings.extend(sanity["warnings"])
            warnings.extend(tradability_warnings[:2])
            confirmed = len(sources) >= int(self.state.get("settings", {}).get("min_independent_sources", 2)) and len(feed_types) >= int(self.state.get("settings", {}).get("min_feed_type_confirmations", 2)) and sanity["passed"] and reliability.can_generate_trade_advice
            if confirmed and shark >= 75:
                status = "SHARK"
                action = "PENDING_ADVICE"
            elif confirmed and shark >= 58:
                status = "WATCH"
                action = "WAIT_FOR_PRICE_OR_VOLUME"
            else:
                status = "LOW"
                action = "MONITOR"
            evidence = [
                f"{len(rows)} live signal(s) across {len(sources)} source(s) and {len(feed_types)} feed type(s)",
                f"Average movement score {statistics.mean(moves):.1f}; average volume score {statistics.mean(vols):.1f}",
                f"Consensus direction {direction}; feed mix: {', '.join(sorted(feed_types))}",
                f"Feed reliability status: {reliability.system_status} ({reliability.reliability_score}%)",
            ]
            metadata = {"sources": sorted(sources), "feed_types": sorted(feed_types), "signal_ids": [r.id for r in rows], "sanity": sanity, "feed_reliability": reliability.to_dict()}
            alert = Alert(new_id("alrt"), now_iso(), narrative, primary, direction, round(shark, 1), round(shock, 1), round(confirmation, 1), round(freshness, 1), round(tradability, 1), round(risk, 1), status, action, instruments, evidence, warnings, metadata)
            advice = self.intelligence.advise(alert.to_dict()).to_dict()
            alert.metadata["advice"] = advice
            if status == "SHARK":
                alert.action = advice["action"]
            alerts.append(alert)
        return sorted(alerts, key=lambda a: a.shark_score, reverse=True)

    def _sanity(self, rows: List[Signal], sources: Set[str], feed_types: Set[str], tradability: float, freshness: float) -> Dict[str, Any]:
        warnings: List[str] = []
        passed = True
        settings = self.state.get("settings", {})
        if len(sources) < int(settings.get("min_independent_sources", 2)):
            passed = False
        if len(feed_types) < int(settings.get("min_feed_type_confirmations", 2)):
            passed = False
        if tradability < float(settings.get("min_tradability_score", 55)):
            passed = False
        if freshness < float(settings.get("min_freshness_score", 55)):
            passed = False
        market_or_options = any((r.metadata.get("feed_type") in {"market_data", "crypto_market_data", "options", "positioning"}) for r in rows)
        event_feed = any((r.metadata.get("feed_type") in {"news", "prediction_market", "forecasting", "filings"}) for r in rows)
        if not market_or_options:
            warnings.append("No market/options/positioning confirmation yet")
            passed = False
        if not event_feed:
            warnings.append("No event/news/prediction confirmation yet")
            passed = False
        bonus = 6.0 if passed else -8.0
        return {"passed": passed, "bonus": bonus, "warnings": warnings}
