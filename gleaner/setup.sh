#!/bin/bash
# gleaner setup for macOS (also works on a Raspberry Pi / Debian).
# Run from inside the gleaner folder:  bash setup.sh
set -e
cd "$(dirname "$0")"
HERE="$(pwd)"
CONF="$HOME/.gleaner"

echo "🌾 Setting up gleaner in $HERE"

if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 not found. On a Mac, run:  xcode-select --install   then run this again."
  exit 1
fi
echo "   Python: $(python3 --version)"

if [ ! -d .venv ]; then
  echo "   Creating a private Python environment (.venv)…"
  python3 -m venv .venv || {
    echo "❌ Couldn't create it. On Debian (fatline), run:  sudo apt install python3-venv"
    echo "   then:  rm -rf .venv  and run this again."; exit 1; }
fi
echo "   Installing libraries (a minute or two the first time)…"
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo "   ✅ libraries installed"

mkdir -p "$CONF" && chmod 700 "$CONF"
if [ -f "$CONF/gleaner.env" ] && grep -q '^DISCORD_TOKEN=.' "$CONF/gleaner.env"; then
  echo "   ✅ Discord token already saved in $CONF/gleaner.env"
else
  echo
  echo "   Paste gleaner's Discord bot token and press Enter."
  echo "   (Nothing will appear as you paste. That's deliberate.)"
  read -r -s -p "   Token: " TOKEN; echo
  if [ -z "$TOKEN" ]; then echo "❌ No token entered."; exit 1; fi
  cat > "$CONF/gleaner.env" <<EOF
# gleaner settings
DISCORD_TOKEN=$TOKEN
CHANNEL=gleanings
# MODE=local saves into the Dropbox desktop app's folder (this Mac).
# MODE=api uploads with ~/.gleaner/dropbox.env instead (Pi / exlo, no desktop app).
MODE=local
# OUTPUT_DIR=~/Library/CloudStorage/Dropbox/Apps/cyby
# DROPBOX_SUBFOLDER=
EOF
  chmod 600 "$CONF/gleaner.env"
  echo "   ✅ token saved to $CONF/gleaner.env"
fi

echo
if grep -qi '^MODE=api' "$CONF/gleaner.env"; then
  echo "   MODE=api: checking the Dropbox login…"
  if [ -f "$CONF/dropbox.env" ]; then
    python3 dropbox_login.py --check
  else
    echo "   ⚠️  No Dropbox login yet. Run:  python3 dropbox_login.py"
  fi
else
  echo "   Checking the Dropbox folder…"
  .venv/bin/python -c "import gleaner; print('   ✅ will deliver to', gleaner.default_dropbox_dir())"
fi
echo
echo "Done. Start gleaner with:   bash $HERE/run.sh"
