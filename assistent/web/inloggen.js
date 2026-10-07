"use strict";

const $ = (id) => document.getElementById(id);

function raadNaam() {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return "iPhone";
  if (/iPad/.test(ua)) return "iPad";
  if (/Android/.test(ua)) return "Android-telefoon";
  if (/Mac/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows-computer";
  return "apparaat";
}

document.addEventListener("DOMContentLoaded", async () => {
  const info = await api("/api/aanmelden");
  $("titel").textContent = info.naam;
  if (info.aangemeld) {
    location.href = "/";
    return;
  }
  if (info.modus === "link") {
    $("melding").textContent =
      "Dit apparaat is nog niet gekoppeld. Maak een koppellink op een apparaat dat al gekoppeld is (Meer > Apparaten), " +
      'of op de Pi met: python -m assistent.kern koppel "naam"';
    return;
  }
  if (!info.pin_ingesteld) {
    $("melding").textContent = "Er is nog geen pincode ingesteld. Zet WEB_PIN in het bestand .env op de Pi en herstart de kern.";
    return;
  }
  $("apparaat").value = raadNaam();
  $("pinformulier").hidden = false;
  $("pin").focus();
  $("pinformulier").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("melding").textContent = "";
    try {
      await api("/api/inloggen", { methode: "POST", data: { pin: $("pin").value, naam: $("apparaat").value } });
      location.href = "/";
    } catch (fout) {
      $("melding").textContent = fout.message;
      $("pin").value = "";
      $("pin").focus();
    }
  });
});
