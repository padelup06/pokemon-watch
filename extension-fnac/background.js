// Service worker : toutes les N minutes, ouvre chaque fiche dans un onglet en arrière-plan
// (votre navigateur, votre session, comme si vous la consultiez), lit la disponibilité,
// referme l'onglet, et alerte sur Discord quand un produit devient achetable.
importScripts("extract.js");

const DEFAULTS = {
  webhook: "",
  intervalMinutes: 3,
  products: [
    "https://www.fnac.com/Cartes-a-collectionner-Pokemon-30A-Coffret-Dresseur-d-Elite/a23200296/w-4",
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
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "pokewatch") checkAll(); });
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg === "reschedule") schedule().then(() => reply(true));
  if (msg === "check-now") checkAll().then((r) => reply(r));
  if (msg === "test-discord") sendDiscord("✅ Test Pokémon Watch — Fnac : les alertes arrivent bien ici.").then((r) => reply(r));
  return true;
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function waitForLoad(tabId, timeoutMs = 45000) {
  return new Promise((resolve) => {
    const done = () => { chrome.tabs.onUpdated.removeListener(listener); clearTimeout(t); resolve(); };
    const listener = (id, info) => { if (id === tabId && info.status === "complete") done(); };
    const t = setTimeout(done, timeoutMs);
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function readProduct(url) {
  const tab = await chrome.tabs.create({ url, active: false });
  try {
    await waitForLoad(tab.id);
    await sleep(2500); // laisse la page afficher la disponibilité
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: pokewatchExtract });
    return res.result;
  } catch (e) {
    return { status: "erreur", error: String(e) };
  } finally {
    chrome.tabs.remove(tab.id).catch(() => {});
  }
}

async function sendDiscord(content) {
  const { webhook } = await settings();
  if (!webhook) return "pas de webhook";
  const r = await fetch(webhook, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }) });
  return r.ok ? "ok" : `erreur ${r.status}`;
}

const BUYABLE = ["en_stock", "precommande"];
const LABEL = { en_stock: "✅ EN STOCK", precommande: "🕒 PRÉCOMMANDE", rupture: "❌ rupture", inconnu: "❔ inconnu" };
let running = false;

async function checkAll() {
  if (running) return "déjà en cours";
  running = true;
  try {
    const { products, state } = await settings();
    const report = [];
    for (const url of products) {
      const r = await readProduct(url);
      const prev = state[url] || {};
      if (r.status === "blocked") {
        if (!prev.blockedNotified) {
          await sendDiscord(`⚠️ La Fnac demande une vérification « humain » : ouvrez la page et validez-la.\n${url}`);
          state[url] = Object.assign({}, prev, { blockedNotified: true });
        }
        report.push(`${url} : vérification demandée par la Fnac`);
        continue;
      }
      if (r.status === "erreur") { report.push(`${url} : ${r.error}`); continue; }
      const name = r.name || url;
      // Premier relevé : on enregistre sans alerter.
      if (prev.status && !BUYABLE.includes(prev.status) && BUYABLE.includes(r.status)) {
        const price = r.price ? ` — ${r.price.toFixed(2)} €` : "";
        await sendDiscord(`${LABEL[r.status]} chez Fnac\n${name}${price}\n${url}`);
        chrome.notifications.create({ type: "basic", iconUrl: "icon.png", title: "Pokémon Watch — Fnac", message: `${LABEL[r.status]} : ${name}` });
      }
      if (r.store && prev.store !== r.store && prev.status) {
        await sendDiscord(`🏬 Fnac — magasin : ${r.store}\n${name}\n${url}`);
      }
      state[url] = { status: r.status, name, price: r.price, store: r.store, source: r.source, at: new Date().toISOString() };
      report.push(`${name} : ${LABEL[r.status] || r.status} (via ${r.source || "?"})${r.store ? " · " + r.store : ""}`);
      await sleep(3000 + Math.random() * 4000);
    }
    await chrome.storage.local.set({ state });
    return report;
  } finally {
    running = false;
  }
}
