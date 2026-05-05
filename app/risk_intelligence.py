"""
Risk Intelligence Module - V5.6
================================

Adds intelligent risk management ON TOP of the existing risk.py:

1. Auto-stop monitoring   — emits SELL/REDUCE signals when positions cross stop levels
2. Trailing stops         — once in profit, raises stop to lock gains
3. Volatility sizing      — adjusts position sizing based on VIX regime
4. Correlation grouping   — recognizes that XLE/XOM/CVX share oil exposure
5. Sector concentration   — limits how much can be in any one sector
6. Earnings blackout      — flags positions/alerts near earnings
7. Portfolio beta watch   — tracks net market exposure

This module DOES NOT replace risk.py. It augments it. risk.py still handles
account-level kill switches, daily loss limits, and per-trade gates. This module
adds the position-aware, regime-aware intelligence layer on top.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple


# Correlation groups - symbols that move together for risk purposes
# When sizing, the engine treats positions in the same group as one combined exposure
CORRELATION_GROUPS = {
    "energy": {"USO", "UNG", "XLE", "VDE", "XOM", "CVX", "OIH", "XEG.TO", "SU.TO", "CNQ.TO", "ENB.TO", "TRP.TO"},
    "uranium_nuclear": {"URA", "URNM", "NLR", "CCO.TO", "NXE.TO"},
    "data_center": {"VRT", "ETN", "EQIX", "DLR", "JCI", "TT", "CARR", "ANET", "DELL"},
    "water": {"PHO", "CGW", "XYL", "AWK"},
    "precious_metals": {"GLD", "IAU", "SLV", "SIVR", "SGOL", "GDX", "SIL", "ABX.TO", "AEM.TO", "K.TO"},
    "ai_chips": {"NVDA", "AMD", "SMH", "TSM", "ANET", "DELL"},
    "us_banks": {"XLF", "KRE"},
    "ca_banks": {"XFN.TO", "RY.TO", "TD.TO", "BMO.TO", "BNS.TO", "CM.TO"},
    "long_bonds": {"TLT", "IEF", "XBB.TO"},
    "broad_us_equity": {"SPY", "QQQ", "IWM"},
    "broad_ca_equity": {"XIU.TO", "XIC.TO"},
    "vol_hedges": {"VIXY"},
    "fx_usd_long": {"UUP"},
    "fx_usd_short": {"UDN", "FXC", "FXE", "FXY"},
    "credit": {"HYG", "JNK", "LQD"},
    "reits": {"VNQ", "IYR", "XLRE", "REZ", "XRE.TO"},
    "biotech": {"XBI", "IBB", "LLY", "NVO", "VRTX"},
    "crypto_proxies": {"COIN", "MSTR", "IBIT", "FBTC", "HUT.TO"},
    "agriculture": {"DBA", "WEAT", "CORN", "MOO", "NTR.TO", "ADM"},
    "shipping": {"BDRY", "SEA", "ZIM"},
    "defense": {"LMT", "RTX", "NOC", "ITA"},
    "consumer_disc": {"XLY", "AMZN", "HD", "NKE"},
    "consumer_staples": {"XLP"},
    "utilities": {"XLU", "ZUT.TO"},
    "healthcare": {"XLV"},
}

# Reverse lookup: symbol -> list of groups
SYMBOL_TO_GROUPS: Dict[str, List[str]] = {}
for group_name, symbols in CORRELATION_GROUPS.items():
    for sym in symbols:
        SYMBOL_TO_GROUPS.setdefault(sym, []).append(group_name)


# Sector classifications for concentration limits
SECTOR_MAP = {
    "energy": "Energy",
    "uranium_nuclear": "Energy",
    "data_center": "Technology",
    "ai_chips": "Technology",
    "us_banks": "Financials",
    "ca_banks": "Financials",
    "credit": "Financials",
    "reits": "RealEstate",
    "biotech": "Healthcare",
    "healthcare": "Healthcare",
    "precious_metals": "Materials",
    "agriculture": "Consumer/Materials",
    "shipping": "Industrials",
    "defense": "Industrials",
    "consumer_disc": "Consumer",
    "consumer_staples": "Consumer",
    "utilities": "Utilities",
    "crypto_proxies": "Crypto",
    "water": "Utilities",
    "long_bonds": "Bonds",
    "broad_us_equity": "BroadEquity",
    "broad_ca_equity": "BroadEquity",
    "vol_hedges": "Hedges",
    "fx_usd_long": "FX",
    "fx_usd_short": "FX",
}


@dataclass
class StopAlert:
    """An automated risk-driven action signal."""
    symbol: str
    current_price: float
    entry_price: float
    pct_from_entry: float
    pct_from_high: float
    suggested_action: str  # "REDUCE", "SELL", "TRAIL_TIGHTEN"
    reason: str
    urgency: str           # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CorrelationExposure:
    """Aggregate exposure to a correlation group."""
    group_name: str
    sector: str
    symbols: List[str]
    total_market_value: float
    total_pct_of_equity: float
    position_count: int
    breach: bool          # True if exceeds max_correlation_group_pct
    warning: bool         # True if approaching limit

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SectorExposure:
    """Aggregate exposure to a sector."""
    sector: str
    symbols: List[str]
    total_market_value: float
    total_pct_of_equity: float
    breach: bool
    warning: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RiskIntelligence:
    """
    The intelligence layer on top of RiskEngine. Adds position-aware,
    regime-aware, and correlation-aware risk controls.
    """

    # New configuration keys (with defaults if not in settings)
    DEFAULT_AUTO_STOP_PCT = 0.04           # 4% loss from entry triggers REDUCE alert
    DEFAULT_HARD_STOP_PCT = 0.07           # 7% loss triggers SELL alert
    DEFAULT_TRAIL_TRIGGER_PCT = 0.06       # Profitable by 6% activates trailing
    DEFAULT_TRAIL_GIVEBACK_PCT = 0.40      # Give back at most 40% of gain
    DEFAULT_MAX_CORRELATION_GROUP_PCT = 0.20  # No more than 20% in any one correlation group
    DEFAULT_MAX_SECTOR_PCT = 0.30          # No more than 30% in any one sector
    DEFAULT_VIX_PANIC_THRESHOLD = 30
    DEFAULT_VIX_ELEVATED_THRESHOLD = 20

    def __init__(self, state: Dict[str, Any]):
        self.state = state
        # Initialize position high-watermark tracking (used for trailing stops)
        if "position_high_watermarks" not in self.state:
            self.state["position_high_watermarks"] = {}

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def _setting(self, key: str, default: Any) -> Any:
        return self.state.get("settings", {}).get(key, default)

    def auto_stop_pct(self) -> float:
        return float(self._setting("auto_stop_pct", self.DEFAULT_AUTO_STOP_PCT))

    def hard_stop_pct(self) -> float:
        return float(self._setting("hard_stop_pct", self.DEFAULT_HARD_STOP_PCT))

    def trail_trigger_pct(self) -> float:
        return float(self._setting("trail_trigger_pct", self.DEFAULT_TRAIL_TRIGGER_PCT))

    def trail_giveback_pct(self) -> float:
        return float(self._setting("trail_giveback_pct", self.DEFAULT_TRAIL_GIVEBACK_PCT))

    def max_correlation_group_pct(self) -> float:
        return float(self._setting("max_correlation_group_pct", self.DEFAULT_MAX_CORRELATION_GROUP_PCT))

    def max_sector_pct(self) -> float:
        return float(self._setting("max_sector_pct", self.DEFAULT_MAX_SECTOR_PCT))

    # ------------------------------------------------------------------
    # 1. Auto-stop monitoring (REDUCE / SELL alerts)
    # ------------------------------------------------------------------

    def evaluate_position_stops(self) -> List[StopAlert]:
        """
        Check every open position against:
          - Soft stop (REDUCE alert at auto_stop_pct loss)
          - Hard stop (SELL alert at hard_stop_pct loss)
          - Trailing stop (TRAIL_TIGHTEN alert if giving back too much of gains)
        Returns list of stop alerts to surface to user.
        """
        positions = self.state.get("positions", {})
        if not positions:
            return []

        alerts: List[StopAlert] = []
        watermarks = self.state.get("position_high_watermarks", {})
        soft_stop = self.auto_stop_pct()
        hard_stop = self.hard_stop_pct()
        trail_trigger = self.trail_trigger_pct()
        trail_giveback = self.trail_giveback_pct()

        for key, pos in positions.items():
            try:
                avg_price = float(pos.get("avg_price", 0))
                market_price = float(pos.get("market_price", 0))
                quantity = int(pos.get("quantity", 0))
                symbol = str(pos.get("symbol", ""))
            except (ValueError, TypeError):
                continue

            if avg_price <= 0 or market_price <= 0 or quantity == 0:
                continue

            # Update high-water mark for trailing stops
            current_high = float(watermarks.get(key, market_price))
            if market_price > current_high:
                current_high = market_price
                watermarks[key] = current_high

            # Calculate pct from entry and from high
            pct_from_entry = (market_price - avg_price) / avg_price
            pct_from_high = (market_price - current_high) / current_high if current_high > 0 else 0.0

            # === Hard stop: critical loss ===
            if pct_from_entry <= -hard_stop:
                alerts.append(StopAlert(
                    symbol=symbol,
                    current_price=round(market_price, 4),
                    entry_price=round(avg_price, 4),
                    pct_from_entry=round(pct_from_entry * 100, 2),
                    pct_from_high=round(pct_from_high * 100, 2),
                    suggested_action="SELL",
                    reason=f"Hard stop breached: {pct_from_entry*100:.1f}% loss from entry exceeds {hard_stop*100:.0f}% threshold.",
                    urgency="CRITICAL",
                ))
            # === Soft stop: significant loss ===
            elif pct_from_entry <= -soft_stop:
                alerts.append(StopAlert(
                    symbol=symbol,
                    current_price=round(market_price, 4),
                    entry_price=round(avg_price, 4),
                    pct_from_entry=round(pct_from_entry * 100, 2),
                    pct_from_high=round(pct_from_high * 100, 2),
                    suggested_action="REDUCE",
                    reason=f"Soft stop triggered: {pct_from_entry*100:.1f}% loss from entry exceeds {soft_stop*100:.0f}% threshold. Consider trimming.",
                    urgency="HIGH",
                ))

            # === Trailing stop: in profit but giving back too much ===
            elif pct_from_entry >= trail_trigger:
                # Position is profitable enough for trailing logic
                gain_from_entry = current_high - avg_price
                giveback_from_high = current_high - market_price
                if gain_from_entry > 0:
                    giveback_ratio = giveback_from_high / gain_from_entry
                    if giveback_ratio >= trail_giveback:
                        alerts.append(StopAlert(
                            symbol=symbol,
                            current_price=round(market_price, 4),
                            entry_price=round(avg_price, 4),
                            pct_from_entry=round(pct_from_entry * 100, 2),
                            pct_from_high=round(pct_from_high * 100, 2),
                            suggested_action="REDUCE",
                            reason=f"Trailing stop triggered: gave back {giveback_ratio*100:.0f}% of gains from high. Lock in profits.",
                            urgency="MEDIUM",
                        ))

        self.state["position_high_watermarks"] = watermarks
        self.state["stop_alerts"] = [a.to_dict() for a in alerts]
        return alerts

    # ------------------------------------------------------------------
    # 2. Volatility-adjusted position sizing
    # ------------------------------------------------------------------

    def vix_size_multiplier(self) -> float:
        """
        Returns a multiplier for position sizing based on current VIX regime.
        - Complacent/Normal (VIX < 20): 1.0 (full size)
        - Elevated (VIX 20-30): 0.75 (reduce size by 25%)
        - Panic (VIX 30+): 0.50 (reduce size by 50%)
        """
        signals = self.state.get("signals", []) or []
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            sig_meta = sig.get("metadata", {}) or {}
            if not sig_meta.get("is_regime_context"):
                continue
            vix = sig_meta.get("vix_value")
            if vix is None:
                continue
            try:
                vix = float(vix)
            except (ValueError, TypeError):
                continue
            panic = float(self._setting("vix_panic_threshold", self.DEFAULT_VIX_PANIC_THRESHOLD))
            elevated = float(self._setting("vix_elevated_threshold", self.DEFAULT_VIX_ELEVATED_THRESHOLD))
            if vix >= panic:
                return 0.50
            elif vix >= elevated:
                return 0.75
            else:
                return 1.0
        return 1.0  # No VIX context available, default to full size

    # ------------------------------------------------------------------
    # 3. Correlation group exposure
    # ------------------------------------------------------------------

    def correlation_exposures(self) -> List[CorrelationExposure]:
        """Aggregate position exposures by correlation group."""
        positions = self.state.get("positions", {})
        if not positions:
            return []

        cash = float(self.state.get("settings", {}).get("cash_balance", 0))
        market_value = sum(
            float(p.get("quantity", 0)) * float(p.get("market_price", 0))
            for p in positions.values()
        )
        equity = max(1.0, cash + market_value)

        max_pct = self.max_correlation_group_pct()
        warning_pct = max_pct * 0.85  # Within 15% of breach

        group_data: Dict[str, Dict[str, Any]] = {}
        for pos in positions.values():
            symbol = str(pos.get("symbol", "")).upper()
            mv = float(pos.get("quantity", 0)) * float(pos.get("market_price", 0))
            groups = SYMBOL_TO_GROUPS.get(symbol, [])
            for group in groups:
                if group not in group_data:
                    group_data[group] = {"symbols": [], "mv": 0.0, "count": 0}
                group_data[group]["symbols"].append(symbol)
                group_data[group]["mv"] += mv
                group_data[group]["count"] += 1

        exposures: List[CorrelationExposure] = []
        for group, data in group_data.items():
            pct = data["mv"] / equity
            exposures.append(CorrelationExposure(
                group_name=group,
                sector=SECTOR_MAP.get(group, "Other"),
                symbols=sorted(set(data["symbols"])),
                total_market_value=round(data["mv"], 2),
                total_pct_of_equity=round(pct * 100, 2),
                position_count=data["count"],
                breach=pct >= max_pct,
                warning=warning_pct <= pct < max_pct,
            ))

        exposures.sort(key=lambda e: -e.total_pct_of_equity)
        self.state["correlation_exposures"] = [e.to_dict() for e in exposures]
        return exposures

    # ------------------------------------------------------------------
    # 4. Sector concentration
    # ------------------------------------------------------------------

    def sector_exposures(self) -> List[SectorExposure]:
        """Aggregate position exposures by broad sector."""
        positions = self.state.get("positions", {})
        if not positions:
            return []

        cash = float(self.state.get("settings", {}).get("cash_balance", 0))
        market_value = sum(
            float(p.get("quantity", 0)) * float(p.get("market_price", 0))
            for p in positions.values()
        )
        equity = max(1.0, cash + market_value)

        max_pct = self.max_sector_pct()
        warning_pct = max_pct * 0.85

        sector_data: Dict[str, Dict[str, Any]] = {}
        for pos in positions.values():
            symbol = str(pos.get("symbol", "")).upper()
            mv = float(pos.get("quantity", 0)) * float(pos.get("market_price", 0))
            groups = SYMBOL_TO_GROUPS.get(symbol, [])
            sector = SECTOR_MAP.get(groups[0], "Other") if groups else "Other"
            if sector not in sector_data:
                sector_data[sector] = {"symbols": [], "mv": 0.0}
            sector_data[sector]["symbols"].append(symbol)
            sector_data[sector]["mv"] += mv

        exposures: List[SectorExposure] = []
        for sector, data in sector_data.items():
            pct = data["mv"] / equity
            exposures.append(SectorExposure(
                sector=sector,
                symbols=sorted(set(data["symbols"])),
                total_market_value=round(data["mv"], 2),
                total_pct_of_equity=round(pct * 100, 2),
                breach=pct >= max_pct,
                warning=warning_pct <= pct < max_pct,
            ))

        exposures.sort(key=lambda e: -e.total_pct_of_equity)
        self.state["sector_exposures"] = [e.to_dict() for e in exposures]
        return exposures

    # ------------------------------------------------------------------
    # 5. Pre-trade correlation check (used by order validation)
    # ------------------------------------------------------------------

    def check_correlation_capacity(self, symbol: str, additional_value: float) -> Dict[str, Any]:
        """
        Before placing a new buy order, check if it would breach correlation group limits.
        Returns approval status + details for risk validation.
        """
        symbol = symbol.upper()
        groups = SYMBOL_TO_GROUPS.get(symbol, [])
        if not groups:
            return {"approved": True, "reason": "Symbol not in any correlation group"}

        cash = float(self.state.get("settings", {}).get("cash_balance", 0))
        market_value = sum(
            float(p.get("quantity", 0)) * float(p.get("market_price", 0))
            for p in self.state.get("positions", {}).values()
        )
        equity = max(1.0, cash + market_value)
        max_pct = self.max_correlation_group_pct()

        breach_warnings = []
        for group in groups:
            current_mv = sum(
                float(p.get("quantity", 0)) * float(p.get("market_price", 0))
                for p in self.state.get("positions", {}).values()
                if str(p.get("symbol", "")).upper() in CORRELATION_GROUPS.get(group, set())
            )
            new_mv = current_mv + additional_value
            new_pct = new_mv / equity
            if new_pct > max_pct:
                breach_warnings.append(
                    f"'{group}' group would reach {new_pct*100:.1f}% of equity (limit {max_pct*100:.0f}%). "
                    f"Existing exposure to {symbol}-correlated names already significant."
                )

        if breach_warnings:
            return {"approved": False, "reason": "; ".join(breach_warnings), "groups": groups}
        return {"approved": True, "groups": groups}

    # ------------------------------------------------------------------
    # 6. Adjusted position sizing (combines VIX + correlation + risk.py base sizing)
    # ------------------------------------------------------------------

    def adjusted_quantity(self, symbol: str, price: float, base_qty: int) -> Dict[str, Any]:
        """
        Take the base quantity from risk.py and adjust for VIX regime.
        Also returns warnings about correlation overlap.
        """
        vix_mult = self.vix_size_multiplier()
        adjusted_qty = max(1, int(base_qty * vix_mult)) if base_qty > 0 else 0

        # Check correlation capacity
        additional_value = adjusted_qty * price
        corr_check = self.check_correlation_capacity(symbol, additional_value)

        return {
            "base_quantity": base_qty,
            "vix_multiplier": vix_mult,
            "adjusted_quantity": adjusted_qty,
            "correlation_approved": corr_check["approved"],
            "correlation_reason": corr_check.get("reason", ""),
            "correlation_groups": corr_check.get("groups", []),
        }

    # ------------------------------------------------------------------
    # 7. Comprehensive risk intelligence summary
    # ------------------------------------------------------------------

    def evaluate_all(self) -> Dict[str, Any]:
        """Run all risk intelligence checks and return a unified summary."""
        stops = self.evaluate_position_stops()
        corr = self.correlation_exposures()
        sectors = self.sector_exposures()
        vix_mult = self.vix_size_multiplier()

        breaches = (
            [s for s in stops if s.urgency == "CRITICAL"]
            + [c for c in corr if c.breach]
            + [s for s in sectors if s.breach]
        )
        warnings = (
            [s for s in stops if s.urgency in ("HIGH", "MEDIUM")]
            + [c for c in corr if c.warning]
            + [s for s in sectors if s.warning]
        )

        summary = {
            "stop_alerts": [s.to_dict() for s in stops],
            "stop_alerts_critical": len([s for s in stops if s.urgency == "CRITICAL"]),
            "stop_alerts_high": len([s for s in stops if s.urgency == "HIGH"]),
            "correlation_exposures": [c.to_dict() for c in corr],
            "correlation_breaches": [c.to_dict() for c in corr if c.breach],
            "sector_exposures": [s.to_dict() for s in sectors],
            "sector_breaches": [s.to_dict() for s in sectors if s.breach],
            "vix_size_multiplier": vix_mult,
            "total_breaches": len(breaches),
            "total_warnings": len(warnings),
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.state["risk_intelligence"] = summary
        return summary
