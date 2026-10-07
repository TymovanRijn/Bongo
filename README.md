# Bongo

De huisassistent van Tymo: een Raspberry Pi 5 met een touchscreen, die je agenda kent,
dingen voor je onthoudt en met je praat. Het brein is Claude.

## De belangrijkste regel

**Niets met gevolgen zonder bevestiging.** Claude kan de agenda lezen, maar een afspraak
toevoegen, iets onthouden of iets vergeten kan hij alleen *voorstellen*. Zo'n voorstel
komt in de wachtrij (`assistent/wachtrij.py`) en gebeurt pas als een mens het goedkeurt:
in de webapp, op het touchscreen (twee keer tikken) of met `/ja` in de terminal.

## Hoe het in elkaar zit

| Bestand | Wat het doet |
|---|---|
| `assistent/kern.py` | De server die altijd draait: webapp, touchscreen, API (`python -m assistent.kern`) |
| `assistent/toegang.py` | Wie er bij de webapp mag (netwerk, herkomst, pincode of koppellink) |
| `assistent/planner.py` | Ochtendoverzicht, logboek opruimen, scherm 's nachts uit |
| `assistent/web/` | De pagina's: webapp (`/`), Bongo's gezicht op het touchscreen (`/kiosk`), aanmelden (`/inloggen`) |
| `assistent/spraak/` | Luisteren, verstaan (Whisper), praten (Piper); zie `docs/spraak.md` |
| `assistent/meet.py` | Meet snelheid en kosten van verschillende modellen (`python -m assistent.meet`) |
| `assistent/brain.py` | De agent-lus rond Claude: vraag stellen, tools uitvoeren, gesprek bijhouden en inkorten |
| `assistent/tools.py` | De tools die Claude mag gebruiken (agenda lezen, voorstellen doen) |
| `assistent/wachtrij.py` | Voorstellen die op goedkeuring wachten, en herstel na een stroomstoring |
| `assistent/executors.py` | Wat er gebeurt *nadat* een voorstel is goedgekeurd, en de controle daarop |
| `assistent/geheugen.py` | `data/over_mij.md`: wat Bongo over je weet |
| `assistent/calendar_backend.py` | Nep-agenda (om te testen) en iCloud via CalDAV |
| `assistent/overzicht.py` | Agenda per dag en het ochtendoverzicht |
| `assistent/logboek.py`, `db.py` | SQLite: gesprekken, kosten, metingen, apparaten |
| `assistent/config.py` | Alle instellingen, gelezen uit `.env` |
| `assistent/opbouw.py` | Knoopt alle onderdelen aan elkaar |
| `assistent/cli.py` | Praten met Bongo in de terminal (`python -m assistent`) |
| `deploy/` | Automatisch starten op de Pi |
| `docs/beslispunten.md` | De keuzes (gespreksgeheugen, toegang, spraak, model, ...) en waarom |
| `docs/spraak.md` | Hoe de spraak werkt, en de microfoon en luidspreker aansluiten |
| `docs/agenda.md` | Je iCloud-agenda's en abonnementen koppelen |
| `docs/hardware.md` | Wat er in en aan de Pi zit (fase 0) |
| `docs/oefeningen.md` | Echte problemen uit deze code, met uitwerking |

## Installeren (op de Pi)

```bash
cd ~/Home_Assistant              # of waar je deze map hebt staan
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env             # vul daarna ANTHROPIC_API_KEY en WEB_PIN in
.venv/bin/python -m pytest       # alles moet slagen
```

> De map `.venv` stond eerst in git, maar hoort daar niet in (zie `.gitignore`). Weigert
> `git pull` vanwege bestanden in `.venv`, of doet Python het daarna niet meer: gooi de map
> weg (`rm -rf .venv`), doe `git pull` opnieuw en maak hem opnieuw met de regels hierboven.

## Gebruiken

```bash
.venv/bin/python -m assistent.kern                   # de kern starten
.venv/bin/python -m assistent                        # of: praten in de terminal (/hulp)
.venv/bin/python -m assistent "wat heb ik morgen?"   # één vraag en klaar
```

Met de kern aan:

- **Touchscreen:** `http://localhost:8765/kiosk` (op de Pi zelf, zonder aanmelden). Tik op het gezicht
  om te praten (zie `docs/spraak.md` voor de microfoon), of zet het wekwoord aan (`WEKWOORD=hey_jarvis`).
- **Microfoon en speakers testen:** `.venv/bin/python -m assistent.kern geluid` (met de kern uit). Hij
  zegt ook wat er in `.env` moet.
- **Telefoon:** `http://192.168.1.53:8765` of `http://raspberrypi.local:8765`. De eerste keer vraagt
  hij de pincode uit `WEB_PIN`. Zet daarna "Toevoegen aan beginscherm" aan in de browser.
- **Nog een apparaat koppelen zonder pincode:** in de webapp onder Meer > Apparaten, of op de Pi:
  `.venv/bin/python -m assistent.kern koppel "iPad"`. Die link werkt één keer, 24 uur lang.
- **Apparaat kwijt?** Meer > Apparaten > Ontkoppel, of `python -m assistent.kern apparaten` en `ontkoppel <id>`.

Standaard gebruikt Bongo een nep-agenda (`data/mock_agenda.json`). Je echte iCloud-agenda's
koppelen, en abonnementen zoals een lesrooster: zie `docs/agenda.md`.

## Altijd aan (op de Pi)

Nog niet op de Pi zelf getest, dus kijk mee in het logboek als je dit de eerste keer doet.

```bash
# De kern als service, die ook start zonder dat iemand inlogt:
mkdir -p ~/.config/systemd/user
cp deploy/bongo-kern.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now bongo-kern
sudo loginctl enable-linger tymo
journalctl --user -u bongo-kern -f      # meekijken (Ctrl+C om te stoppen)

# Het touchscreen start met de desktop:
mkdir -p ~/.config/autostart
cp deploy/bongo-kiosk.desktop ~/.config/autostart/
```

Staat de projectmap niet in `~/Home_Assistant`? Pas dan de paden aan in beide bestanden.

## Testen

```bash
.venv/bin/python -m pytest
```

De tests praten niet met de echte Claude: `tests/nep_claude.py` doet alsof hij de API is.
Ze kosten dus niets en werken zonder internet. De nep-API controleert wel een paar regels
van de echte API, zodat een fout in de manier waarop het brein het gesprek bijhoudt hier al
opvalt in plaats van pas op de Pi.

## Stand van zaken

- [x] Fase 0: hardware in kaart gebracht (`docs/hardware.md`). Microfoon en speakers nog niet klaar.
- [x] Het brein, de tools, de wachtrij, het geheugen en de agenda, met tests
- [x] Praten via de terminal
- [x] De kern: webapp, aanmelden, ochtendoverzicht, herstel na een stroomstoring
- [x] Het touchscreen als kiosk (fase 4): Bongo's gezicht, nog te testen op het echte scherm
- [x] Spraak (fase 3): gebouwd en getest zonder microfoon; nog te testen met de ReSpeaker
- [x] Een wekwoord met openWakeWord ("Hey Jarvis"), standaard uit; getest met een computerstem, nog niet met de ReSpeaker
- [ ] Een eigen wekwoord trainen ("Hé Bongo"), zie `docs/spraak.md`
