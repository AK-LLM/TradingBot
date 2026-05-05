"""
Velocity Tracker - V5.5 Intelligence Enhancement

The core insight: a signal at strength 60 that was at strength 20 yesterday is
WAY more interesting than a signal at strength 80 that's been at 80 for a week.

The shark doesn't care that there's blood in the water. It cares that
MORE blood is appearing than a moment ago.

This module:
1. Maintains a short rolling history of signals per (source, narrative, symbol)
2. Computes velocity (1h delta) and acceleration (rate of change of delta)
3. Flags "accelerating" signals so the constellation engine and intelligence
   engine can prioritize them

Storage: in-memory only (per state dict). Survives across scans within a session.
"""

from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# How many samples to keep per signal channel
HISTORY_DEPTH = 24  # ~24 scans worth of history

# Thresholds for what counts as "accelerating"
ACCEL_THRESHOLD_RISING = 1.30   # Signal strength rising by 30% in recent vs prior window
ACCEL_THRESHOLD_FALLING = 0.70  # Signal strength falling by 30%
MIN_SAMPLES_FOR_VELOCITY = 4    # Need at least 4 samples to compute meaningful velocity


@dataclass
class VelocityReading:
    """Per-channel velocity calculation."""
    channel: str                # e.g., "Polymarket::oil_geopolitics::USO"
    current_strength: float
    recent_avg: float           # Avg of latest half of history
    prior_avg: float            # Avg of older half
    velocity_ratio: float       # recent_avg / prior_avg
    acceleration: str           # "ACCELERATING_UP", "ACCELERATING_DOWN", "STABLE", "NEW"
    samples: int
    first_seen: str
    last_seen: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class VelocityTracker:
    """
    Tracks how signal strength changes over time per (source, narrative, symbol)
    channel. Stores history in state for cross-scan continuity.
    """

    def __init__(self, state: Dict[str, Any]):
        self.state = state
        # Initialize history container if absent
        if "velocity_history" not in self.state:
            self.state["velocity_history"] = {}

    def _channel_key(self, signal: Dict[str, Any]) -> str:
        """Build a stable channel key for grouping over time."""
        source = signal.get("source", "unknown")
        meta = signal.get("metadata", {}) or {}
        narrative = meta.get("narrative", "general")
        symbol = signal.get("symbol", "MARKET")
        return f"{source}::{narrative}::{symbol}"

    def _compute_strength(self, signal: Dict[str, Any]) -> float:
        """
        Convert a signal into a single strength value 0-100 for velocity tracking.
        Combines confidence and magnitude into one number.
        """
        confidence = float(signal.get("confidence", 0.5))
        magnitude = float(signal.get("magnitude", 0))
        # Normalize magnitude to 0-1 range using soft cap
        norm_mag = min(1.0, magnitude / 100) if magnitude > 1 else magnitude
        # Weighted blend: confidence is the floor, magnitude is the amplifier
        strength = (confidence * 70) + (norm_mag * 30)
        return round(strength, 2)

    def record(self, signals: List[Dict[str, Any]]) -> None:
        """Add the current scan's signals to the rolling history."""
        history = self.state["velocity_history"]
        now_iso = datetime.now(timezone.utc).isoformat()

        for sig in signals:
            if not isinstance(sig, dict):
                continue
            channel = self._channel_key(sig)
            strength = self._compute_strength(sig)

            if channel not in history:
                history[channel] = {
                    "samples": [],
                    "first_seen": now_iso,
                }

            history[channel]["samples"].append({
                "ts": now_iso,
                "strength": strength,
                "direction": sig.get("direction", "WATCH"),
            })
            history[channel]["last_seen"] = now_iso

            # Keep only HISTORY_DEPTH most recent samples
            if len(history[channel]["samples"]) > HISTORY_DEPTH:
                history[channel]["samples"] = history[channel]["samples"][-HISTORY_DEPTH:]

        # Garbage collection: drop channels with no activity in last 100 scans
        # (we don't track scan count, so we cap total channels to prevent unbounded growth)
        if len(history) > 5000:
            # Drop oldest by last_seen
            sorted_channels = sorted(history.items(),
                                    key=lambda x: x[1].get("last_seen", ""),
                                    reverse=True)
            self.state["velocity_history"] = dict(sorted_channels[:3000])

    def compute_velocities(self) -> List[VelocityReading]:
        """Compute velocity readings for all channels with enough history."""
        history = self.state.get("velocity_history", {})
        readings: List[VelocityReading] = []

        for channel, data in history.items():
            samples = data.get("samples", [])
            if len(samples) < MIN_SAMPLES_FOR_VELOCITY:
                continue

            half = len(samples) // 2
            recent_samples = samples[half:]
            prior_samples = samples[:half]

            recent_avg = sum(s["strength"] for s in recent_samples) / len(recent_samples)
            prior_avg = sum(s["strength"] for s in prior_samples) / len(prior_samples)

            if prior_avg < 1:
                velocity_ratio = 1.0
            else:
                velocity_ratio = recent_avg / prior_avg

            if velocity_ratio >= ACCEL_THRESHOLD_RISING:
                acceleration = "ACCELERATING_UP"
            elif velocity_ratio <= ACCEL_THRESHOLD_FALLING:
                acceleration = "ACCELERATING_DOWN"
            else:
                acceleration = "STABLE"

            current_strength = samples[-1]["strength"]

            readings.append(VelocityReading(
                channel=channel,
                current_strength=current_strength,
                recent_avg=round(recent_avg, 2),
                prior_avg=round(prior_avg, 2),
                velocity_ratio=round(velocity_ratio, 3),
                acceleration=acceleration,
                samples=len(samples),
                first_seen=data.get("first_seen", ""),
                last_seen=data.get("last_seen", ""),
            ))

        # Mark new channels (those not yet at MIN_SAMPLES) as "NEW" so the
        # constellation engine can flag fresh signal sources
        for channel, data in history.items():
            samples = data.get("samples", [])
            if 0 < len(samples) < MIN_SAMPLES_FOR_VELOCITY:
                readings.append(VelocityReading(
                    channel=channel,
                    current_strength=samples[-1]["strength"] if samples else 0,
                    recent_avg=0,
                    prior_avg=0,
                    velocity_ratio=1.0,
                    acceleration="NEW",
                    samples=len(samples),
                    first_seen=data.get("first_seen", ""),
                    last_seen=data.get("last_seen", ""),
                ))

        return readings

    def accelerating_channels(self) -> List[VelocityReading]:
        """Return only channels that are accelerating up (the interesting ones)."""
        return [r for r in self.compute_velocities()
                if r.acceleration in ("ACCELERATING_UP", "NEW")]

    def velocity_for_signal(self, signal: Dict[str, Any]) -> Optional[VelocityReading]:
        """Get velocity reading for a specific signal's channel."""
        channel = self._channel_key(signal)
        for reading in self.compute_velocities():
            if reading.channel == channel:
                return reading
        return None

    def summary(self) -> Dict[str, Any]:
        """High-level summary of velocity state for UI/debugging."""
        readings = self.compute_velocities()
        return {
            "total_channels": len(self.state.get("velocity_history", {})),
            "tracked_with_velocity": len([r for r in readings if r.acceleration != "NEW"]),
            "accelerating_up": len([r for r in readings if r.acceleration == "ACCELERATING_UP"]),
            "accelerating_down": len([r for r in readings if r.acceleration == "ACCELERATING_DOWN"]),
            "new_channels": len([r for r in readings if r.acceleration == "NEW"]),
            "stable": len([r for r in readings if r.acceleration == "STABLE"]),
        }
