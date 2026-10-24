#!/usr/bin/env bash
# Build the art preview on macOS.
# Usage: tools/art_preview/run_macos.sh [--redraw] OUT_DIR [STATIC_DIR | IMAGE...]
#   With no inputs, scenes are rendered from the Black Gate files Exult uses.
#   --redraw also repaints each image with SDXL (first run downloads about 7 GB).
set -euo pipefail
eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/exult-art-preview"
mkdir -p "$CACHE/models"

REDRAW=()
if [ "${1:-}" = "--redraw" ]; then
  REDRAW=(--redraw)
  shift
fi
OUT="$1"
shift

# Exult's scalers as a standalone tool.
c++ -std=c++17 -O2 -DHAVE_CONFIG_H -I"$ROOT" -I"$ROOT/headers" -I"$ROOT/imagewin" -I"$ROOT/files" -I"$ROOT/shapes" \
  $(pkg-config --cflags sdl3 sdl3-image) "$ROOT/tools/upscale_preview.cc" -o "$CACHE/upscale_preview" \
  $(pkg-config --libs sdl3 sdl3-image)

# Pixel-art upscaling models from OpenModelDB (non-commercial licences: fine for previews).
BASE=https://objectstorage.us-phoenix-1.oraclecloud.com/n/ax6ygfvpvzka/b/open-modeldb-files/o
for m in 4x-NXbrz 4x-Fatal-Pixels 4x-Fatality-MK2 2x-Faithful-Lite; do
  [ -s "$CACHE/models/$m.pth" ] || curl -fsSL -o "$CACHE/models/$m.pth" "$BASE/$m.pth"
done

if [ ! -x "$CACHE/venv/bin/python" ]; then
  python3 -m venv "$CACHE/venv"
fi
"$CACHE/venv/bin/pip" -q install --upgrade pip
"$CACHE/venv/bin/pip" -q install pillow numpy torch spandrel diffusers transformers accelerate safetensors

if [ $# -eq 0 ]; then
  set -- "/Library/Application Support/Exult/blackgate/STATIC"
fi
if [ $# -eq 1 ] && [ -d "$1" ]; then
  "$CACHE/venv/bin/python" "$HERE/render_scenes.py" "$1" "$OUT/shots"
  set -- "$OUT"/shots/*.png
fi
UPSCALE_PREVIEW="$CACHE/upscale_preview" \
  "$CACHE/venv/bin/python" "$HERE/make_preview.py" --models "$CACHE/models" ${REDRAW[@]+"${REDRAW[@]}"} "$OUT" "$@"
