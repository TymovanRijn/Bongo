"use strict";
// Het touchscreen in de kamer (1024 x 600): Bongo's gezicht. Draait op de Pi zelf, dus zonder aanmelden.
//
// Het gezicht laat zien wat Bongo doet (de klasse op <body>):
//   rust       knippert en kijkt af en toe rond
//   luisteren  grote ogen, gloed eromheen: praat maar
//   denken     tuurt omhoog
//   praten     lacht met zijn ogen, de neus wipt mee
//   slaapt     's nachts: ogen dicht
//   verward    er ging iets mis (even)
// Tik op het gezicht: luisteren. Nog een tik: klaar met praten. Tik terwijl hij praat: stil.

const $ = (id) => document.getElementById(id);
const BEVESTIG_MS = 4_000; // zo lang staat "Zeker?" klaar
const MAX_VOORSTELLEN = 2; // meer gele balken passen niet
const WAKKER_NA_TIK_MS = 60_000; // na een tik 's nachts blijft hij een minuut wakker
const ONDERTITEL_NA_MS = 6_000; // zo lang blijft wat hij zei nog staan

let toestand = null;
let wakkerTot = 0;
let wachtOpZeker = null;
let ondertitelTimer = null;
let verwardTimer = null;

// ---- het gezicht ------------------------------------------------------------------------
const STANDEN = ["rust", "luisteren", "denken", "praten", "slaapt"];

function zetStand(stand) {
  for (const s of STANDEN) document.body.classList.toggle(s, s === stand);
  if (stand !== "rust") kijk(0, 0);
}

function huidigeStand() {
  const spraak = toestand ? toestand.spraak.toestand : "rust";
  if (spraak === "luisteren" || spraak === "denken" || spraak === "praten") return spraak;
  if (toestand && toestand.nacht && Date.now() > wakkerTot) return "slaapt";
  return "rust";
}

// Kijken: verschuif iris en pupil (in punten van het gezicht, hooguit 40 opzij en 30 op en neer).
function kijk(x, y) {
  const r = document.documentElement.style;
  r.setProperty("--kijk-x", `${Math.max(-40, Math.min(40, x))}px`);
  r.setProperty("--kijk-y", `${Math.max(-30, Math.min(30, y))}px`);
}

function knipper() {
  document.body.classList.add("knipper");
  setTimeout(() => document.body.classList.remove("knipper"), 130);
}

// Leven: knipperen om de 2,5 tot 6 seconden (soms twee keer), rondkijken als hij niets doet.
function levenLus() {
  const stand = huidigeStand();
  if (stand !== "slaapt") {
    knipper();
    if (Math.random() < 0.2) setTimeout(knipper, 260);
  }
  setTimeout(levenLus, 2500 + Math.random() * 3500);
}

function rondkijkLus() {
  if (huidigeStand() === "rust") {
    if (Math.random() < 0.35) kijk(0, 0);
    else kijk((Math.random() * 2 - 1) * 40, (Math.random() * 2 - 1) * 24);
  }
  setTimeout(rondkijkLus, 2000 + Math.random() * 3000);
}

function verward(melding) {
  document.body.classList.add("verward");
  clearTimeout(verwardTimer);
  verwardTimer = setTimeout(() => document.body.classList.remove("verward"), 2500);
  if (melding) toonOndertitel(melding, true);
}

function toonOndertitel(tekst, fout = false) {
  const o = $("ondertitel");
  clearTimeout(ondertitelTimer);
  o.textContent = tekst;
  o.classList.toggle("fout", fout);
  o.classList.toggle("zichtbaar", Boolean(tekst));
  if (tekst && (fout || huidigeStand() !== "praten")) {
    ondertitelTimer = setTimeout(() => o.classList.remove("zichtbaar"), ONDERTITEL_NA_MS);
  }
}

// ---- tikken -----------------------------------------------------------------------------
async function tikOpGezicht(e) {
  // Kijk naar de vinger.
  const vak = $("gezicht").getBoundingClientRect();
  kijk(((e.clientX - vak.left) / vak.width - 0.5) * 120, ((e.clientY - vak.top) / vak.height - 0.45) * 90);
  if (huidigeStand() === "slaapt") {
    wakkerTot = Date.now() + WAKKER_NA_TIK_MS;
    zetStand("rust");
    return;
  }
  try {
    const status = await api("/api/luister", { methode: "POST" });
    if (toestand) toestand.spraak = status;
    zetStand(huidigeStand());
    if (status.melding && status.toestand === "rust") verward(status.melding); // bijvoorbeeld: nog aan het laden
  } catch (fout) {
    verward(fout.message);
  }
}

// ---- voorstellen: "Ja" vraagt om een tweede tik ----------------------------------------
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
    // Let op: replaceChildren(null) zet letterlijk de tekst "null" op het scherm. Dus een lege lijst.
    ...(meer > 0 ? [el("p", { class: "kiosk-meer" }, `En nog ${meer} ${meer === 1 ? "voorstel" : "voorstellen"}. Die komen hierna.`)] : []),
  );
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
  await api(`/api/voorstellen/${id}/ja`, { methode: "POST" }).catch((e) => verward(e.message));
  await ververs();
}

async function nee(id) {
  wachtOpZeker = null;
  await api(`/api/voorstellen/${id}/nee`, { methode: "POST" }).catch((e) => verward(e.message));
  await ververs();
}

// ---- de toestand ----------------------------------------------------------------------
async function ververs() {
  const vorige = toestand ? toestand.spraak : null;
  toestand = await api("/api/toestand");
  const spraak = toestand.spraak;
  if (toestand.open.length) wakkerTot = Math.max(wakkerTot, Date.now() + WAKKER_NA_TIK_MS);
  zetStand(huidigeStand());
  if (spraak.toestand === "praten") toonOndertitel(spraak.ondertitel);
  else if (vorige && vorige.toestand === "praten") toonOndertitel(spraak.ondertitel); // laat hem nog even staan
  if (spraak.melding && (!vorige || vorige.melding !== spraak.melding)) verward(spraak.melding);
  tekenVoorstellen();
  return toestand;
}

document.addEventListener("DOMContentLoaded", () => {
  $("gezicht").addEventListener("pointerdown", tikOpGezicht);
  levenLus();
  rondkijkLus();
  // Elke minuut opnieuw: dag en nacht wisselen ook zonder melding van de kern.
  setInterval(() => ververs().catch(() => {}), 60_000);
  volgWijzigingen(ververs, (storing) => ($("storing").hidden = !storing));
});
