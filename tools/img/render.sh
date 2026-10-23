#!/bin/sh
# Render the README's pictures: tools/img/*.html -> doc/img/*.png (needs a Chromium; Playwright's will do).
set -e
cd "$(dirname "$0")"
CHROME="${CHROME:-$(ls /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1)}"
for name in layers contract tour; do
  "$CHROME" --headless --no-sandbox --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --window-size=1600,1400 --screenshot="../../doc/img/$name-full.png" "file://$PWD/$name.html" >/dev/null 2>&1
done
python3 crop.py ../../doc/img/*-full.png
rm ../../doc/img/*-full.png
