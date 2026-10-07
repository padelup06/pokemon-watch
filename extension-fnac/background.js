// Service worker : toutes les N minutes, ouvre chaque fiche dans un onglet en arrière-plan
// (votre navigateur, votre session, comme si vous la consultiez), lit la disponibilité,
// referme l'onglet, et alerte sur Discord quand un produit devient achetable.
importScripts("extract.js");

const DEFAULTS = {
  webhook: "",
  webhook06: "", // ancien réglage : salon #alertes-06 seul
  zoneHooks: "", // contenu de webhooks-regions.txt : « 06=https://… », « paca=https://… »…
  intervalMinutes: 3,
  products: [
    "https://www.fnac.com/Cartes-a-collectionner-Pokemon-30A-Coffret-Dresseur-d-Elite/a23200296/w-4",
    "https://www.fnac.com/Cartes-a-collectionner-Pokemon-30A-Coffret-Amphinobi-ex/a23200310/w-4",
    "https://www.fnac.com/Cartes-a-collectionner-Pokemon-30A-Coffret-Nymphali-ex/a23200275/w-4",
    "https://www.fnac.com/Cartes-a-collectionner-Pokemon-30A-Pack-2-boosters/a23200298/w-4",
    "https://www.fnac.com/Cartes-a-collectionner-Pokemon-30A-Coffret-Poster/a23200285/w-4",
    "https://www.fnac.com/Carte-a-collectionner-Pokemon-Q3-26-Bundle-6-boosters/a23318846/w-4",
    "https://www.fnac.com/Pokemon-Q3-26-Mini-tin-Q3-2026-10-visuels/a23318837/w-4",
  ],
  state: {},
};

async function settings() {
  return Object.assign({}, DEFAULTS, await chrome.storage.local.get(Object.keys(DEFAULTS)));
}

async function schedule() {
  const { intervalMinutes } = await settings();
  await chrome.alarms.clear("pokewatch");
  chrome.alarms.create("pokewatch", { periodInMinutes: Math.max(1, Number(intervalMinutes) || 3), delayInMinutes: 0.1 });
}

chrome.runtime.onInstalled.addListener(schedule);
chrome.runtime.onStartup.addListener(schedule);
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "pokewatch") checkAll().catch((e) => console.warn("Pokémon Watch :", e));
});
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg === "defaults") reply(DEFAULTS.products);
  if (msg === "reschedule") schedule().then(() => reply(true));
  if (msg === "check-now") checkAll().then(reply, (e) => reply(`Erreur : ${e}`));
  if (msg === "test-discord") {
    (async () => {
      const main = await sendDiscord("✅ Test Pokémon Watch — Fnac : les alertes en ligne arrivent bien ici.");
      const { webhook06, zoneHooks } = await settings();
      const hooks = parseZoneHooks(zoneHooks);
      if (webhook06 && !hooks["06"]) hooks["06"] = webhook06;
      const res = [`Salon principal : ${main}`];
      for (const zone of ["06", "paca"]) {
        res.push(`salon ${zone} : ${hooks[zone] ? await sendDiscord(`✅ Test Pokémon Watch — Fnac : les alertes magasin (${zone}) arrivent bien ici.`, zone) : "non configuré"}`);
      }
      return res.join(" — ");
    })().then(reply, (e) => reply(`Erreur : ${e}`));
  }
  return true;
});

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

function waitForLoad(tabId, timeoutMs = 45000) {
  return new Promise((resolve) => {
    const done = () => { chrome.tabs.onUpdated.removeListener(listener); clearTimeout(t); resolve(); };
    const listener = (id, info) => { if (id === tabId && info.status === "complete") done(); };
    const t = setTimeout(done, timeoutMs);
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function readProduct(url, region = null, searchMode = null) {
  const tab = await chrome.tabs.create({ url, active: false });
  try {
    await waitForLoad(tab.id);
    await sleep(1500); // la lecture attend elle-même le bloc d'achat (jusqu'à 10 s)
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id }, func: pokewatchExtract, args: [region, searchMode],
    });
    const result = results && results[0] && results[0].result;
    // Page d'erreur, onglet fermé, vérification anti-robot… : pas de résultat exploitable.
    return result || { status: "erreur", error: "page non lue (chargement incomplet ?)" };
  } catch (e) {
    return { status: "erreur", error: String(e) };
  } finally {
    chrome.tabs.remove(tab.id).catch(() => {}); // onglet déjà fermé : rien à faire
  }
}

// Autres régions : une par vérification, à tour de rôle (recherche « Trouver un magasin » sur sa
// grande ville). Clés identiques aux salons Discord (webhooks-regions.txt).
const FNAC_REGIONS = [
  ["idf", "Paris"], ["ara", "Lyon"], ["occ", "Toulouse"], ["naq", "Bordeaux"], ["hdf", "Lille"],
  ["ge", "Strasbourg"], ["pdl", "Nantes"], ["bre", "Rennes"], ["nor", "Rouen"], ["bfc", "Dijon"],
  ["cvl", "Tours"], ["cor", "Ajaccio"], ["paca", "Marseille"],
];

// Salon de région d'une Fnac (alertes magasin). Les Fnac vues depuis Cannes vont du 06 à Marseille.
const ZONE_OF = [
  ["06", /cannes|cagnes|nice|monaco|antibes|grasse|menton|mandelieu|cap 3000|saint-laurent/i],
  ["paca", /toulon|la garde|marseille|aix|aubagne|avignon|fr[ée]jus|draguignan|hy[èe]res|plan de campagne|vitrolles|martigues|salon-de-provence|arles|gap/i],
];
function zoneOf(storeName) {
  const z = ZONE_OF.find(([, re]) => re.test(storeName || ""));
  return z ? z[0] : null;
}
function parseZoneHooks(text) {
  const hooks = {};
  for (const line of (text || "").split(/\r?\n/)) {
    const m = line.match(/^\s*([a-z0-9]+)\s*=\s*(https:\/\/\S+)/i);
    if (m) hooks[m[1].toLowerCase()] = m[2];
  }
  return hooks;
}

async function sendDiscord(content, zone = null) {
  const { webhook, webhook06, zoneHooks } = await settings();
  const hooks = parseZoneHooks(zoneHooks);
  if (webhook06 && !hooks["06"]) hooks["06"] = webhook06;
  const hook = (zone && hooks[zone]) || webhook;
  if (!hook) return "pas de webhook";
  try {
    const r = await fetch(hook, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }) });
    return r.ok ? "ok" : `erreur ${r.status}`;
  } catch (e) {
    return `envoi Discord impossible : ${e}`;
  }
}

function notify(message) {
  try {
    chrome.notifications.create({ type: "basic", iconUrl: "icon.png", title: "Pokémon Watch — Fnac", message }, () => void chrome.runtime.lastError);
  } catch (e) { /* notifications Windows désactivées : l'alerte Discord suffit */ }
}

const BUYABLE = ["en_stock", "precommande"];
const LABEL = { en_stock: "✅ EN STOCK", precommande: "🕒 PRÉCOMMANDE", rupture: "❌ rupture", inconnu: "❔ inconnu" };
let running = false;

async function checkAll() {
  if (running) return "Une vérification est déjà en cours : rouvrez cette fenêtre dans une minute pour voir le résultat.";
  running = true;
  try {
    const { products, state } = await settings();
    const report = [];
    const { regionIdx = 0, searchMode = null } = await chrome.storage.local.get(["regionIdx", "searchMode"]);
    const [rkey, rterm] = FNAC_REGIONS[regionIdx % FNAC_REGIONS.length];
    let mode = searchMode;
    for (const url of products) {
      let r;
      try {
        r = await readProduct(url, { key: rkey, term: rterm }, mode);
      } catch (e) {
        r = { status: "erreur", error: String(e) };
      }
      if (!r) r = { status: "erreur", error: "page non lue" };
      const prev = state[url] || {};
      if (r.status === "blocked") {
        if (!prev.blockedNotified) {
          await sendDiscord(`⚠️ La Fnac demande une vérification « humain » : ouvrez la page et validez-la.\n${url}`);
          state[url] = Object.assign({}, prev, { blockedNotified: true });
        }
        report.push(`${url} : vérification demandée par la Fnac`);
        continue;
      }
      if (r.status === "erreur") {
        report.push(`${url} : ${r.error}`);
        state[url] = Object.assign({}, prev, { error: r.error, at: new Date().toISOString() });
        continue;
      }
      const name = r.name || url;
      const known = Boolean(prev.status); // premier relevé : on enregistre sans alerter
      if (known && !BUYABLE.includes(prev.status) && BUYABLE.includes(r.status)) {
        const price = r.price ? ` — ${r.price.toFixed(2)} €` : "";
        await sendDiscord(`${LABEL[r.status]} EN LIGNE chez Fnac\n${name}${price}\n${url}`);
        notify(`${LABEL[r.status]} en ligne : ${name}`);
      }
      const storeRank = { rupture: 0, inconnu: 0, arrivage: 1, en_stock: 2 };
      // Magasins de la région du tour : rangés dans son salon.
      let seen = r.stores ? r.stores.map((s) => ({ ...s, zone: zoneOf(s.name) })) : null;
      if (r.region && r.region.stores) {
        if (r.region.mode != null) mode = r.region.mode; // format de recherche qui marche : gardé
        const names = new Set((seen || []).map((s) => s.name));
        seen = (seen || []).concat(r.region.stores.filter((s) => !names.has(s.name)).map((s) => ({ ...s, zone: rkey })));
      }
      if (r.region && !r.region.stores && mode != null) mode = null; // format devenu invalide : on réessaiera tout
      let merged = null;
      if (seen) {
        // Tous les magasins suivis : alerte pour ceux qui passent en stock (ou en arrivage). Un
        // magasin vu pour la première fois (nouvelle région) est seulement noté.
        const before = Object.fromEntries((prev.stores || []).map((s) => [s.name, s.status]));
        const better = seen.filter((s) => s.name in before && (storeRank[s.status] || 0) > (storeRank[before[s.name]] || 0));
        const byName = Object.fromEntries((prev.stores || []).map((s) => [s.name, s]));
        for (const s of seen) byName[s.name] = s;
        merged = Object.values(byName);
        if (better.length) {
          const head = better.some((s) => s.status === "en_stock") ? "🏬 EN STOCK EN MAGASIN" : "🚚 ARRIVAGE EN MAGASIN";
          for (const zone of new Set(better.map((s) => s.zone))) { // un message par salon de région
            const group = better.filter((s) => s.zone === zone);
            await sendDiscord(`${head} — Fnac\n${name}\n${group.map((s) => `  • Fnac ${s.name} : ${s.text}`).join("\n")}\n${url}`, zone);
          }
          notify(`${head} : ${name} (${better.map((s) => s.name).join(", ")})`);
        }
      } else if (known && r.storeStatus && (storeRank[r.storeStatus] || 0) > (storeRank[prev.storeStatus] || 0)) {
        const head = r.storeStatus === "en_stock" ? "🏬 EN STOCK EN MAGASIN" : "🚚 ARRIVAGE EN MAGASIN";
        await sendDiscord(`${head} — ${r.storeName || "Fnac"}\n${name}\n${r.storeText}\n${url}`, zoneOf(r.storeName));
        notify(`${head} (${r.storeName || "Fnac"}) : ${name}`);
      }
      if (!r.web && !r.source) {
        report.push(`${name} : bloc de disponibilité introuvable (la Fnac a peut-être changé sa page)`);
      }
      state[url] = {
        status: r.status, storeStatus: r.storeStatus, storeName: r.storeName, name,
        web: r.web, storeText: r.storeText, source: r.source, diag: r.diag, stores: merged || prev.stores, at: new Date().toISOString(),
      };
      report.push(`${name}\n   en ligne : ${r.web ? `${r.web} → ${LABEL[r.status] || r.status}` : LABEL[r.status]}\n   ` +
        (r.stores ? r.stores.map((s) => `Fnac ${s.name} : ${s.text}`).join("\n   ") : `${r.storeName || "magasin"} : ${r.storeText || "—"}`) +
        (r.region ? `\n   région ${r.region.key} (${r.region.term}) : ` + (r.region.stores
          ? `${r.region.stores.length} Fnac, ${r.region.stores.filter((s) => s.status === "en_stock").length} en rayon`
          : `recherche impossible (${r.region.error || "?"})`) : ""));
      await sleep(3000 + Math.random() * 4000);
    }
    await chrome.storage.local.set({ state, regionIdx: regionIdx + 1, searchMode: mode });
    return report;
  } finally {
    running = false;
  }
}
