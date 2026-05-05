from __future__ import annotations
from typing import Dict, Any, List, Optional
import pandas as pd
from app.storage import JsonStore, DEFAULT_STATE
from app.models import Alert, now_iso
from app.signals import collect_live_signals
from app.shark_engine import SharkEngine
from app.paper_broker import PaperBroker
from app.ibkr_broker import IBKRBroker
from app.market_data import MarketDataService
from app.risk import RiskEngine
from app.feed_reliability import FeedReliabilityEngine
from app.intelligence import summarize_alert_actions
from app.flash_alerts import FlashAlertEngine
from app.watchdog import Watchdog
# V5.5 Intelligence Enhancements
from app.velocity_tracker import VelocityTracker
from app.constellation_engine import ConstellationEngine, summarize_constellations
# V5.6 Risk Intelligence
from app.risk_intelligence import RiskIntelligence

class TradingPlatform:
    def __init__(self, store_path: str = "data/state.json") -> None:
        self.store = JsonStore(store_path)
        self.state = self.store.load()
        self.shark = SharkEngine(self.state)
        self.market = MarketDataService(self.state)
        self.risk = RiskEngine(self.state)
        self.reliability = FeedReliabilityEngine(self.state)
        self.flash = FlashAlertEngine(self.state)
        # V5.5 Intelligence Enhancements
        self.velocity = VelocityTracker(self.state)
        self.constellations = ConstellationEngine(self.state)
        # V5.6 Risk Intelligence
        self.risk_intel = RiskIntelligence(self.state)

    def save(self) -> None:
        self.store.save(self.state)

    def broker(self):
        return IBKRBroker(self.state) if self.state["settings"].get("broker_backend") == "ibkr" else PaperBroker(self.state)

    def reset(self) -> None:
        start = float(self.state["settings"].get("starting_cash", 10000))
        settings = dict(self.state["settings"])
        fresh = {k: (v.copy() if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in DEFAULT_STATE.items()}
        self.state.clear()
        self.state.update(fresh)
        self.state["settings"].update(settings)
        self.state["settings"]["cash_balance"] = start
        self.save()

    def scan_signals(self, max_signals: int = 40, enabled_feeds: Optional[List[str]] = None) -> int:
        signals, _health = collect_live_signals(self.state, max_per_feed=max(5, max_signals // 4), enabled_feeds=enabled_feeds)
        reliability = self.reliability.evaluate()
        signals_dicts = [s.to_dict() for s in signals]
        self.state["signals"] = signals_dicts

        # === V5.6 PIPELINE FIX: Detect constellations + risk intel BEFORE building alerts ===
        # Otherwise the intelligence engine runs without context and flash alerts use stale advice.

        # 1. Velocity tracking on raw signals
        self.velocity.record(signals_dicts)
        velocity_readings = self.velocity.compute_velocities()
        self.state["velocity_summary"] = self.velocity.summary()
        self.state["velocity_readings"] = [r.to_dict() for r in velocity_readings]

        # 2. Detect constellations BEFORE alert generation so intelligence engine sees them
        constellations = self.constellations.detect_all(signals_dicts, velocity_readings)
        self.state["constellations"] = [c.to_dict() for c in constellations]
        self.state["constellation_summary"] = summarize_constellations(self.state, constellations)

        # 3. Mark positions to market and run risk intelligence BEFORE alert generation
        # so the intelligence engine has live position prices and stop alerts available
        try:
            self.broker().mark_to_market() if self.state["settings"].get("broker_backend") == "paper" else None
        except Exception:
            pass
        self.risk_intel.evaluate_all()

        # 4. NOW build alerts — intelligence.advise() can see constellations + risk intel + velocity
        alerts = self.shark.build_alerts(signals)
        self.state["alerts"] = [a.to_dict() for a in alerts]

        # 5. Action advice summary (using the same enriched state)
        self.state["action_advice"] = summarize_alert_actions(self.state)

        # 6. Flash alerts now operate on the fully-enriched alerts
        if self.state.get("settings", {}).get("flash_alerts_enabled", True):
            self.flash.evaluate()

        self.state["risk_snapshot"] = self.risk.snapshot().to_dict()
        self.state["journal"].append({
            "ts": now_iso(),
            "event": "shark_scan_completed",
            "mode": "live_only",
            "signals": len(signals),
            "alerts": len(alerts),
            "constellations": len(constellations),
            "early_opportunities": len([c for c in constellations if c.stage in ("SCOUT", "STALKING")]),
            "top_score": alerts[0].shark_score if alerts else 0,
            "feed_status": reliability.system_status
        })
        self.save()
        return len(signals)

    def morning_radar(self) -> int:
        return self.scan_signals(max_signals=80)

    def watchdog_cycle(self, max_signals: Optional[int] = None) -> Dict[str, Any]:
        return Watchdog(self).cycle(max_signals=max_signals)

    def acknowledge_flash_alert(self, flash_id: str) -> bool:
        ok = self.flash.acknowledge(flash_id)
        self.save()
        return ok

    def flash_alerts_df(self) -> pd.DataFrame:
        cols = ["id", "created_at", "alert_id", "narrative", "action", "confidence", "shark_score", "primary_symbol", "direction", "trend_stage", "reasons", "acknowledged", "acknowledged_at"]
        return pd.DataFrame(self.state.get("active_flash_alerts", []), columns=cols)

    def flash_history_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.state.get("flash_history", []))

    def auto_paper_top_alert(self, alert_id: str, dollars: float = 800) -> Dict[str, Any]:
        alerts = [Alert(**a) for a in self.state.get("alerts", []) if a["id"] == alert_id]
        if not alerts:
            return {"ok": False, "error": "Alert not found"}
        alert = alerts[0]
        risk_gate = self.risk.validate_alert(alert.to_dict())
        if not risk_gate["approved"]:
            return {"ok": False, "error": "; ".join(risk_gate["reasons"])}
        inst = alert.instruments[0] if alert.instruments else {"symbol": alert.primary_symbol, "asset_type": "stock", "direction": alert.direction}
        q = self.market.quote(inst["symbol"])
        sizing = self.risk.suggested_quantity(inst["symbol"], q["last"])
        requested_qty = max(1, int(float(dollars) / float(q["last"])))
        base_qty = min(requested_qty, max(1, int(sizing["quantity"])))
        # === V5.6: Apply VIX adjustment + correlation check ===
        adj = self.risk_intel.adjusted_quantity(inst["symbol"], q["last"], base_qty)
        if not adj["correlation_approved"]:
            return {"ok": False, "error": f"Correlation check failed: {adj['correlation_reason']}"}
        qty = adj["adjusted_quantity"]
        side = "buy" if inst.get("direction", alert.direction).upper() in ["BUY", "LONG"] else "sell"
        notes = f"Auto paper from shark alert {alert.narrative}; sizing={sizing}; vix_mult={adj['vix_multiplier']}; corr_groups={adj['correlation_groups']}"
        return self.place_order({"symbol": inst["symbol"], "asset_type": inst.get("asset_type", "stock"), "side": side, "quantity": qty, "order_type": "market", "mark_price": q["last"], "spread_bps": q.get("spread_bps", 0), "notes": notes, "alert_id": alert.id})

    def place_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        result = self.broker().place_order(order_data)
        self.state["risk_snapshot"] = self.risk.snapshot().to_dict()
        self.save()
        return result

    def cancel_order(self, order_id: str) -> bool:
        ok = self.broker().cancel_order(order_id)
        self.save()
        return ok

    def status(self) -> Dict[str, Any]:
        status = self.broker().get_status()
        self.state["risk_snapshot"] = self.risk.snapshot().to_dict()
        self.save()
        return status

    def risk_snapshot(self) -> Dict[str, Any]:
        snap = self.risk.snapshot().to_dict()
        self.state["risk_snapshot"] = snap
        self.save()
        return snap

    def feed_reliability_report(self) -> Dict[str, Any]:
        rep = self.reliability.evaluate().to_dict()
        self.save()
        return rep

    def signals_df(self) -> pd.DataFrame:
        cols = ["id", "created_at", "source", "symbol", "direction", "confidence", "magnitude", "title", "description", "horizon", "metadata"]
        return pd.DataFrame(self.state.get("signals", []), columns=cols)

    def alerts_df(self) -> pd.DataFrame:
        cols = ["id", "created_at", "narrative", "direction", "primary_symbol", "shark_score", "shock_score", "confirmation_score", "freshness_score", "tradability_score", "risk_score", "status", "action", "evidence", "warnings", "instruments", "metadata"]
        return pd.DataFrame(self.state.get("alerts", []), columns=cols)

    def advice_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.state.get("action_advice", []))

    def orders_df(self) -> pd.DataFrame:
        cols = ["id", "created_at", "symbol", "asset_type", "side", "quantity", "order_type", "limit_price", "status", "mark_price", "notes", "alert_id"]
        return pd.DataFrame(self.state.get("orders", []), columns=cols)

    def fills_df(self) -> pd.DataFrame:
        cols = ["id", "order_id", "created_at", "symbol", "asset_type", "side", "quantity", "fill_price", "commission", "slippage"]
        return pd.DataFrame(self.state.get("fills", []), columns=cols)

    def positions_df(self) -> pd.DataFrame:
        rows = list(self.state.get("positions", {}).values())
        if not rows:
            return pd.DataFrame(columns=["symbol", "asset_type", "quantity", "avg_price", "market_price", "market_value", "unrealized_pnl"])
        df = pd.DataFrame(rows)
        df["market_value"] = df["quantity"] * df["market_price"]
        df["unrealized_pnl"] = (df["market_price"] - df["avg_price"]) * df["quantity"]
        return df

    def journal_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.state.get("journal", []))

    def feed_health_df(self) -> pd.DataFrame:
        cols = ["feed", "status", "message", "count", "ts"]
        return pd.DataFrame(self.state.get("feed_health", []), columns=cols)

    # === V5.5 Intelligence Accessors ===
    def constellations_df(self) -> pd.DataFrame:
        cols = ["pattern_name", "stage", "confidence", "direction", "primary_narrative",
                "primary_symbol", "contributing_feeds", "description", "why_it_matters",
                "velocity_context", "detected_at"]
        return pd.DataFrame(self.state.get("constellations", []), columns=cols)

    def velocity_df(self) -> pd.DataFrame:
        cols = ["channel", "current_strength", "recent_avg", "prior_avg",
                "velocity_ratio", "acceleration", "samples", "first_seen", "last_seen"]
        return pd.DataFrame(self.state.get("velocity_readings", []), columns=cols)

    def early_opportunities(self) -> List[Dict[str, Any]]:
        """Return SCOUT and STALKING constellations - the early-stage opportunities."""
        cs = self.state.get("constellations", [])
        return [c for c in cs if c.get("stage") in ("SCOUT", "STALKING")]

    def late_warnings(self) -> List[Dict[str, Any]]:
        """Return LATE-stage constellations - the 'you're behind' warnings."""
        cs = self.state.get("constellations", [])
        return [c for c in cs if c.get("stage") == "LATE"]

    def constellation_summary(self) -> Dict[str, Any]:
        return self.state.get("constellation_summary", {})

    def velocity_summary(self) -> Dict[str, Any]:
        return self.state.get("velocity_summary", {})

    # === V5.6 Risk Intelligence Accessors ===
    def stop_alerts_df(self) -> pd.DataFrame:
        """Active stop alerts requiring user attention (REDUCE / SELL signals from positions)."""
        cols = ["symbol", "current_price", "entry_price", "pct_from_entry", "pct_from_high",
                "suggested_action", "reason", "urgency", "detected_at"]
        return pd.DataFrame(self.state.get("stop_alerts", []), columns=cols)

    def correlation_exposures_df(self) -> pd.DataFrame:
        """Correlation group exposures showing where you may be over-concentrated."""
        cols = ["group_name", "sector", "symbols", "total_market_value",
                "total_pct_of_equity", "position_count", "breach", "warning"]
        return pd.DataFrame(self.state.get("correlation_exposures", []), columns=cols)

    def sector_exposures_df(self) -> pd.DataFrame:
        """Sector exposures."""
        cols = ["sector", "symbols", "total_market_value", "total_pct_of_equity", "breach", "warning"]
        return pd.DataFrame(self.state.get("sector_exposures", []), columns=cols)

    def risk_intelligence_summary(self) -> Dict[str, Any]:
        return self.state.get("risk_intelligence", {})

    def vix_size_multiplier(self) -> float:
        return self.risk_intel.vix_size_multiplier()

    def settings(self) -> Dict[str, Any]:
        return self.state["settings"]

    def update_settings(self, new_settings: Dict[str, Any]) -> None:
        self.state["settings"].update(new_settings)
        self.save()
