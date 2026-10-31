#!/bin/bash
# Example: "photo touch-up" pipeline — all edits happen inside Photoshop.
set -euo pipefail
CLI="${CLI:-cli-anything-photoshop}"
OUT="${1:-/tmp/ps_cli_pipeline}"
mkdir -p "$OUT"

echo "» 1. ensure app"
($CLI app info --json | grep -q running) || $CLI app launch --wait 180

echo "» 2. create canvas"
$CLI --json doc new --width 640 --height 400 --name cli_pipeline --fill white

echo "» 3. text layer"
$CLI --doc cli_pipeline layer new --kind text --name Banner
$CLI --doc cli_pipeline layer text-set --layer Banner "Made with CLI-Anything"

echo "» 4. art layer + adjustment"
$CLI --doc cli_pipeline layer new --kind art --name Art
$CLI --doc cli_pipeline adj run invert --layer Art
$CLI --doc cli_pipeline adj run posterize --amount 8 --layer Art

echo "» 5. history walk"
$CLI --doc cli_pipeline history undo
$CLI --doc cli_pipeline history redo

echo "» 6. exports (python-verified magic bytes)"
$CLI --doc cli_pipeline export document "$OUT/pipeline.png" --overwrite
$CLI --doc cli_pipeline export document "$OUT/pipeline.psd" --overwrite

echo "» 7. close (discard)"
$CLI --doc cli_pipeline doc close

echo "done. artifacts in $OUT"
