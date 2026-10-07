"use strict";
// De webapp voor de telefoon. De kern stuurt alles als JSON; deze code tekent het.

const $ = (id) => document.getElementById(id);
let toestand = null;

// ---- tabbladen ------------------------------------------------------------------------
const bijOpenen = {
  agenda: laadAgenda,
  geheugen: laadGeheugen,
  meer: laadMeer,
};

function kiesTab(naam) {
  for (const knop of document.querySelectorAll(".tabs button")) knop.classList.toggle("actief", knop.dataset.tab === naam);
  for (const tab of document.querySelectorAll(".tab")) tab.classList.toggle("actief", tab.id === `tab-${naam}`);
  if (bijOpenen[naam]) bijOpenen[naam]().catch(toonFout);
}

function toonFout(e) {
  alert(e.message || String(e));
}

// ---- voorstellen ----------------------------------------------------------------------
function voorstelKaart(v) {
  const knoppen =
    v.status === "open"
      ? el(
          "div",
          { class: "rij" },
          el("button", { type: "button", onclick: () => beslis(v.id, "ja") }, "Ja, doen"),
          el("button", { type: "button", class: "tweede", onclick: () => beslis(v.id, "nee") }, "Nee"),
        )
      : null;
  return el(
    "article",
    { class: `voorstel status-${v.status}`, "data-id": v.id },
    el("p", { class: "voorstel-wat" }, v.samenvatting),
    el("p", { class: "voorstel-meta" }, `#${v.id} · ${STATUS[v.status] || v.status}`, v.resultaat && v.status !== "uitgevoerd" ? ` · ${v.resultaat}` : ""),
    knoppen,
  );
}

async function beslis(id, keuze) {
  try {
    const v = await api(`/api/voorstellen/${id}/${keuze}`, { methode: "POST" });
    // Ook de kaartjes in het gesprek bijwerken.
    for (const kaart of document.querySelectorAll(`.gesprek .voorstel[data-id="${id}"]`)) kaart.replaceWith(voorstelKaart(v));
  } catch (e) {
    toonFout(e);
  }
  await ververs();
}

// ---- de toestand ----------------------------------------------------------------------
async function ververs() {
  toestand = await api("/api/toestand");
  $("naam").textContent = toestand.naam;
  document.title = toestand.naam;
  $("vraag").placeholder = `Vraag iets aan ${toestand.naam}`;
  $("open").replaceChildren(...(toestand.open.length ? toestand.open.map(voorstelKaart) : [el("p", { class: "uitleg" }, "Er wacht niets op je.")]));
  $("recent").replaceChildren(...toestand.recent.map(voorstelKaart));
  $("aantal").textContent = toestand.open.length;
  $("aantal").hidden = toestand.open.length === 0;
  // Kaartjes in het gesprek die niet meer open zijn (bijvoorbeeld goedgekeurd op het scherm).
  const nogOpen = new Set(toestand.open.map((v) => v.id));
  for (const kaart of document.querySelectorAll(".gesprek .voorstel.status-open")) {
    const id = Number(kaart.dataset.id);
    const nieuw = toestand.recent.find((v) => v.id === id);
    if (!nogOpen.has(id) && nieuw) kaart.replaceWith(voorstelKaart(nieuw));
  }
  if (!toestand.kan_nadenken) $("welkom").textContent = "Let op: er is nog geen API-sleutel ingesteld, dus vragen lukken nog niet.";
  return toestand;
}

// ---- praten ---------------------------------------------------------------------------
function bericht(wie, tekst, extra = []) {
  const b = el("div", { class: `bericht ${wie}` }, el("p", {}, tekst), extra);
  $("gesprek").append(b);
  b.scrollIntoView({ block: "end", behavior: "smooth" });
  return b;
}

async function stelVraag(e) {
  e.preventDefault();
  const tekst = $("vraag").value.trim();
  if (!tekst) return;
  $("vraag").value = "";
  bericht("jij", tekst);
  const wacht = bericht("bongo denkt", "…");
  $("vraagformulier").classList.add("bezig");
  try {
    const a = await api("/api/vraag", { methode: "POST", data: { tekst, bron: "web" } });
    wacht.remove();
    bericht("bongo", a.tekst, a.voorstellen.map(voorstelKaart));
  } catch (fout) {
    wacht.remove();
    bericht("bongo fout", fout.message);
  } finally {
    $("vraagformulier").classList.remove("bezig");
    $("vraag").focus();
  }
}

// ---- agenda ---------------------------------------------------------------------------
async function laadAgenda() {
  const { dagen } = await api("/api/agenda?dagen=7");
  $("agenda").replaceChildren(...dagen.map((d) => agendaDag(d)));
}

// ---- geheugen -------------------------------------------------------------------------
async function laadGeheugen() {
  const { tekst } = await api("/api/geheugen");
  $("geheugen").value = tekst;
  $("geheugen-status").textContent = "";
}

async function bewaarGeheugen() {
  try {
    await api("/api/geheugen", { methode: "PUT", data: { tekst: $("geheugen").value } });
    $("geheugen-status").textContent = "Opgeslagen.";
  } catch (e) {
    $("geheugen-status").textContent = e.message;
  }
}

// ---- meer -----------------------------------------------------------------------------
async function laadMeer() {
  const [kosten, apparaten, logboek] = await Promise.all([api("/api/kosten"), api("/api/apparaten"), api("/api/logboek?limiet=30")]);

  const totaal = kosten.dagen.reduce((som, d) => som + d.kosten_usd, 0);
  $("kosten").replaceChildren(
    kosten.dagen.length
      ? el(
          "table",
          {},
          el("tr", {}, el("th", {}, "Dag"), el("th", {}, "Aanroepen"), el("th", {}, "Kosten")),
          kosten.dagen.map((d) => el("tr", {}, el("td", {}, d.datum), el("td", {}, d.aanroepen), el("td", {}, `$ ${d.kosten_usd.toFixed(3)}`))),
          el("tr", { class: "totaal" }, el("td", {}, "30 dagen"), el("td", {}), el("td", {}, `$ ${totaal.toFixed(2)}`)),
        )
      : el("p", { class: "uitleg" }, "Nog geen kosten."),
  );

  $("apparaten").replaceChildren(
    ...(apparaten.apparaten.length
      ? apparaten.apparaten.map((a) =>
          el(
            "div",
            { class: "apparaat rij" },
            el("span", {}, a.naam, el("small", {}, `laatst gezien ${(a.laatst_gezien || "").slice(0, 16).replace("T", " ")}`)),
            el("button", { type: "button", class: "tweede klein", onclick: () => ontkoppel(a) }, "Ontkoppel"),
          ),
        )
      : [el("p", { class: "uitleg" }, apparaten.toegang === "open" ? "Iedereen op het thuisnetwerk mag erbij (WEB_TOEGANG=open)." : "Nog geen apparaten.")]),
  );

  $("logboek").replaceChildren(
    ...logboek.gebeurtenissen.reverse().map((g) => el("li", {}, el("time", {}, g.tijd.slice(5, 16).replace("T", " ")), el("b", {}, g.soort), g.inhoud.slice(0, 200))),
  );
}

async function ontkoppel(apparaat) {
  if (!confirm(`${apparaat.naam} ontkoppelen?`)) return;
  await api(`/api/apparaten/${apparaat.id}`, { methode: "DELETE" }).catch(toonFout);
  laadMeer().catch(toonFout);
}

async function maakKoppellink(e) {
  e.preventDefault();
  const naam = $("koppel-naam").value.trim();
  if (!naam) return;
  try {
    const { link, geldig_tot } = await api("/api/apparaten", { methode: "POST", data: { naam } });
    $("koppel-uitkomst").replaceChildren(
      `Open deze link op het nieuwe apparaat (één keer bruikbaar, geldig tot ${geldig_tot.slice(11, 16)} morgen):`,
      el("br"),
      el("code", {}, link),
    );
    $("koppel-uitkomst").hidden = false;
    $("koppel-naam").value = "";
  } catch (fout) {
    toonFout(fout);
  }
}

// ---- starten --------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  for (const knop of document.querySelectorAll(".tabs button")) knop.addEventListener("click", () => kiesTab(knop.dataset.tab));
  $("vraagformulier").addEventListener("submit", stelVraag);
  $("geheugen-opslaan").addEventListener("click", bewaarGeheugen);
  $("koppelformulier").addEventListener("submit", maakKoppellink);
  $("nieuw-gesprek").addEventListener("click", async () => {
    await api("/api/gesprek/nieuw", { methode: "POST" }).catch(toonFout);
    $("gesprek").replaceChildren();
    kiesTab("praten");
  });
  $("ochtend-nu").addEventListener("click", async () => {
    const o = await api("/api/ochtendoverzicht", { methode: "POST" }).catch(toonFout);
    if (o) {
      kiesTab("praten");
      bericht("bongo", o.tekst);
    }
  });
  $("uitloggen").addEventListener("click", async () => {
    if (!confirm("Dit apparaat afmelden?")) return;
    await api("/api/uitloggen", { methode: "POST" }).catch(() => {});
    location.href = "/inloggen";
  });
  volgWijzigingen(ververs, (storing) => ($("storing").hidden = !storing));
});
