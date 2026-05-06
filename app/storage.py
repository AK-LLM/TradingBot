from __future__ import annotations
import json, os
from typing import Any, Dict

DEFAULT_STATE: Dict[str, Any] = {
    "settings": {
        "starting_cash": 10000.0,
        "cash_balance": 10000.0,
        "broker_backend": "paper",
        "paper_live_like": True,
        "paper_slippage_bps": 8,
        "paper_commission_per_share": 0.005,
        "paper_min_commission": 1.0,
        "max_daily_loss": 200.0,
        "max_drawdown_pct": 0.06,
        "risk_per_trade_pct": 0.0075,
        "default_stop_pct": 0.025,
        "max_position_pct": 0.12,
        "max_trade_pct": 0.08,
        "max_total_exposure_pct": 0.45,
        "max_open_positions": 6,
        "max_consecutive_losses": 4,
        "symbol_cooldown_minutes": 20,
        "max_spread_bps": 80,
        "require_manual_approval": True,
        "minimum_live_feeds_required": 4,
        "minimum_feed_types_required": 3,
        "min_independent_sources": 2,
        "min_feed_type_confirmations": 2,
        "min_shark_score": 70,
        "min_confirmation_score": 50,
        "min_freshness_score": 55,
        "min_tradability_score": 55,
        "max_move_before_entry_pct": 2.5,
        "ibkr_enabled": False,
        "ibkr_host": "127.0.0.1",
        "ibkr_port": 7497,
        "ibkr_client_id": 7,
        "trading_halted": False,
        "watchdog_enabled": False,
        "watchdog_interval_seconds": 60,
        "watchdog_max_signals": 80,
        "flash_alerts_enabled": True,
        "flash_min_score": 82,
        "flash_min_confidence": 78,
        "flash_cooldown_minutes": 20,
        "flash_active_ttl_minutes": 180,
        "flash_allowed_trend_stages": ["EMERGING", "CONFIRMED"],
        # === V5.6 Risk Intelligence settings ===
        "auto_stop_pct": 0.04,           # Soft stop -> REDUCE alert at 4% loss from entry
        "hard_stop_pct": 0.07,           # Hard stop -> SELL alert at 7% loss from entry
        "trail_trigger_pct": 0.06,       # Trailing logic activates once 6% in profit
        "trail_giveback_pct": 0.40,      # Triggers REDUCE if giving back 40% of gains
        "max_correlation_group_pct": 0.20, # Max 20% of equity in any one correlation group
        "max_sector_pct": 0.30,          # Max 30% of equity in any one sector
        "vix_panic_threshold": 30,       # VIX above this triggers 50% size reduction
        "vix_elevated_threshold": 20,    # VIX above this triggers 25% size reduction
        # === V5.7 Decision Engine settings ===
        "decision_min_score": 65,           # Min shark score to generate a Decision
        "decision_base_dollars": 800,       # Default dollars for ENTER_NEW
        "decision_add_dollars": 400,        # Default dollars for ADD
        "decision_avg_down_dollars": 400,   # Default dollars for AVERAGE_DOWN
        "first_target_pct": 0.08,           # 8% first profit target
        "time_stop_days": 14,               # Stale position exit
        "enable_average_down": True,        # AVERAGE_DOWN active (paper test mode)
        "enable_auto_execute": True,        # Auto-execute eligible decisions (PAPER ONLY enforced)
    },
    "signals": [],
    "alerts": [],
    "orders": [],
    "fills": [],
    "positions": {},
    "journal": [],
    "baselines": {},
    "market_cache": {},
    "feed_health": [],
    "feed_reliability": {},
    "risk_snapshot": {},
    "action_advice": [],
    "active_feed_count": 0,
    "active_flash_alerts": [],
    "flash_history": [],
    "last_watchdog_run": None,
    # V5.6 risk intelligence state
    "stop_alerts": [],
    "correlation_exposures": [],
    "sector_exposures": [],
    "risk_intelligence": {},
    "position_high_watermarks": {},
    # V5.7 decision engine state
    "decisions": [],
    "decision_history": [],
    "decision_summary": {},
    "average_down_count": {},
}

class JsonStore:
    def __init__(self, path: str = "data/state.json") -> None:
        self.path = path
    def load(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return json.loads(json.dumps(DEFAULT_STATE))
        with open(self.path, "r", encoding="utf-8") as f:
            state = json.load(f)
        merged = json.loads(json.dumps(DEFAULT_STATE))
        for k, v in state.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k].update(v)
            else:
                merged[k] = v
        return merged
    def save(self, state: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
