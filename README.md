# Bongo

De huisassistent van Tymo: een Raspberry Pi 5 met een touchscreen, die je agenda kent,
dingen voor je onthoudt en met je praat. Het brein is Claude.

## De belangrijkste regel

**Niets met gevolgen zonder bevestiging.** Claude kan de agenda lezen, maar een afspraak
toevoegen, iets onthouden of iets vergeten kan hij alleen *voorstellen*. Zo'n voorstel
komt in de wachtrij (`assistent/wachtrij.py`) en gebeurt pas als een mens het goedkeurt.

## Hoe het in elkaar zit

| Bestand | Wat het doet |
|---|---|
| `assistent/brain.py` | De agent-lus rond Claude: vraag stellen, tools uitvoeren, gesprek bijhouden en inkorten |
| `assistent/tools.py` | De tools die Claude mag gebruiken (agenda lezen, voorstellen doen) |
| `assistent/wachtrij.py` | Voorstellen die op goedkeuring wachten |
| `assistent/executors.py` | Wat er gebeurt *nadat* een voorstel is goedgekeurd |
| `assistent/geheugen.py` | `data/over_mij.md`: wat Bongo over je weet |
| `assistent/calendar_backend.py` | Nep-agenda (om te testen) en iCloud via CalDAV |
| `assistent/overzicht.py` | Agenda per dag en het ochtendoverzicht |
| `assistent/logboek.py`, `db.py` | SQLite: gesprekken, kosten, metingen |
| `assistent/config.py` | Alle instellingen, gelezen uit `.env` |
| `assistent/opbouw.py` | Knoopt alle onderdelen aan elkaar |
| `assistent/cli.py` | Praten met Bongo in de terminal |
| `docs/hardware.md` | Wat er in en aan de Pi zit (fase 0) |
| `docs/oefeningen.md` | Problemen om zelf uit te zoeken |

## Installeren (op de Pi)

```bash
cd ~/Home_Assistant              # of waar je deze map hebt staan
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env             # en vul daarna je ANTHROPIC_API_KEY in
```

> De map `.venv` stond eerst in git, maar hoort daar niet in (zie `.gitignore`). Weigert
> `git pull` vanwege bestanden in `.venv`, of doet Python het daarna niet meer: gooi de map
> weg (`rm -rf .venv`), doe `git pull` opnieuw en maak hem opnieuw met de regels hierboven.

## Gebruiken

```bash
.venv/bin/python -m assistent                        # gesprek in de terminal, /hulp voor de opdrachten
.venv/bin/python -m assistent "wat heb ik morgen?"   # één vraag en klaar
```

Standaard gebruikt Bongo een nep-agenda (`data/mock_agenda.json`). Voor je echte agenda zet je
`CALENDAR_BACKEND=icloud` en de iCloud-gegevens in `.env`.

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
- [ ] De kern: een server die altijd draait, met de webapp en het ochtendoverzicht
- [ ] Spraak (fase 3)
- [ ] Het touchscreen als kiosk (fase 4)
