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
# Een eigen profiel: staat Chromium al open (bijvoorbeeld met de webapp), dan geeft een nieuwe
# Chromium met hetzelfde profiel zijn opdracht door aan die al draaiende, en die negeert --kiosk.
# Dan krijg je een gewoon venster met een titelbalk in plaats van het hele scherm.
exec "$CHROMIUM" --user-data-dir="$HOME/.config/bongo-kiosk" \
  --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
  --no-first-run --password-store=basic --check-for-update-interval=31536000 \
  --app="http://localhost:$POORT/kiosk"
