from __future__ import annotations
from app.config import load_env_file
load_env_file()
import argparse
import time
from app.platform import TradingPlatform
from app.watchdog import Watchdog


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Signal Trading Platform watchdog without Streamlit.")
    parser.add_argument("--state", default="data/state.json", help="Path to shared state file used by the UI.")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between watchdog cycles.")
    parser.add_argument("--signals", type=int, default=80, help="Maximum live signals to collect per cycle.")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    args = parser.parse_args()

    platform = TradingPlatform(store_path=args.state)
    watchdog = Watchdog(platform)
    while True:
        result = watchdog.cycle(max_signals=args.signals)
        print(f"[{result['last_run']}] signals={result['signals']} new_flash={result['new_flash_alerts']} active_flash={result['active_flash_alerts']}", flush=True)
        if args.once:
            break
        time.sleep(max(10, args.interval))

if __name__ == "__main__":
    main()
