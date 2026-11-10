#!/bin/bash
# Run gleaner as a background service on macOS (starts at login, restarts if it stops).
#   bash service.sh install     set up and start
#   bash service.sh status      is it running? (plus the last few log lines)
#   bash service.sh log         follow the log live (Ctrl+C to stop watching)
#   bash service.sh restart     restart, e.g. after updating gleaner.py
#   bash service.sh uninstall   stop and remove the service
set -e
cd "$(dirname "$0")"
HERE="$(pwd)"
LABEL="com.blueskyharvest.gleaner"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/gleaner.log"
DOMAIN="gui/$(id -u)"

case "${1:-}" in
  install)
    if [ ! -x "$HERE/.venv/bin/python" ]; then
      echo "❌ Run  bash setup.sh  first."; exit 1
    fi
    if pgrep -f "gleaner.py" >/dev/null 2>&1 && ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      echo "⚠️  gleaner is already running in a Terminal window."
      echo "    Press Ctrl+C in that window first, so there aren't two copies answering."
      exit 1
    fi
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$HERE/.venv/bin/python</string>
    <string>-u</string>
    <string>$HERE/gleaner.py</string>
  </array>
  <key>WorkingDirectory</key><string>$HERE</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
    plutil -lint "$PLIST" >/dev/null
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "✅ gleaner installed as a background service."
    echo "   It starts when you log in and restarts itself if it stops."
    sleep 8
    bash "$HERE/service.sh" status
    ;;
  status)
    if launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -q "state = running"; then
      echo "🌾 gleaner is running."
    else
      echo "💤 gleaner is not running right now."
    fi
    if [ -f "$LOG" ]; then echo "--- last log lines ---"; tail -n 6 "$LOG"; fi
    ;;
  log)
    tail -n 30 -f "$LOG"
    ;;
  restart)
    launchctl kickstart -k "$DOMAIN/$LABEL" && echo "🔄 gleaner restarted." && sleep 6 && bash "$HERE/service.sh" status
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "✅ gleaner service removed. (Run it by hand any time with  bash run.sh)"
    ;;
  *)
    echo "Usage: bash service.sh install | status | log | restart | uninstall"
    ;;
esac
