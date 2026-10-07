# Oefeningen, met uitwerking

Bij het testen van Bongo vond ik (Claude) een paar echte problemen. Eerst liet ik ze liggen als
oefening; daarna heb ik ze opgelost. De vragen staan er nog, met de uitwerking ingeklapt eronder.
Wil je ervan leren: beantwoord eerst zelf de vragen, en klap dan pas open.

---

## 0. Opwarmer: waarom faalt een test?

In `assistent/geheugen.py` staat in `voeg_toe()` een `with self._slot:` om het lezen en schrijven
heen. Haal die regel weg (en zet de code eronder een stap terug), en draai
`.venv/bin/python -m pytest tests/test_geheugen.py`.

1. Welke test faalt, en waarom? Beschrijf stap voor stap wat twee threads tegelijk doen.
2. In die test staat een `time.sleep(0.005)` in een nep-versie van `lees()`. Haal die ook weg.
   Faalt de test nu nog? Draai hem een paar keer. Wat zegt dat over het testen van threads?

<details><summary>Uitwerking</summary>

Thread A leest het bestand, thread B leest hetzelfde bestand, A schrijft zijn versie (met feit A),
B schrijft zijn versie (met feit B, zonder feit A). Feit A is weg. Dit heet een *lost update*: het
lezen, aanpassen en schrijven moet één ondeelbaar geheel zijn, dus onder één slot.

Zonder de `sleep` slaagt de test meestal, omdat het moment tussen lezen en schrijven heel kort is.
Een fout met threads die "meestal" goed gaat, is de vervelendste soort: hij gebeurt pas na weken,
op de Pi, en nooit als je kijkt. Daarom maakt de test het venster expres groter.

Een tweede les uit dezelfde code: het slot is een `RLock` (een slot dat dezelfde thread meerdere
keren mag pakken), omdat `voeg_toe()` het slot vasthoudt en daarbinnen `schrijf()` aanroept, die het
ook pakt. Met een gewone `Lock` wacht de thread dan op zichzelf: hij blijft voor altijd hangen.
</details>

---

## 1. Halverwege gestorven

Tymo tikt op "ja" bij een nieuwe afspraak. `Wachtrij.approve()` zet het voorstel op `bezig` en
vraagt iCloud de afspraak op te slaan. Precies op dat moment valt de stroom uit.

1. In welke toestand staat het voorstel als de Pi weer opstart? Kan Tymo er nog iets mee?
2. Staat de afspraak in iCloud? Weet je dat zeker?
3. "Zet bij het opstarten alles wat op `bezig` staat terug op `open`." Wat kan er dan misgaan?
   En als je ze op `mislukt` zet?
4. Wat is erger: een afspraak die er twee keer in staat, of een die ontbreekt?

<details><summary>Uitwerking</summary>

1. Op `bezig`, voor altijd. `approve()` en `reject()` werken alleen op `open`, dus Tymo kan niets meer.
2. Dat weet niemand. Misschien kwam het verzoek bij iCloud aan vlak voor de stroom uitviel,
   misschien niet. Dit is het klassieke probleem van elk systeem dat met een ander systeem praat.
3. Terug op `open`: als het wél gelukt was, keurt Tymo hem opnieuw goed en staat de afspraak er
   twee keer in (*at-least-once*). Op `mislukt`: als het wél gelukt was, liegt Bongo (*at-most-once*).
4. Allebei vervelend. Dus: ga het na in plaats van te gokken.

Wat ik gebouwd heb (`Wachtrij.herstel_onderbroken()`):

- Elke afspraak krijgt bij het voorstellen al een vaste `uid` (in `tools.py`). Die gaat mee naar
  iCloud. Na een herstart kijkt de *controle* (in `executors.py`) of er in iCloud een afspraak met
  die `uid` staat. Ja: `uitgevoerd`. Nee: weer `open`, zodat Tymo opnieuw kan kiezen. Zo wordt
  "minstens één keer" toch "precies één keer": dat heet *idempotentie*.
- Bij `onthouden` en `vergeten` kijkt de controle in het geheugenbestand.
- Lukt nagaan niet (iCloud onbereikbaar): de eerlijke status `onbekend`, met de melding dat Tymo
  zelf moet kijken.
- Alleen voorstellen die al twee minuten `bezig` zijn: de CLI kan op dat moment nog netjes bezig zijn.

Tests: `test_herstel_*` in `tests/test_wachtrij.py` en `tests/test_tools.py`.
</details>

---

## 2. Het voorstel dat niemand meer kent

Tymo zegt: "zet morgen om tien uur de kapper erin." Claude maakt voorstel #7, en bij de volgende
aanroep van de API valt het internet weg. Bongo zegt: "Ik kan het internet niet bereiken."

1. Wat gebeurt er met de geschiedenis van het gesprek? En met voorstel #7?
2. Tymo vraagt het een minuut later nog een keer. Hoeveel open voorstellen staan er dan?
3. Weet Claude nog dat #7 bestaat? Wat ziet Claude als Tymo #7 later goedkeurt?
4. Laten staan, automatisch afwijzen, of iets anders?

<details><summary>Uitwerking</summary>

1. De beurt wordt uit de geschiedenis gehaald (anders blijft er een `tool_use` zonder antwoord
   staan), maar voorstel #7 stond al in de database en bleef open.
2. Twee: #7 en het nieuwe #8, voor dezelfde afspraak.
3. Nee, die beurt is weg. Keurt Tymo #7 goed, dan krijgt Claude te horen "voorstel #7 is
   goedgekeurd", over een voorstel waar hij nooit van gehoord heeft.
4. Gekozen: het voorstel *vervalt* (een nieuwe status), want Tymo kreeg een foutmelding en geen
   voorstel; hij gaat het opnieuw vragen. Eén uitzondering: had Tymo #7 in die paar seconden al
   goedgekeurd, dan blijft het staan en hoort Claude het bij de volgende vraag.

De les: als je bij een fout iets terugdraait, draai dan *alles* terug wat die beurt veranderde, niet
alleen het deel dat je toevallig in het geheugen had. Kijk naar `_laat_voorstellen_vervallen()` in
`brain.py`. Tests: `test_voorstel_uit_een_mislukte_beurt_vervalt` en de test eronder.
</details>

---

## 3. Wie betaalde dit?

Om half acht maakt de kern het ochtendoverzicht met `Brain.eenmalig()`. Op hetzelfde moment stelt
Tymo via de webapp een vraag met `Brain.vraag()`. Allebei rekenen ze uit wat hun aanroep kostte.

1. Waar werd `self._laatste_kosten` geschreven en gelezen? Welke methodes hielden `self._slot` vast?
2. Teken een tijdlijn waarin Tymo's vraag de kosten van het ochtendoverzicht te zien krijgt.
3. Hoe erg is het?
4. Oplossing A: `eenmalig()` ook het slot laten pakken. Oplossing B: `_roep_api()` geeft de kosten
   terug in plaats van ze in `self` te bewaren. Welke is beter?

<details><summary>Uitwerking</summary>

1. Geschreven in `_roep_api()`, gelezen in `_lus()` en `eenmalig()`. Alleen `vraag()` (en dus `_lus()`)
   hield het slot vast; `eenmalig()` niet.
2. Vraag: `_roep_api()` zet `_laatste_kosten = 0,02`. Ochtend: `_roep_api()` zet `_laatste_kosten = 0,05`.
   Vraag: leest `_laatste_kosten` en krijgt 0,05.
3. Niet erg: alleen het bedrag dat bij één antwoord getoond wordt, klopt niet. De tabel `verbruik` in
   de database is wel goed, want elke aanroep schrijft daar zijn eigen regel.
4. B (gebouwd). Met A moet Tymo's vraag wachten tot het ochtendoverzicht klaar is (tien seconden),
   terwijl die twee niets met elkaar te maken hebben. B haalt de gedeelde toestand gewoon weg: een
   returnwaarde is van de aanroeper alleen. Minder gedeelde toestand is bijna altijd beter dan meer sloten.

Test: `test_kosten_komen_van_de_eigen_aanroep`.
</details>

---

## 4. Bonus: een test die te makkelijk slaagt

`test_laatste_n_knipt_zonder_de_api_boos_te_maken` controleert dat het brein een te lang gesprek
netjes inkort. Haal in `_knip()` het `_zonder_denkblokken(...)` weg en draai de test.

<details><summary>Uitwerking</summary>

Zonder de laatste regel van de test (`assert len(nep.verzoeken) == 5`) zou hij nog steeds slagen.
De nep-API weigert dan het verzoek (de denkblokken passen niet meer bij het ingekorte gesprek), maar
`_lus()` heeft een noodroute: denkblokken weghalen en opnieuw proberen. Die redt het, en de fout in
`_knip()` blijft onzichtbaar. Je ziet hem alleen aan het extra verzoek, en op de Pi aan een hogere
rekening en een langzamer antwoord.

De les: een vangnet in je code kan een fout verbergen. Test daarom niet alleen *dat* het goed
afloopt, maar ook *hoe*.
</details>
