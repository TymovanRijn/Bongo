# Spraak (fase 3)

Tik op Bongo's gezicht (of zeg het wekwoord, als dat aan staat), praat, en hij antwoordt hardop.

## Hoe het werkt

```
tik op het gezicht (of het wekwoord)
  -> piepje, microfoon aan                      (arecord)
  -> Silero VAD hoort wanneer je klaar bent     (op de Pi; zit in faster-whisper)
  -> microfoon uit
  -> Whisper maakt er tekst van                 (op de Pi: er gaat geen geluid naar internet)
  -> Claude denkt na en schrijft het antwoord   (alleen de tekst gaat naar Anthropic)
     ... zodra zijn eerste zin af is:
  -> Piper maakt er spraak van                  (op de Pi)
  -> luidspreker                                (aplay)
     ... terwijl Claude de volgende zin schrijft
```

Bongo wacht dus niet tot Claude het hele antwoord af heeft: Claude's antwoord komt in stukjes
binnen (streaming), `spraak/zinnen.py` knipt het in hele zinnen, en elke zin gaat naar de
luidspreker zodra hij af is. Zegt Claude eerst "even kijken" en zoekt hij dan in de agenda,
dan hoor je dat ook meteen.

Het gezicht laat zien waar hij is: grote ogen met een gele gloed (luisteren), turen
(denken), lachende ogen en een wippende neus (praten). Wat hij zegt, staat eronder.

Eén tik doet steeds het logische:

| Bongo is aan het... | Een tik betekent |
|---|---|
| niets doen | luister naar me |
| luisteren | ik ben klaar met praten (anders wacht hij op 0,8 seconde stilte) |
| praten | stil maar |

De code staat in `assistent/spraak/`: `audio.py` (microfoon, luidspreker, einde van je zin),
`verstaan.py` (Whisper), `stem.py` (Piper), `zinnen.py` (tekst in zinnen knippen) en `keten.py`
(alles in de goede volgorde).

## Waarom zo

- **Tikken werkt altijd, het wekwoord zet je zelf aan.** Een wekwoord betekent dat de microfoon
  altijd aan staat. Het geluid blijft wel op de Pi (zie "Het wekwoord" hieronder), maar een
  microfoon die altijd luistert, hoort een bewuste keuze te zijn, niet iets wat ongemerkt aan
  staat. Daarom staat het standaard uit.
- **Verstaan en praten op de Pi zelf.** Er gaat geen geluid uit je kamer naar internet, het kost
  niets per vraag en je hebt geen extra account nodig. De prijs: snelheid. Whisper `small` op de
  processor van de Pi 5 doet er naar schatting 2 tot 5 seconden over voor een korte zin (gemeten
  heb ik het niet; zie "Hoe snel is het?").
- **Alleen het scherm van de Pi kan de microfoon aanzetten.** De webapp op je telefoon niet:
  anders kan iemand die bij de webapp komt, op afstand meeluisteren in je kamer.
- **Een piepje** als de microfoon aangaat, zodat je weet wanneer je kunt praten.
- **Zin voor zin praten.** De eerste zin klinkt al terwijl Claude de rest nog schrijft. Hoeveel
  dat scheelt, hangt af van hoe lang het antwoord is: bij één korte zin niets, bij drie zinnen
  ongeveer de tijd die Claude nodig heeft voor de tweede en derde. Een vraag over de agenda heeft
  bovendien twee rondes met Claude (eerst "ik wil in de agenda kijken", dan het antwoord), en
  alleen de laatste ronde kan sneller.

## Het wekwoord

Zet in `.env`:

```
WEKWOORD=hey_jarvis
```

en herstart de kern. Zeg "Hey Jarvis" en Bongo piept en luistert, net alsof je op zijn gezicht
tikte. Je mag in één adem doorpraten ("Hey Jarvis, wat heb ik morgen?"): wat je na het wekwoord
zegt, bewaart hij tot de opname begint. Uitzetten: maak `WEKWOORD=` weer leeg.

De code staat in `assistent/spraak/wekwoord.py`. Het werkt met
[openWakeWord](https://github.com/dscripka/openWakeWord):

- **Waarom "Hey Jarvis" en niet "Hé Bongo"?** openWakeWord heeft een paar kant-en-klare
  wekwoorden, allemaal Engels: `hey_jarvis`, `alexa`, `hey_mycroft` en `hey_rhasspy`. Een eigen
  wekwoord moet je trainen (zie hieronder). Begin met een kant-en-klaar wekwoord: dan weet je of
  de rest werkt voordat je tijd in trainen steekt.
- **Zeg het op z'n Engels.** In een proef met een computerstem gaf "Hey Jarvis" met een Engelse
  uitspraak een kans van 0,99, en met een Nederlandse uitspraak ("Hé Jarvis") maar 0,07.
- **Wat er met het geluid gebeurt.** De microfoon staat altijd aan, maar het geluid gaat alleen naar
  openWakeWord, op de Pi zelf. Dat kijkt steeds naar de laatste twee seconden, houdt hooguit tien
  seconden in het geheugen om mee te rekenen, en gooit ouder geluid weg. Niets wordt opgeslagen en
  niets gaat naar internet. Pas na het wekwoord gebeurt hetzelfde als na een tik: opnemen, Whisper
  maakt er tekst van, en alleen die tekst gaat naar Claude.
- **Hij maakt zichzelf niet wakker.** De ReSpeaker haalt wat de luidspreker afspeelt al uit de
  microfoon (echo-onderdrukking), als de luidspreker aan de ReSpeaker zit. Maar dat lukt nooit
  helemaal: er blijft een zachte rest over, vooral als hij hard staat. Daarom krijgt openWakeWord
  niets te horen terwijl Bongo luistert, nadenkt of praat, en begint het daarna met een schone lei
  (`mag_wekken` in `wekwoord.py`). Het nadeel: met het wekwoord kun je hem niet onderbreken.
  Stil maar: tik op het gezicht.
- **De drempel.** openWakeWord geeft per 80 ms een kans van 0 tot 1 dat het wekwoord gezegd werd.
  Boven `WEKWOORD_DREMPEL` (standaard 0,5) wordt Bongo wakker. Wordt hij vaak wakker van de
  televisie, zet hem hoger (0,7). Hoort hij je vaak niet, lager (0,3).
- **Wat het kost.** Op mijn testcomputer rekende openWakeWord 3 à 4 procent van de tijd, op één
  processorkern. De Pi 5 is langzamer; reken op een paar keer zoveel, en dat is nog steeds weinig.
  De eerste keer downloadt hij een paar kleine modellen van GitHub (samen zo'n 8 MB).
- **Gaat er iets mis** (het model downloaden lukt niet, de microfoon is weg), dan kijkt het gezicht
  verward en staat de reden eronder. Tikken werkt dan nog gewoon. Valt de microfoon weg, dan
  probeert hij het elke tien seconden opnieuw.

Getest met het echte model en een computerstem (espeak-ng), in een proef die net zo snel geluid
geeft als een microfoon: hij hoorde "Hey Jarvis" binnen een tiende seconde nadat het gezegd was,
en de vraag die er in één adem achteraan kwam, zat helemaal in de opname. Niet getest: een echte
microfoon, een echte stem en een echte kamer. Dat moet de Pi uitwijzen.

### Een eigen wekwoord: "Hé Bongo"

openWakeWord kan een nieuw wekwoord leren zonder dat jij honderden keren "Hé Bongo" hoeft in te
spreken: een computerstem spreekt het duizenden keren uit, met allerlei stemmen, snelheden en
achtergrondgeluid, en daar leert het model van. De openWakeWord-README beschrijft hoe, onder
"Training New Models" (er is een Google Colab-notebook voor). Train op "hey bongo": de computerstemmen
zijn Engels, en "Hey Bongo" klinkt bijna hetzelfde als "Hé Bongo".

Je krijgt een `.onnx`-bestand. Zet het in de projectmap, bijvoorbeeld in
`data/modellen/wekwoord/hey_bongo.onnx`, en dan:

```
WEKWOORD=data/modellen/wekwoord/hey_bongo.onnx
```

Eerlijk: dit heb ik niet zelf gedaan. Een zelfgetraind wekwoord is vaak minder goed dan de
kant-en-klare, die met veel meer werk gemaakt zijn. Probeer het, en zet de drempel bij als hij te
vaak of te weinig reageert.

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
Met een wekwoord zie je ook `wekwoord staat aan`.

## Hoe snel is het?

In de webapp, onder Meer > Snelheid, staat per stap hoe lang het duurde. Lees vooral:

- **tot_geluid**: van het einde van je zin tot Bongo begint te praten. Dat is wat jij merkt.
- **verstaan**: Whisper. Te traag? Zet `STT_MODEL=base` (sneller, iets slordiger).
- **eerste_zin_bedacht**: tot Claude zijn eerste hele zin af heeft. Dit is het deel van het
  nadenken dat je echt merkt.
- **nadenken**: Claude, tot het hele antwoord af is. Het verschil met `eerste_zin_bedacht` is
  wat streaming je oplevert.
- **stem**: hoe lang Piper over de eerste zin doet. Meestal minder dan een seconde.

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
| "Het wekwoord werkt niet: No module named 'openwakeword'" | De pakketten zijn van voor het wekwoord: `.venv/bin/pip install -r requirements.txt` |
| "Het wekwoord werkt niet: ..." over downloaden | De eerste keer moet de Pi bij GitHub kunnen. Kijk of hij internet heeft en herstart de kern |
| Hij reageert niet op het wekwoord | Kijk eerst of tikken werkt (dan doet de microfoon het). Zeg het wat duidelijker, of zet `WEKWOORD_DREMPEL` lager |
| Hij wordt vanzelf wakker | Zet `WEKWOORD_DREMPEL` hoger (bijvoorbeeld 0,7) |
