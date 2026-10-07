# Oefeningen

Bij het testen van Bongo vond ik (Claude) een paar echte problemen. Sommige heb ik opgelost
(zie de git-geschiedenis). Deze heb ik **bewust laten staan**, zodat jij ze kunt uitzoeken.
Ze zijn nu nog niet gevaarlijk, omdat de kern nog niet draait, maar ze zijn wel echt.

Zo werk je ze af:

1. Lees de situatie en beantwoord de vragen **op papier**, voordat je code leest of schrijft.
2. Zoek in de code of je gelijk had.
3. Kom je vast te zitten, klap dan één hint open. Niet alle drie tegelijk.
4. Schrijf eerst een test die het probleem laat zien (hij moet falen), en repareer het daarna.

---

## 0. Opwarmer: waarom faalt een test?

In `assistent/geheugen.py` staat in `voeg_toe()` een `with self._slot:` om het lezen en
schrijven heen. Haal die regel weg (en zet de code eronder een stap terug), en draai:

```bash
.venv/bin/python -m pytest tests/test_geheugen.py
```

1. Welke test faalt, en waarom? Beschrijf stap voor stap wat twee threads tegelijk doen.
2. In die test staat een `time.sleep(0.005)` in een nep-versie van `lees()`. Haal die ook weg.
   Faalt de test nu nog steeds? Draai hem een paar keer. Wat zegt dat over het testen van
   problemen met threads?

<details><summary>Hint</summary>

Thread A leest het bestand, thread B leest het bestand, A schrijft zijn versie, B schrijft
zijn versie. Wat staat er nu in het bestand? De `sleep` maakt het venster tussen lezen en
schrijven groter. Zonder dat venster is de kans dat het misgaat klein, maar niet nul.
</details>

Zet het slot daarna weer terug.

---

## 1. Halverwege gestorven

Tymo tikt op "ja" bij een nieuwe afspraak. `Wachtrij.approve()` zet het voorstel op `bezig`
en vraagt iCloud de afspraak op te slaan. Precies op dat moment valt de stroom uit.

1. In welke toestand staat het voorstel als de Pi weer opstart? Kan Tymo er nog iets mee
   (goedkeuren, afwijzen)?
2. Staat de afspraak in iCloud? Weet je dat zeker?
3. Iemand stelt voor: "zet bij het opstarten alles wat op `bezig` staat terug op `open`."
   Wat kan er dan misgaan? En als je ze op `mislukt` zet?
4. Wat is erger voor Tymo: een afspraak die er twee keer in staat, of een die ontbreekt?
   Is je antwoord hetzelfde voor `onthouden`?

<details><summary>Hint 1</summary>

Zoek in `wachtrij.py` alle plekken waar `status` verandert. Teken de toestanden als bolletjes
en de overgangen als pijlen. Welk bolletje heeft geen pijl naar buiten?
</details>

<details><summary>Hint 2</summary>

Zoek op "at-most-once" en "at-least-once". Welke van de twee doet `approve()` nu?
</details>

<details><summary>Hint 3</summary>

Je kunt het niet altijd weten. Een eerlijke extra status (bijvoorbeeld `onbekend`) met een
melding aan Tymo kan beter zijn dan gokken. En kun je bij een afspraak achteraf controleren
of hij er al staat? Kijk wat `ICloudAgenda.voeg_toe()` als `uid` gebruikt, en wanneer die
gekozen wordt.
</details>

**Klaar als:** er een test in `tests/test_wachtrij.py` staat die een voorstel met SQL op
`bezig` zet, de wachtrij opnieuw opstart en controleert wat jij besloten hebt.

---

## 2. Het voorstel dat niemand meer kent

Tymo zegt: "zet morgen om tien uur de kapper erin." Claude roept `afspraak_voorstellen` aan
en voorstel #7 komt in de wachtrij. Bij de volgende aanroep van de API valt het internet weg,
en Bongo zegt: "Ik kan het internet niet bereiken."

1. Lees `Brain.vraag()`. Wat gebeurt er met de geschiedenis van het gesprek? En met voorstel #7?
2. Een minuut later doet het internet het weer en vraagt Tymo het nog een keer. Hoeveel open
   voorstellen staan er dan? Wat ziet hij op het scherm?
3. Weet Claude nog dat #7 bestaat? Wat krijgt Claude te zien als Tymo #7 later goedkeurt?
   (Kijk naar `_statuswijzigingen`.)
4. Wat zou jij doen: #7 laten staan, automatisch afwijzen, of iets anders? Noem bij elke
   keuze een nadeel.

<details><summary>Hint</summary>

Het antwoord op vraag 1 staat in het `finally`-blok van `vraag()`. Vergelijk wat daar wordt
teruggedraaid met wat `_voer_tools_uit()` allemaal verandert. Wat wordt níet teruggedraaid?
</details>

**Klaar als:** er een test in `tests/test_brain.py` staat met
`maak([tool("afspraak_voorstellen", ...), geen_verbinding()])` die laat zien wat jij gekozen hebt.

---

## 3. Wie betaalde dit?

Om half acht maakt de kern het ochtendoverzicht met `Brain.eenmalig()`. Op precies hetzelfde
moment stelt Tymo via de webapp een vraag met `Brain.vraag()`. Allebei rekenen ze uit wat
hun aanroep van Claude kostte.

1. Zoek elke plek waar `self._laatste_kosten` wordt geschreven of gelezen. Welke van die
   methodes houden `self._slot` vast, en welke niet?
2. Teken een tijdlijn met twee threads waarin de vraag van Tymo de kosten van het
   ochtendoverzicht te zien krijgt.
3. Hoe erg is het? Wat klopt er daarna niet meer, en wat juist wel? (Kijk naar de tabel `verbruik`.)
4. Er zijn twee oplossingen: `eenmalig()` ook het slot laten pakken, of `_roep_api()` de kosten
   laten *teruggeven* in plaats van ze in `self` te bewaren. Wat is het nadeel van de eerste?
   Waarom is de tweede netter?

<details><summary>Hint</summary>

Dit heet een *race condition*. Toestand die gedeeld wordt tussen threads en kan veranderen
(zoals `self.iets`) is daar de klassieke oorzaak van. Een waarde die een functie teruggeeft,
is van de aanroeper alleen.
</details>

**Klaar als:** je de tweede oplossing hebt gebouwd en alle tests nog slagen.
