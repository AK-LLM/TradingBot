from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

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
        
        # === V5.4: Noise-aware confirmation ===
        # Build noise distribution of contributing signals
        noise_levels = self._collect_noise_levels(alert)
        low_noise_count = sum(1 for n in noise_levels if n == "low")
        medium_noise_count = sum(1 for n in noise_levels if n == "medium")
        high_noise_count = sum(1 for n in noise_levels if n == "high")
        
        # === V5.4: Regime context check (VIX/credit spread) ===
        regime_context = self._extract_regime_context(alert)
        
        # === V5.4: Reddit knee-jerk safeguard ===
        # If the ONLY signals are high-noise (e.g., only Reddit), require extra confirmation
        only_high_noise = high_noise_count > 0 and low_noise_count == 0 and medium_noise_count == 0
        
        checks = {
            "two_sources": len(set(sources)) >= int(self.state.get("settings", {}).get("min_independent_sources", 2)),
            "feed_diversity": len(set(feed_types)) >= int(self.state.get("settings", {}).get("min_feed_type_confirmations", 2)),
            "sanity_passed": bool(sanity.get("passed")),
            "feed_reliability": bool(feed_reliability.get("can_generate_trade_advice", True)),
            "score_threshold": score >= float(self.state.get("settings", {}).get("min_shark_score", 70)),
            # V5.4 new gates:
            "not_only_high_noise": not only_high_noise,
            "has_low_noise_anchor": low_noise_count >= 1,  # At least one authoritative source
        }
        passed = all(checks.values())
        stage = self._trend_stage(alert)
        if not passed:
            action = "HOLD"
            if only_high_noise:
                reason = "Signal cluster is dominated by high-noise sources (e.g., social sentiment) without confirmation from authoritative feeds. Knee-jerk gate active."
            elif not checks["has_low_noise_anchor"]:
                reason = "No low-noise anchor signal (regulatory, macro, or filings). Holding for confirmation."
            else:
                reason = "Confirmation or sanity gate is incomplete; monitor without opening a new position."
        elif direction in {"BUY", "LONG"}:
            action = "STRONG_BUY" if score >= 84 and stage in {"EMERGING", "CONFIRMED"} else "BUY"
            reason = "Multi-feed confirmation and sanity checks support upside exposure."
            # V5.4: Apply regime context as a modifier
            if regime_context.get("regime") == "panic" and action == "STRONG_BUY":
                action = "BUY"
                reason += " (downgraded from STRONG_BUY due to panic volatility regime)"
        elif direction in {"SELL", "SHORT"}:
            action = "STRONG_SELL" if score >= 84 and stage in {"EMERGING", "CONFIRMED"} else "SELL"
            reason = "Multi-feed confirmation and sanity checks support downside or hedge exposure."
            if regime_context.get("regime") == "complacent" and action == "SELL":
                reason += " (note: complacent regime — short squeezes possible)"
        else:
            action = "HOLD"
            reason = "Direction is not strong enough for a trade recommendation."
        
        # V5.4: Enriched summary with noise breakdown and regime
        noise_summary = f"noise[L:{low_noise_count}/M:{medium_noise_count}/H:{high_noise_count}]"
        regime_summary = f"regime:{regime_context.get('regime', 'unknown')}" if regime_context else ""
        summary_parts = [
            f"{len(set(sources))} source(s)",
            f"{len(set(feed_types))} feed type(s)",
            noise_summary,
        ]
        if regime_summary:
            summary_parts.append(regime_summary)
        
        # === V5.5: Constellation enrichment ===
        constellation = self._matching_constellation(alert)
        if constellation:
            c_stage = constellation.get("stage", "")
            pattern = constellation.get("pattern_name", "")
            c_meta = constellation.get("metadata", {}) or {}
            summary_parts.append(f"⭐{pattern}[{c_stage}]")

            # === V5.6: Constellation explicitly suggests REDUCE ===
            # Some patterns (Crowded Long Warning) explicitly hint at REDUCE
            suggested = c_meta.get("suggested_action", "")
            if suggested == "REDUCE" and action in ("BUY", "STRONG_BUY", "HOLD"):
                action = "REDUCE"
                reason = f"⚠️ {pattern} [{c_stage}] suggests trimming exposure rather than adding. {constellation.get('why_it_matters', '')}"

            # SCOUT-stage early warning: enrich reason but stay cautious
            elif action == "HOLD" and c_stage == "SCOUT" and constellation.get("confidence", 0) >= 0.5:
                reason += f" | EARLY SIGNAL: {pattern} pattern detected (SCOUT). Watch for confirmation."
            elif c_stage == "STALKING" and action in ("BUY", "SELL"):
                reason += f" | Constellation: {pattern} (STALKING) — multi-feed alignment building."
            elif c_stage == "STRIKING" and action in ("BUY", "SELL", "STRONG_BUY", "STRONG_SELL"):
                reason += f" | Constellation: {pattern} (STRIKING) — full multi-feed confirmation."
            elif c_stage == "LATE":
                # === V5.6: LATE stage now downgrades to REDUCE if user is already long ===
                # If we have an existing long position in this symbol, the right move is REDUCE not HOLD
                existing_position = self._has_existing_long(alert.get("primary_symbol", ""))
                if action in ("STRONG_BUY", "BUY"):
                    if existing_position:
                        action = "REDUCE"
                        reason = f"⚠️ LATE-stage '{pattern}' detected and you're already long. REDUCE exposure rather than chasing the consensus."
                    else:
                        action = "HOLD"
                        reason = f"⚠️ LATE-stage constellation '{pattern}' detected. Consensus already formed; chasing not advised."
                elif action in ("STRONG_SELL", "SELL"):
                    reason += f" | NOTE: LATE-stage '{pattern}' constellation — consider that capitulation may be near."

        # === V5.6: Velocity-based REDUCE logic ===
        # If a previously bullish channel is decelerating, and we'd otherwise BUY,
        # consider that bullish momentum is fading
        if action in ("BUY", "STRONG_BUY"):
            velocity_decel = self._velocity_decelerating(alert)
            if velocity_decel:
                # Decelerating momentum on what we'd want to buy = warning sign
                if self._has_existing_long(alert.get("primary_symbol", "")):
                    action = "REDUCE"
                    reason = "Bullish momentum is decelerating on this channel and you're already long. REDUCE rather than add."
                else:
                    # Don't enter; downgrade to HOLD
                    action = "HOLD"
                    reason = "Bullish momentum is decelerating on this channel. Hold rather than enter into fading momentum."

        # === V5.6: Divergence-based REDUCE logic ===
        # If low-noise feeds disagree with high-noise feeds, that's uncertainty.
        # On an existing long, that warrants trimming.
        if action in ("BUY", "STRONG_BUY") and self._signal_divergence_detected(alert):
            if self._has_existing_long(alert.get("primary_symbol", "")):
                action = "REDUCE"
                reason = "Low-noise feeds (regulatory/macro) diverging from high-noise feeds (social) on this symbol. Trim existing long while signal clarifies."

        # === V5.6: Risk-off regime forming on existing long ===
        if action in ("BUY", "STRONG_BUY") and regime_context.get("regime") in ("elevated", "wide_credit"):
            if self._has_existing_long(alert.get("primary_symbol", "")):
                action = "REDUCE"
                reason = f"Risk-off regime forming ({regime_context.get('regime')}). REDUCE existing long exposure rather than adding."

        summary = " | ".join(summary_parts) + f": {', '.join(sorted(set(feed_types))) or 'none'}"

        return ActionAdvice(action, reason, round(min(99.0, max(0.0, score)), 1), stage, summary, checks)

    def _has_existing_long(self, symbol: str) -> bool:
        """Check if we currently hold a long position in this symbol."""
        if not symbol:
            return False
        positions = self.state.get("positions", {})
        for pos in positions.values():
            if str(pos.get("symbol", "")).upper() == symbol.upper():
                if int(pos.get("quantity", 0)) > 0:
                    return True
        return False

    def _velocity_decelerating(self, alert: Dict[str, Any]) -> bool:
        """Check if the velocity for this alert's primary channel is decelerating."""
        readings = self.state.get("velocity_readings", []) or []
        narrative = alert.get("narrative", "")
        symbol = alert.get("primary_symbol", "")
        for r in readings:
            channel = r.get("channel", "")
            if narrative in channel and symbol in channel:
                if r.get("acceleration") == "ACCELERATING_DOWN":
                    return True
        return False

    def _signal_divergence_detected(self, alert: Dict[str, Any]) -> bool:
        """Detect if low-noise and high-noise signals disagree on direction."""
        metadata = alert.get("metadata", {}) if isinstance(alert.get("metadata"), dict) else {}
        contributing = metadata.get("contributing_signals", []) or alert.get("signals", []) or []
        low_dirs = []
        high_dirs = []
        for sig in contributing:
            if not isinstance(sig, dict):
                continue
            sig_meta = sig.get("metadata", {}) if isinstance(sig.get("metadata"), dict) else {}
            noise = sig_meta.get("noise_level", "")
            direction = sig.get("direction", "")
            if direction in ("WATCH", ""):
                continue
            if noise == "low":
                low_dirs.append(direction)
            elif noise == "high":
                high_dirs.append(direction)
        if not low_dirs or not high_dirs:
            return False
        # Divergence if low-noise consensus differs from high-noise consensus
        from collections import Counter
        low_consensus = Counter(low_dirs).most_common(1)[0][0]
        high_consensus = Counter(high_dirs).most_common(1)[0][0]
        return low_consensus != high_consensus

    def _collect_noise_levels(self, alert: Dict[str, Any]) -> List[str]:
        """Extract noise levels from contributing signals in the alert."""
        metadata = alert.get("metadata", {}) if isinstance(alert.get("metadata"), dict) else {}
        contributing = metadata.get("contributing_signals", []) or alert.get("signals", []) or []
        levels = []
        for sig in contributing:
            if isinstance(sig, dict):
                sig_meta = sig.get("metadata", {}) if isinstance(sig.get("metadata"), dict) else {}
                noise = sig_meta.get("noise_level")
                if noise:
                    levels.append(noise)
        # Fallback: infer from feed types
        if not levels:
            feed_types = metadata.get("feed_types", []) or []
            for ft in feed_types:
                if ft in {"crowd_sentiment"}:
                    levels.append("high")
                elif ft in {"attention", "news"}:
                    levels.append("medium")
                else:
                    levels.append("low")
        return levels

    def _extract_regime_context(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """Pull current regime context from state if available."""
        signals = self.state.get("signals", []) or []
        for sig in signals:
            if isinstance(sig, dict):
                sig_meta = sig.get("metadata", {}) if isinstance(sig.get("metadata"), dict) else {}
                if sig_meta.get("is_regime_context") and sig_meta.get("regime"):
                    return {
                        "regime": sig_meta.get("regime"),
                        "note": sig_meta.get("regime_note"),
                    }
        return {}

    def _matching_constellation(self, alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """V5.5: Find the highest-confidence constellation matching this alert's narrative/symbol."""
        constellations = self.state.get("constellations", []) or []
        narrative = alert.get("narrative", "")
        symbol = alert.get("primary_symbol", "")
        matching = [c for c in constellations
                    if c.get("primary_narrative") == narrative or c.get("primary_symbol") == symbol]
        if not matching:
            return None
        # Return the highest-confidence early-stage match (SCOUT/STALKING) over confirmed
        stage_priority = {"SCOUT": 0, "STALKING": 1, "STRIKING": 2, "LATE": 3}
        matching.sort(key=lambda c: (stage_priority.get(c.get("stage", "LATE"), 99),
                                     -float(c.get("confidence", 0))))
        return matching[0]

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
