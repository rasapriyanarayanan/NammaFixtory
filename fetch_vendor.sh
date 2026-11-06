#!/usr/bin/env bash
# Run ONCE with internet access to bundle the map library, so the prototype also works
# offline (for example at a symposium venue with unreliable wifi). Map tiles still need
# internet; without them the pins and rings show on a plain background.
set -euo pipefail
cd "$(dirname "$0")/../static"
mkdir -p vendor/images
V=1.9.4
BASE="https://unpkg.com/leaflet@${V}/dist"
curl -fsSL "$BASE/leaflet.js"  -o vendor/leaflet.js
curl -fsSL "$BASE/leaflet.css" -o vendor/leaflet.css
for f in marker-icon.png marker-icon-2x.png marker-shadow.png layers.png layers-2x.png; do
  curl -fsSL "$BASE/images/$f" -o "vendor/images/$f"
done
echo "Leaflet ${V} bundled in static/vendor"
