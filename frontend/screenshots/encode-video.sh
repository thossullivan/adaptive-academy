#!/usr/bin/env sh
# Turn the raw README recording (readme-video.shots.ts) into docs/images/demo.gif and demo.mp4.
# Needs ffmpeg. Run from frontend/ via `npm run demo-video`.
set -eu

RAW=test-results/readme-video
OUT=../docs/images
TRIM=$(sed -E 's/.*"trimSeconds":([0-9.]+).*/\1/' "$RAW/demo.json")

# The GIF plays inline on GitHub; 10 fps at 960px keeps it a few MB.
ffmpeg -loglevel error -y -ss "$TRIM" -i "$RAW/demo.webm" \
  -vf "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
  "$OUT/demo.gif"

# Full size, for anyone who clicks through.
ffmpeg -loglevel error -y -ss "$TRIM" -i "$RAW/demo.webm" \
  -c:v libx264 -preset slow -crf 24 -pix_fmt yuv420p -movflags +faststart -an \
  "$OUT/demo.mp4"

ls -lh "$OUT/demo.gif" "$OUT/demo.mp4"
