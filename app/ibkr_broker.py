from __future__ import annotations
from typing import Dict, Any
from app.models import Order, new_id, now_iso

IB_AVAILABLE = None
IB = Stock = Future = Option = MarketOrder = LimitOrder = None

def _load_ib():
    global IB_AVAILABLE, IB, Stock, Future, Option, MarketOrder, LimitOrder
    if IB_AVAILABLE is not None:
        return IB_AVAILABLE
    try:
        from ib_insync import IB as _IB, Stock as _Stock, Future as _Future, Option as _Option, MarketOrder as _MarketOrder, LimitOrder as _LimitOrder
        IB, Stock, Future, Option, MarketOrder, LimitOrder = _IB, _Stock, _Future, _Option, _MarketOrder, _LimitOrder
        IB_AVAILABLE = True
    except Exception:
        IB_AVAILABLE = False
    return IB_AVAILABLE

class IBKRBroker:
    """Guarded IBKR adapter. Live orders require ibkr_enabled=True and TWS/Gateway running."""
    def __init__(self, state: Dict[str, Any]) -> None:
        self.state = state
        available = _load_ib() if self.state["settings"].get("ibkr_enabled") else False
        self.ib = IB() if available else None
        self.connected = False
        if self.state["settings"].get("ibkr_enabled") and available:
            self.connect()

    def connect(self) -> bool:
        if not _load_ib(): return False
        s = self.state["settings"]
        try:
            if not self.ib.isConnected():
                self.ib.connect(s.get("ibkr_host","127.0.0.1"), int(s.get("ibkr_port",7497)), clientId=int(s.get("ibkr_client_id",7)), timeout=10)
            self.connected = True; return True
        except Exception as e:
            self.state["journal"].append({"ts":now_iso(), "event":"ibkr_connect_failed", "error":str(e)})
            self.connected = False; return False

    def _contract(self, od: Dict[str, Any]):
        sym = od["symbol"].upper(); typ = od.get("asset_type","stock")
        if typ == "stock": return Stock(sym, "SMART", "USD")
        if typ == "future": return Future(sym, od.get("future_expiry", ""), "SMART")
        if typ == "option": return Option(sym, od["option_expiry"], float(od["option_strike"]), od.get("option_right","C"), "SMART", currency="USD")
        raise ValueError(f"Unsupported IBKR asset_type: {typ}")

    def place_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.state["settings"].get("ibkr_enabled"):
            return {"ok": False, "error":"IBKR disabled. Enable only when ready."}
        if not _load_ib():
            return {"ok": False, "error":"ib_insync not installed."}
        if self.ib is None:
            self.ib = IB()
        if not self.connected and not self.connect():
            return {"ok": False, "error":"Could not connect to IBKR TWS/Gateway."}
        try:
            contract = self._contract(order_data); self.ib.qualifyContracts(contract)
            side = "BUY" if order_data["side"].lower() == "buy" else "SELL"
            qty = int(order_data["quantity"])
            ib_order = MarketOrder(side, qty) if order_data.get("order_type","market") == "market" else LimitOrder(side, qty, float(order_data["limit_price"]))
            trade = self.ib.placeOrder(contract, ib_order); self.ib.sleep(1)
            order = Order(new_id("ord"), now_iso(), "ibkr", order_data["symbol"].upper(), order_data.get("asset_type","stock"), order_data["side"], qty, order_data.get("order_type","market"), float(order_data.get("mark_price",0)), order_data.get("limit_price"), status="submitted", notes=f"IBKR order ID: {trade.order.orderId}", alert_id=order_data.get("alert_id"))
            self.state["orders"].append(order.to_dict())
            self.state["journal"].append({"ts":now_iso(), "event":"ibkr_order_submitted", "symbol":order.symbol, "ib_order_id":trade.order.orderId})
            return {"ok": True, "order": order.to_dict(), "ib_order_id": trade.order.orderId, "status": trade.orderStatus.status}
        except Exception as e:
            self.state["journal"].append({"ts":now_iso(), "event":"ibkr_order_failed", "error":str(e)})
            return {"ok": False, "error": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        return False

    def get_status(self) -> Dict[str, Any]:
        s = self.state["settings"]
        return {"backend":"ibkr", "enabled":bool(s.get("ibkr_enabled")), "library_available": bool(_load_ib()), "connected":self.connected, "host":s.get("ibkr_host"), "port":s.get("ibkr_port"), "mode":"LIVE ⚠️" if int(s.get("ibkr_port",7497)) in [7496,4001] else "PAPER"}
