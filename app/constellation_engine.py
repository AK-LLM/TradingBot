"""
Constellation Engine - V5.5 Intelligence Enhancement

The core insight: individual signals are noise. CONSTELLATIONS of signals
across feed types are the actual intelligence. Smart money positioning looks
different from retail FOMO. Geopolitical cascades look different from
narrative ignition.

This module recognizes specific multi-feed patterns that historically precede
market moves. It explicitly tags WHERE in the lifecycle each pattern is so
the engine can say "you're early" vs "you're late".

Pattern lifecycle stages:
  SCOUT    - First leading-indicator signal appears (you're early)
  STALKING - Multiple feeds aligning, not yet confirmed (still early)
  STRIKING - Full multi-feed confirmation (act now)
  LATE     - Heavy news + retail + late attention (consensus formed, you're behind)

This is rule-based pattern recognition. Not ML. The intelligence comes from
how the patterns are designed - encoded shark-radar intuition at machine scale.
"""

from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set


# Lifecycle stages
STAGE_SCOUT = "SCOUT"
STAGE_STALKING = "STALKING"
STAGE_STRIKING = "STRIKING"
STAGE_LATE = "LATE"

# Feed type categories used for pattern matching
LEADING_INDICATOR_TYPES = {
    "filings",              # SEC Form 4 - smart money positioning
    "canada_filings",       # SEDI - Canadian smart money
    "options",              # Options flow - sophisticated positioning
    "prediction_market",    # Polymarket/Manifold/Kalshi - aggregated futures odds
    "positioning",          # CFTC COT - large speculator positioning
    "macro_data",           # FRED - macroeconomic data surprises
    "canada_macro",         # Bank of Canada / StatCan
    "rates",                # Treasury rate moves
    "regime_context",       # VIX/credit spread regime shifts
}

LAGGING_INDICATOR_TYPES = {
    "news",                 # By the time news reports it, smart money already moved
    "crowd_sentiment",      # Reddit - retail follows institutions
    "attention",            # Google Trends - search attention is a lagging indicator
}

CONFIRMING_INDICATOR_TYPES = {
    "market_data",          # Stooq - price action confirms moves
    "crypto_market_data",   # Crypto market action
    "energy_data",          # EIA - confirms energy thesis
    "weather",              # NOAA - confirms supply chain thesis
    "power_grid",           # Confirms infrastructure thesis
    "supply_chain",         # Confirms trade/logistics thesis
    "forecasting",          # Metaculus - expert forecasts
}


@dataclass
class Constellation:
    """A detected multi-feed pattern."""
    pattern_name: str
    stage: str                              # SCOUT, STALKING, STRIKING, LATE
    confidence: float                       # 0.0-1.0
    direction: str                          # BUY, SELL, WATCH
    primary_narrative: str
    primary_symbol: str
    contributing_feeds: List[str]
    contributing_signal_ids: List[str]
    description: str
    why_it_matters: str
    velocity_context: Optional[str] = None  # If a contributing signal is accelerating
    detected_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.detected_at:
            self.detected_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ConstellationEngine:
    """
    Pattern recognition engine that scans current signals + velocity context
    and identifies known constellations.
    """

    def __init__(self, state: Dict[str, Any]):
        self.state = state

    def detect_all(self, signals: List[Dict[str, Any]],
                   velocity_readings: Optional[List[Any]] = None) -> List[Constellation]:
        """
        Run all pattern detectors and return constellation matches.
        velocity_readings: list of VelocityReading dicts/objects from velocity_tracker
        """
        velocity_map = self._build_velocity_map(velocity_readings or [])

        # Group signals by narrative for efficient pattern matching
        signals_by_narrative = defaultdict(list)
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            meta = sig.get("metadata", {}) or {}
            narrative = meta.get("narrative", "general")
            signals_by_narrative[narrative].append(sig)

        constellations: List[Constellation] = []

        for narrative, narrative_signals in signals_by_narrative.items():
            if not narrative_signals:
                continue

            # Run each pattern detector against this narrative's signals
            constellations.extend(self._detect_smart_money_positioning(narrative, narrative_signals, velocity_map))
            constellations.extend(self._detect_narrative_ignition(narrative, narrative_signals, velocity_map))
            constellations.extend(self._detect_macro_regime_shift(narrative, narrative_signals, velocity_map))
            constellations.extend(self._detect_geopolitical_cascade(narrative, narrative_signals, velocity_map))
            constellations.extend(self._detect_insider_cluster(narrative, narrative_signals, velocity_map))
            constellations.extend(self._detect_sentiment_capitulation(narrative, narrative_signals, velocity_map))
            constellations.extend(self._detect_echo_chamber_warning(narrative, narrative_signals, velocity_map))
            constellations.extend(self._detect_canadian_macro_divergence(narrative, narrative_signals, velocity_map))
            # === V5.6 SELL-side patterns (the missing twins) ===
            constellations.extend(self._detect_distribution_pattern(narrative, narrative_signals, velocity_map))
            constellations.extend(self._detect_euphoria_top(narrative, narrative_signals, velocity_map))
            constellations.extend(self._detect_crowded_long_warning(narrative, narrative_signals, velocity_map))

        # Sort by stage priority (SCOUT first - those are the early ones we care about most)
        # then by confidence within stage
        stage_priority = {STAGE_SCOUT: 0, STAGE_STALKING: 1, STAGE_STRIKING: 2, STAGE_LATE: 3}
        constellations.sort(key=lambda c: (stage_priority.get(c.stage, 99), -c.confidence))

        return constellations

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def _build_velocity_map(self, velocity_readings: List[Any]) -> Dict[str, Any]:
        """Build a lookup of channel -> acceleration status."""
        vm = {}
        for r in velocity_readings:
            if hasattr(r, "channel"):
                vm[r.channel] = r
            elif isinstance(r, dict):
                vm[r.get("channel", "")] = r
        return vm

    def _signal_is_accelerating(self, signal: Dict[str, Any], velocity_map: Dict[str, Any]) -> bool:
        """Check if this signal's channel is currently accelerating."""
        meta = signal.get("metadata", {}) or {}
        narrative = meta.get("narrative", "general")
        symbol = signal.get("symbol", "MARKET")
        source = signal.get("source", "unknown")
        channel = f"{source}::{narrative}::{symbol}"
        v = velocity_map.get(channel)
        if not v:
            return False
        accel = getattr(v, "acceleration", None) if hasattr(v, "acceleration") else v.get("acceleration")
        return accel in ("ACCELERATING_UP", "NEW")

    def _feed_types_present(self, signals: List[Dict[str, Any]]) -> Set[str]:
        """Get the set of feed_types in this signal group."""
        types = set()
        for sig in signals:
            meta = sig.get("metadata", {}) or {}
            ft = meta.get("feed_type")
            if ft:
                types.add(ft)
        return types

    def _filter_by_type(self, signals: List[Dict[str, Any]], types: Set[str]) -> List[Dict[str, Any]]:
        """Filter signals to only those matching given feed types."""
        return [s for s in signals
                if (s.get("metadata", {}) or {}).get("feed_type") in types]

    def _avg_confidence(self, signals: List[Dict[str, Any]]) -> float:
        if not signals:
            return 0.0
        return sum(float(s.get("confidence", 0)) for s in signals) / len(signals)

    def _dominant_direction(self, signals: List[Dict[str, Any]]) -> str:
        if not signals:
            return "WATCH"
        directions = [s.get("direction", "WATCH") for s in signals]
        counter = Counter(directions)
        most_common = counter.most_common(1)
        return most_common[0][0] if most_common else "WATCH"

    def _primary_symbol(self, signals: List[Dict[str, Any]]) -> str:
        symbols = [s.get("symbol") for s in signals if s.get("symbol")]
        if not symbols:
            return "MARKET"
        return Counter(symbols).most_common(1)[0][0]

    # -------------------------------------------------------------------------
    # Pattern Detectors
    # -------------------------------------------------------------------------

    def _detect_smart_money_positioning(self, narrative: str, signals: List[Dict[str, Any]],
                                         velocity_map: Dict[str, Any]) -> List[Constellation]:
        """
        Smart Money Positioning:
          - Insider filings (SEC Form 4 / SEDI) AND/OR
          - Options flow concentration AND
          - Low news volume (institutions accumulating quietly)
        """
        types_present = self._feed_types_present(signals)
        smart_money_signals = self._filter_by_type(signals, {"filings", "canada_filings", "options"})
        news_signals = self._filter_by_type(signals, {"news"})

        if not smart_money_signals:
            return []

        # The defining feature: smart money present, retail attention LOW
        if len(news_signals) >= 5:
            return []  # News volume too high - not smart money quietly accumulating

        # Stage detection
        if len(smart_money_signals) == 1 and len(types_present) <= 2:
            stage = STAGE_SCOUT
            confidence = 0.45
        elif len(smart_money_signals) >= 2:
            stage = STAGE_STALKING
            confidence = 0.65
        else:
            return []

        any_accelerating = any(self._signal_is_accelerating(s, velocity_map) for s in smart_money_signals)
        if any_accelerating:
            confidence = min(0.85, confidence + 0.15)

        return [Constellation(
            pattern_name="Smart Money Positioning",
            stage=stage,
            confidence=confidence,
            direction=self._dominant_direction(smart_money_signals),
            primary_narrative=narrative,
            primary_symbol=self._primary_symbol(smart_money_signals),
            contributing_feeds=sorted({s.get("source", "") for s in smart_money_signals}),
            contributing_signal_ids=[s.get("id", "") for s in smart_money_signals],
            description=f"{len(smart_money_signals)} institutional/insider signal(s) on '{narrative}' with low news volume.",
            why_it_matters="Smart money positions before retail. Quiet accumulation suggests catalyst awareness.",
            velocity_context="Accelerating" if any_accelerating else None,
            metadata={"news_signal_count": len(news_signals)}
        )]

    def _detect_narrative_ignition(self, narrative: str, signals: List[Dict[str, Any]],
                                    velocity_map: Dict[str, Any]) -> List[Constellation]:
        """
        Narrative Ignition:
          - Google Trends spike + Reddit mentions starting + GDELT event = retail attention beginning
          - Sources are lagging but EARLY in the wave - retail is just discovering
        """
        attention_signals = self._filter_by_type(signals, {"attention"})
        crowd_signals = self._filter_by_type(signals, {"crowd_sentiment"})
        news_signals = self._filter_by_type(signals, {"news"})

        # Need at least 2 of the 3 retail-facing signal types
        type_count = sum(1 for x in [attention_signals, crowd_signals, news_signals] if x)
        if type_count < 2:
            return []

        # Velocity matters HUGELY here - is attention building or already peaked?
        all_contributing = attention_signals + crowd_signals + news_signals
        accelerating_count = sum(1 for s in all_contributing if self._signal_is_accelerating(s, velocity_map))

        if accelerating_count >= 2:
            stage = STAGE_STALKING
            confidence = 0.70
        elif accelerating_count == 1:
            stage = STAGE_SCOUT
            confidence = 0.55
        else:
            stage = STAGE_LATE
            confidence = 0.40

        return [Constellation(
            pattern_name="Narrative Ignition",
            stage=stage,
            confidence=confidence,
            direction=self._dominant_direction(all_contributing),
            primary_narrative=narrative,
            primary_symbol=self._primary_symbol(all_contributing),
            contributing_feeds=sorted({s.get("source", "") for s in all_contributing}),
            contributing_signal_ids=[s.get("id", "") for s in all_contributing],
            description=f"Retail attention building on '{narrative}': {len(attention_signals)} attention + {len(crowd_signals)} crowd + {len(news_signals)} news",
            why_it_matters="Attention is building. If accelerating, you may be ahead of the consensus wave.",
            velocity_context=f"{accelerating_count} of {len(all_contributing)} signals accelerating" if accelerating_count else None,
            metadata={"accelerating_signals": accelerating_count}
        )]

    def _detect_macro_regime_shift(self, narrative: str, signals: List[Dict[str, Any]],
                                    velocity_map: Dict[str, Any]) -> List[Constellation]:
        """
        Macro Regime Shift:
          - FRED data surprise + Treasury rate move + VIX move = environment changing
        """
        macro_signals = self._filter_by_type(signals, {"macro_data", "canada_macro"})
        rate_signals = self._filter_by_type(signals, {"rates"})
        regime_signals = self._filter_by_type(signals, {"regime_context"})

        type_count = sum(1 for x in [macro_signals, rate_signals, regime_signals] if x)
        if type_count < 2:
            return []

        all_contributing = macro_signals + rate_signals + regime_signals

        # Macro shifts are slow — STALKING/STRIKING based on signal count, not velocity
        if type_count == 3:
            stage = STAGE_STRIKING
            confidence = 0.75
        else:
            stage = STAGE_STALKING
            confidence = 0.60

        return [Constellation(
            pattern_name="Macro Regime Shift",
            stage=stage,
            confidence=confidence,
            direction=self._dominant_direction(all_contributing),
            primary_narrative=narrative,
            primary_symbol=self._primary_symbol(all_contributing),
            contributing_feeds=sorted({s.get("source", "") for s in all_contributing}),
            contributing_signal_ids=[s.get("id", "") for s in all_contributing],
            description=f"Macro regime indicators aligning on '{narrative}': {type_count} of 3 macro feed types active.",
            why_it_matters="Regime shifts move markets across all instruments. Position for the new regime, not the old.",
            metadata={}
        )]

    def _detect_geopolitical_cascade(self, narrative: str, signals: List[Dict[str, Any]],
                                      velocity_map: Dict[str, Any]) -> List[Constellation]:
        """
        Geopolitical Cascade:
          - GDELT event spike + Polymarket odds shift + commodity move = real-world event escalating
        """
        # GDELT signals come through news feed_type with gdelt_events feed_key
        gdelt_signals = [s for s in signals
                         if (s.get("metadata", {}) or {}).get("feed_key") == "gdelt_events"]
        prediction_signals = self._filter_by_type(signals, {"prediction_market"})
        commodity_signals = [s for s in signals
                             if (s.get("metadata", {}) or {}).get("feed_key") in
                             {"eia_energy", "noaa_alerts", "shipping_events", "stooq_market"}]

        type_count = sum(1 for x in [gdelt_signals, prediction_signals, commodity_signals] if x)
        if type_count < 2:
            return []

        all_contributing = gdelt_signals + prediction_signals + commodity_signals

        any_accelerating = any(self._signal_is_accelerating(s, velocity_map) for s in all_contributing)

        if type_count == 3 and any_accelerating:
            stage = STAGE_STRIKING
            confidence = 0.80
        elif type_count == 3:
            stage = STAGE_STALKING
            confidence = 0.65
        elif any_accelerating:
            stage = STAGE_STALKING
            confidence = 0.55
        else:
            stage = STAGE_SCOUT
            confidence = 0.45

        return [Constellation(
            pattern_name="Geopolitical Cascade",
            stage=stage,
            confidence=confidence,
            direction=self._dominant_direction(all_contributing),
            primary_narrative=narrative,
            primary_symbol=self._primary_symbol(all_contributing),
            contributing_feeds=sorted({s.get("source", "") for s in all_contributing}),
            contributing_signal_ids=[s.get("id", "") for s in all_contributing],
            description=f"Real-world event cascading on '{narrative}': events + prediction markets + commodity flow aligning.",
            why_it_matters="Geopolitical events compound. Early position in the chain captures the full move.",
            velocity_context="Accelerating" if any_accelerating else None,
            metadata={}
        )]

    def _detect_insider_cluster(self, narrative: str, signals: List[Dict[str, Any]],
                                 velocity_map: Dict[str, Any]) -> List[Constellation]:
        """
        Insider Cluster: Multiple insider filings + options activity + low retail = smart money before retail.
        """
        insider_signals = self._filter_by_type(signals, {"filings", "canada_filings"})
        options_signals = self._filter_by_type(signals, {"options"})
        crowd_signals = self._filter_by_type(signals, {"crowd_sentiment"})

        # The pattern: insiders AND options activity, but minimal retail noise
        if len(insider_signals) < 1 or len(options_signals) < 1:
            return []
        if len(crowd_signals) >= 3:
            return []  # Too much retail noise — pattern doesn't apply

        all_contributing = insider_signals + options_signals
        any_accelerating = any(self._signal_is_accelerating(s, velocity_map) for s in all_contributing)

        if len(insider_signals) >= 2 and len(options_signals) >= 2:
            stage = STAGE_STRIKING
            confidence = 0.80
        elif any_accelerating:
            stage = STAGE_STALKING
            confidence = 0.65
        else:
            stage = STAGE_SCOUT
            confidence = 0.50

        return [Constellation(
            pattern_name="Insider Cluster",
            stage=stage,
            confidence=confidence,
            direction=self._dominant_direction(all_contributing),
            primary_narrative=narrative,
            primary_symbol=self._primary_symbol(all_contributing),
            contributing_feeds=sorted({s.get("source", "") for s in all_contributing}),
            contributing_signal_ids=[s.get("id", "") for s in all_contributing],
            description=f"Insider + options activity on '{narrative}' with limited retail attention.",
            why_it_matters="Insiders and sophisticated options traders typically act 2-6 weeks before catalysts. Retail attention is still low.",
            velocity_context="Accelerating" if any_accelerating else None,
            metadata={"crowd_signal_count": len(crowd_signals)}
        )]

    def _detect_sentiment_capitulation(self, narrative: str, signals: List[Dict[str, Any]],
                                        velocity_map: Dict[str, Any]) -> List[Constellation]:
        """
        Sentiment Capitulation: Reddit doom + VIX spike + crypto/equity crash = potential bottom forming.
        """
        crowd_signals = self._filter_by_type(signals, {"crowd_sentiment"})
        regime_signals = self._filter_by_type(signals, {"regime_context"})
        market_signals = self._filter_by_type(signals, {"market_data", "crypto_market_data"})

        # Need negative crowd sentiment + elevated VIX/credit + market weakness
        bearish_crowd = [s for s in crowd_signals if s.get("direction") == "SELL"]
        if len(bearish_crowd) < 1:
            return []

        # Check regime is panic or wide_credit
        panic_regime = False
        for s in regime_signals:
            meta = s.get("metadata", {}) or {}
            if meta.get("regime") in ("panic", "elevated", "wide_credit", "stress_credit"):
                panic_regime = True
                break

        if not panic_regime:
            return []

        bearish_market = [s for s in market_signals if s.get("direction") == "SELL"]
        if not bearish_market and not market_signals:
            return []

        all_contributing = bearish_crowd + regime_signals + market_signals

        if len(bearish_crowd) >= 2 and len(market_signals) >= 1:
            stage = STAGE_STRIKING
            confidence = 0.70
        else:
            stage = STAGE_STALKING
            confidence = 0.55

        return [Constellation(
            pattern_name="Sentiment Capitulation",
            stage=stage,
            confidence=confidence,
            direction="BUY",  # Capitulation patterns are contrarian buy signals
            primary_narrative=narrative,
            primary_symbol=self._primary_symbol(all_contributing),
            contributing_feeds=sorted({s.get("source", "") for s in all_contributing}),
            contributing_signal_ids=[s.get("id", "") for s in all_contributing],
            description=f"Bearish crowd sentiment + elevated volatility regime + market weakness on '{narrative}'.",
            why_it_matters="Maximum pessimism often marks bottoms. Contrarian opportunity if other anchors confirm.",
            metadata={"contrarian_signal": True}
        )]

    def _detect_echo_chamber_warning(self, narrative: str, signals: List[Dict[str, Any]],
                                      velocity_map: Dict[str, Any]) -> List[Constellation]:
        """
        Echo Chamber Warning: News volume spiking + Reddit accelerating + Google Trends late + options chasing
        = wave already broke, you're late.
        """
        news_signals = self._filter_by_type(signals, {"news"})
        crowd_signals = self._filter_by_type(signals, {"crowd_sentiment"})
        attention_signals = self._filter_by_type(signals, {"attention"})

        # The defining pattern: lagging indicators dominant
        if len(news_signals) < 3 or len(crowd_signals) < 1:
            return []

        # Check if attention/crowd are accelerating (means it's still building) or stable (means it's peaked)
        all_lagging = crowd_signals + attention_signals
        accelerating_count = sum(1 for s in all_lagging if self._signal_is_accelerating(s, velocity_map))

        # If lagging indicators are accelerating, it's still building (don't flag)
        # If they're stable/decelerating, the wave has likely peaked
        if accelerating_count >= len(all_lagging) / 2:
            return []  # Still building — not late yet

        all_contributing = news_signals + crowd_signals + attention_signals

        return [Constellation(
            pattern_name="Echo Chamber Warning",
            stage=STAGE_LATE,
            confidence=0.70,
            direction=self._dominant_direction(all_contributing),
            primary_narrative=narrative,
            primary_symbol=self._primary_symbol(all_contributing),
            contributing_feeds=sorted({s.get("source", "") for s in all_contributing}),
            contributing_signal_ids=[s.get("id", "") for s in all_contributing],
            description=f"Heavy news + crowd attention on '{narrative}' but momentum stable/decelerating.",
            why_it_matters="Consensus has formed. Smart money likely already moved. Avoid chasing or consider fading.",
            velocity_context="Lagging indicators no longer accelerating",
            metadata={"warning_type": "late_to_party"}
        )]

    def _detect_canadian_macro_divergence(self, narrative: str, signals: List[Dict[str, Any]],
                                           velocity_map: Dict[str, Any]) -> List[Constellation]:
        """
        Canadian Macro Divergence: Bank of Canada / StatCan / SEDI moving while US macro is quiet.
        Catches Canada-specific opportunities US-centric feeds would miss.
        """
        ca_macro = self._filter_by_type(signals, {"canada_macro"})
        ca_filings = self._filter_by_type(signals, {"canada_filings"})
        us_macro = self._filter_by_type(signals, {"macro_data"})

        if len(ca_macro) < 1 and len(ca_filings) < 1:
            return []

        ca_signals = ca_macro + ca_filings

        # Divergence: Canadian signals active, US macro quiet
        if len(us_macro) >= 3:
            return []  # Not a Canadian-specific divergence, broader macro move

        if len(ca_signals) >= 2:
            stage = STAGE_STALKING
            confidence = 0.60
        else:
            stage = STAGE_SCOUT
            confidence = 0.45

        return [Constellation(
            pattern_name="Canadian Macro Divergence",
            stage=stage,
            confidence=confidence,
            direction=self._dominant_direction(ca_signals),
            primary_narrative=narrative,
            primary_symbol=self._primary_symbol(ca_signals),
            contributing_feeds=sorted({s.get("source", "") for s in ca_signals}),
            contributing_signal_ids=[s.get("id", "") for s in ca_signals],
            description=f"Canadian-specific signals on '{narrative}' without corresponding US macro activity.",
            why_it_matters="Canadian-listed equities and CAD-sensitive instruments may move on Canadian-specific catalysts US traders miss.",
            metadata={"jurisdiction_focus": "CA"}
        )]

    # =========================================================================
    # V5.6 SELL-SIDE CONSTELLATIONS (the missing twins)
    # =========================================================================

    def _detect_distribution_pattern(self, narrative: str, signals: List[Dict[str, Any]],
                                      velocity_map: Dict[str, Any]) -> List[Constellation]:
        """
        Distribution Pattern (twin of Smart Money Positioning):
          - Insider SELLING (Form 4 sales) AND/OR put options activity
          - News volume LOW or RETAIL still bullish
          - Institutions distributing while retail is unaware
        """
        types_present = self._feed_types_present(signals)
        # Smart-money sell signals: insider sells + put-side options
        insider_sells = [s for s in self._filter_by_type(signals, {"filings", "canada_filings"})
                         if s.get("direction") == "SELL"]
        options_signals = self._filter_by_type(signals, {"options"})
        # Bearish options bias: any options signal with SELL direction OR description mentioning puts
        bearish_options = [s for s in options_signals
                           if s.get("direction") == "SELL"
                           or "put" in str(s.get("description", "")).lower()
                           or "put" in str(s.get("title", "")).lower()]
        crowd_signals = self._filter_by_type(signals, {"crowd_sentiment"})
        news_signals = self._filter_by_type(signals, {"news"})

        # Need either insider sells or bearish options
        if not insider_sells and not bearish_options:
            return []

        # The pattern: smart money distributing, retail still bullish or quiet
        bullish_crowd = [s for s in crowd_signals if s.get("direction") == "BUY"]
        retail_unaware = (len(crowd_signals) == 0 and len(news_signals) <= 2) or len(bullish_crowd) >= 1

        if not retail_unaware:
            return []

        smart_money_sells = insider_sells + bearish_options
        any_accelerating = any(self._signal_is_accelerating(s, velocity_map) for s in smart_money_sells)

        if len(smart_money_sells) >= 2 and any_accelerating:
            stage = STAGE_STRIKING
            confidence = 0.80
        elif len(smart_money_sells) >= 2:
            stage = STAGE_STALKING
            confidence = 0.65
        elif any_accelerating:
            stage = STAGE_STALKING
            confidence = 0.55
        else:
            stage = STAGE_SCOUT
            confidence = 0.45

        return [Constellation(
            pattern_name="Distribution Pattern",
            stage=stage,
            confidence=confidence,
            direction="SELL",  # This pattern is specifically bearish
            primary_narrative=narrative,
            primary_symbol=self._primary_symbol(smart_money_sells),
            contributing_feeds=sorted({s.get("source", "") for s in smart_money_sells}),
            contributing_signal_ids=[s.get("id", "") for s in smart_money_sells],
            description=f"Smart money distributing on '{narrative}': {len(insider_sells)} insider sale(s), {len(bearish_options)} bearish options signal(s). Retail unaware or still bullish.",
            why_it_matters="Institutions exit before tops the same way they enter before bottoms. This is the SELL-side twin of Smart Money Positioning.",
            velocity_context="Accelerating" if any_accelerating else None,
            metadata={
                "bullish_crowd_count": len(bullish_crowd),
                "news_signal_count": len(news_signals),
                "is_sell_side_pattern": True,
            }
        )]

    def _detect_euphoria_top(self, narrative: str, signals: List[Dict[str, Any]],
                              velocity_map: Dict[str, Any]) -> List[Constellation]:
        """
        Euphoria Top (twin of Sentiment Capitulation):
          - Bullish Reddit consensus + complacent VIX + Google Trends spike + price at highs
          - Maximum optimism marks tops the same way maximum pessimism marks bottoms
        """
        crowd_signals = self._filter_by_type(signals, {"crowd_sentiment"})
        attention_signals = self._filter_by_type(signals, {"attention"})
        regime_signals = self._filter_by_type(signals, {"regime_context"})

        # Need bullish crowd sentiment
        bullish_crowd = [s for s in crowd_signals if s.get("direction") == "BUY"]
        if len(bullish_crowd) < 1:
            return []

        # Need complacent or normal VIX regime
        complacent_regime = False
        for s in regime_signals:
            meta = s.get("metadata", {}) or {}
            if meta.get("regime") in ("complacent", "tight_credit"):
                complacent_regime = True
                break

        if not complacent_regime:
            return []

        # Bonus if attention is also high (Google Trends spiking)
        all_contributing = bullish_crowd + attention_signals + regime_signals

        if len(bullish_crowd) >= 2 and len(attention_signals) >= 1:
            stage = STAGE_STRIKING
            confidence = 0.70
        elif len(bullish_crowd) >= 2 or len(attention_signals) >= 1:
            stage = STAGE_STALKING
            confidence = 0.55
        else:
            stage = STAGE_SCOUT
            confidence = 0.45

        return [Constellation(
            pattern_name="Euphoria Top",
            stage=stage,
            confidence=confidence,
            direction="SELL",  # Hardcoded contrarian SELL (mirror of Sentiment Capitulation)
            primary_narrative=narrative,
            primary_symbol=self._primary_symbol(all_contributing),
            contributing_feeds=sorted({s.get("source", "") for s in all_contributing}),
            contributing_signal_ids=[s.get("id", "") for s in all_contributing],
            description=f"Bullish crowd sentiment + complacent volatility regime on '{narrative}'. {'+ attention spike' if attention_signals else ''}.",
            why_it_matters="Maximum optimism often marks tops. Contrarian SELL opportunity if other anchors confirm. Mirror of Sentiment Capitulation.",
            metadata={
                "contrarian_signal": True,
                "is_sell_side_pattern": True,
            }
        )]

    def _detect_crowded_long_warning(self, narrative: str, signals: List[Dict[str, Any]],
                                       velocity_map: Dict[str, Any]) -> List[Constellation]:
        """
        Crowded Long Warning:
          - Bullish signals across multiple feeds + insider selling beginning + complacent VIX
          - Setup for sharp reversal — crowded trades unwind violently
        """
        all_bullish = [s for s in signals if s.get("direction") == "BUY"]
        insider_sells = [s for s in self._filter_by_type(signals, {"filings", "canada_filings"})
                         if s.get("direction") == "SELL"]
        regime_signals = self._filter_by_type(signals, {"regime_context"})

        # Need a strong bullish setup PLUS insider selling
        if len(all_bullish) < 4 or len(insider_sells) < 1:
            return []

        # Need complacent regime
        complacent = any(
            (s.get("metadata", {}) or {}).get("regime") in ("complacent", "tight_credit")
            for s in regime_signals
        )
        if not complacent:
            return []

        all_contributing = all_bullish + insider_sells + regime_signals

        if len(all_bullish) >= 6 and len(insider_sells) >= 2:
            stage = STAGE_STRIKING
            confidence = 0.70
        else:
            stage = STAGE_STALKING
            confidence = 0.55

        return [Constellation(
            pattern_name="Crowded Long Warning",
            stage=stage,
            confidence=confidence,
            direction="SELL",  # Warning to trim/exit longs
            primary_narrative=narrative,
            primary_symbol=self._primary_symbol(all_bullish),
            contributing_feeds=sorted({s.get("source", "") for s in all_contributing}),
            contributing_signal_ids=[s.get("id", "") for s in all_contributing],
            description=f"Heavy bullish signal stack on '{narrative}' ({len(all_bullish)} signals) BUT insiders beginning to sell ({len(insider_sells)}) in complacent regime.",
            why_it_matters="Crowded trades unwind violently. Insider selling into a bullish consensus is a classic distribution top setup. Trim longs, do not add.",
            metadata={
                "bullish_signal_count": len(all_bullish),
                "insider_sell_count": len(insider_sells),
                "is_sell_side_pattern": True,
                "suggested_action": "REDUCE",  # Hint to intelligence engine
            }
        )]


def summarize_constellations(state: Dict[str, Any], constellations: List[Constellation]) -> Dict[str, Any]:
    """High-level summary for the UI / engine."""
    by_stage = defaultdict(int)
    by_pattern = defaultdict(int)
    early_opportunities = []
    late_warnings = []

    for c in constellations:
        by_stage[c.stage] += 1
        by_pattern[c.pattern_name] += 1
        if c.stage in (STAGE_SCOUT, STAGE_STALKING):
            early_opportunities.append(c.to_dict())
        elif c.stage == STAGE_LATE:
            late_warnings.append(c.to_dict())

    return {
        "total_constellations": len(constellations),
        "by_stage": dict(by_stage),
        "by_pattern": dict(by_pattern),
        "early_opportunities": early_opportunities[:10],
        "late_warnings": late_warnings[:5],
    }
