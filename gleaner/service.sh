#!/bin/bash
# Run gleaner as a background service (starts by itself, restarts if it stops).
#   macOS: a launchd agent (starts at login).
#   Linux (fatline): a systemd user service that runs from boot, nobody logged in.
#   bash service.sh install     set up and start
#   bash service.sh status      is it running? (plus the last few log lines)
#   bash service.sh log         follow the log live (Ctrl+C to stop watching)
#   bash service.sh restart     restart, e.g. after updating gleaner.py
#   bash service.sh uninstall   stop and remove the service
set -e
cd "$(dirname "$0")"
HERE="$(pwd)"

if [ "$(uname)" = "Linux" ]; then
  UNIT="gleaner.service"
  UNIT_FILE="$HOME/.config/systemd/user/$UNIT"
  case "${1:-}" in
    install)
      if [ ! -x "$HERE/.venv/bin/python" ]; then
        echo "❌ Run  bash setup.sh  first."; exit 1
      fi
      mkdir -p "$(dirname "$UNIT_FILE")"
      printf '%s\n' \
        "[Unit]" \
        "Description=gleaner, the Blue Sky Harvest courier for cyby" \
        "Wants=network-online.target" \
        "After=network-online.target" \
        "" \
        "[Service]" \
        "WorkingDirectory=$HERE" \
        "ExecStart=$HERE/.venv/bin/python -u $HERE/gleaner.py" \
        "Restart=always" \
        "RestartSec=30" \
        "Nice=5" \
        "" \
        "[Install]" \
        "WantedBy=default.target" > "$UNIT_FILE"
      echo "   Letting gleaner run from boot, even when nobody is logged in"
      echo "   (may ask for your password)…"
      sudo loginctl enable-linger "$USER"
      systemctl --user daemon-reload
      systemctl --user enable --now "$UNIT"
      echo "✅ gleaner installed as a background service."
      echo "   It starts when this machine boots and restarts itself if it stops."
      sleep 8
      bash "$HERE/service.sh" status
      ;;
    status)
      if systemctl --user is-active --quiet "$UNIT"; then
        echo "🌾 gleaner is running."
      else
        echo "💤 gleaner is not running right now."
      fi
      echo "--- last log lines ---"
      journalctl --user -u "$UNIT" -n 6 --no-pager -o cat 2>/dev/null || true
      ;;
    log)
      journalctl --user -u "$UNIT" -n 30 -f -o cat
      ;;
    restart)
      systemctl --user restart "$UNIT" && echo "🔄 gleaner restarted." && sleep 6 && bash "$HERE/service.sh" status
      ;;
    uninstall)
      systemctl --user disable --now "$UNIT" 2>/dev/null || true
      rm -f "$UNIT_FILE"
      systemctl --user daemon-reload
      echo "✅ gleaner service removed. (Run it by hand any time with  bash run.sh)"
      ;;
    *)
      echo "Usage: bash service.sh install | status | log | restart | uninstall"
      ;;
  esac
  exit 0
fi

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
