#!/bin/sh
# Start het touchscreen als kiosk: Chromium op het hele scherm met de pagina /kiosk.
# Wordt gestart door de desktop (deploy/bongo-kiosk.desktop, zie README).

POORT="${KERN_POORT:-8765}"

xset s off          # geen schermbeveiliging
xset s noblank
xset dpms 0 0 0     # het scherm niet vanzelf uit; 's nachts regelt Bongo dat zelf
unclutter -idle 0.5 -root &   # de muisaanwijzer verbergen

# Wacht tot de kern draait (na een herstart kan dat even duren).
until curl -fs "http://localhost:$POORT/api/toestand" > /dev/null; do sleep 2; done

CHROMIUM="$(command -v chromium-browser || command -v chromium)"
exec "$CHROMIUM" --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
  --no-first-run --password-store=basic --check-for-update-interval=31536000 \
  --app="http://localhost:$POORT/kiosk"
