from __future__ import annotations
from typing import Dict, Any, List, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict

@dataclass
class RiskSnapshot:
    equity: float
    cash: float
    market_value: float
    daily_realized_pnl: float
    drawdown_pct: float
    exposure_pct: float
    open_positions: int
    consecutive_losses: int
    risk_status: str
    messages: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class RiskEngine:
    def __init__(self, state: Dict[str, Any]):
        self.state = state

    def snapshot(self) -> RiskSnapshot:
        settings = self.state["settings"]
        cash = float(settings.get("cash_balance", 0.0))
        positions = self.state.get("positions", {})
        market_value = sum(float(p.get("quantity", 0))*float(p.get("market_price", 0)) for p in positions.values())
        equity = cash + market_value
        start = float(settings.get("starting_cash", 10000.0))
        drawdown_pct = max(0.0, (start - equity) / start) if start else 0.0
        exposure_pct = market_value / equity if equity else 0.0
        daily_pnl = self._daily_realized_pnl()
        losses = self._consecutive_loss_count()
        messages: List[str] = []
        status = "NORMAL"
        if bool(settings.get("trading_halted", False)):
            status = "HALTED"
            messages.append("Kill switch is active.")
        if daily_pnl <= -abs(float(settings.get("max_daily_loss", 200.0))):
            status = "HALTED"
            messages.append("Daily loss limit reached.")
        if drawdown_pct >= abs(float(settings.get("max_drawdown_pct", 0.06))):
            status = "HALTED"
            messages.append("Maximum account drawdown reached.")
        if losses >= int(settings.get("max_consecutive_losses", 4)):
            status = "COOLDOWN"
            messages.append("Consecutive-loss cooldown active.")
        if exposure_pct >= float(settings.get("max_total_exposure_pct", 0.45)):
            status = "CAUTION" if status == "NORMAL" else status
            messages.append("Portfolio exposure is near or above limit.")
        return RiskSnapshot(round(equity,2), round(cash,2), round(market_value,2), round(daily_pnl,2), round(drawdown_pct*100,2), round(exposure_pct*100,2), len(positions), losses, status, messages)

    def suggested_quantity(self, symbol: str, price: float, stop_pct: float | None = None) -> Dict[str, Any]:
        settings = self.state["settings"]
        snap = self.snapshot()
        risk_per_trade = float(settings.get("risk_per_trade_pct", 0.0075))
        stop_pct = float(stop_pct if stop_pct is not None else settings.get("default_stop_pct", 0.025))
        risk_dollars = snap.equity * risk_per_trade
        risk_qty = int(risk_dollars / max(price * stop_pct, 0.01))
        cap_qty = int((snap.equity * float(settings.get("max_trade_pct", 0.08))) / max(price, 0.01))
        qty = max(0, min(risk_qty, cap_qty))
        return {"quantity": qty, "risk_dollars": round(risk_dollars,2), "stop_pct": stop_pct, "cap_qty": cap_qty, "risk_qty": risk_qty}

    def validate_order(self, order: Dict[str, Any], estimated_price: float) -> Dict[str, Any]:
        settings = self.state["settings"]
        snap = self.snapshot()
        positions = self.state.get("positions", {})
        gross = float(order.get("quantity", 0))*float(estimated_price)
        reasons: List[str] = []
        warnings: List[str] = []
        if snap.risk_status == "HALTED":
            reasons.extend(snap.messages or ["Trading is halted by risk engine."])
        if gross <= 0:
            reasons.append("Order has no positive notional value.")
        if gross > snap.equity * float(settings.get("max_trade_pct", 0.08)):
            reasons.append(f"Trade value ${gross:,.2f} exceeds per-trade cap.")
        side = str(order.get("side", "")).lower()
        if len(positions) >= int(settings.get("max_open_positions", 6)) and side == "buy" and str(order.get("symbol", "")).upper() not in [p.get("symbol") for p in positions.values()]:
            reasons.append("Maximum open positions reached.")
        sym = str(order.get("symbol", "")).upper()
        sym_exposure = sum(float(p.get("quantity", 0))*float(p.get("market_price", 0)) for p in positions.values() if p.get("symbol") == sym)
        if side == "buy" and sym_exposure + gross > snap.equity * float(settings.get("max_position_pct", 0.12)):
            reasons.append("Symbol exposure cap exceeded.")
        if side == "buy" and snap.cash < gross:
            reasons.append("Insufficient cash.")
        if side == "buy" and self._recent_trade_exists(sym, int(settings.get("symbol_cooldown_minutes", 20))):
            reasons.append("Symbol cooldown active; duplicate or rapid-repeat trade blocked.")
        if snap.exposure_pct >= float(settings.get("max_total_exposure_pct", 0.45))*100 and side == "buy":
            reasons.append("Total exposure cap reached.")
        spread_bps = float(order.get("spread_bps", 0) or 0)
        if spread_bps and spread_bps > float(settings.get("max_spread_bps", 80)):
            reasons.append("Spread exceeds execution limit.")
        if snap.risk_status == "COOLDOWN" and side == "buy":
            reasons.append("Loss-streak cooldown active.")
        return {"approved": len(reasons) == 0, "reasons": reasons, "warnings": warnings, "estimated_gross": round(gross, 2), **snap.to_dict()}

    def validate_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        s = self.state["settings"]
        reasons: List[str] = []
        if alert.get("shark_score", 0) < float(s.get("min_shark_score", 70)):
            reasons.append("Shark score below threshold.")
        if alert.get("confirmation_score", 0) < float(s.get("min_confirmation_score", 50)):
            reasons.append("Confirmation score below threshold.")
        if alert.get("freshness_score", 0) < float(s.get("min_freshness_score", 55)):
            reasons.append("Freshness score below threshold.")
        if alert.get("tradability_score", 0) < float(s.get("min_tradability_score", 55)):
            reasons.append("Tradability score below threshold.")
        if self.snapshot().risk_status in {"HALTED", "COOLDOWN"}:
            reasons.append("Risk engine is not accepting new trades.")
        return {"approved": len(reasons) == 0, "reasons": reasons}

    def _daily_realized_pnl(self) -> float:
        today = datetime.now(timezone.utc).date().isoformat()
        pnl = 0.0
        for j in self.state.get("journal", []):
            if str(j.get("ts", ""))[:10] != today:
                continue
            if j.get("event") == "realized_pnl":
                pnl += float(j.get("amount", 0.0))
        return pnl

    def _consecutive_loss_count(self) -> int:
        losses = 0
        for j in reversed(self.state.get("journal", [])):
            if j.get("event") != "realized_pnl":
                continue
            amt = float(j.get("amount", 0.0))
            if amt < 0:
                losses += 1
            elif amt > 0:
                break
        return losses

    def _recent_trade_exists(self, symbol: str, cooldown_minutes: int) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
        for j in reversed(self.state.get("journal", [])):
            if j.get("event") not in {"paper_fill", "ibkr_order_submitted"}:
                continue
            if str(j.get("symbol", "")).upper() != symbol.upper():
                continue
            try:
                ts = datetime.fromisoformat(str(j.get("ts")).replace("Z", "+00:00"))
            except Exception:
                continue
            if ts >= cutoff:
                return True
        return False
