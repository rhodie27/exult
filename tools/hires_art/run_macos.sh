#!/usr/bin/env bash
# Make hi-res art for Exult on macOS and switch it on.
# Usage: tools/hires_art/run_macos.sh [SHAPES]   (default 0-149: the ground tiles)
#   SHAPES is a list like 0-149,500 of shapes.vga numbers.
# Needs the game in /Library/Application Support/Exult/blackgate, owned by you.
# The first run downloads PyTorch and the 4x-PixelPerfectV4 model (WTFPL licence).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
GAME="/Library/Application Support/Exult/blackgate"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/exult-hires-art"
MODEL="$CACHE/4x-PixelPerfectV4.pth"
SHAPES="${1:-0-149}"
mkdir -p "$CACHE"

[ -d "$GAME/STATIC" ] || { echo "No game files in $GAME/STATIC"; exit 1; }
mkdir -p "$GAME/patch" 2>/dev/null && [ -w "$GAME/patch" ] || {
  echo "Can't write to $GAME/patch. Fix with: sudo chown -R \"\$(whoami)\" \"$GAME\""
  exit 1
}

if [ ! -x "$CACHE/venv/bin/python" ]; then
  python3 -m venv "$CACHE/venv"
fi
"$CACHE/venv/bin/pip" -q install --upgrade pip
"$CACHE/venv/bin/pip" -q install pillow numpy torch spandrel gdown

if [ ! -s "$MODEL" ]; then
  "$CACHE/venv/bin/gdown" -q -O "$MODEL" 1x583PgpY5O4T2603gJK8kwrGiIc4aFne
fi

"$CACHE/venv/bin/python" "$HERE/upscale_shapes.py" --model "$MODEL" --res 4 --shapes "$SHAPES" --sheet \
  "$GAME/STATIC" "$GAME/patch"

# Turn hi-res art on (config/video/hires_art = 4).
CFG="$HOME/Library/Preferences/exult.cfg"
if [ -f "$CFG" ]; then
  cp "$CFG" "$CFG.before-hires"
  "$CACHE/venv/bin/python" - "$CFG" <<'EOF'
import re, sys
path = sys.argv[1]
text = open(path).read()
if re.search(r"<hires_art>", text):
    text = re.sub(r"<hires_art>.*?</hires_art>", "<hires_art>4</hires_art>", text, flags=re.S)
else:
    text = text.replace("<video>", "<video>\n\t\t<hires_art>4</hires_art>", 1)
open(path, "w").write(text)
EOF
  echo "Turned on hi-res art in $CFG (old copy: $CFG.before-hires)."
else
  echo "No $CFG yet: run Exult once, then run this again."
fi
echo "Art is in $GAME/patch/hires. To go back to the original look, delete that folder."
open "$GAME/patch/hires" 2>/dev/null || true
