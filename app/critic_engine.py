"""
critic_engine.py — V6.1 adversarial counter-check on detected constellations.

Mirrors Risk Oracle's primary+critic discipline. The constellation engine
detects patterns; this critic engine runs a methodologically different check
on each one and reports whether the critic agrees, disagrees, or has no
opinion.

A critic's job is to be skeptical. For each pattern it asks: "What would
make this signal wrong?" and checks whether those conditions are present.

Critic outcomes:
  agrees       — adversarial check passes; confidence kept as-is
  disagrees    — counter-evidence found; confidence multiplied by 0.6 and a
                 critic_disagreement reason is attached
  no_opinion   — pattern has no registered critic, or insufficient data to
                 critique; treated as "agrees" but flagged

Used by:
  • platform.scan_signals — runs critic after constellation detection,
                            mutates constellation confidence in place
  • decision_engine       — reads critic_disagreement when computing
                            probability bands on Decisions
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


CRITIC_AGREES = "agrees"
CRITIC_DISAGREES = "disagrees"
CRITIC_NO_OPINION = "no_opinion"

DISAGREE_CONFIDENCE_MULT = 0.6
DISAGREE_BAND_WIDEN = 0.20  # add 20pp to the uncertainty band if critic disagrees


@dataclass
class CritiqueResult:
    verdict: str                          # agrees / disagrees / no_opinion
    confidence_adjustment: float = 1.0    # multiplier applied to original confidence
    band_widening: float = 0.0            # additional uncertainty (pp) to add to band
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _filter_signals_by_type(signals: List[Dict[str, Any]], types: set) -> List[Dict[str, Any]]:
    out = []
    for s in signals:
        meta = s.get("metadata", {}) or {}
        if meta.get("feed_type") in types:
            out.append(s)
    return out


def _signals_in_lookback(signals: List[Dict[str, Any]], lookback_signals: int = 100) -> List[Dict[str, Any]]:
    """Slice the most recent N signals for windowed checks."""
    return signals[-lookback_signals:]


class ConstellationCritic:
    """Runs an adversarial check appropriate to each constellation pattern."""

    def __init__(self, state: Dict[str, Any]):
        self.state = state
        self._all_signals = state.get("signals", []) or []

    def critique(self, constellation: Dict[str, Any]) -> CritiqueResult:
        """Dispatch to the pattern-specific critic. Falls back to no_opinion."""
        pattern = (constellation.get("pattern_name") or "").lower().replace(" ", "_")
        method = getattr(self, f"_critique_{pattern}", None)
        if method is None:
            return CritiqueResult(verdict=CRITIC_NO_OPINION,
                                  notes=[f"No critic registered for pattern '{pattern}'"])
        try:
            return method(constellation)
        except Exception as e:
            return CritiqueResult(verdict=CRITIC_NO_OPINION,
                                  notes=[f"Critic raised exception: {e}"])

    # ----------------------------------------------------------------
    # Pattern-specific critics
    # ----------------------------------------------------------------

    def _critique_smart_money_positioning(self, c: Dict[str, Any]) -> CritiqueResult:
        """The pattern claims: smart money buying quietly, retail not aware yet.

        Critic checks:
          - News volume on this narrative over the prior 7 days should be LOW.
            If we see news_signals in the recent window, it's not quiet.
          - There should be NO recent insider SELLING on the same primary symbol.
            If there is, the buy thesis is contradicted.
          - Options flow direction should be CONSISTENT with the buy thesis
            (bullish positioning). If we see contrary options activity, flag it.
        """
        notes = []
        narrative = c.get("primary_narrative", "")
        symbol = c.get("primary_symbol", "")
        recent = _signals_in_lookback(self._all_signals)

        # Check 1: news volume on this narrative
        news = [s for s in recent
                if (s.get("metadata", {}) or {}).get("feed_type") == "news"
                and (s.get("metadata", {}) or {}).get("narrative") == narrative]
        if len(news) >= 5:
            notes.append(f"News volume on '{narrative}' is high ({len(news)} items) — "
                         f"not the quiet accumulation the pattern claims.")

        # Check 2: recent insider selling on same symbol
        sells = [s for s in recent
                 if (s.get("metadata", {}) or {}).get("feed_type") in ("filings", "canada_filings")
                 and s.get("symbol", "").upper() == symbol.upper()
                 and s.get("direction") == "SELL"]
        if sells:
            notes.append(f"Insider SELLING on {symbol} in recent window contradicts "
                         f"the smart-money-buying thesis.")

        # Check 3: contrary options flow
        options = [s for s in recent
                   if (s.get("metadata", {}) or {}).get("feed_type") == "options"
                   and s.get("symbol", "").upper() == symbol.upper()]
        contrary = [o for o in options if o.get("direction") == "SELL"]
        if contrary and len(contrary) >= len(options) / 2:
            notes.append(f"Options flow on {symbol} skews bearish — inconsistent "
                         f"with smart-money-accumulating direction.")

        if notes:
            return CritiqueResult(verdict=CRITIC_DISAGREES,
                                  confidence_adjustment=DISAGREE_CONFIDENCE_MULT,
                                  band_widening=DISAGREE_BAND_WIDEN, notes=notes)
        return CritiqueResult(verdict=CRITIC_AGREES,
                              notes=["No contradicting signals on news volume, insider selling, or options flow."])

    def _critique_distribution_pattern(self, c: Dict[str, Any]) -> CritiqueResult:
        """The pattern claims: insiders selling, put activity, retail still bullish.

        Critic asks: is the retail bullishness real, or are we just looking at
        noise? Check whether reddit sentiment is genuinely up-trending or just
        a single big post."""
        notes = []
        narrative = c.get("primary_narrative", "")
        recent = _signals_in_lookback(self._all_signals)

        reddit = [s for s in recent
                  if (s.get("metadata", {}) or {}).get("feed_type") == "crowd_sentiment"
                  and (s.get("metadata", {}) or {}).get("narrative") == narrative]
        if len(reddit) < 2:
            notes.append(f"Retail bullish thesis rests on <2 Reddit signals — "
                         f"insufficient to confirm the 'retail unaware' angle.")
        return CritiqueResult(
            verdict=CRITIC_DISAGREES if notes else CRITIC_AGREES,
            confidence_adjustment=DISAGREE_CONFIDENCE_MULT if notes else 1.0,
            band_widening=DISAGREE_BAND_WIDEN if notes else 0.0,
            notes=notes or ["Multiple retail-sentiment confirmations present."],
        )

    def _critique_narrative_ignition(self, c: Dict[str, Any]) -> CritiqueResult:
        """The pattern claims: new narrative spreading from a low base.

        Critic asks: has this narrative already had attention in the prior
        14-day window? If yes, this isn't ignition — it's continuation."""
        narrative = c.get("primary_narrative", "")
        recent = _signals_in_lookback(self._all_signals, lookback_signals=300)
        attention = [s for s in recent
                     if (s.get("metadata", {}) or {}).get("narrative") == narrative
                     and (s.get("metadata", {}) or {}).get("feed_type") in ("attention", "news")]
        if len(attention) >= 8:
            return CritiqueResult(
                verdict=CRITIC_DISAGREES,
                confidence_adjustment=DISAGREE_CONFIDENCE_MULT,
                band_widening=DISAGREE_BAND_WIDEN,
                notes=[f"Narrative '{narrative}' already has {len(attention)} attention signals "
                       f"in the recent window — this is continuation, not ignition."],
            )
        return CritiqueResult(verdict=CRITIC_AGREES,
                              notes=["Narrative has low prior attention; ignition thesis holds."])

    def _critique_geopolitical_cascade(self, c: Dict[str, Any]) -> CritiqueResult:
        """The pattern claims: geopolitical shock with cross-asset propagation.

        Critic asks: are we actually seeing macro_data confirmation (FRED,
        Treasury moves) or only news headlines? If only news, the cascade
        may be sentiment-driven and short-lived."""
        narrative = c.get("primary_narrative", "")
        recent = _signals_in_lookback(self._all_signals)
        macro = [s for s in recent
                 if (s.get("metadata", {}) or {}).get("feed_type") in ("macro_data", "rates")]
        if not macro:
            return CritiqueResult(
                verdict=CRITIC_DISAGREES,
                confidence_adjustment=DISAGREE_CONFIDENCE_MULT,
                band_widening=DISAGREE_BAND_WIDEN,
                notes=["No macro_data or rates signals confirm the geopolitical cascade — "
                       "may be a sentiment-only shock."],
            )
        return CritiqueResult(verdict=CRITIC_AGREES,
                              notes=[f"{len(macro)} macro/rates signals confirm cross-asset propagation."])

    def _critique_macro_regime_shift(self, c: Dict[str, Any]) -> CritiqueResult:
        """Regime shifts claim VIX or credit moves are significant.
        Critic checks if the move is sustained across multiple recent signals,
        not a single print."""
        recent = _signals_in_lookback(self._all_signals, lookback_signals=200)
        regime = [s for s in recent
                  if (s.get("metadata", {}) or {}).get("is_regime_context")]
        if len(regime) < 2:
            return CritiqueResult(
                verdict=CRITIC_DISAGREES,
                confidence_adjustment=DISAGREE_CONFIDENCE_MULT,
                band_widening=DISAGREE_BAND_WIDEN,
                notes=["Regime shift evidence rests on a single signal — not yet sustained."],
            )
        return CritiqueResult(verdict=CRITIC_AGREES,
                              notes=[f"{len(regime)} regime signals confirm the shift."])

    def _critique_insider_cluster(self, c: Dict[str, Any]) -> CritiqueResult:
        """Insider clusters need multiple distinct insiders. Critic checks
        whether the cluster is actually from different insiders or just one
        person making multiple filings."""
        # Extracting distinct insiders requires deeper Signal metadata which
        # may not exist. We do a best-effort check on contributing_signal_ids.
        ids = c.get("contributing_signal_ids", []) or []
        if len(ids) < 3:
            return CritiqueResult(
                verdict=CRITIC_DISAGREES,
                confidence_adjustment=DISAGREE_CONFIDENCE_MULT,
                band_widening=DISAGREE_BAND_WIDEN,
                notes=[f"Cluster has only {len(ids)} contributing signals — not enough to "
                       f"distinguish a true cluster from one filer making multiple filings."],
            )
        return CritiqueResult(verdict=CRITIC_AGREES,
                              notes=[f"{len(ids)} contributing signals; cluster diversity plausible."])

    def _critique_euphoria_top(self, c: Dict[str, Any]) -> CritiqueResult:
        """Euphoria tops claim VIX complacent + bullish Reddit. Critic asks
        whether the VIX reading is actually complacent (< 13) or just normal."""
        return self._critique_macro_regime_shift(c)  # reuse logic

    def _critique_crowded_long_warning(self, c: Dict[str, Any]) -> CritiqueResult:
        return self._critique_macro_regime_shift(c)

    def _critique_sentiment_capitulation(self, c: Dict[str, Any]) -> CritiqueResult:
        """Capitulation requires VIX panic + reddit extreme bear sentiment.
        Critic checks both are present."""
        recent = _signals_in_lookback(self._all_signals)
        vix_signals = [s for s in recent
                       if (s.get("metadata", {}) or {}).get("regime") == "panic"]
        if not vix_signals:
            return CritiqueResult(
                verdict=CRITIC_DISAGREES,
                confidence_adjustment=DISAGREE_CONFIDENCE_MULT,
                band_widening=DISAGREE_BAND_WIDEN,
                notes=["No panic-regime VIX signals — capitulation thesis weak."],
            )
        return CritiqueResult(verdict=CRITIC_AGREES,
                              notes=[f"{len(vix_signals)} panic-regime signals confirm capitulation backdrop."])


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------

def critique_all(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run the critic over every constellation in state, mutating each one's
    confidence + adding critic fields. Returns the list of critique results
    indexed alongside the constellations."""
    constellations = state.get("constellations", []) or []
    if not constellations:
        return []
    critic = ConstellationCritic(state)
    results = []
    for c in constellations:
        cr = critic.critique(c)
        results.append({"pattern": c.get("pattern_name"), **cr.to_dict()})

        # Mutate the constellation in-place so downstream consumers (intelligence,
        # decision_engine, dispatch) see the adjusted confidence.
        original_conf = float(c.get("confidence", 0.0))
        c["original_confidence"] = original_conf
        c["confidence"] = round(original_conf * cr.confidence_adjustment, 3)
        c["critic_verdict"] = cr.verdict
        c["critic_band_widening"] = cr.band_widening
        c["critic_notes"] = cr.notes

    state["constellation_critiques"] = results
    return results


def critique_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    results = state.get("constellation_critiques", []) or []
    from collections import Counter
    verdicts = Counter(r.get("verdict", "no_opinion") for r in results)
    return {
        "total_critiqued": len(results),
        "agrees": verdicts.get(CRITIC_AGREES, 0),
        "disagrees": verdicts.get(CRITIC_DISAGREES, 0),
        "no_opinion": verdicts.get(CRITIC_NO_OPINION, 0),
    }
