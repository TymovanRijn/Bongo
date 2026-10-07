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
  -> Azure maakt er spraak van                  (of Piper, op de Pi: zie "Een betere stem")
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
`verstaan.py` (Whisper), `stem.py` (Azure en Piper), `zinnen.py` (tekst in zinnen knippen),
`uitspraak.py` (tekst uitspreekbaar maken: "14:30" wordt "half drie", emoji en opmaak eruit),
`wekwoord.py` en `keten.py` (alles in de goede volgorde).

## Waarom zo

- **Tikken werkt altijd, het wekwoord zet je zelf aan.** Een wekwoord betekent dat de microfoon
  altijd aan staat. Het geluid blijft wel op de Pi (zie "Het wekwoord" hieronder), maar een
  microfoon die altijd luistert, hoort een bewuste keuze te zijn, niet iets wat ongemerkt aan
  staat. Daarom staat het standaard uit.
- **Verstaan op de Pi zelf.** Er gaat geen geluid uit je kamer naar internet, het kost niets per
  vraag en je hebt geen extra account nodig. De prijs: snelheid. Whisper `small` op de processor van
  de Pi 5 doet er naar schatting 2 tot 5 seconden over voor een korte zin (gemeten heb ik het niet;
  zie "Hoe snel is het?").
- **Praten mag via internet (Azure).** Daarvoor gaat alleen de tekst van Bongo's antwoord weg, en
  die ging al naar Claude. Je stem blijft thuis. Zonder Azure praat hij met Piper, op de Pi zelf.
- **Alleen het scherm van de Pi kan de microfoon aanzetten.** De webapp op je telefoon niet:
  anders kan iemand die bij de webapp komt, op afstand meeluisteren in je kamer.
- **Een piepje** als de microfoon aangaat, zodat je weet wanneer je kunt praten.
- **Zin voor zin praten.** De eerste zin klinkt al terwijl Claude de rest nog schrijft. Hoeveel
  dat scheelt, hangt af van hoe lang het antwoord is: bij één korte zin niets, bij drie zinnen
  ongeveer de tijd die Claude nodig heeft voor de tweede en derde. Een vraag over de agenda heeft
  bovendien twee rondes met Claude (eerst "ik wil in de agenda kijken", dan het antwoord), en
  alleen de laatste ronde kan sneller.

## Een betere stem: Azure

Piper (op de Pi zelf) is gratis en werkt zonder internet, maar klinkt robotachtig. Microsoft Azure
heeft echte Nederlandse stemmen die veel natuurlijker klinken. Anthropic zelf heeft geen stemmen:
Claude kan alleen tekst lezen en schrijven.

Wat er naar Microsoft gaat: alleen de tekst van Bongo's antwoord, nooit je stem. Het gratis tegoed
is 0,5 miljoen tekens per maand. Een antwoord van Bongo is meestal zo'n 100 tot 200 tekens, dus dat
is ruim genoeg voor duizenden antwoorden.

1. Ga naar [portal.azure.com](https://portal.azure.com) en maak een account. Microsoft vraagt een
   creditcard om te controleren wie je bent; met het gratis tegoed betaal je niets.
2. Zoek bovenin naar **Speech service** (in het Nederlands soms "Spraakservice") en kies **Maken**.
   De namen in Azure veranderen nogal eens; zoek anders op "Speech".
3. Vul in:
   - Resourcegroep: nieuw, bijvoorbeeld `bongo`
   - Regio: **West Europe**
   - Naam: iets unieks, bijvoorbeeld `bongo-stem-tymo`
   - Prijscategorie: **Free F0**

   Dan **Controleren en maken** en **Maken**.
4. Open de nieuwe resource en kies **Sleutels en eindpunt** (Keys and Endpoint). Neem **Sleutel 1**
   over en kijk welke **Locatie/regio** er staat (bijvoorbeeld `westeurope`).
5. Zet in `.env` op de Pi:
   ```
   AZURE_SPEECH_KEY=de-sleutel
   AZURE_SPEECH_REGIO=westeurope
   ```
6. Test het met de kern uit: `.venv/bin/python -m assistent.kern geluid`. In stap 4 staat dan
   `Stem: Azure (nl-NL-FennaNeural)` en hoor je de nieuwe stem. Start daarna de kern.

Andere stemmen: zet `AZURE_STEM=nl-NL-MaartenNeural` (een man) of `nl-NL-ColetteNeural` (een vrouw).
Standaard is `nl-NL-FennaNeural` (een vrouw).

Werkt Azure niet (geen internet, verkeerde sleutel, tegoed op), dan praat Bongo met Piper verder.
In het logboek van de kern staat dan waarom (`de stem van Azure werkt niet`). Na een minuut probeert
hij Azure opnieuw.

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

## De microfoon en de speakers aansluiten (ReSpeaker Mic Array v2.0)

Steek de ReSpeaker in een USB-poort en de speakers in de **3,5 mm-uitgang van de ReSpeaker**. Dan
hoort de ReSpeaker zelf wat er afgespeeld wordt en haalt hij dat uit de microfoon
(echo-onderdrukking). Zie ook `docs/hardware.md`, hoofdstuk 4.

Draai dan de geluidstest, met de kern uit (anders is de microfoon bezet):

```bash
.venv/bin/python -m assistent.kern geluid
```

Die doet zes dingen:

1. Kijkt of de ReSpeaker er is.
2. Kijkt hoeveel kanalen hij geeft. Dat hangt af van zijn firmware. Bij `6` is kanaal 0 je stem,
   schoongemaakt (echo eruit, ruis eruit), zijn kanaal 1 tot en met 4 de losse microfoons, en is
   kanaal 5 wat hij zelf afspeelt. Bij `1` is dat ene kanaal al de schoongemaakte stem. Bongo
   gebruikt altijd de schoongemaakte stem.
3. Vraagt je iets te zeggen en laat per kanaal zien hoe hard je stem binnenkomt.
4. Als het wekwoord aan staat: vraagt je het een paar keer te zeggen en laat zien hoe zeker
   openWakeWord het hoorde, naast de drempel die nodig is.
5. Spreekt een zin uit via de speakers (met de stem uit `.env`: Azure of Piper) en luistert
   tegelijk mee. Daarmee meet hij hoeveel van Bongo's eigen stem er na de echo-onderdrukking nog in
   de microfoon zit.
6. Zegt wat er in `.env` moet, en wat er nu staat.

Daarna: `.env` aanpassen zoals hij zegt, en de kern opnieuw starten. In het logboek van de kern
staat bij het starten welke microfoon en luidspreker hij gebruikt (`spraak: microfoon ...`).

Liever met de hand? Dit zijn de commando's die de test gebruikt:

```bash
arecord -l                                   # opnemen: zie je ArrayUAC10?
aplay -l                                     # afspelen: zie je ArrayUAC10?
# Hoeveel kanalen: gebruik hw: en niet plughw:, want plughw doet alsof elk aantal kan.
arecord -D hw:CARD=ArrayUAC10,DEV=0 -f S16_LE -r 16000 -c 6 -d 1 /dev/null && echo "6 kanalen"
# Opnemen en via de ReSpeaker terugspelen:
arecord -D plughw:CARD=ArrayUAC10,DEV=0 -f S16_LE -r 16000 -c 1 -d 5 /tmp/proef.wav
aplay -D plughw:CARD=ArrayUAC10,DEV=0 /tmp/proef.wav
```

Waarom niet gewoon `default`? `default` is wat de Pi als standaard heeft gekozen, en dat is vaak de
HDMI-uitgang van het scherm, niet de ReSpeaker. Met `plughw:CARD=ArrayUAC10,DEV=0` wijs je de
ReSpeaker aan bij zijn naam. Die blijft hetzelfde, ook als je hem in een andere USB-poort steekt.

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
| Hij hoort je niet, of je hoort hem niet | Draai de geluidstest: `.venv/bin/python -m assistent.kern geluid` |
| "de microfoon stopte: ... No such file or directory" | `MIC_APPARAAT` klopt niet: kijk met `arecord -l` |
| "de microfoon stopte: ... Device or resource busy" | PipeWire gebruikt de microfoon al. Probeer `MIC_APPARAAT=default` en maak de ReSpeaker de standaard met `wpctl status` en `wpctl set-default <nummer>` |
| Hij reageert nooit op je stem | Verkeerd kanaal (`MIC_KANAAL`), of de microfoon staat te zacht (`alsamixer`) |
| Hij verstaat "Bingo" in plaats van "Bongo" | Praat wat dichterbij, of probeer `STT_MODEL=medium` (beter, maar trager) |
| De stem downloaden lukt niet | De naam in `STEM` bestaat niet. Lijst: `.venv/bin/python -m piper.download_voices \| grep nl_` |
| Hij spreekt woorden raar uit | Kijk in de webapp onder Meer > Logboek bij `uitgesproken`: daar staat precies wat er naar de stem ging (met \| tussen de zinnen). Staat daar iets geks, dan ligt het aan de tekst (zeg het mij); staat het er goed en klinkt het fout, dan ligt het aan de stem: zet Azure aan |
| "Azure weigert de sleutel" | `AZURE_SPEECH_KEY` of `AZURE_SPEECH_REGIO` klopt niet. Kijk bij Sleutels en eindpunt |
| Hij klinkt nog steeds als Piper | Kijk in het logboek van de kern waarom Azure niet werkt, of draai de geluidstest |
| Hij hoort zichzelf praten | De luidspreker zit niet aan de ReSpeaker, dus er is geen echo-onderdrukking. Zet hem zachter |
| "Het wekwoord werkt niet: No module named 'openwakeword'" | De pakketten zijn van voor het wekwoord: `.venv/bin/pip install -r requirements.txt` |
| "Het wekwoord werkt niet: ..." over downloaden | De eerste keer moet de Pi bij GitHub kunnen. Kijk of hij internet heeft en herstart de kern |
| Hij reageert niet op het wekwoord | Draai de geluidstest: stap 4 meet hoe zeker hij het wekwoord hoort. Zeg het op z'n Engels |
| Hij wordt vanzelf wakker | Zet `WEKWOORD_DREMPEL` hoger (bijvoorbeeld 0,7) |
