"use strict";
// Hulpjes voor alle pagina's van Bongo.
//
// Belangrijk: tekst die van buiten komt (agenda-titels kunnen van anderen zijn!) komt altijd
// via textContent op de pagina, nooit via innerHTML. Anders kan iemand met een uitnodiging
// als "<img src=x onerror=...>" code laten draaien in Tymo's browser.

function el(tag, eigenschappen = {}, ...kinderen) {
  const e = document.createElement(tag);
  for (const [sleutel, waarde] of Object.entries(eigenschappen)) {
    if (waarde === null || waarde === undefined || waarde === false) continue;
    if (sleutel === "class") e.className = waarde;
    else if (sleutel.startsWith("on")) e.addEventListener(sleutel.slice(2), waarde);
    else e.setAttribute(sleutel, waarde === true ? "" : waarde);
  }
  for (const kind of kinderen.flat()) {
    if (kind === null || kind === undefined || kind === false) continue;
    e.append(kind instanceof Node ? kind : String(kind));
  }
  return e;
}

class ApiFout extends Error {
  constructor(status, melding) {
    super(melding);
    this.status = status;
  }
}

async function api(pad, { methode = "GET", data } = {}) {
  const opties = { method: methode, headers: {} };
  if (data !== undefined) {
    opties.headers["Content-Type"] = "application/json";
    opties.body = JSON.stringify(data);
  }
  const r = await fetch(pad, opties);
  if (r.status === 401 && pad !== "/api/inloggen") {
    location.href = "/inloggen";
    throw new ApiFout(401, "Meld je eerst aan.");
  }
  let inhoud = null;
  try {
    inhoud = await r.json();
  } catch {
    // geen JSON, bijvoorbeeld een foutpagina
  }
  if (!r.ok) throw new ApiFout(r.status, (inhoud && (inhoud.fout || inhoud.detail)) || `Er ging iets mis (${r.status}).`);
  return inhoud;
}

const slaap = (ms) => new Promise((klaar) => setTimeout(klaar, ms));

// Haal de toestand op met `ververs` (die geeft de toestand terug) en doe dat opnieuw zodra
// de kern meldt dat er iets veranderd is. `bijStoring(true/false)` hoort of de kern bereikbaar is.
async function volgWijzigingen(ververs, bijStoring = () => {}) {
  let versie = null;
  for (;;) {
    try {
      if (versie === null) versie = (await ververs()).versie;
      bijStoring(false);
      const r = await api(`/api/wacht?versie=${versie}`);
      if (r.versie !== versie) versie = (await ververs()).versie;
    } catch (e) {
      bijStoring(true);
      versie = null;
      await slaap(5000);
    }
  }
}

const STATUS = {
  open: "wacht op jou",
  bezig: "bezig",
  uitgevoerd: "gedaan",
  afgewezen: "afgewezen",
  mislukt: "mislukt",
  vervallen: "vervallen",
  onbekend: "onzeker: kijk zelf",
};

function klokTijd(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
}

// Eén dag uit de agenda als lijstje. `dag` komt van agenda_per_dag() in overzicht.py.
function agendaDag(dag, metLabel = true) {
  const items = dag.afspraken.length
    ? dag.afspraken.map((a) =>
        el(
          "li",
          { class: "afspraak" },
          el("span", { class: "afspraak-tijd" }, a.hele_dag ? "hele dag" : a.tijd + (a.eind ? `–${a.eind}` : "")),
          el("span", { class: "afspraak-titel" }, a.titel, a.locatie ? el("small", {}, a.locatie) : null),
        ),
      )
    : [el("li", { class: "afspraak leeg" }, "Niets gepland")];
  return el(
    "section",
    { class: "dag" },
    metLabel ? el("h3", {}, dag.label, el("small", {}, dag.lang)) : null,
    el("ul", {}, items),
  );
}
