#!/bin/zsh
# Full asset rebuild: model -> textures -> optimise -> GLB for the web.
set -e
cd "$(dirname "$0")/.."
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
G="$PWD/tools/gltf/node_modules/.bin/gltf-transform"

echo "▸ generating model + textures in Blender"
"$BLENDER" -b --factory-startup -P tools/gen_sneaker.py -- --out assets/models "$@"

echo "▸ optimising for the web"
mv -f assets/models/phantom-runner.glb tools/source/phantom-runner.raw.glb
"$G" optimize tools/source/phantom-runner.raw.glb assets/models/phantom-runner.glb \
  --compress meshopt --texture-compress webp \
  --palette false --simplify false --join false --flatten false

echo "▸ verifying material + node names survived"
node tools/gltf/check.cjs assets/models/phantom-runner.glb

echo "✓ done — $(du -h assets/models/phantom-runner.glb | cut -f1)"
