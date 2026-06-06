#!/usr/bin/env bash
# uninstall_mac.sh — unregister STP's launchd agent.
set -euo pipefail
LABEL="ventures.local.signal-trading-platform.monitor"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
if [[ -f "$PLIST" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "✓ Removed ${LABEL}"
else
  echo "(${LABEL} was not installed)"
fi
