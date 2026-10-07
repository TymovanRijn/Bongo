# Beslispunten

Het oorspronkelijke bouwplan is niet bewaard gebleven. De beslispunten hieronder heb ik (Claude)
gereconstrueerd uit de code en daarna zelf beslist, omdat Tymo zei: "jij mag alles uitpluizen".
Elke keuze is een instelling in `.env`: wie het anders wil, verandert één regel.

Bij elke keuze staat waarom. Lees vooral de redenering: die is belangrijker dan de keuze zelf.

---

## 1. Hoe lang onthoudt Bongo een gesprek?

**Keuze: `GESPREKSGEHEUGEN=stilte`, na 10 minuten stilte begint een nieuw gesprek.**

De opties: `stilte` (na een pauze opnieuw beginnen), `laatste_n` (alleen de laatste 20 beurten
bewaren) en `samenvatten` (na 20 beurten het gesprek samenvatten en daarmee verdergaan).

Waarom `stilte`:

- Een huisassistent krijgt korte gesprekjes ("wat heb ik morgen?"), met uren ertussen. Na tien
  minuten stilte gaat de volgende vraag bijna altijd over iets anders.
- Elke vraag stuurt het hele gesprek opnieuw naar Claude. Hoe langer het gesprek, hoe duurder
  elke vraag. Prompt caching maakt de herhaling goedkoop (een twintigste van de prijs bij Opus 5.5),
  maar de cache verloopt na 5 minuten. Na een lange pauze betaal je het hele gesprek dus opnieuw.
  Een nieuw gesprek na stilte is dan goedkoper én beter.
- Wat blijvend is, hoort in het geheugen (`over_mij.md`), niet in het gesprek.

`samenvatten` werkt sinds deze versie echt (daarvoor viel hij stilletjes terug op knippen), maar
kost een extra aanroep en verliest details. Pas het aan als Bongo vaak "vergeet" waar het net over ging.

## 2. Wie mag bij de webapp?

**Keuze: `WEB_TOEGANG=pin`, alleen vanaf het thuisnetwerk, `TAILSCALE_TOEGESTAAN=nee`.
Het scherm van de Pi zelf mag altijd, zonder pincode.**

Eerst de vraag die alles bepaalt: wat kan iemand die bij de webapp komt? Tymo's agenda lezen,
voorstellen goedkeuren (en dus in zijn agenda schrijven), zijn geheugen lezen en aanpassen, en
Claude laten werken op zijn kosten. Dat is genoeg om het serieus te beveiligen.

De beveiliging heeft drie lagen (de code staat in `assistent/toegang.py`):

1. **Netwerk.** Alleen de Pi zelf en de privé-adressen van het thuisnetwerk (192.168.x.x, 10.x.x.x,
   172.16-31.x.x). Tailscale staat uit: de Pi zit in Tymo's tailnet (zie `docs/hardware.md`), en dat
   moet een bewuste keuze zijn. De kern luistert wel op `0.0.0.0` (alle netwerkkaarten), anders kan
   de telefoon er niet bij; de netwerkcontrole zit daarom in de code zelf.
2. **Herkomst.** Een kwaadaardige website kan Tymo's browser stiekem verzoeken naar
   `http://192.168.1.53:8765` laten sturen (CSRF), of zijn eigen domeinnaam naar het adres van de Pi
   laten wijzen (DNS-rebinding). Daarom: een verzoek dat iets verandert, moet een `Origin` van Bongo
   zelf hebben, en de `Host` moet een IP-adres, `localhost`, een `.local`- of een `.ts.net`-naam zijn.
3. **Apparaat.** Met de juiste pincode krijgt een apparaat een cookie die 400 dagen geldig is. De
   database bewaart alleen een hash daarvan. Na vijf foute pincodes in een kwartier wordt elke poging
   (ook de goede) een kwartier lang geweigerd: een pincode van vier cijfers is anders in minuten te raden.

Waarom `pin` en niet:

- **`open`**: dan kan iedereen op het wifi erbij, ook een logé of een gehackte slimme lamp.
- **`link`** (alleen koppellinks, geen pincode): veiliger, want er is niets te raden. Maar onhandiger:
  voor elk nieuw apparaat moet je een link maken op een apparaat dat al gekoppeld is. Wie dat wil,
  zet `WEB_TOEGANG=link`. Koppellinks werken ook in `pin`-modus (Meer > Apparaten).

Wat nog niet beveiligd is: het verkeer gaat onversleuteld over het wifi (`http`, geen `https`).
Iemand op hetzelfde wifi kan de cookie dus afluisteren. Voor een thuisnetwerk vind ik dat
aanvaardbaar; via Tailscale is het verkeer wel versleuteld.

**Te doen voor Tymo:** zet een pincode van liefst zes cijfers in `.env`: `WEB_PIN=......`

## 3. Naar welke agenda schrijft Bongo? (gereconstrueerd)

Dit nummer kwam nergens in de code voor. Het enige deel van de instellingen zonder nummer is de
agenda, dus ik vermoed dat het daarover ging.

**Advies: maak in iCloud een aparte agenda "Bongo" en zet `ICLOUD_CALENDAR_NAME=Bongo`. Laat
`ICLOUD_READ_CALENDARS` leeg, zodat hij alle agenda's leest.**

Waarom een aparte agenda: alles wat Bongo toevoegt, heeft dan een eigen kleur op de iPhone. Je ziet
meteen wat van hem komt, en gaat er iets mis, dan gooi je die ene agenda weg zonder je eigen
afspraken te raken. Afspraken in een aparte agenda tellen gewoon mee als je kijkt of je vrij bent.

## 4. Mag een hardop "ja" een voorstel goedkeuren?

**Keuze: `STEM_BEVESTIGEN=nee`.**

De hele veiligheid van Bongo rust op één regel: niets met gevolgen zonder dat een mens het
bevestigt. Een "ja" van de televisie, of een spraakherkenning die "ja" hoort waar "nee, laat maar"
gezegd werd, is geen bevestiging. Tikken kost één seconde. Kijk hier opnieuw naar als de microfoon
met echo-onderdrukking werkt (fase 3) en blijkt dat de herkenning betrouwbaar is.

Op het touchscreen zelf vraagt "Ja" om een tweede tik ("Zeker? Tik nog eens"), om dezelfde reden:
een scherm in de kamer wordt ook per ongeluk aangeraakt.

Spraak bestaat nu (zie punt 6), maar deze keuze blijft: een voorstel goedkeuren doe je op het
scherm of in de webapp, ook als je het hardop gevraagd hebt.

## 5. Het ochtendoverzicht

**Keuze: `OCHTEND_TIJD=07:30`, op het scherm, `OCHTEND_UITSPREKEN=nee`.**

Om half acht maakt de kern een korte ochtendgroet met de afspraken van vandaag (en van morgenvroeg).
Hij staat op het scherm en in de webapp (Meer > Maak het ochtendoverzicht). Start de Pi later op,
dan komt het overzicht tot vier uur na `OCHTEND_TIJD` alsnog. Werkt Claude niet, dan maakt Bongo een
eenvoudige versie zonder Claude.

Uitspreken kan sinds de spraak er is (`OCHTEND_UITSPREKEN=ja`), maar staat uit: een luidspreker
die uit zichzelf begint te praten, kan iemand wakker maken die uitslaapt. Zet het aan als je het wilt.

## 6. Spraak

**Keuze: tikken op het gezicht, verstaan en praten op de Pi zelf (Whisper en Piper), en alleen
het scherm van de Pi kan de microfoon aanzetten. Een wekwoord kan erbij (openWakeWord, ook op de
Pi zelf), maar staat standaard uit: `WEKWOORD=` (leeg).**

Waarom uit: met een wekwoord staat de microfoon altijd aan. Het geluid verlaat de Pi niet, maar
een microfoon die altijd luistert, moet je zelf willen, niet ongemerkt krijgen. Tymo koos voor
openWakeWord; zet `WEKWOORD=hey_jarvis` om het aan te zetten.

De uitleg en de afwegingen staan in `docs/spraak.md`.

## 7. Welk model?

**Keuze (Tymo, 7 oktober 2026): `claude-sonnet-5-5` met adaptief nadenken (`BONGO_DENKEN=adaptief`).**

De eerste echte vraag op de Pi duurde 21,9 seconden met Opus 5.5. Dat leek te traag om tegen te
praten. Opus 5.5 kan niet zonder nadenken; Sonnet 5.5 wel (`BONGO_DENKEN=tussen_tools`) en is
bovendien goedkoper. Maar sneller is alleen beter als de antwoorden goed blijven. Dus eerst
gemeten met `.venv/bin/python -m assistent.meet`, op de Pi (vier vragen per instelling):

| Instelling | Mediaan | Langzaamst | Per vraag |
|---|---|---|---|
| Sonnet 5.5, adaptief | 4,4 s | 5,4 s | $ 0,0054 |
| Opus 5.5, adaptief | 4,5 s | 5,5 s | $ 0,0100 |
| Sonnet 5.5, tussen_tools | 4,9 s | 13,4 s | $ 0,0054 |

Wat de meting leerde:

- **Opus was helemaal niet zo traag.** 4,5 seconden, niet 21,9. Die eerste vraag was één meting,
  en één meting is geen meting: de eerste verbinding, een lege cache of gewoon een trage keer.
- **Zonder nadenken was niet sneller.** Op effort `low` slaat Sonnet het nadenken bij simpele
  vragen meestal al over (dat staat ook in Anthropic's documentatie). `tussen_tools` won dus niets,
  en had de traagste uitschieter.
- **Het echte verschil is de prijs.** Sonnet is even snel en kost de helft.

Opnieuw meten kan altijd, bijvoorbeeld als er een nieuw model is.

## Het scherm

**Keuze: alleen Bongo's gezicht (twee ogen en een neus), dat laat zien wat hij doet. 's Nachts
(van 23:00 tot 07:00, `NACHT_VAN` en `NACHT_TOT`) slaapt hij: ogen dicht, scherm gedimd.
`NACHT_SCHERM_UIT=nee`.**

Agenda en klok staan niet meer op het scherm (vraag het hem, of kijk in de webapp). Voorstellen
wel: die moet je kunnen goedkeuren. Het slapende gezicht werkt altijd. Het scherm echt uitzetten (`xset dpms force off`) is ingebouwd, maar
in `docs/hardware.md` staat dat nog niet getest is of de achtergrondverlichting van dit paneel dan
echt uitgaat. Test dat eerst (`xset -display :0 dpms force off`), en zet het daarna pas aan.
