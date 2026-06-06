#!/usr/bin/env bash
# uninstall_linux.sh — remove STP's systemd-user service or crontab block.
set -euo pipefail

# systemd-user path
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/signal-trading-platform.service"
if [[ -f "$UNIT" ]]; then
  systemctl --user stop signal-trading-platform.service 2>/dev/null || true
  systemctl --user disable signal-trading-platform.service 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload 2>/dev/null || true
  echo "✓ Removed systemd-user service"
fi

# crontab fallback path
MARK_START="# >>> signal-trading-platform (managed) >>>"
MARK_END="# <<< signal-trading-platform (managed) <<<"
current="$(crontab -l 2>/dev/null || true)"
if printf '%s' "$current" | grep -q "$MARK_START"; then
  stripped="$(printf '%s\n' "$current" | awk -v s="$MARK_START" -v e="$MARK_END" '
    $0==s {skip=1; next}
    $0==e {skip=0; next}
    !skip {print}
  ')"
  printf '%s\n' "$stripped" | crontab -
  echo "✓ Removed crontab block"
fi
echo "STP scripts + state are untouched at ${PWD}/"
