"use strict";
// Het touchscreen in de kamer (1024 x 600). Draait in Chromium op de Pi zelf, dus zonder aanmelden.

const $ = (id) => document.getElementById(id);
const DAGEN = ["zondag", "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag"];
const MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"];
const WAKKER_NA_TIK_MS = 60_000; // na een tik 's nachts blijft het scherm een minuut aan
const BEVESTIG_MS = 4_000; // zo lang staat "Zeker?" klaar
const MAX_VOORSTELLEN = 2; // meer gele balken passen niet naast de agenda

let toestand = null;
let wakkerTot = 0;
let wachtOpZeker = null; // id van het voorstel dat op de tweede tik wacht

function tikKlok() {
  const nu = new Date();
  const tijd = nu.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
  $("klok").textContent = tijd;
  $("nachtklok").textContent = tijd;
  $("datum").textContent = `${DAGEN[nu.getDay()]} ${nu.getDate()} ${MAANDEN[nu.getMonth()]}`;
  toonNacht();
}

function toonNacht() {
  const nacht = toestand && toestand.nacht && Date.now() > wakkerTot;
  $("nacht").hidden = !nacht;
}

// ---- voorstellen: "Ja" vraagt om een tweede tik --------------------------------------
// Een aanraakscherm in de kamer wordt ook per ongeluk aangeraakt (door een elleboog, een
// kat of een kind). Eén tik mag daarom nooit iets in de agenda zetten.
function voorstelKaart(v) {
  const zeker = wachtOpZeker === v.id;
  return el(
    "article",
    { class: "kiosk-voorstel" },
    el("p", {}, v.samenvatting),
    el(
      "div",
      { class: "rij" },
      el("button", { type: "button", class: zeker ? "zeker" : "", onclick: () => ja(v.id) }, zeker ? "Zeker? Tik nog eens" : "Ja"),
      el("button", { type: "button", class: "tweede", onclick: () => nee(v.id) }, "Nee"),
    ),
  );
}

function tekenVoorstellen() {
  const open = toestand ? toestand.open : [];
  const meer = open.length - MAX_VOORSTELLEN;
  $("voorstellen").replaceChildren(
    ...open.slice(0, MAX_VOORSTELLEN).map(voorstelKaart),
    meer > 0 ? el("p", { class: "kiosk-meer" }, `En nog ${meer} ${meer === 1 ? "voorstel" : "voorstellen"}. Die komen hierna.`) : null,
  );
  // Maak onderaan precies zoveel ruimte als de gele balken hoog zijn, zodat ze niets bedekken.
  document.body.style.paddingBottom = open.length ? `${$("voorstellen").offsetHeight + 32}px` : "";
}

async function ja(id) {
  if (wachtOpZeker !== id) {
    wachtOpZeker = id;
    tekenVoorstellen();
    setTimeout(() => {
      if (wachtOpZeker === id) {
        wachtOpZeker = null;
        tekenVoorstellen();
      }
    }, BEVESTIG_MS);
    return;
  }
  wachtOpZeker = null;
  await api(`/api/voorstellen/${id}/ja`, { methode: "POST" }).catch(() => {});
  await ververs();
}

async function nee(id) {
  wachtOpZeker = null;
  await api(`/api/voorstellen/${id}/nee`, { methode: "POST" }).catch(() => {});
  await ververs();
}

// ---- de toestand ----------------------------------------------------------------------
async function ververs() {
  toestand = await api("/api/toestand");
  $("agenda").replaceChildren(...toestand.agenda.map((d) => agendaDag(d)));
  $("agenda-fout").hidden = !toestand.agenda_fout;
  $("agenda-fout").textContent = toestand.agenda_fout ? `Agenda niet bereikbaar: ${toestand.agenda_fout}` : "";
  $("ochtend").textContent = toestand.ochtend ? toestand.ochtend.tekst : "";
  // Staat er iets klaar, dan maakt het scherm zich wakker.
  if (toestand.open.length) wakkerTot = Math.max(wakkerTot, Date.now() + WAKKER_NA_TIK_MS);
  tekenVoorstellen();
  toonNacht();
  return toestand;
}

document.addEventListener("DOMContentLoaded", () => {
  $("nacht").addEventListener("click", () => {
    wakkerTot = Date.now() + WAKKER_NA_TIK_MS;
    toonNacht();
  });
  tikKlok();
  setInterval(tikKlok, 1000);
  // Elke vijf minuten alles opnieuw, voor het geval de datum verspringt of een melding mist.
  setInterval(() => ververs().catch(() => {}), 5 * 60_000);
  volgWijzigingen(ververs, (storing) => ($("storing").hidden = !storing));
});
