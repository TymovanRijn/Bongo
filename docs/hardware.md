# Hardware-inventarisatie (fase 0)

Gemeten op 7 oktober 2026, op de Pi zelf.

Gebruik in configuratie en scripts altijd **namen** (ALSA-kaartnamen, `/dev/input/by-id/...`)
en nooit nummers. `card 0`, `event5` en dergelijke kunnen na een herstart veranderen.

## Samenvatting

| Onderdeel | Status | Naam om te gebruiken |
|---|---|---|
| Systeem | ✅ | Raspberry Pi 5 Model B Rev 1.0, 8 GB, start van NVMe |
| AI-chip | ✅ geïdentificeerd | Hailo-8L, `/dev/hailo0` (voorlopig niet nodig) |
| Scherm | ✅ | `HDMI-1` (poort HDMI0), 1024x600 |
| Touch | ✅ apparaat gevonden, aanraaktest nog doen | `/dev/input/by-id/usb-WaveShare_WS170120_WaveShare_ws170120-event-if00` |
| Speakers | ⚠️ toon afgespeeld, nog niet bevestigd dat hij hoorbaar was | ALSA `hdmi:CARD=vc4hdmi0,DEV=0` |
| Microfoon | ❌ **niet aangesloten / niet gevonden** | (verwacht: `ArrayUAC10`, zie hieronder) |
| Netwerk | ✅ | `192.168.1.53` op wifi, `raspberrypi.local` |

## 1. Besturingssysteem

- Debian GNU/Linux 12 (bookworm), Raspberry Pi OS
- Kernel `6.12.47+rpt-rpi-v8`, aarch64
- Python 3.11.2; `venv` werkt; SQLite 3.40.1
- Opslag: NVMe SSD van 512 GB (BIWIN/KingSpec), `/` en `/boot/firmware` staan erop.
  De trage SD-kaart uit `~/rpdiags.txt` (oktober 2025) speelt dus geen rol meer.
- Desktop: **X11** (Xorg + openbox/lxsession), niet Wayland. Van belang voor de kiosk in fase 4.
- Temperatuur in rust: 63 °C, geen throttling (`get_throttled=0x0`).
- Al geïnstalleerd en handig voor later: Chromium 141, ffmpeg, unclutter (muiscursor verbergen).
- Draait ook: RealVNC-server, Docker, Tailscale.

## 2. AI HAT

```
$ lspci
0001:01:00.0 PCI bridge: ASMedia ASM2806 4-Port PCIe x2 Gen3 Packet Switch
0001:03:00.0 Co-processor: Hailo Technologies Ltd. Hailo-8 AI Processor
0001:06:00.0 Non-Volatile memory controller: KingSpec NX series NVMe SSD

$ hailortcli fw-control identify
Device Architecture: HAILO8L
Product Name: HAILO-8L AI ACC M.2 B+M KEY MODULE EXT TMP
Firmware Version: 4.20.0
```

- Chip: **Hailo-8L** (13 TOPS), als M.2-module op een PCIe-switchbord dat hij deelt met de NVMe-SSD.
  Hij hangt aan de PCIe-flatcable, niet aan de GPIO-header.
- Software: `hailort` en `python3-hailort` 4.20.0, apparaat `/dev/hailo0`.
- **Sterk in:** beeldherkenning met neurale netwerken op een camerastroom, zoals objectdetectie (YOLO),
  personen- en gezichtsdetectie, pose-estimatie en segmentatie, in realtime en met weinig stroom.
- **Niet geschikt voor:** taalmodellen. Er bestaan experimentele Whisper-demo's voor Hailo, maar dit project
  heeft de chip voorlopig niet nodig. Kandidaat voor later: aanwezigheidsdetectie met een camera.

## 3. Microfoon: niet gevonden

```
$ arecord -l
**** List of CAPTURE Hardware Devices ****
(leeg)
```

Er is op dit moment **geen enkel opnameapparaat**. Wat ik gecontroleerd heb:

- **USB** (`lsusb`): alleen de touchcontroller van het scherm, geen ReSpeaker.
- **GPIO-HAT**: in `/boot/firmware/config.txt` staat geen ReSpeaker-overlay, en op I2C-bus 1 zit geen
  ReSpeaker-codec (de 2-Mic HAT gebruikt WM8960 op `0x1a`, de 4/6-Mic HAT AC108 op `0x35`/`0x3b`).
  Er zit wel één onbekend apparaat op adres `0x55`, zonder driver. Dat is geen ReSpeaker.
  Tymo: weet jij wat er op de GPIO-header zit?
- Er is geen HAT-EEPROM gevonden (`/proc/device-tree/hat` bestaat niet).

**Waarschijnlijk model:** in `~/maatje/README.md` staat een **ReSpeaker Mic Array v2.0 (USB)**. Als dat
dezelfde microfoon is:

- Het is een USB-array, dus **geen botsing met de AI HAT** en geen extra driver nodig.
- Na het aansluiten verwacht ik in `lsusb`: `2886:0018 Seeed Technology ... ReSpeaker 4 Mic Array (UAC1.0)`
  en in `arecord -l` de kaartnaam `ArrayUAC10`.
- Hij heeft een eigen **3,5 mm-uitgang** en ingebouwde echo-onderdrukking (AEC). Zie het advies bij de speakers.

**Nog te doen zodra hij aangesloten is** (5 seconden opnemen en terugspelen):

```bash
lsusb | grep -i 2886
arecord -l
arecord -D plughw:CARD=ArrayUAC10,DEV=0 -f S16_LE -r 16000 -c 1 -d 5 /tmp/test.wav
pw-play /tmp/test.wav
```

Bij de 6-kanaalsfirmware is kanaal 0 het bewerkte signaal (met AEC en ruisonderdrukking), kanaal 1 tot en met 4
zijn de ruwe microfoons en kanaal 5 is het afspeelsignaal. Gebruik dan kanaal 0.

## 4. Speakers

De Pi 5 heeft geen analoge audio-uitgang. Op dit moment bestaan alleen de HDMI-uitgangen:

```
$ aplay -l
card 0: vc4hdmi0 [vc4-hdmi-0]   <- HDMI0, hier zit het scherm op
card 1: vc4hdmi1 [vc4-hdmi-1]   <- HDMI1, niets aangesloten
```

- Het scherm zit op **HDMI0** (de poort naast de USB-C-voeding). De EDID van het scherm meldt
  HDMI-audio-ondersteuning.
- Standaarduitgang in PipeWire: `alsa_output.platform-107c701400.hdmi.hdmi-stereo` (het achtervoegsel `.4`
  kan veranderen, dus zoek op het begin), volume 40%.
- Testtoon: 2 seconden 440 Hz via `pw-play` naar deze uitgang. Het afspelen lukte (exitcode 0).
  **Tymo moet nog bevestigen dat hij hem gehoord heeft.**

Mogelijke aansluitingen voor de 2 speakers:

1. **Koptelefoonaansluiting van het scherm** (HDMI-audio). Werkt nu al, als het scherm die aansluiting heeft.
2. **3,5 mm-uitgang van de ReSpeaker Mic Array v2.0. Dit is mijn advies.** De chip in de ReSpeaker hoort dan
   zelf wat er afgespeeld wordt en haalt dat uit het microfoonsignaal (echo-onderdrukking). Dat lost fase 3,
   stap 6 ("niet naar zichzelf luisteren") in hardware op, en Tymo kan de assistent dan zelfs onderbreken.
   Via HDMI kan dat niet: dan moet de microfoon tijdens het spreken uit.
3. Een USB-geluidskaart. Werkt, maar heeft dezelfde nadelen als optie 1.

Als de speakers in de ReSpeaker gaan, wordt de afspeelnaam `plughw:CARD=ArrayUAC10,DEV=0`.

Hoe zitten de speakers nu aangesloten? Als het de Creative Pebble V2 uit het maatje-project is: die krijgt
stroom via USB, maar het geluid komt via de 3,5 mm-plug. Die plug moet dus in het scherm of in de ReSpeaker.

## 5. Touch

```
$ libinput list-devices
Device:           WaveShare WS170120
Kernel:           /dev/input/event5
Capabilities:     touch
```

- USB-ID `0eef:0005` (D-WAV Scientific, Waveshare-touchcontroller).
- Stabiele naam: `/dev/input/by-id/usb-WaveShare_WS170120_WaveShare_ws170120-event-if00`.
- Beeld: uitgang `HDMI-1`, 1024x600 bij 59,82 Hz, fysiek 154 x 86 mm (7").
- Let op: de EDID van het paneel geeft als naam `LEN L1950wD` (fabrikantcode `YZH`). Dat is een
  overgenomen EDID, wat bij dit soort panelen vaker voorkomt. Het is wel degelijk het Waveshare-scherm.
- **Aanraaktest nog doen** (raak het scherm aan, er moeten events verschijnen, stoppen met Ctrl+C):
  `sudo evtest /dev/input/by-id/usb-WaveShare_WS170120_WaveShare_ws170120-event-if00`

## 6. Netwerk

| | |
|---|---|
| Verbinding | wifi (`wlan0`), netwerk `Odido-04F584` |
| IP-adres | `192.168.1.53/24` (via DHCP) |
| Router | `192.168.1.1` |
| MAC wlan0 | `2c:cf:67:33:fb:af` |
| MAC eth0 | `2c:cf:67:33:fb:ae` (alleen nodig als de Pi op een kabel gaat) |
| mDNS | `raspberrypi.local` (avahi draait) |
| Tailscale | actief, `100.125.54.40` |

**Advies:** reserveer `192.168.1.53` in de Odido-router (`http://192.168.1.1`, meestal onder LAN/DHCP,
"vast IP-adres" of "reservering") voor MAC `2c:cf:67:33:fb:af`. Dan blijven bladwijzers naar de webapp
werken. Een netwerkkabel is voor een apparaat dat altijd aan staat betrouwbaarder dan wifi, maar is niet nodig.

**Belangrijk voor beslispunt 2 (toegang tot de webapp):** door Tailscale is de Pi ook bereikbaar vanaf
elk apparaat in Tymo's tailnet, dus ook buiten huis. Een server die op `0.0.0.0` luistert, is daar ook te zien.
Dat kan handig zijn, maar het moet een bewuste keuze zijn.

## Aandachtspunten voor latere fases

- **Audio vanuit systemd:** PipeWire draait in de gebruikerssessie van `tymo`. Een systeemservice kan
  daar niet bij. Opties: de spraakketen als `systemctl --user`-service draaien met
  `loginctl enable-linger tymo` (staat nu op `Linger=no`), of de service ALSA rechtstreeks laten gebruiken.
  Kiezen in fase 3.
- **Kiosk (fase 4):** de sessie is X11/openbox, dus de kiosk start via de autostart van lxsession.
  Het scherm uitzetten kan met `xset dpms`. Of de achtergrondverlichting van dit paneel dan echt uitgaat,
  moet getest worden.
