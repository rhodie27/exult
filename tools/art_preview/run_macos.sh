#!/usr/bin/env bash
# Build the art preview on macOS from Exult screenshots.
# Usage: tools/art_preview/run_macos.sh OUT_DIR SCREENSHOT...
set -euo pipefail
eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/exult-art-preview"
mkdir -p "$CACHE"

# Exult's scalers as a standalone tool.
c++ -std=c++17 -O2 -DHAVE_CONFIG_H -I"$ROOT" -I"$ROOT/headers" -I"$ROOT/imagewin" -I"$ROOT/files" -I"$ROOT/shapes" \
  $(pkg-config --cflags sdl3 sdl3-image) "$ROOT/tools/upscale_preview.cc" -o "$CACHE/upscale_preview" \
  $(pkg-config --libs sdl3 sdl3-image)

# Real-ESRGAN (runs on the Mac's GPU through Vulkan/MoltenVK).
if [ ! -x "$CACHE/esrgan/realesrgan-ncnn-vulkan" ]; then
  curl -sSL -o "$CACHE/esrgan.zip" https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip
  mkdir -p "$CACHE/esrgan" && unzip -oq "$CACHE/esrgan.zip" -d "$CACHE/esrgan"
  chmod +x "$CACHE/esrgan/realesrgan-ncnn-vulkan"
  xattr -dr com.apple.quarantine "$CACHE/esrgan" 2>/dev/null || true
fi

python3 -m venv "$CACHE/venv" && "$CACHE/venv/bin/pip" -q install pillow
UPSCALE_PREVIEW="$CACHE/upscale_preview" ESRGAN="$CACHE/esrgan/realesrgan-ncnn-vulkan" \
  "$CACHE/venv/bin/python" "$HERE/make_preview.py" "$@"
