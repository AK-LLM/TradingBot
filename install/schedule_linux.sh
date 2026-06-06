#!/usr/bin/env bash
# schedule_linux.sh — register STP's monitor with systemd-user (preferred) or
# crontab (fallback). Logs land in ~/.local/state/signal-trading-platform/.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v python3)"
if [[ -z "$PY" ]]; then
  echo "python3 not found on PATH. Install Python 3.10+ first." >&2
  exit 1
fi

LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/signal-trading-platform"
mkdir -p "$LOG_DIR"

if command -v systemctl >/dev/null 2>&1 && systemctl --user >/dev/null 2>&1; then
  # --- systemd-user path (preferred) ---
  UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  mkdir -p "$UNIT_DIR"

  cat >"$UNIT_DIR/signal-trading-platform.service" <<EOF
[Unit]
Description=Signal Trading Platform monitor loop
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_ROOT}
ExecStart=${PY} ${PROJECT_ROOT}/monitor.py --interval 60
Restart=on-failure
RestartSec=10
StandardOutput=append:${LOG_DIR}/monitor.out.log
StandardError=append:${LOG_DIR}/monitor.err.log

[Install]
WantedBy=default.target
EOF

  systemctl --user daemon-reload
  systemctl --user enable signal-trading-platform.service
  systemctl --user restart signal-trading-platform.service

  echo "✓ STP monitor installed as systemd-user service."
  echo "  Status: systemctl --user status signal-trading-platform"
  echo "  Logs:   ${LOG_DIR}/"
  echo "  (To survive logout: 'loginctl enable-linger \$USER')"

else
  # --- crontab fallback ---
  MARK_START="# >>> signal-trading-platform (managed) >>>"
  MARK_END="# <<< signal-trading-platform (managed) <<<"

  current="$(crontab -l 2>/dev/null || true)"
  stripped="$(printf '%s\n' "$current" | awk -v s="$MARK_START" -v e="$MARK_END" '
    $0==s {skip=1; next}
    $0==e {skip=0; next}
    !skip {print}
  ')"

  block="$(cat <<EOF
${MARK_START}
* * * * * cd ${PROJECT_ROOT} && ${PY} monitor.py --interval 60 >> ${LOG_DIR}/monitor.cron.log 2>&1
${MARK_END}
EOF
)"
  # Note: monitor.py loops internally on --interval, so the cron entry above
  # will start it once a minute. If it's already running, monitor.py's lock
  # behavior (or a simple `pgrep -f monitor.py && exit` guard) prevents
  # duplicates. For belt-and-braces, use a wrapper script.
  printf '%s\n\n%s\n' "$stripped" "$block" | crontab -

  echo "✓ STP monitor scheduled via crontab."
  echo "  Inspect: crontab -l"
  echo "  Logs:    ${LOG_DIR}/"
fi
