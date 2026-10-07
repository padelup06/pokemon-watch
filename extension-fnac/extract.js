// Exécuté DANS la fiche produit Fnac : renvoie ce que la page affiche dans son bloc d'achat.
// Repères relevés sur une vraie fiche (5 octobre 2026) : attributs data-automation-id
//   pdp-buyBox-webAvailability-status    -> « Stock en ligne épuisé », « En stock »…
//   pdp-buyBox-storeShipping-shippingPlace -> magasin choisi sur fnac.com (« Fnac Cannes »)
//   pdp-buyBox-storeAvailability-status  -> « Indisponible en magasin », « Retrait 1h »…
// Les offres de vendeurs tiers (marketplace) et les « Ajouter au panier » des produits
// recommandés sont ignorés : seul le bloc d'achat Fnac compte.
async function pokewatchExtract(region = null, searchMode = null) {
  // Tout doit être DANS cette fonction : Chrome n'injecte dans la page que son code,
  // pas les autres fonctions du fichier.
  const pokewatchClassify = function (text, kind) {
    const t = (text || "").toLowerCase();
    if (!t) return "inconnu";
    // « En stock vendeur partenaire » : vendu par un tiers (marketplace), pas par la Fnac.
    if (kind === "web" && /partenaire|marketplace|vendeur tiers/.test(t)) return "rupture";
    if (/épuisé|epuise|indisponible|rupture|plus disponible|non disponible/.test(t)) return "rupture";
    if (/précommande|precommande|pré-commande|disponible le|à paraître|a paraitre/.test(t)) return "precommande";
    if (kind === "store" && /sous \d+|jours|à partir du|a partir du|commande/.test(t)) return "arrivage";
    if (/en stock|disponible|retrait|expédié|expedie|livré|livre/.test(t)) return "en_stock";
    return "inconnu";
  };

  // Liste « Retirer en magasin » : nom de chaque Fnac et « En rayon » / « Indisponible en rayon ».
  const parseStores = function (htmlText) {
    const pop = new DOMParser().parseFromString(htmlText, "text/html");
    const list = [];
    for (const li of pop.querySelectorAll("li.liStore")) {
      const name = (li.querySelector(".storeName") || {}).textContent;
      const col = li.querySelector('[class*="liCol_2"]');
      if (!name || !col) continue;
      const text = col.textContent.replace(/\s+/g, " ").trim();
      // La Fnac écrit « En rayon » (attribut data-available, ColorStatus_2) ou « Indisponible en rayon ».
      let status = pokewatchClassify(text, "store");
      if (status !== "rupture" && (li.hasAttribute("data-available") || /en rayon/i.test(text))) status = "en_stock";
      list.push({ name: name.trim(), text, status });
    }
    return list;
  };

  const html = document.documentElement.outerHTML;
  const bodyText = document.body ? document.body.innerText : "";
  if (/captcha-delivery|geo\.captcha|Accès temporairement restreint/i.test(html + bodyText)) {
    return { status: "blocked" };
  }
  let doc = document;
  const pick = (id) => {
    const el = doc.querySelector(`[data-automation-id="${id}"]`);
    return el ? el.textContent.replace(/\s+/g, " ").trim() : null;
  };
  // Le bloc d'achat peut s'afficher après le chargement : on l'attend jusqu'à 10 s.
  for (let i = 0; i < 20 && !pick("pdp-buyBox-webAvailability-status"); i++) {
    await new Promise((r) => setTimeout(r, 500));
  }
  let fromServer = false;
  if (!pick("pdp-buyBox-webAvailability-status")) {
    // Dans un onglet en arrière-plan, la Fnac n'affiche pas toujours son bloc d'achat.
    // Il figure pourtant dans la page telle que le site l'envoie : on relit donc cette
    // même page (même navigateur, mêmes cookies, donc même magasin choisi).
    try {
      const r = await fetch(location.href, { credentials: "include" });
      const text = await r.text();
      if (r.ok && !/captcha-delivery|geo\.captcha/i.test(text)) {
        const parsed = new DOMParser().parseFromString(text, "text/html");
        if (parsed.querySelector('[data-automation-id="pdp-buyBox-webAvailability-status"]')) {
          doc = parsed;
          fromServer = true;
        }
      }
    } catch (e) { /* tant pis : on se rabat sur les offres plus bas */ }
  }
  const title = pick("pdp-productInformation-title");
  const h1 = document.querySelector("h1");
  const result = {
    name: title || (h1 ? h1.textContent.trim() : document.title),
    price: null,
    web: pick("pdp-buyBox-webAvailability-status"),
    storeName: pick("pdp-buyBox-storeShipping-shippingPlace"),
    storeText: pick("pdp-buyBox-storeAvailability-status"),
    source: fromServer ? "bloc d'achat (page relue)" : "bloc d'achat",
  };
  result.status = pokewatchClassify(result.web, "web");
  result.storeStatus = result.storeText ? pokewatchClassify(result.storeText, "store") : null;
  // Pas de lecture de prix : dans le bloc d'achat, le prix affiché peut être celui d'un
  // vendeur tiers (ex. 296,10 € chez SuperPromos pour un coffret à 64,99 €).

  // Disponibilité dans chaque Fnac proche : même appel que le panneau « Retirer en magasin »
  // de la fiche (liste des magasins autour du magasin choisi, avec « Disponible / Indisponible
  // en rayon »).
  result.stores = null;
  try {
    const prid = (location.pathname.match(/\/a(\d+)/) || [])[1];
    const m = document.documentElement.outerHTML.match(/storeid["'=:\s]+(\d+)/i);
    const storeid = (m && m[1] !== "0" && m[1]) || "173"; // 173 = Fnac Cannes (magasin choisi le 6/10)
    if (prid) {
      const formid = crypto.randomUUID().replace(/-/g, "");
      const r = await fetch(`/nav/api/storepickup/storepickuppopin?prid=${prid}&storeid=${storeid}` +
        `&formid=${formid}&offerref=00000000-0000-0000-0000-000000000000&catalog=1`, { credentials: "include" });
      if (r.ok) {
        const list = parseStores(await r.text());
        if (list.length) result.stores = list;
      }
      // Magasins d'une autre région : même recherche que la case « Trouver un magasin » du panneau
      // (format relevé par l'utilisateur le 7/10 : ville + coordonnées GPS, formulaire classique).
      if (region) {
        const params = new URLSearchParams({
          inputValue: region.term.toLowerCase(), latitude: String(region.lat), longitude: String(region.lon),
          prid, catalog: "1", onShlef: "false", isRetreatOneHour: "false", formId: formid,
          offerref: "00000000-0000-0000-0000-000000000000",
        });
        result.region = { key: region.key, term: region.term, stores: null, mode: 0 };
        const rr = await fetch("/nav/api/StorePickup/SearchStore", {
          method: "POST", body: params.toString(), credentials: "include",
          headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest" },
        });
        const list = rr.ok ? parseStores(await rr.text()) : [];
        if (list.length) result.region.stores = list;
        else result.region.error = `HTTP ${rr.status}, aucun magasin dans la réponse`;
      }
    }
  } catch (e) { /* le bloc d'achat suffit si cet appel échoue */ }

  // Diagnostic affiché dans la fenêtre de l'extension.
  const offers = [];
  for (const sc of doc.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const d = JSON.parse(sc.textContent);
      for (const node of [].concat(d && d["@graph"] ? d["@graph"] : d)) {
        for (const o of [].concat((node && node.offers) || [])) {
          for (const sub of [].concat(o.offers || o)) {
            const seller = sub.seller ? (sub.seller.name || String(sub.seller)) : "";
            offers.push({ seller, price: sub.price || sub.lowPrice || null,
                          availability: String(sub.availability || "").split("/").pop() });
          }
        }
      }
    } catch (e) { /* bloc JSON-LD illisible */ }
  }
  // Photo du produit (affichée sous les alertes Discord).
  const og = doc.querySelector('meta[property="og:image"]') || document.querySelector('meta[property="og:image"]');
  result.image = og && /^https?:/.test(og.content) ? og.content : null;
  if (!result.image) {
    for (const sc of doc.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const d = JSON.parse(sc.textContent);
        for (const node of [].concat(d && d["@graph"] ? d["@graph"] : d)) {
          let img = node && node.image;
          if (Array.isArray(img)) img = img[0];
          if (img && typeof img === "object") img = img.url || img.contentUrl;
          if (typeof img === "string" && /^https?:/.test(img)) { result.image = img; break; }
        }
      } catch (e) { /* bloc illisible */ }
      if (result.image) break;
    }
  }
  if (!result.image && result.name) {
    // Repli : photo de la galerie dont la légende reprend le nom du produit.
    const key = result.name.toLowerCase().slice(0, 25);
    for (const img of document.querySelectorAll("img[src], img[data-src]")) {
      const src = img.getAttribute("src") || img.getAttribute("data-src") || "";
      if (/^https?:/.test(src) && (img.alt || "").toLowerCase().includes(key)) { result.image = src; break; }
    }
  }

  result.diag = {
    url: location.href,
    titre: document.title.slice(0, 80),
    reperes: document.querySelectorAll("[data-automation-id]").length,
    blocAchat: Boolean(result.web),
    offres: offers.slice(0, 6),
  };

  if (!result.web) {
    // Pas de bloc d'achat : on ne conclut « en stock » que pour une offre vendue par la Fnac
    // elle-même, jamais pour un vendeur tiers (marketplace).
    result.source = null;
    const fnac = offers.filter((o) => /fnac/i.test(o.seller));
    const av = fnac.map((o) => o.availability.toLowerCase());
    if (av.includes("instock")) { result.status = "en_stock"; result.source = "jsonld (vendu par Fnac)"; }
    else if (av.includes("outofstock")) { result.status = "rupture"; result.source = "jsonld (vendu par Fnac)"; }
    // Seuls des vendeurs tiers : la Fnac elle-même ne le vend pas, donc rupture chez la Fnac.
    // Dès qu'elle le remet en vente, son offre apparaît et l'alerte part.
    else if (offers.length) { result.status = "rupture"; result.source = "pas vendu par la Fnac, seulement par des vendeurs tiers"; }
    else { result.status = "inconnu"; }
  } else if (["en_stock", "precommande"].includes(result.status) && offers.length &&
             !offers.some((o) => /fnac/i.test(o.seller) && /instock|preorder|presale/i.test(o.availability))) {
    // Quand la Fnac n'a plus le produit, son bloc d'achat affiche l'offre d'un vendeur
    // partenaire (« En stock ») : ce n'est pas un retour en stock chez la Fnac.
    const tiers = offers.filter((o) => !/fnac/i.test(o.seller) && /instock/i.test(o.availability));
    result.status = "rupture";
    result.source = "en stock seulement chez des vendeurs partenaires";
    result.web = `${result.web} — vendeur partenaire` +
      (tiers.length ? ` (${tiers.map((o) => `${o.seller} ${o.price || "?"} €`).join(", ")})` : "") + ", pas la Fnac";
  }
  return result;
}
