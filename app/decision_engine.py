"""
Decision Engine - V5.7 "Decision Offload"
==========================================

This is the layer that turns your engine from advisory to decision-making.

Inputs (already produced by V5.4/V5.5/V5.6):
  - Alerts (with intelligence advice)
  - Constellations (multi-feed patterns + lifecycle stages)
  - Velocity readings (acceleration data)
  - Risk intelligence (stops, correlations, sectors, VIX)
  - Open positions

Output: a list of Decision objects, each containing everything a trader needs
to act in 5 seconds:
  - Verdict (action + conviction + time-sensitivity)
  - Sizing (auto-calculated, fully risk-adjusted)
  - Plan (entry/stop/target/trail/time-stop)
  - Why (compressed reasoning)
  - Kill conditions (what makes this wrong)
  - One-line summary

Action vocabulary (expanded from existing):
  ENTER_NEW             - No position, fresh entry
  ADD_TO_EXISTING       - Offensive scale-up on confirming thesis
  AVERAGE_DOWN          - Lower avg cost on a dip with strong reinforcement (gated)
  TAKE_PARTIAL_PROFIT   - Offensive scale-out, lock gains while letting rest run
  REDUCE                - Defensive trim
  EXIT_FULL             - Close position
  AVOID                 - Don't enter (bearish or contraindicated)
  WAIT                  - Hold/monitor (no actionable edge yet)
"""

from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# Action vocabulary
ACTION_ENTER_NEW = "ENTER_NEW"
ACTION_ADD = "ADD_TO_EXISTING"
ACTION_AVG_DOWN = "AVERAGE_DOWN"
ACTION_TAKE_PROFIT = "TAKE_PARTIAL_PROFIT"
ACTION_REDUCE = "REDUCE"
ACTION_EXIT_FULL = "EXIT_FULL"
ACTION_AVOID = "AVOID"
ACTION_WAIT = "WAIT"

OFFENSIVE_ACTIONS = {ACTION_ENTER_NEW, ACTION_ADD, ACTION_AVG_DOWN}
PROFIT_TAKING = {ACTION_TAKE_PROFIT}
DEFENSIVE_ACTIONS = {ACTION_REDUCE, ACTION_EXIT_FULL}
PASSIVE_ACTIONS = {ACTION_AVOID, ACTION_WAIT}

CONVICTION_HIGH = "HIGH"
CONVICTION_MEDIUM = "MEDIUM"
CONVICTION_LOW = "LOW"

URGENCY_ACT_NOW = "ACT_NOW"     # next 30 min
URGENCY_TODAY = "TODAY"          # today's session
URGENCY_THIS_WEEK = "THIS_WEEK"  # this week
URGENCY_WATCH = "WATCH"          # no immediate action


@dataclass
class DecisionPlan:
    """The execution plan for a Decision — entry, stops, targets, trail, time stop."""
    entry_price: float          # Suggested entry/execution price
    entry_zone_low: float       # Low end of acceptable entry zone
    entry_zone_high: float      # High end of acceptable entry zone
    stop_price: float           # Hard stop for the position
    stop_pct_from_entry: float  # Stop expressed as % from entry
    first_target: float         # First profit target
    target_pct_from_entry: float # Target as % from entry
    trail_trigger: float        # Price at which trailing stop activates
    time_stop_days: int         # Exit if no momentum after this many days
    risk_reward_ratio: float    # First target gain / stop loss ratio

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionSizing:
    """Auto-calculated position sizing accounting for VIX/correlation/risk-per-trade/cash."""
    suggested_dollars: float
    suggested_quantity: int
    pct_of_equity: float
    base_dollars: float          # Pre-adjustment baseline
    vix_multiplier: float        # Applied VIX adjustment
    correlation_approved: bool
    correlation_groups: List[str]
    correlation_note: str
    headroom_remaining_pct: float # Additional capacity if thesis confirms more

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Decision:
    """A complete decision package the engine offloads to the user."""
    id: str
    created_at: str
    symbol: str
    narrative: str
    action: str                  # One of ACTION_* constants
    conviction: str              # HIGH / MEDIUM / LOW
    urgency: str                 # ACT_NOW / TODAY / THIS_WEEK / WATCH
    side: str                    # buy / sell
    sizing: Dict[str, Any]       # DecisionSizing.to_dict()
    plan: Dict[str, Any]         # DecisionPlan.to_dict()
    primary_driver: str          # Main constellation/reason
    confirming_feeds: List[str]  # Feed types confirming
    velocity_context: str        # Accelerating/stable/etc
    regime_context: str          # VIX regime
    why: str                     # Compressed multi-sentence reasoning
    kill_conditions: List[str]   # What makes this wrong
    one_line: str                # The summary — read this and decide
    source_alert_id: str         # Link back to alert
    constellation_pattern: str   # Pattern name if from constellation
    constellation_stage: str     # SCOUT/STALKING/STRIKING/LATE
    auto_executable: bool        # Engine eligible for auto-fire?
    executed: bool = False       # Has been acted on?
    executed_at: str = ""
    skipped: bool = False        # User dismissed?
    skipped_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_decision_id() -> str:
    import uuid
    return f"dec_{uuid.uuid4().hex[:10]}"


class DecisionEngine:
    """
    Synthesizes signals + constellations + velocity + risk_intel + positions
    into actionable Decision objects. Rule-based, deterministic.
    """

    # Sizing defaults (settings-overridable)
    DEFAULT_BASE_DOLLARS = 800
    DEFAULT_ADD_DOLLARS = 400        # Offensive add is smaller than fresh entry
    DEFAULT_AVG_DOWN_DOLLARS = 400   # Same as ADD — never bet bigger on a loser
    DEFAULT_TAKE_PROFIT_PCT = 0.30   # Trim 30% by default
    DEFAULT_REDUCE_PCT = 0.40        # Trim 40% on defensive REDUCE
    DEFAULT_TIME_STOP_DAYS = 14      # Stale position exit
    DEFAULT_FIRST_TARGET_PCT = 0.08  # 8% first target

    # Average-down safeguards
    AVG_DOWN_MIN_LOSS = 0.05         # Position must be down at least 5%
    AVG_DOWN_MAX_LOSS = 0.15         # No more than 15% (otherwise it's a falling knife)
    AVG_DOWN_MAX_PER_POSITION = 1    # Max 1 average-down per position

    def __init__(self, state: Dict[str, Any]):
        self.state = state
        if "decisions" not in self.state:
            self.state["decisions"] = []
        if "decision_history" not in self.state:
            self.state["decision_history"] = []
        if "average_down_count" not in self.state:
            self.state["average_down_count"] = {}  # symbol -> count

    def _setting(self, key: str, default: Any) -> Any:
        return self.state.get("settings", {}).get(key, default)

    # ------------------------------------------------------------------
    # Position lookup helpers
    # ------------------------------------------------------------------

    def _existing_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not symbol:
            return None
        positions = self.state.get("positions", {})
        for pos in positions.values():
            if str(pos.get("symbol", "")).upper() == symbol.upper() and int(pos.get("quantity", 0)) > 0:
                return pos
        return None

    def _position_pct_pnl(self, position: Dict[str, Any]) -> float:
        try:
            avg = float(position.get("avg_price", 0))
            mkt = float(position.get("market_price", 0))
            if avg <= 0:
                return 0.0
            return (mkt - avg) / avg
        except (ValueError, TypeError):
            return 0.0

    # ------------------------------------------------------------------
    # Sizing calculation
    # ------------------------------------------------------------------

    def _calculate_sizing(self, symbol: str, price: float, base_dollars: float,
                          existing_position: Optional[Dict[str, Any]] = None) -> DecisionSizing:
        """Auto-size with VIX adjustment and correlation check."""
        from app.risk_intelligence import RiskIntelligence
        ri = RiskIntelligence(self.state)
        vix_mult = ri.vix_size_multiplier()
        adjusted_dollars = base_dollars * vix_mult
        # Cap at cash available
        cash = float(self.state.get("settings", {}).get("cash_balance", 0))
        if adjusted_dollars > cash * 0.95:  # Leave 5% buffer
            adjusted_dollars = cash * 0.95
        suggested_qty = max(1, int(adjusted_dollars / price)) if price > 0 else 0
        actual_dollars = suggested_qty * price
        # Equity for percent calculation
        positions_mv = sum(float(p.get("quantity", 0)) * float(p.get("market_price", 0))
                           for p in self.state.get("positions", {}).values())
        equity = max(1.0, cash + positions_mv)
        # Correlation check
        corr_check = ri.check_correlation_capacity(symbol, actual_dollars)
        # Headroom: if approved, how much more could we add later?
        max_pos_pct = float(self._setting("max_position_pct", 0.12))
        existing_value = (float(existing_position.get("quantity", 0)) * float(existing_position.get("market_price", 0))
                          if existing_position else 0)
        max_position_value = equity * max_pos_pct
        headroom = max(0, max_position_value - existing_value - actual_dollars)
        headroom_pct = (headroom / equity) * 100 if equity > 0 else 0

        return DecisionSizing(
            suggested_dollars=round(actual_dollars, 2),
            suggested_quantity=suggested_qty,
            pct_of_equity=round((actual_dollars / equity) * 100, 2),
            base_dollars=round(base_dollars, 2),
            vix_multiplier=vix_mult,
            correlation_approved=corr_check["approved"],
            correlation_groups=corr_check.get("groups", []),
            correlation_note=corr_check.get("reason", "Approved"),
            headroom_remaining_pct=round(headroom_pct, 2),
        )

    # ------------------------------------------------------------------
    # Plan calculation (entry/stop/target/trail/time stop)
    # ------------------------------------------------------------------

    def _calculate_plan(self, price: float, side: str, regime: str = "normal") -> DecisionPlan:
        """Generate entry zone, stops, targets based on price + regime."""
        # Stop tighter in panic regime, looser in normal
        hard_stop_pct = float(self._setting("hard_stop_pct", 0.07))
        if regime == "panic":
            hard_stop_pct *= 0.7  # Tighter stops in panic
        elif regime == "complacent":
            hard_stop_pct *= 1.2  # Slightly wider in complacent

        target_pct = float(self._setting("first_target_pct", self.DEFAULT_FIRST_TARGET_PCT))
        # Wider targets in trending/elevated regimes
        if regime in ("elevated", "panic"):
            target_pct *= 1.3
        trail_pct = float(self._setting("trail_trigger_pct", 0.06))

        if side == "buy":
            entry_zone_low = price * 0.998   # Allow 0.2% below
            entry_zone_high = price * 1.005  # Allow 0.5% above
            stop_price = price * (1 - hard_stop_pct)
            first_target = price * (1 + target_pct)
            trail_trigger = price * (1 + trail_pct)
        else:  # sell
            entry_zone_low = price * 0.995
            entry_zone_high = price * 1.002
            stop_price = price * (1 + hard_stop_pct)
            first_target = price * (1 - target_pct)
            trail_trigger = price * (1 - trail_pct)

        # Risk/reward
        risk_dollars = abs(price - stop_price)
        reward_dollars = abs(first_target - price)
        rr_ratio = round(reward_dollars / risk_dollars, 2) if risk_dollars > 0 else 0

        return DecisionPlan(
            entry_price=round(price, 4),
            entry_zone_low=round(entry_zone_low, 4),
            entry_zone_high=round(entry_zone_high, 4),
            stop_price=round(stop_price, 4),
            stop_pct_from_entry=round(hard_stop_pct * 100, 2),
            first_target=round(first_target, 4),
            target_pct_from_entry=round(target_pct * 100, 2),
            trail_trigger=round(trail_trigger, 4),
            time_stop_days=int(self._setting("time_stop_days", self.DEFAULT_TIME_STOP_DAYS)),
            risk_reward_ratio=rr_ratio,
        )

    # ------------------------------------------------------------------
    # Verdict logic — what action, conviction, urgency
    # ------------------------------------------------------------------

    def _classify_verdict(self, alert: Dict[str, Any]) -> Tuple[str, str, str]:
        """
        Classify (action, conviction, urgency) based on alert + constellation context.
        """
        meta = alert.get("metadata", {}) if isinstance(alert.get("metadata"), dict) else {}
        advice = meta.get("advice", {}) if isinstance(meta.get("advice"), dict) else {}
        action_advice = str(advice.get("action", "HOLD"))
        score = float(alert.get("shark_score", 0))
        symbol = alert.get("primary_symbol", "")
        existing = self._existing_position(symbol)
        position_pnl = self._position_pct_pnl(existing) if existing else 0.0
        # Look up matching constellation
        constellation = self._find_matching_constellation(alert)
        c_stage = (constellation.get("stage") if constellation else "")
        c_pattern = (constellation.get("pattern_name") if constellation else "")
        c_conf = float(constellation.get("confidence", 0)) if constellation else 0
        c_meta = (constellation.get("metadata", {}) or {}) if constellation else {}

        # === DEFENSIVE LOGIC FIRST ===
        # If advice already said REDUCE, that's defensive trim
        if action_advice == "REDUCE":
            return ACTION_REDUCE, CONVICTION_MEDIUM, URGENCY_ACT_NOW
        if action_advice in ("SELL", "STRONG_SELL"):
            if existing:
                return ACTION_EXIT_FULL, CONVICTION_HIGH if action_advice == "STRONG_SELL" else CONVICTION_MEDIUM, URGENCY_ACT_NOW
            else:
                return ACTION_AVOID, CONVICTION_MEDIUM, URGENCY_WATCH

        # === OFFENSIVE/PROFIT-TAKING LOGIC ===
        if action_advice in ("BUY", "STRONG_BUY"):
            # Already long?
            if existing:
                # Profit-taking opportunity? Position significantly up + STRIKING stage = lock partial
                if position_pnl >= 0.15 and c_stage == "STRIKING":
                    return ACTION_TAKE_PROFIT, CONVICTION_HIGH, URGENCY_ACT_NOW
                if position_pnl >= 0.20:
                    return ACTION_TAKE_PROFIT, CONVICTION_MEDIUM, URGENCY_TODAY

                # ADD opportunity? Profitable + strong fresh signal = scale up winner
                if position_pnl > 0 and c_stage in ("STALKING", "STRIKING") and c_conf >= 0.65:
                    if action_advice == "STRONG_BUY":
                        return ACTION_ADD, CONVICTION_HIGH, URGENCY_ACT_NOW
                    return ACTION_ADD, CONVICTION_MEDIUM, URGENCY_TODAY

                # AVERAGE_DOWN opportunity? (gated)
                if (self._setting("enable_average_down", True) and
                        self.AVG_DOWN_MIN_LOSS <= -position_pnl <= self.AVG_DOWN_MAX_LOSS and
                        self._can_average_down(symbol) and
                        c_stage in ("SCOUT", "STALKING") and
                        c_conf >= 0.55 and
                        not self._has_contradicting_low_noise(alert)):
                    # Conviction LOWER than entries — averaging down is risky
                    return ACTION_AVG_DOWN, CONVICTION_MEDIUM, URGENCY_TODAY

                # Otherwise: already long, no add reason → wait
                return ACTION_WAIT, CONVICTION_LOW, URGENCY_WATCH

            # No existing position — ENTER_NEW
            if action_advice == "STRONG_BUY":
                # SCOUT/STALKING = early & worth acting; STRIKING = act now; LATE = avoid
                if c_stage == "LATE":
                    return ACTION_AVOID, CONVICTION_MEDIUM, URGENCY_WATCH
                if c_stage in ("STRIKING",):
                    return ACTION_ENTER_NEW, CONVICTION_HIGH, URGENCY_ACT_NOW
                if c_stage in ("STALKING",):
                    return ACTION_ENTER_NEW, CONVICTION_MEDIUM, URGENCY_ACT_NOW
                if c_stage == "SCOUT":
                    return ACTION_ENTER_NEW, CONVICTION_MEDIUM, URGENCY_TODAY
                # No constellation but STRONG_BUY = good
                return ACTION_ENTER_NEW, CONVICTION_MEDIUM, URGENCY_TODAY
            else:  # BUY (not STRONG_BUY)
                if c_stage == "LATE":
                    return ACTION_AVOID, CONVICTION_MEDIUM, URGENCY_WATCH
                if c_stage in ("STRIKING", "STALKING"):
                    return ACTION_ENTER_NEW, CONVICTION_MEDIUM, URGENCY_TODAY
                return ACTION_WAIT, CONVICTION_LOW, URGENCY_WATCH

        # HOLD or unclassified
        return ACTION_WAIT, CONVICTION_LOW, URGENCY_WATCH

    def _find_matching_constellation(self, alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        constellations = self.state.get("constellations", []) or []
        narrative = alert.get("narrative", "")
        symbol = alert.get("primary_symbol", "")
        matching = [c for c in constellations
                    if c.get("primary_narrative") == narrative or c.get("primary_symbol") == symbol]
        if not matching:
            return None
        stage_priority = {"STRIKING": 0, "STALKING": 1, "SCOUT": 2, "LATE": 3}
        matching.sort(key=lambda c: (stage_priority.get(c.get("stage", "LATE"), 99),
                                     -float(c.get("confidence", 0))))
        return matching[0]

    def _can_average_down(self, symbol: str) -> bool:
        """Has this position already been averaged down?"""
        count = int(self.state.get("average_down_count", {}).get(symbol.upper(), 0))
        return count < self.AVG_DOWN_MAX_PER_POSITION

    def _has_contradicting_low_noise(self, alert: Dict[str, Any]) -> bool:
        """Check if low-noise feeds disagree with the buy thesis."""
        meta = alert.get("metadata", {}) if isinstance(alert.get("metadata"), dict) else {}
        contributing = meta.get("contributing_signals", []) or alert.get("signals", []) or []
        for sig in contributing:
            if not isinstance(sig, dict):
                continue
            sig_meta = sig.get("metadata", {}) if isinstance(sig.get("metadata"), dict) else {}
            if sig_meta.get("noise_level") == "low" and sig.get("direction") == "SELL":
                return True
        return False

    # ------------------------------------------------------------------
    # Build Decision objects
    # ------------------------------------------------------------------

    def _build_kill_conditions(self, action: str, alert: Dict[str, Any],
                                constellation: Optional[Dict[str, Any]]) -> List[str]:
        """Generate explicit 'what makes this wrong' conditions."""
        conditions = []
        if action in (ACTION_ENTER_NEW, ACTION_ADD, ACTION_AVG_DOWN):
            conditions.append("Exit if VIX spikes above panic threshold")
            conditions.append("Exit if Distribution Pattern fires on this narrative")
            conditions.append("Exit if low-noise feeds turn bearish")
            if constellation and constellation.get("pattern_name") == "Smart Money Positioning":
                conditions.append("Exit if news volume spikes (smart money advantage gone)")
            if constellation and constellation.get("stage") == "STALKING":
                conditions.append("Reassess if pattern doesn't reach STRIKING within 5 days")
        elif action == ACTION_TAKE_PROFIT:
            conditions.append("Skip if velocity still strongly accelerating up")
            conditions.append("Reverse to ADD if STRIKING + accelerating confirms")
        elif action == ACTION_REDUCE:
            conditions.append("Reverse if low-noise feeds re-confirm thesis")
            conditions.append("Skip if regime returns to normal within 2 hours")
        return conditions

    def _build_one_line(self, action: str, sizing: DecisionSizing, plan: DecisionPlan,
                          symbol: str, constellation: Optional[Dict[str, Any]],
                          existing: Optional[Dict[str, Any]]) -> str:
        """The compressed summary — read this and decide in 5 seconds."""
        pattern = constellation.get("pattern_name") if constellation else "multi-feed signal"
        stage = constellation.get("stage") if constellation else ""
        stage_str = f" {stage}" if stage else ""

        if action == ACTION_ENTER_NEW:
            return (f"ENTER ${sizing.suggested_dollars:,.0f} {symbol} @ ${plan.entry_price:.2f}. "
                    f"Stop ${plan.stop_price:.2f}, target ${plan.first_target:.2f} (R:R {plan.risk_reward_ratio}:1). "
                    f"{pattern}{stage_str}.")
        elif action == ACTION_ADD:
            return (f"ADD ${sizing.suggested_dollars:,.0f} to {symbol} @ ${plan.entry_price:.2f}. "
                    f"Position currently profitable, thesis confirming via {pattern}{stage_str}.")
        elif action == ACTION_AVG_DOWN:
            avg = float(existing.get("avg_price", 0)) if existing else 0
            return (f"AVERAGE DOWN ${sizing.suggested_dollars:,.0f} {symbol} @ ${plan.entry_price:.2f} "
                    f"(prev avg ${avg:.2f}). {pattern}{stage_str} reinforcing thesis. "
                    f"⚠️ One-shot only — no second average-down on this position.")
        elif action == ACTION_TAKE_PROFIT:
            qty_to_sell = int(int(existing.get("quantity", 0)) * self.DEFAULT_TAKE_PROFIT_PCT) if existing else 0
            return (f"TAKE PROFIT: sell {qty_to_sell} of {symbol} @ ${plan.entry_price:.2f} "
                    f"(~{int(self.DEFAULT_TAKE_PROFIT_PCT*100)}% of position). Lock gains, let rest run.")
        elif action == ACTION_REDUCE:
            qty_to_reduce = int(int(existing.get("quantity", 0)) * self.DEFAULT_REDUCE_PCT) if existing else 0
            return (f"REDUCE: trim {qty_to_reduce} of {symbol} @ ${plan.entry_price:.2f} "
                    f"(~{int(self.DEFAULT_REDUCE_PCT*100)}% of position). Defensive trim.")
        elif action == ACTION_EXIT_FULL:
            qty = int(existing.get("quantity", 0)) if existing else 0
            return f"EXIT FULL: sell all {qty} of {symbol} @ ${plan.entry_price:.2f}. {pattern}{stage_str}."
        elif action == ACTION_AVOID:
            return f"AVOID {symbol}: {pattern}{stage_str} contraindicates entry."
        else:  # WAIT
            return f"WAIT on {symbol}: monitoring {pattern}{stage_str}."

    def build_decisions(self) -> List[Decision]:
        """Main entry — generate decision packages from current state."""
        from app.market_data import MarketDataService
        market = MarketDataService(self.state)

        decisions: List[Decision] = []
        alerts = self.state.get("alerts", []) or []
        # Min score threshold for decision generation
        min_score = float(self._setting("decision_min_score", 65))

        for alert in alerts:
            score = float(alert.get("shark_score", 0))
            if score < min_score:
                continue
            symbol = alert.get("primary_symbol", "")
            if not symbol:
                continue

            action, conviction, urgency = self._classify_verdict(alert)
            # Skip pure WAIT decisions to keep the queue actionable
            if action == ACTION_WAIT:
                continue

            existing = self._existing_position(symbol)
            constellation = self._find_matching_constellation(alert)

            # Get current quote
            try:
                quote = market.quote(symbol)
                price = float(quote.get("last", 0))
            except Exception:
                continue
            if price <= 0:
                continue

            # Determine side and base sizing dollars
            if action in (ACTION_ENTER_NEW,):
                side = "buy"
                base_dollars = float(self._setting("decision_base_dollars", self.DEFAULT_BASE_DOLLARS))
            elif action == ACTION_ADD:
                side = "buy"
                base_dollars = float(self._setting("decision_add_dollars", self.DEFAULT_ADD_DOLLARS))
            elif action == ACTION_AVG_DOWN:
                side = "buy"
                base_dollars = float(self._setting("decision_avg_down_dollars", self.DEFAULT_AVG_DOWN_DOLLARS))
            elif action in (ACTION_TAKE_PROFIT, ACTION_REDUCE):
                side = "sell"
                if existing:
                    qty_to_trim_pct = (self.DEFAULT_TAKE_PROFIT_PCT
                                       if action == ACTION_TAKE_PROFIT else self.DEFAULT_REDUCE_PCT)
                    base_dollars = float(existing.get("quantity", 0)) * price * qty_to_trim_pct
                else:
                    continue  # No position to trim — skip
            elif action == ACTION_EXIT_FULL:
                side = "sell"
                if existing:
                    base_dollars = float(existing.get("quantity", 0)) * price
                else:
                    continue
            else:  # AVOID
                side = "buy"
                base_dollars = 0

            # Sizing (skip for AVOID)
            if action != ACTION_AVOID:
                sizing = self._calculate_sizing(symbol, price, base_dollars, existing)
                # If correlation rejected, downgrade to WAIT
                if not sizing.correlation_approved and action in (ACTION_ENTER_NEW, ACTION_ADD, ACTION_AVG_DOWN):
                    action = ACTION_WAIT
                    continue
            else:
                sizing = DecisionSizing(
                    suggested_dollars=0, suggested_quantity=0, pct_of_equity=0,
                    base_dollars=0, vix_multiplier=1.0, correlation_approved=True,
                    correlation_groups=[], correlation_note="N/A for AVOID",
                    headroom_remaining_pct=0,
                )

            # Regime context for plan
            regime = "normal"
            for sig in self.state.get("signals", []):
                if not isinstance(sig, dict):
                    continue
                sig_meta = sig.get("metadata", {}) or {}
                if sig_meta.get("is_regime_context"):
                    regime = sig_meta.get("regime", "normal")
                    break

            plan = self._calculate_plan(price, side, regime)
            kill_conditions = self._build_kill_conditions(action, alert, constellation)

            # Why text
            meta = alert.get("metadata", {}) if isinstance(alert.get("metadata"), dict) else {}
            advice = meta.get("advice", {}) if isinstance(meta.get("advice"), dict) else {}
            why_parts = [advice.get("reason", "")]
            if constellation:
                why_parts.append(f"Constellation: {constellation.get('pattern_name')} [{constellation.get('stage')}] (conf {constellation.get('confidence', 0):.2f})")
            if existing:
                pnl = self._position_pct_pnl(existing) * 100
                why_parts.append(f"Existing position: {existing.get('quantity', 0)} @ ${existing.get('avg_price', 0):.2f} ({pnl:+.1f}% PnL)")

            # Velocity context
            velocity_context = "stable"
            for r in self.state.get("velocity_readings", []):
                if isinstance(r, dict) and symbol in r.get("channel", "") and r.get("acceleration") == "ACCELERATING_UP":
                    velocity_context = "accelerating up"
                    break

            one_line = self._build_one_line(action, sizing, plan, symbol, constellation, existing)

            # Auto-executable? (paper trades only; aggressive mode for ENTER_NEW + ADD only)
            auto_exec = False
            if (self._setting("enable_auto_execute", False)
                    and self.state.get("settings", {}).get("broker_backend") == "paper"
                    and conviction == CONVICTION_HIGH
                    and urgency == URGENCY_ACT_NOW
                    and action in (ACTION_ENTER_NEW, ACTION_ADD, ACTION_REDUCE, ACTION_EXIT_FULL)):
                auto_exec = True

            decision = Decision(
                id=_new_decision_id(),
                created_at=_now_iso(),
                symbol=symbol,
                narrative=alert.get("narrative", ""),
                action=action,
                conviction=conviction,
                urgency=urgency,
                side=side,
                sizing=sizing.to_dict(),
                plan=plan.to_dict(),
                primary_driver=(constellation.get("pattern_name") if constellation else "multi-feed alert"),
                confirming_feeds=meta.get("feed_types", []) or [],
                velocity_context=velocity_context,
                regime_context=regime,
                why=" | ".join([w for w in why_parts if w]),
                kill_conditions=kill_conditions,
                one_line=one_line,
                source_alert_id=str(alert.get("id", "")),
                constellation_pattern=(constellation.get("pattern_name", "") if constellation else ""),
                constellation_stage=(constellation.get("stage", "") if constellation else ""),
                auto_executable=auto_exec,
            )
            decisions.append(decision)

        # Sort: ACT_NOW first, then by conviction
        urgency_order = {URGENCY_ACT_NOW: 0, URGENCY_TODAY: 1, URGENCY_THIS_WEEK: 2, URGENCY_WATCH: 3}
        conviction_order = {CONVICTION_HIGH: 0, CONVICTION_MEDIUM: 1, CONVICTION_LOW: 2}
        decisions.sort(key=lambda d: (urgency_order.get(d.urgency, 99), conviction_order.get(d.conviction, 99)))

        # Persist
        self.state["decisions"] = [d.to_dict() for d in decisions]
        return decisions

    def summary(self) -> Dict[str, Any]:
        decisions = self.state.get("decisions", []) or []
        from collections import Counter
        action_counts = Counter(d.get("action", "") for d in decisions)
        urgency_counts = Counter(d.get("urgency", "") for d in decisions)
        conviction_counts = Counter(d.get("conviction", "") for d in decisions)
        auto_eligible = sum(1 for d in decisions if d.get("auto_executable"))
        return {
            "total": len(decisions),
            "by_action": dict(action_counts),
            "by_urgency": dict(urgency_counts),
            "by_conviction": dict(conviction_counts),
            "auto_executable": auto_eligible,
            "act_now_high_conviction": sum(1 for d in decisions
                                           if d.get("urgency") == URGENCY_ACT_NOW
                                           and d.get("conviction") == CONVICTION_HIGH),
        }
