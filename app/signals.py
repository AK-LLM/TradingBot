from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
from app.models import Signal
from app.live_feeds import collect_live_signals as _collect_live_signals, LIVE_FEEDS

def collect_live_signals(state: Dict[str, Any], max_per_feed: int = 25, enabled_feeds: Optional[List[str]] = None) -> Tuple[List[Signal], List[Dict[str, Any]]]:
    return _collect_live_signals(state, max_per_feed=max_per_feed, enabled_feeds=enabled_feeds)

def list_live_feeds() -> List[Dict[str, Any]]:
    return [{"key": cfg.key, "name": cfg.name, "feed_type": cfg.feed_type, "requires_env": cfg.requires_env} for cfg in LIVE_FEEDS.values()]
