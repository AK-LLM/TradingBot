#!/usr/bin/env bash
# schedule_mac.sh — install STP's monitor loop as a launchd LaunchAgent.
#
# Runs `python monitor.py --interval 60` as a background service that survives
# logout. Idempotent: re-running unloads + reloads cleanly.
#
# Logs land in ~/Library/Logs/signal-trading-platform/

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v python3)"
if [[ -z "$PY" ]]; then
  echo "python3 not found on PATH. Install Python 3.10+ first." >&2
  exit 1
fi

LABEL="ventures.local.signal-trading-platform.monitor"
LA_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/signal-trading-platform"
PLIST="$LA_DIR/${LABEL}.plist"

mkdir -p "$LA_DIR" "$LOG_DIR"

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PY}</string>
    <string>${PROJECT_ROOT}/monitor.py</string>
    <string>--interval</string>
    <string>60</string>
  </array>
  <key>WorkingDirectory</key><string>${PROJECT_ROOT}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key><false/>
  </dict>
  <key>StandardOutPath</key><string>${LOG_DIR}/monitor.out.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/monitor.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "✓ STP monitor installed at ${LABEL}"
echo "  Logs → ${LOG_DIR}/"
echo "  Uninstall with: bash ${PROJECT_ROOT}/install/uninstall_mac.sh"
