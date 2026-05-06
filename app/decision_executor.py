"""
Decision Executor - V5.7
========================

Executes Decision objects. Two modes:

1. MANUAL — User clicks execute on a Decision card. Works for paper OR IBKR.
2. AUTO — Engine fires automatically. HARDCODED PAPER-ONLY.

The auto-execute safety gate is non-negotiable:
  - If broker_backend != "paper", auto-execute is FORCIBLY DISABLED
  - Even if enable_auto_execute=True in settings, IBKR mode ignores it
  - This protects real money even if the user forgets to flip the setting back

The executor:
  - Validates the decision is still actionable (price hasn't moved away from entry zone)
  - Calls the existing place_order flow (which does its own risk gates)
  - Records execution in journal with full decision context
  - For AVERAGE_DOWN, increments the per-position counter
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionExecutor:
    """Executes Decision objects. Respects paper-only auto-execute hard gate."""

    def __init__(self, platform):
        # Avoid circular import — accept platform instance
        self.p = platform
        self.state = platform.state

    # ------------------------------------------------------------------
    # The hard safety gate
    # ------------------------------------------------------------------

    def is_auto_execute_active(self) -> bool:
        """
        Returns True ONLY IF:
          - broker_backend is exactly 'paper'
          - enable_auto_execute setting is True
        Real-money auto-execute is impossible — hardcoded.
        """
        backend = self.state.get("settings", {}).get("broker_backend", "paper")
        if backend != "paper":
            return False
        return bool(self.state.get("settings", {}).get("enable_auto_execute", False))

    # ------------------------------------------------------------------
    # Find a decision by ID
    # ------------------------------------------------------------------

    def _find_decision(self, decision_id: str) -> Optional[Dict[str, Any]]:
        for d in self.state.get("decisions", []) or []:
            if d.get("id") == decision_id:
                return d
        return None

    def _mark_executed(self, decision_id: str, success: bool, result: Dict[str, Any]) -> None:
        for d in self.state.get("decisions", []) or []:
            if d.get("id") == decision_id:
                d["executed"] = success
                d["executed_at"] = _now_iso()
                d["execution_result"] = result
                # Move to history
                if "decision_history" not in self.state:
                    self.state["decision_history"] = []
                self.state["decision_history"].append(dict(d))
                break
        # Remove from active list once executed
        self.state["decisions"] = [d for d in self.state.get("decisions", []) if d.get("id") != decision_id]

    def _mark_skipped(self, decision_id: str) -> None:
        for d in self.state.get("decisions", []) or []:
            if d.get("id") == decision_id:
                d["skipped"] = True
                d["skipped_at"] = _now_iso()
                if "decision_history" not in self.state:
                    self.state["decision_history"] = []
                self.state["decision_history"].append(dict(d))
                break
        self.state["decisions"] = [d for d in self.state.get("decisions", []) if d.get("id") != decision_id]

    # ------------------------------------------------------------------
    # Execute a single decision
    # ------------------------------------------------------------------

    def execute(self, decision_id: str, allow_real_money_auto: bool = False) -> Dict[str, Any]:
        """
        Execute a Decision. allow_real_money_auto must NEVER be set by the engine —
        only by user-driven manual execution paths.
        """
        d = self._find_decision(decision_id)
        if not d:
            return {"ok": False, "error": "Decision not found or already executed"}

        symbol = d.get("symbol", "")
        action = d.get("action", "")
        side = d.get("side", "buy")
        sizing = d.get("sizing", {}) or {}
        plan = d.get("plan", {}) or {}
        backend = self.state.get("settings", {}).get("broker_backend", "paper")

        # Re-validate price hasn't drifted out of entry zone
        try:
            quote = self.p.market.quote(symbol)
            current_price = float(quote.get("last", 0))
        except Exception as e:
            return {"ok": False, "error": f"Could not get quote: {e}"}
        if current_price <= 0:
            return {"ok": False, "error": "Invalid quote"}

        zone_low = float(plan.get("entry_zone_low", 0))
        zone_high = float(plan.get("entry_zone_high", 0))
        if zone_low > 0 and zone_high > 0:
            if current_price < zone_low or current_price > zone_high:
                drift_pct = ((current_price - float(plan.get("entry_price", current_price))) /
                             max(0.001, float(plan.get("entry_price", current_price)))) * 100
                return {"ok": False,
                        "error": f"Price drifted out of entry zone (now ${current_price:.2f}, was ${plan.get('entry_price', 0):.2f}, {drift_pct:+.2f}%). Decision rejected."}

        # Build order
        if action in ("ENTER_NEW", "ADD_TO_EXISTING", "AVERAGE_DOWN"):
            quantity = int(sizing.get("suggested_quantity", 0))
        elif action in ("TAKE_PARTIAL_PROFIT", "REDUCE", "EXIT_FULL"):
            # Quantity calculated from existing position
            existing = None
            for pos in self.state.get("positions", {}).values():
                if str(pos.get("symbol", "")).upper() == symbol.upper():
                    existing = pos
                    break
            if not existing:
                return {"ok": False, "error": "No existing position to trim/exit"}
            existing_qty = int(existing.get("quantity", 0))
            if action == "TAKE_PARTIAL_PROFIT":
                quantity = max(1, int(existing_qty * 0.30))
            elif action == "REDUCE":
                quantity = max(1, int(existing_qty * 0.40))
            else:  # EXIT_FULL
                quantity = existing_qty
        else:
            return {"ok": False, "error": f"Action {action} is not executable"}

        if quantity <= 0:
            return {"ok": False, "error": "Computed quantity is zero"}

        order = {
            "symbol": symbol,
            "asset_type": "stock",
            "side": side,
            "quantity": quantity,
            "order_type": "market",
            "mark_price": current_price,
            "spread_bps": quote.get("spread_bps", 0),
            "notes": f"Decision {decision_id} | {action} | {d.get('one_line', '')}",
            "alert_id": d.get("source_alert_id", ""),
            "decision_id": decision_id,
        }

        # Place order through existing flow (which has its own risk gates)
        try:
            result = self.p.place_order(order)
        except Exception as e:
            return {"ok": False, "error": f"Order placement failed: {e}"}

        if result.get("ok"):
            # AVERAGE_DOWN: increment per-position counter
            if action == "AVERAGE_DOWN":
                self.state.setdefault("average_down_count", {})
                key = symbol.upper()
                self.state["average_down_count"][key] = self.state["average_down_count"].get(key, 0) + 1

            self._mark_executed(decision_id, True, result)

            # Journal entry
            self.state.setdefault("journal", []).append({
                "ts": _now_iso(),
                "event": "decision_executed",
                "decision_id": decision_id,
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "price": current_price,
                "backend": backend,
                "auto": allow_real_money_auto if backend != "paper" else False,
                "one_line": d.get("one_line", ""),
            })
            self.p.save()
            return {"ok": True, "decision_id": decision_id, "order": result.get("order"), "decision": d}
        else:
            # Failed — keep decision in queue, don't mark executed
            self.state.setdefault("journal", []).append({
                "ts": _now_iso(),
                "event": "decision_execution_failed",
                "decision_id": decision_id,
                "symbol": symbol,
                "action": action,
                "error": result.get("error", "Unknown"),
            })
            self.p.save()
            return {"ok": False, "error": result.get("error", "Unknown"), "decision": d}

    # ------------------------------------------------------------------
    # Skip / dismiss
    # ------------------------------------------------------------------

    def skip(self, decision_id: str) -> Dict[str, Any]:
        d = self._find_decision(decision_id)
        if not d:
            return {"ok": False, "error": "Decision not found"}
        self._mark_skipped(decision_id)
        self.state.setdefault("journal", []).append({
            "ts": _now_iso(),
            "event": "decision_skipped",
            "decision_id": decision_id,
            "symbol": d.get("symbol"),
            "action": d.get("action"),
            "one_line": d.get("one_line"),
        })
        self.p.save()
        return {"ok": True, "decision_id": decision_id}

    # ------------------------------------------------------------------
    # Auto-execute pass (called on each scan when conditions met)
    # ------------------------------------------------------------------

    def run_auto_execute_pass(self) -> List[Dict[str, Any]]:
        """
        Run through current decisions and auto-execute eligible ones.
        HARDCODED: only fires when broker_backend == 'paper'.
        """
        if not self.is_auto_execute_active():
            return []

        results: List[Dict[str, Any]] = []
        # Snapshot decision IDs before iterating (executor mutates the list)
        decisions_snapshot = list(self.state.get("decisions", []))
        for d in decisions_snapshot:
            if not d.get("auto_executable"):
                continue
            # Double-check: never auto-execute on real money even if flagged
            if self.state.get("settings", {}).get("broker_backend") != "paper":
                continue
            res = self.execute(d.get("id", ""))
            results.append({
                "decision_id": d.get("id"),
                "symbol": d.get("symbol"),
                "action": d.get("action"),
                "ok": res.get("ok", False),
                "error": res.get("error", ""),
            })
        return results
