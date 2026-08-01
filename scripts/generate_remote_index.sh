#!/usr/bin/env bash
# Regenerates the remote asset library index (_asset-library-meta.json,
# _v1/asset-index.json, _v1/assets-*.json, and per-asset .webp thumbnails)
# from assets/primitives.blend, using Blender's built-in listing generator.
#
# Run this after scripts/build_library.py whenever primitives.blend changes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BLENDER="${BLENDER:-blender}"

"$BLENDER" -c asset_listing generate "$ROOT/assets"
