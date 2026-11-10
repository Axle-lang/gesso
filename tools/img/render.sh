#!/bin/sh
# Render the README's pictures: tools/img/*.html -> doc/img/*.png (needs a Chromium; Playwright's will do).
# Each picture is shot in a window of exactly its own size, so nothing is cropped afterwards.
set -e
cd "$(dirname "$0")"
CHROME="${CHROME:-$(ls /opt/pw-browsers/chromium-*/chrome-linux/chrome 2>/dev/null | head -1)}"
shot() { # name width height
  "$CHROME" --headless --no-sandbox --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --window-size="$2,$3" --screenshot="../../doc/img/$1.png" "file://$PWD/$1.html" >/dev/null 2>&1
}
shot layers 1600 949
shot contract 1600 965
shot tour 1600 732
# The GitHub social preview is 1280x640.
shot social 1280 640
