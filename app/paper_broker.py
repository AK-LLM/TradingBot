from __future__ import annotations
from typing import Dict, Any, Optional
from app.models import Order, Fill, Position, new_id, now_iso
from app.market_data import MarketDataService
from app.risk import RiskEngine

class PaperBroker:
    """Paper broker that behaves more like live trading: submitted orders, bid/ask, slippage, commissions, rejects, and fills."""
    def __init__(self, state: Dict[str, Any]) -> None:
        self.state = state
        self.market = MarketDataService(state)
        self.risk = RiskEngine(state)

    def _position_key(self, order: Order) -> str:
        if order.asset_type == "option":
            return f"{order.symbol}|{order.option_expiry}|{order.option_strike}|{order.option_right}"
        return order.symbol
    def _get_position(self, key: str) -> Optional[Position]:
        raw = self.state["positions"].get(key); return Position(**raw) if raw else None
    def _save_position(self, pos: Position) -> None: self.state["positions"][pos.key] = pos.to_dict()
    def _delete_position(self, key: str) -> None: self.state["positions"].pop(key, None)

    def place_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        symbol = order_data["symbol"].upper(); q = self.market.quote(symbol)
        side = order_data["side"].lower(); order_type = order_data.get("order_type", "market")
        mark = float(order_data.get("mark_price") or q["last"])
        order = Order(id=new_id("ord"), created_at=now_iso(), submitted_at=now_iso(), broker="paper", symbol=symbol,
                      asset_type=order_data.get("asset_type","stock"), side=side, quantity=int(order_data["quantity"]),
                      order_type=order_type, limit_price=order_data.get("limit_price"), stop_price=order_data.get("stop_price"),
                      mark_price=mark, status="submitted", notes=order_data.get("notes", ""), alert_id=order_data.get("alert_id"),
                      option_expiry=order_data.get("option_expiry"), option_strike=order_data.get("option_strike"), option_right=order_data.get("option_right"))
        expected_px = q["ask"] if side == "buy" else q["bid"]
        order_for_risk = order.to_dict()
        order_for_risk["spread_bps"] = q.get("spread_bps", 0)
        risk = self.risk.validate_order(order_for_risk, expected_px)
        if not risk["approved"]:
            order.status = "rejected"; self.state["orders"].append(order.to_dict())
            self.state["journal"].append({"ts": now_iso(), "event":"paper_reject", "symbol":symbol, "reasons":risk["reasons"]})
            return {"ok": False, "order": order.to_dict(), "error": "; ".join(risk["reasons"])}
        # Limit handling: unfilled if away from current bid/ask.
        if order_type == "limit" and order.limit_price is not None:
            lim = float(order.limit_price)
            if (side == "buy" and lim < q["ask"]) or (side == "sell" and lim > q["bid"]):
                self.state["orders"].append(order.to_dict())
                self.state["journal"].append({"ts":now_iso(), "event":"paper_submitted_unfilled", "order_id":order.id, "symbol":symbol})
                return {"ok": True, "order": order.to_dict(), "status":"submitted_unfilled"}
        bps = float(self.state["settings"].get("paper_slippage_bps", 8))
        slip = expected_px * (bps/10000.0)
        fill_price = expected_px + slip if side == "buy" else expected_px - slip
        commission = max(float(self.state["settings"].get("paper_min_commission",1.0)), order.quantity*float(self.state["settings"].get("paper_commission_per_share",0.005)))
        fill = Fill(new_id("fill"), order.id, now_iso(), symbol, order.asset_type, side, order.quantity, round(fill_price,4), round(commission,2), round(abs(fill_price-expected_px),4), order.option_expiry, order.option_strike, order.option_right)
        key = self._position_key(order); pos = self._get_position(key); cash = float(self.state["settings"]["cash_balance"]); gross = fill.fill_price*fill.quantity
        if side == "buy":
            cash -= gross + fill.commission
            if pos is None:
                pos = Position(key, symbol, order.asset_type, fill.quantity, fill.fill_price, fill.fill_price, option_expiry=order.option_expiry, option_strike=order.option_strike, option_right=order.option_right)
            else:
                new_qty = pos.quantity + fill.quantity
                pos.avg_price = ((pos.avg_price*pos.quantity)+gross)/new_qty
                pos.quantity = new_qty; pos.market_price = fill.fill_price
            self._save_position(pos)
        else:
            if pos is None or pos.quantity < fill.quantity:
                order.status="rejected"; self.state["orders"].append(order.to_dict())
                return {"ok":False, "order":order.to_dict(), "error":"Insufficient position to sell"}
            cash += gross - fill.commission
            realized = (fill.fill_price - pos.avg_price)*fill.quantity - fill.commission
            pos.realized_pnl += realized
            self.state["journal"].append({"ts": now_iso(), "event":"realized_pnl", "symbol": symbol, "amount": round(realized, 2)})
            pos.quantity -= fill.quantity; pos.market_price = fill.fill_price
            self._delete_position(key) if pos.quantity == 0 else self._save_position(pos)
        order.status = "filled"; order.filled_at = fill.created_at
        self.state["settings"]["cash_balance"] = round(cash,2)
        self.state["orders"].append(order.to_dict()); self.state["fills"].append(fill.to_dict())
        self.state["journal"].append({"ts":now_iso(), "event":"paper_fill", "order_id":order.id, "symbol":symbol, "side":side, "qty":order.quantity, "price":fill.fill_price, "commission":fill.commission, "spread_bps":q["spread_bps"]})
        return {"ok": True, "order": order.to_dict(), "fill": fill.to_dict(), "quote": q}

    def cancel_order(self, order_id: str) -> bool:
        for o in self.state["orders"]:
            if o["id"] == order_id and o["status"] == "submitted":
                o["status"] = "cancelled"; self.state["journal"].append({"ts":now_iso(),"event":"cancelled","order_id":order_id}); return True
        return False

    def mark_to_market(self) -> None:
        for key, p in self.state.get("positions",{}).items():
            p["market_price"] = self.market.quote(p["symbol"])["last"]

    def get_status(self) -> Dict[str, Any]:
        self.mark_to_market()
        cash = float(self.state["settings"]["cash_balance"])
        mv = sum(float(p["quantity"])*float(p["market_price"]) for p in self.state["positions"].values())
        unrl = sum((float(p["market_price"])-float(p["avg_price"]))*float(p["quantity"]) for p in self.state["positions"].values())
        return {"backend":"paper", "cash_balance":cash, "positions":len(self.state["positions"]), "market_value":round(mv,2), "equity":round(cash+mv,2), "unrealized_pnl":round(unrl,2)}
