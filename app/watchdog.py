from __future__ import annotations
from typing import Any, Dict, Optional
from app.models import now_iso
from app.flash_alerts import FlashAlertEngine

class Watchdog:
    """Portable monitoring cycle used by Streamlit and local CLI worker."""
    def __init__(self, platform: Any):
        self.platform = platform

    def cycle(self, max_signals: Optional[int] = None) -> Dict[str, Any]:
        state = self.platform.state
        settings = state.get("settings", {})
        max_sigs = int(max_signals or settings.get("watchdog_max_signals", 80))
        before = len(state.get("active_flash_alerts", []))
        # V5.7.1: Wrap scan + flash evaluation so a single feed failure doesn't kill the cycle
        error_msg = None
        signals = 0
        new_flash = []
        try:
            signals = self.platform.scan_signals(max_sigs)
            new_flash = FlashAlertEngine(state).evaluate()
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)[:200]}"
        state["last_watchdog_run"] = now_iso()
        journal_entry = {
            "ts": now_iso(),
            "event": "watchdog_cycle_completed" if error_msg is None else "watchdog_cycle_partial",
            "signals": signals,
            "new_flash_alerts": len(new_flash),
            "active_flash_alerts_before": before,
            "active_flash_alerts_after": len(state.get("active_flash_alerts", [])),
        }
        if error_msg:
            journal_entry["error"] = error_msg
        state.setdefault("journal", []).append(journal_entry)
        self.platform.save()
        return {"signals": signals, "new_flash_alerts": len(new_flash), "active_flash_alerts": len(state.get("active_flash_alerts", [])), "last_run": state["last_watchdog_run"], "error": error_msg}
