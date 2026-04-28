from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class Signal:
    id: str
    created_at: str
    source: str
    symbol: str
    direction: str
    confidence: float
    magnitude: float = 0.0
    title: str = ""
    description: str = ""
    horizon: str = "swing"
    metadata: Dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return asdict(self)


@dataclass
class Alert:
    id: str
    created_at: str
    narrative: str
    primary_symbol: str
    direction: str
    shark_score: float
    shock_score: float
    confirmation_score: float
    freshness_score: float
    tradability_score: float
    risk_score: float
    status: str
    action: str
    instruments: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return asdict(self)


@dataclass
class Order:
    id: str
    created_at: str
    broker: str
    symbol: str
    asset_type: str
    side: str
    quantity: int
    order_type: str
    mark_price: float
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    tif: str = "DAY"
    status: str = "submitted"
    notes: str = ""
    alert_id: Optional[str] = None
    submitted_at: Optional[str] = None
    filled_at: Optional[str] = None
    option_expiry: Optional[str] = None
    option_strike: Optional[float] = None
    option_right: Optional[str] = None
    def to_dict(self): return asdict(self)


@dataclass
class Fill:
    id: str
    order_id: str
    created_at: str
    symbol: str
    asset_type: str
    side: str
    quantity: int
    fill_price: float
    commission: float = 0.0
    slippage: float = 0.0
    option_expiry: Optional[str] = None
    option_strike: Optional[float] = None
    option_right: Optional[str] = None
    def to_dict(self): return asdict(self)


@dataclass
class Position:
    key: str
    symbol: str
    asset_type: str
    quantity: int
    avg_price: float
    market_price: float
    realized_pnl: float = 0.0
    option_expiry: Optional[str] = None
    option_strike: Optional[float] = None
    option_right: Optional[str] = None
    def market_value(self) -> float: return self.quantity * self.market_price
    def unrealized_pnl(self) -> float: return (self.market_price - self.avg_price) * self.quantity
    def to_dict(self): return asdict(self)
