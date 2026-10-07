#!/bin/sh
# Start het touchscreen als kiosk: Chromium op het hele scherm met de pagina /kiosk.
# Wordt gestart door de desktop (deploy/bongo-kiosk.desktop, zie README).

POORT="${KERN_POORT:-8765}"

if [ -z "$DISPLAY" ]; then
  echo "Geen scherm gevonden. Start dit in een terminal op de Pi zelf, of via SSH met: DISPLAY=:0 $0" >&2
  exit 1
fi
CHROMIUM="$(command -v chromium-browser || command -v chromium)"
if [ -z "$CHROMIUM" ]; then
  echo "Chromium is niet geïnstalleerd: sudo apt install chromium-browser" >&2
  exit 1
fi

xset s off          # geen schermbeveiliging
xset s noblank
xset dpms 0 0 0     # het scherm niet vanzelf uit; 's nachts regelt Bongo dat zelf
unclutter -idle 0.5 -root 2> /dev/null &   # de muisaanwijzer verbergen

# Wacht tot de kern draait (na een herstart kan dat even duren).
if ! curl -fs "http://localhost:$POORT/api/toestand" > /dev/null; then
  echo "Wachten tot de kern draait op poort $POORT... Start hem met: systemctl --user start bongo-kern"
  echo "(of in een andere terminal: cd ~/Home_Assistant && .venv/bin/python -m assistent.kern)"
  until curl -fs "http://localhost:$POORT/api/toestand" > /dev/null; do sleep 2; done
fi
echo "De kern draait. Bongo's gezicht gaat open."

# Een eigen profiel: staat Chromium al open (bijvoorbeeld met de webapp), dan geeft een nieuwe
# Chromium met hetzelfde profiel zijn opdracht door aan die al draaiende, en die negeert --kiosk.
# Dan krijg je een gewoon venster met een titelbalk in plaats van het hele scherm.
exec "$CHROMIUM" --user-data-dir="$HOME/.config/bongo-kiosk" \
  --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
  --no-first-run --password-store=basic --check-for-update-interval=31536000 \
  --app="http://localhost:$POORT/kiosk"
