#!/usr/bin/env bash
# Genera los íconos PNG de pantalla de inicio desde scripts/icon.svg (macOS: Quick Look + sips).
set -euo pipefail
cd "$(dirname "$0")/.."
tmp="$(mktemp -d)"
qlmanage -t -s 512 -o "$tmp" scripts/icon.svg >/dev/null
sips -s format png "$tmp/icon.svg.png" --out public/icon-512.png >/dev/null
sips -z 180 180 public/icon-512.png --out public/apple-touch-icon.png >/dev/null
sips -z 192 192 public/icon-512.png --out public/icon-192.png >/dev/null
rm -rf "$tmp"
echo "Íconos listos en public/"
