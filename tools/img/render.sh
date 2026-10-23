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
# The GitHub social preview is 1280x640; the headless window is taller than the page, so it is cropped.
"$CHROME" --headless --no-sandbox --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --window-size=1280,800 --screenshot=/tmp/social-full.png "file://$PWD/social.html" >/dev/null 2>&1
python3 -c "from PIL import Image; Image.open('/tmp/social-full.png').crop((0,0,1280,640)).save('../../doc/img/social.png', optimize=True)"
