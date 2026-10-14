// King Jouet : stock en ligne et stock de chaque magasin, lus dans TON Chrome, avec les
// mêmes adresses que la fiche produit appelle elle-même pour tout visiteur (relevé le
// 14 octobre 2026) :
//   /api/product/<ref>                                    -> fiche (nom, prix, dispo en ligne)
//   /api/store/search/postal-code?query=<CP>              -> les 5 magasins les plus proches
//   /api/product/<id>/availability-in-stores/<g1_g2_…>    -> « Non disponible », « Stock Limité »…
// Une seule fiche est ouverte par tour ; les fiches suivies sont lues depuis cette page,
// à vitesse humaine, toutes les KJ_EVERY_MIN minutes. Pas de contournement : si King Jouet
// demande une vérification « humain », on s'arrête et on prévient.

const KJ_EVERY_MIN = 5;          // un tour King Jouet toutes les 5 min
const KJ_CPS_PER_ROUND = 2;      // codes postaux de régions ajoutés à chaque tour (à tour de rôle)
const KJ_HOME_CP = "06210";      // Mandelieu : toujours vérifié
// Grandes villes de chaque région (salons Discord de webhooks-regions.txt).
const KJ_REGION_CPS = [
  "75001", "69001", "63000", "38000", "13001", "83000", "84000", "31000", "34000", "33000",
  "87000", "64000", "59000", "80000", "67000", "54000", "51100", "44000", "49000", "35000",
  "29200", "76000", "14000", "21000", "25000", "45000", "37000", "20000", "20200",
];
// Département -> salon de région (le 06 a son propre salon).
const KJ_DEPT_REGION = (() => {
  const m = { "06": "06" };
  const add = (key, depts) => depts.split(" ").forEach((d) => { m[d] = key; });
  add("paca", "04 05 13 83 84");
  add("idf", "75 77 78 91 92 93 94 95");
  add("ara", "01 03 07 15 26 38 42 43 63 69 73 74");
  add("occ", "09 11 12 30 31 32 34 46 48 65 66 81 82");
  add("naq", "16 17 19 23 24 33 40 47 64 79 86 87");
  add("hdf", "02 59 60 62 80");
  add("ge", "08 10 51 52 54 55 57 67 68 88");
  add("pdl", "44 49 53 72 85");
  add("bre", "22 29 35 56");
  add("nor", "14 27 50 61 76");
  add("bfc", "21 25 39 58 70 71 89 90");
  add("cvl", "18 28 36 37 41 45");
  add("cor", "20");
  return m;
})();

// Recherche du site (rayon Cartes à collectionner, mot « pokemon ») toutes les 30 min : alerte
// et suivi automatique des nouvelles fiches 30 ans, sans avoir à copier leur adresse.
const KJ_SEARCH_EVERY_MIN = 30;
const KJ_TRACK = "30\\s*(e|è|ème|eme)?\\s*anniv|30\\s*ans|30th";  // produits suivis automatiquement
const KJ_HOME = "https://www.king-jouet.com/";

const kjRef = (url) => (String(url).match(/\/ref-(\d+)-/) || [])[1] || null;
const isKingJouet = (url) => /^https:\/\/www\.king-jouet\.com\//.test(url);

// Injectée dans une page king-jouet.com : tout doit être DANS la fonction.
async function kingJouetExtract(refs, cps, search = false, track = "") {
  const pause = (ms) => new Promise((r) => setTimeout(r, ms));
  const KJ_SEARCH_PAGE = "/api/search/products/jeux-jouets/jeux-societes/cartes-a-collectionner/page1.htm?search=pokemon";
  const get = async (path) => {
    const r = await fetch(path, { credentials: "include", headers: { Accept: "application/json" }, signal: AbortSignal.timeout(15000) });
    const text = await r.text();
    if (r.status === 403 || /captcha-delivery|Accès temporairement restreint/i.test(text)) throw new Error("BLOCKED");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return JSON.parse(text);
  };
  const classify = (txt, open) => {
    const t = (txt || "").toLowerCase();
    if (open === false || !t || /non disponible|indisponible|rupture|épuisé/.test(t)) return "rupture";
    if (/sous \d|jours|commande|arrivage|bientôt|bientot|réassort/.test(t)) return "arrivage";
    if (/stock|disponible/.test(t)) return "en_stock";
    return "rupture";
  };
  try {
    const stores = {};
    for (const cp of cps) {
      try {
        for (const s of await get(`/api/store/search/postal-code?query=${encodeURIComponent(cp)}`)) {
          if (s && s.guid && !stores[s.guid]) stores[s.guid] = { name: s.label, cp: String(s.postalCode || "") };
        }
      } catch (e) { if (String(e).includes("BLOCKED")) throw e; }
      await pause(700 + Math.random() * 600);
    }
    // Recherche du site : fiches Pokémon du rayon cartes (format lu sans hypothèse : toute
    // fiche dont une valeur contient « /ref-<numéro>- … .htm »).
    let found = null, searchKeys = null;
    if (search) {
      found = [];
      const seenRef = new Set();
      for (let page = 1; page <= 4; page++) {
        let data;
        try { data = await get(KJ_SEARCH_PAGE.replace("page1.htm", `page${page}.htm`)); }
        catch (e) { if (String(e).includes("BLOCKED")) throw e; break; }
        const walk = (node) => {
          if (Array.isArray(node)) return node.forEach(walk);
          if (!node || typeof node !== "object") return;
          const flat = JSON.stringify(node);
          const m = flat.match(/\/[^"\\]*ref-(\d+)-[^"\\]*\.htm/);
          const name = node.label || node.name || node.title || node.libelle;
          if (m && typeof name === "string" && Object.values(node).some((v) => typeof v === "string" && /ref-\d+-/.test(v))) {
            if (!searchKeys) searchKeys = Object.keys(node).slice(0, 25);
            if (!seenRef.has(m[1])) { seenRef.add(m[1]); found.push({ ref: m[1], name, path: m[0] }); }
            return;
          }
          Object.values(node).forEach(walk);
        };
        walk(data);
        if (page === 1 && !found.length && data && typeof data === "object") {
          // Format inattendu : de quoi l'adapter (clés et début de la réponse).
          searchKeys = [...Object.keys(data), JSON.stringify(data).slice(0, 400)];
        }
        if (!data || !data.nbPages || page >= data.nbPages) break;
        await pause(800 + Math.random() * 700);
      }
      if (track) {
        const re = new RegExp(track, "i");
        for (const f of found) if (re.test(f.name) && !refs.includes(f.ref)) refs.push(f.ref);
      }
    }
    const guids = Object.keys(stores);
    const items = [];
    for (const ref of refs) {
      try {
        const p = await get(`/api/product/${ref}`);
        const av = p.availability || {};
        const res = {
          ref, name: p.label || null, ean: p.ean || null,
          price: p.price && typeof p.price.price === "number" ? p.price.price : null,
          image: (p.images || [])[0] || null,
          status: av.isAvailableOnWeb ? (p.isPreorder ? "precommande" : "en_stock") : "rupture",
          stores: [],
        };
        for (let i = 0; p.id && i < guids.length; i += 5) {
          const chunk = guids.slice(i, i + 5);
          for (const a of await get(`/api/product/${p.id}/availability-in-stores/${chunk.join("_")}`)) {
            const st = stores[a.storeGuid];
            if (st) res.stores.push({ id: a.storeGuid, name: st.name, cp: st.cp, text: a.availability || "?", status: classify(a.availability, a.isStoreAvailable) });
          }
          await pause(500 + Math.random() * 500);
        }
        items.push(res);
      } catch (e) {
        if (String(e).includes("BLOCKED")) throw e;
        items.push({ ref, error: String(e) });
      }
      await pause(900 + Math.random() * 900);
    }
    return { items, found, searchKeys };
  } catch (e) {
    return String(e).includes("BLOCKED") ? { blocked: true } : { error: String(e) };
  }
}

let kjRunning = false;

async function checkKingJouet(force = false) {
  const { products = [] } = await settings();
  let { kjState = {}, kjLast = 0, kjIdx = 0, kjBlock = null, kjTracked = {}, kjSeen = null, kjSearchLast = 0 } =
    await chrome.storage.local.get(["kjState", "kjLast", "kjIdx", "kjBlock", "kjTracked", "kjSeen", "kjSearchLast"]);
  const manual = products.filter(isKingJouet).filter(kjRef);
  const urls = [...new Set(manual.concat(Object.values(kjTracked)))];
  // Pas de fiche King Jouet dans la liste : rien à faire (la recherche démarre dès qu'il y en a une).
  if (!manual.length || kjRunning) return [];
  if (!force && Date.now() - kjLast < KJ_EVERY_MIN * 60000) return [];
  if (kjBlock && !force && Date.now() < kjBlock.until) {
    return [`King Jouet en pause jusqu'à ${new Date(kjBlock.until).toLocaleTimeString("fr-FR")} (vérification « humain » demandée).`];
  }
  kjRunning = true;
  const report = [];
  try {
    await chrome.storage.local.set({ kjLast: Date.now() });
    const cps = [KJ_HOME_CP, ...[...Array(KJ_CPS_PER_ROUND).keys()].map((i) => KJ_REGION_CPS[(kjIdx + i) % KJ_REGION_CPS.length])];
    // Une vraie fiche King Jouet ouverte en arrière-plan : les lectures partent de cette page.
    const search = force || Date.now() - kjSearchLast >= KJ_SEARCH_EVERY_MIN * 60000;
    const tab = await chrome.tabs.create({ url: urls[0] || KJ_HOME, active: false });
    let out;
    try {
      await waitForLoad(tab.id);
      await sleep(1500);
      const res = await Promise.race([
        chrome.scripting.executeScript({ target: { tabId: tab.id }, func: kingJouetExtract, args: [urls.map(kjRef), cps, search, KJ_TRACK] }),
        sleep(180000).then(() => "timeout"),  // au plus 3 min pour un tour
      ]);
      if (res === "timeout") return ["King Jouet : lecture trop longue (3 min), nouvel essai au prochain tour"];
      out = res && res[0] && res[0].result;
    } finally {
      chrome.tabs.remove(tab.id).catch(() => {});
    }
    if (!out || out.blocked) {
      const pauseMin = kjBlock ? Math.min(kjBlock.pauseMin * 2, 120) : 30;
      if (!kjBlock) {
        await sendDiscord(`⚠️ King Jouet demande une vérification « humain ». Surveillance King Jouet en pause ${pauseMin} min.\n` +
          `Ouvrez cette fiche dans Chrome et validez la vérification si elle s'affiche :\n${urls[0]}`);
      }
      await chrome.storage.local.set({ kjBlock: { until: Date.now() + pauseMin * 60000, pauseMin } });
      return [`King Jouet : ${out && out.error ? out.error : "vérification demandée"} — pause de ${pauseMin} min`];
    }
    if (out.error) return [`King Jouet : ${out.error}`];
    if (kjBlock) {
      await chrome.storage.local.remove("kjBlock");
      await sendDiscord("✅ King Jouet de nouveau lisible : surveillance reprise.");
    }
    if (out.found) {
      // Nouvelles fiches Pokémon chez King Jouet (premier passage : on note l'existant).
      const re = new RegExp(KJ_TRACK, "i");
      const first = kjSeen === null;
      const seen = new Set(kjSeen || []);
      let tracked = 0;
      for (const f of out.found) {
        const url = new URL(f.path, KJ_HOME).href;
        if (re.test(f.name) && !kjTracked[f.ref]) { kjTracked[f.ref] = url; tracked++; }
        if (!seen.has(f.ref)) {
          seen.add(f.ref);
          if (!first && re.test(f.name)) {
            await sendDiscord(`🆕 NOUVELLE FICHE chez King Jouet : ${f.name}\n${url}`);
            notify(`Nouvelle fiche King Jouet : ${f.name}`);
          }
        }
      }
      await chrome.storage.local.set({ kjSeen: [...seen], kjTracked, kjSearchLast: Date.now() });
      report.push(`Recherche King Jouet : ${out.found.length} fiche(s) Pokémon (cartes), ${Object.keys(kjTracked).length} fiche(s) 30 ans suivie(s) automatiquement` +
        (out.found.length ? "" : ` — format des résultats à vérifier (clés : ${(out.searchKeys || []).join(", ") || "aucune fiche reconnue"})`));
    }
    const rank = { rupture: 0, arrivage: 1, en_stock: 2 };
    for (const it of out.items) {
      const url = urls.find((u) => kjRef(u) === it.ref) || kjTracked[it.ref] || KJ_HOME;
      if (it.error) { report.push(`King Jouet ${it.ref} : ${it.error}`); continue; }
      const prev = kjState[it.ref] || {};
      const known = Boolean(prev.status); // premier relevé : on note sans alerter
      if (known && !["en_stock", "precommande"].includes(prev.status) && ["en_stock", "precommande"].includes(it.status)) {
        const price = it.price ? ` — ${it.price.toFixed(2)} €` : "";
        await sendDiscord(`${LABEL[it.status]} EN LIGNE chez King Jouet\n${it.name}${price}\n${url}`, null, it.image);
        notify(`${LABEL[it.status]} en ligne chez King Jouet : ${it.name}`);
      }
      const before = prev.stores || {};
      const better = it.stores.filter((s) => s.id in before && rank[s.status] > (rank[before[s.id].status] || 0));
      const zoneOfStore = (s) => KJ_DEPT_REGION[s.cp.slice(0, 2)] || null;
      for (const zone of new Set(better.map(zoneOfStore))) {
        const group = better.filter((s) => zoneOfStore(s) === zone);
        const head = group.some((s) => s.status === "en_stock") ? "🏬 EN STOCK EN MAGASIN" : "🚚 ARRIVAGE EN MAGASIN";
        await sendDiscord(`${head} — King Jouet\n${it.name}\n${group.map((s) => `  • ${s.name} : ${s.text}`).join("\n")}\n${url}`, zone, it.image);
        notify(`${head} King Jouet : ${it.name} (${group.map((s) => s.name).join(", ")})`);
      }
      const stores = { ...before };
      for (const s of it.stores) stores[s.id] = { name: s.name, cp: s.cp, text: s.text, status: s.status };
      kjState[it.ref] = { name: it.name, status: it.status, price: it.price, stores, at: new Date().toISOString() };
      const near = it.stores.filter((s) => ["06", "paca"].includes(zoneOfStore(s)));
      report.push(`King Jouet — ${it.name}\n   en ligne : ${LABEL[it.status]}\n   ` +
        (near.map((s) => `${s.name} : ${s.text}`).join("\n   ") || "magasins : —") +
        `\n   (${Object.keys(stores).length} magasins King Jouet suivis en France)`);
    }
    await chrome.storage.local.set({ kjState, kjIdx: kjIdx + KJ_CPS_PER_ROUND });
    return report;
  } catch (e) {
    return [`King Jouet : ${e}`];
  } finally {
    kjRunning = false;
  }
}
