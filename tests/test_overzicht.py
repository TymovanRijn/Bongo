from datetime import date, datetime, timedelta

from nep_claude import TZ, geen_verbinding, tekst

from assistent.overzicht import agenda_per_dag, eenvoudig_overzicht, maak_ochtendoverzicht


def test_agenda_per_dag(maak):
    o, _ = maak()
    dag = date(2030, 3, 4)
    o.agenda.voeg_toe("Kapper", datetime(2030, 3, 4, 10, tzinfo=TZ), datetime(2030, 3, 4, 10, 30, tzinfo=TZ))
    o.agenda.voeg_toe("Weekend weg", datetime(2030, 3, 4, tzinfo=TZ), datetime(2030, 3, 7, tzinfo=TZ), hele_dag=True)
    o.agenda.voeg_toe("Nachtdienst", datetime(2030, 3, 5, 22, tzinfo=TZ), datetime(2030, 3, 6, 6, tzinfo=TZ))

    dagen = agenda_per_dag(o.agenda, TZ, dagen=3, vanaf=dag)
    assert [d["label"] for d in dagen] == ["Vandaag", "Morgen", "Woensdag"]
    assert [a["titel"] for a in dagen[0]["afspraken"]] == ["Weekend weg", "Kapper"]
    assert dagen[0]["afspraken"][1]["tijd"] == "10:00" and dagen[0]["afspraken"][1]["eind"] == "10:30"
    # Een afspraak over middernacht staat op beide dagen; op de tweede dag vanaf 00:00.
    assert [a["tijd"] for a in dagen[1]["afspraken"] if a["titel"] == "Nachtdienst"] == ["22:00"]
    assert [a["tijd"] for a in dagen[2]["afspraken"] if a["titel"] == "Nachtdienst"] == ["00:00"]


def test_eenvoudig_overzicht():
    dag = {"lang": "maandag 4 maart 2030", "afspraken": []}
    assert eenvoudig_overzicht(dag, "Tymo") == "Goedemorgen Tymo! Het is maandag 4 maart 2030. Je agenda is vandaag leeg."
    dag["afspraken"] = [{"titel": "Kapper", "tijd": "10:00"}]
    assert "één afspraak: Kapper (10:00)." in eenvoudig_overzicht(dag, "Tymo")
    dag["afspraken"].append({"titel": "Sporten", "tijd": "18:00"})
    assert "2 afspraken: Kapper (10:00) en Sporten (18:00)." in eenvoudig_overzicht(dag, "Tymo")


def test_ochtendoverzicht_met_claude(maak):
    o, nep = maak([tekst("Goedemorgen! Druk dagje.")])
    tekst_, kosten = maak_ochtendoverzicht(o.brain, o.agenda, TZ, "Tymo")
    assert tekst_ == "Goedemorgen! Druk dagje."
    assert "Afspraken vandaag" in nep.verzoeken[0]["messages"][0]["content"]


def test_ochtendoverzicht_werkt_ook_zonder_internet(maak):
    o, _ = maak([geen_verbinding()])
    tekst_, kosten = maak_ochtendoverzicht(o.brain, o.agenda, TZ, "Tymo")
    assert tekst_.startswith("Goedemorgen Tymo!") and kosten == 0.0
