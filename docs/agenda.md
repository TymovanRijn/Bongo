# Je agenda's koppelen

Standaard gebruikt Bongo een nep-agenda (`data/mock_agenda.json`), zodat alles werkt zonder dat er
een wachtwoord in staat. Zo koppel je je echte iCloud-agenda's.

## 1. Een app-specifiek wachtwoord

Bongo logt niet in met je gewone Apple ID-wachtwoord, maar met een apart wachtwoord dat alleen
voor hem is. Dat kun je altijd intrekken zonder dat de rest van je account iets merkt.

1. Ga naar [account.apple.com](https://account.apple.com) en log in.
2. Kies **Inloggen en beveiliging** > **App-specifieke wachtwoorden** en maak er een met de naam "Bongo".
3. Je krijgt iets als `abcd-efgh-ijkl-mnop`. Bewaar het alleen in `.env` (de volgende stap).

## 2. In `.env` op de Pi

```
CALENDAR_BACKEND=icloud
ICLOUD_USERNAME=jouw-apple-id@icloud.com
ICLOUD_APP_PASSWORD=abcd-efgh-ijkl-mnop
ICLOUD_CALENDAR_NAME=Privé
```

`ICLOUD_CALENDAR_NAME` is de standaardagenda: daar komt een afspraak in als er geen duidelijk past.

## 3. Kijk wat Bongo ziet

```bash
.venv/bin/python -m assistent.kern agendas
```

Je krijgt een lijst met elke agenda en wat Bongo ermee mag, bijvoorbeeld:

```
Agenda: icloud
  Calendar                 lezen en schrijven
  Privé                    lezen en schrijven (de standaard)
  Werk                     lezen en schrijven
  ...
```

Klopt het, herstart dan de kern.

## Welke agenda's leest hij?

Alle agenda's in je iCloud. Let op: het vinkje voor een agenda in Agenda op je Mac geldt alleen
voor je Mac. Een agenda zonder vinkje ziet Bongo dus gewoon wel. Wil je dat hij er een overslaat:

```
ICLOUD_NIET_LEZEN=Naam van de agenda
```

Meer dan één? Zet er komma's tussen. In een agenda die hij niet leest, zet hij ook niets.

## Waarin zet hij afspraken?

Bongo kiest per afspraak de agenda die erbij past: een training in Sport, een tentamen in School.
In het voorstel staat in welke agenda het komt, bijvoorbeeld "Afspraak: Training, woensdag 14
oktober 2026, 19:00-20:30 (agenda Sport)". Klopt de agenda niet, keur het dan af en zeg welke het moet zijn.

Een agenda die iemand anders met je deelt, mag je soms alleen bekijken. Zet Bongo daar toch iets in,
dan mislukt het goedkeuren en staat de reden bij het voorstel.

## Abonnementen, zoals een lesrooster

Een abonnement is een agenda die je volgt via een link (van school, een sportclub, een
voetbalprogramma). In Agenda op de Mac staat er vaak een icoontje met golfjes naast. Zulke agenda's
zitten voor zover ik weet niet in de CalDAV-koppeling van iCloud, dus die leest Bongo rechtstreeks
via hun link.

1. Zoek de link. Op de Mac: klik met rechts op de agenda en kies **Toon info**. Bij een abonnement
   staat daar een link die begint met `webcal://` of `https://`. Vaak staat hij ook op de
   roosterwebsite van school, bij iets als "exporteren naar agenda".
2. Zet in `.env` (naam=link, meer dan één met komma's ertussen):
   ```
   AGENDA_ABONNEMENTEN=Hogeschool=webcal://...
   ```
3. Kijk met `.venv/bin/python -m assistent.kern agendas` of het werkt. Bij het abonnement staat dan
   hoeveel afspraken er de komende week in staan.

Een abonnement kan Bongo alleen lezen; er iets in zetten kan niet (dat kan je Mac ook niet).

De link is persoonlijk: wie hem heeft, kan je rooster zien. Zet hem dus alleen in `.env`, nooit in
de code of in een bericht.

Staat de agenda in de lijst van stap 3 al bij iCloud? Dan is het geen abonnement maar een gewone
agenda (misschien een die je openbaar deelt), en hoef je niets te doen.
