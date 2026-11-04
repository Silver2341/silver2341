#!/usr/bin/env bash
# Pull the newest Lookout renderer from the original repo so every banner
# (yours and all copies) gets new features automatically.
# Opt out by setting "auto_update": false in config.json.
set -u
if [ "${GITHUB_REPOSITORY:-}" = "Flaco2009/lookout-banner" ]; then exit 0; fi
if grep -q '"auto_update": *false' config.json 2>/dev/null; then echo "auto update disabled"; exit 0; fi
base="https://raw.githubusercontent.com/Flaco2009/lookout-banner/main"
mkdir -p assets/terrain
for f in generate.py terrain.py assets/terrain/depth.png assets/terrain/height.png assets/terrain/normal.png assets/terrain/tex.png; do
  if curl -fsSL --retry 2 "$base/$f" -o "$f.new"; then mv "$f.new" "$f"; else rm -f "$f.new"; echo "keeping local $f"; fi
done
