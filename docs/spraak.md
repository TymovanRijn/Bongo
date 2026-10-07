# Spraak (fase 3)

Tik op Bongo's gezicht, praat, en hij antwoordt hardop.

## Hoe het werkt

```
tik op het gezicht
  -> piepje, microfoon aan                      (arecord)
  -> Silero VAD hoort wanneer je klaar bent     (op de Pi; zit in faster-whisper)
  -> microfoon uit
  -> Whisper maakt er tekst van                 (op de Pi: er gaat geen geluid naar internet)
  -> Claude denkt na                            (alleen de tekst gaat naar Anthropic)
  -> Piper maakt er spraak van, zin voor zin    (op de Pi)
  -> luidspreker                                (aplay)
```

Het gezicht laat zien waar hij is: grote ogen met een gele gloed (luisteren), turen
(denken), lachende ogen en een wippende neus (praten). Wat hij zegt, staat eronder.

Eén tik doet steeds het logische:

| Bongo is aan het... | Een tik betekent |
|---|---|
| niets doen | luister naar me |
| luisteren | ik ben klaar met praten (anders wacht hij op 0,8 seconde stilte) |
| praten | stil maar |

De code staat in `assistent/spraak/`: `audio.py` (microfoon, luidspreker, einde van je zin),
`verstaan.py` (Whisper), `stem.py` (Piper) en `keten.py` (alles in de goede volgorde).

## Waarom zo

- **Tikken, nog geen wekwoord.** Een wekwoord ("Hé Bongo") betekent dat de microfoon altijd aan
  staat en een model continu meeluistert. Een Nederlands wekwoord moet je bovendien zelf trainen,
  en een televisie die iets zegt wat erop lijkt, maakt Bongo wakker. Tikken is betrouwbaar en
  privé, en het scherm staat er toch. Later kan er een wekwoord bij (bijvoorbeeld openWakeWord):
  dat hoeft alleen `Spraak.tik()` aan te roepen.
- **Verstaan en praten op de Pi zelf.** Er gaat geen geluid uit je kamer naar internet, het kost
  niets per vraag en je hebt geen extra account nodig. De prijs: snelheid. Whisper `small` op de
  processor van de Pi 5 doet er naar schatting 2 tot 5 seconden over voor een korte zin (gemeten
  heb ik het niet; zie "Hoe snel is het?").
- **Alleen het scherm van de Pi kan de microfoon aanzetten.** De webapp op je telefoon niet:
  anders kan iemand die bij de webapp komt, op afstand meeluisteren in je kamer.
- **Een piepje** als de microfoon aangaat, zodat je weet wanneer je kunt praten.
- **Zin voor zin praten.** Piper maakt de eerste zin, die klinkt al terwijl de rest nog gemaakt wordt.

## De microfoon aansluiten (ReSpeaker Mic Array v2.0)

1. Steek hem in een USB-poort en kijk of hij er is:
   ```bash
   lsusb | grep -i 2886          # Seeed Technology ... ReSpeaker
   arecord -l                    # card ...: ArrayUAC10
   ```
2. Kijk hoeveel kanalen hij heeft (dat hangt af van de firmware):
   ```bash
   arecord -D plughw:CARD=ArrayUAC10,DEV=0 --dump-hw-params -d 1 /dev/null 2>&1 | grep CHANNELS
   ```
   - `6`: kanaal 0 is je stem, schoongemaakt (echo eruit, ruis eruit). Kanaal 1 tot en met 4
     zijn de losse microfoons, kanaal 5 is wat de luidspreker afspeelt. Bongo moet dus kanaal 0.
   - `1`: dat ene kanaal is al de schoongemaakte stem.
3. Zet in `.env` (met `MIC_KANALEN=1` als stap 2 dat zei):
   ```
   MIC_APPARAAT=plughw:CARD=ArrayUAC10,DEV=0
   MIC_KANALEN=6
   MIC_KANAAL=0
   ```
4. Proef: neem 5 seconden op en speel het af.
   ```bash
   arecord -D plughw:CARD=ArrayUAC10,DEV=0 -f S16_LE -r 16000 -c 1 -d 5 /tmp/proef.wav
   aplay /tmp/proef.wav
   ```

## De luidspreker

Het beste is de luidspreker in de **3,5 mm-uitgang van de ReSpeaker**. Dan hoort de ReSpeaker zelf
wat er afgespeeld wordt en haalt hij dat uit de microfoon (echo-onderdrukking). Zie ook
`docs/hardware.md`, hoofdstuk 4. Zet dan in `.env`:

```
SPEAKER_APPARAAT=plughw:CARD=ArrayUAC10,DEV=0
```

Proef: `aplay -D plughw:CARD=ArrayUAC10,DEV=0 /usr/share/sounds/alsa/Front_Center.wav`

## De eerste keer opstarten

Bij de eerste start downloadt de kern de modellen naar `data/modellen/`: Whisper `small`
(ongeveer 480 MB) en de stem (ongeveer 60 MB). Dat kan een paar minuten duren. Meekijken:

```bash
journalctl --user -u bongo-kern -f     # of de uitvoer van python -m assistent.kern
```

Klaar is het bij: `spraak klaar (modellen geladen in ... s)`.

## Hoe snel is het?

In de webapp, onder Meer > Snelheid, staat per stap hoe lang het duurde. Lees vooral:

- **tot_geluid**: van het einde van je zin tot Bongo begint te praten. Dat is wat jij merkt.
- **verstaan**: Whisper. Te traag? Zet `STT_MODEL=base` (sneller, iets slordiger).
- **nadenken**: Claude. Te traag? Meet de modellen met `.venv/bin/python -m assistent.meet`
  en kies daarna in `.env` bijvoorbeeld `BONGO_MODEL=claude-sonnet-5-5` en `BONGO_DENKEN=tussen_tools`.
- **eerste_zin_gemaakt**: Piper. Meestal minder dan een seconde.

## Als het niet werkt

| Wat je ziet | Wat het meestal is |
|---|---|
| "Spraak staat uit" | `SPRAAK=nee` in `.env`, of de pakketten ontbreken: `.venv/bin/pip install -r requirements.txt` |
| "de microfoon stopte: ... No such file or directory" | `MIC_APPARAAT` klopt niet: kijk met `arecord -l` |
| "de microfoon stopte: ... Device or resource busy" | PipeWire gebruikt de microfoon al. Probeer `MIC_APPARAAT=default` en maak de ReSpeaker de standaard met `wpctl status` en `wpctl set-default <nummer>` |
| Hij reageert nooit op je stem | Verkeerd kanaal (`MIC_KANAAL`), of de microfoon staat te zacht (`alsamixer`) |
| Hij verstaat "Bingo" in plaats van "Bongo" | Praat wat dichterbij, of probeer `STT_MODEL=medium` (beter, maar trager) |
| De stem downloaden lukt niet | De naam in `STEM` bestaat niet. Lijst: `.venv/bin/python -m piper.download_voices \| grep nl_` |
| Hij hoort zichzelf praten | De luidspreker zit niet aan de ReSpeaker, dus er is geen echo-onderdrukking. Zet hem zachter |
