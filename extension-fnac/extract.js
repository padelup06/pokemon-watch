// Exécuté DANS la fiche produit Fnac : renvoie ce que la page dit de la disponibilité.
// Ordre : données schema.org (JSON-LD), puis textes de la page.
function pokewatchExtract() {
  const text = (document.body ? document.body.innerText : "").replace(/\s+/g, " ");
  const html = document.documentElement.outerHTML;
  if (/captcha-delivery|geo\.captcha|Accès temporairement restreint/i.test(html + text)) {
    return { status: "blocked" };
  }
  const result = { status: "inconnu", name: null, price: null, source: null, store: null };
  // Retrait / stock en magasin, tel qu'affiché sur la fiche (magasin choisi sur fnac.com).
  const m = text.match(/(Disponible|En stock|Retrait[^.]{0,40}?)\s+(?:dans votre magasin|en magasin|au magasin)[^.]{0,80}/i);
  if (m) result.store = m[0].slice(0, 140);
  const walk = (node, out) => {
    if (Array.isArray(node)) node.forEach((n) => walk(n, out));
    else if (node && typeof node === "object") {
      out.push(node);
      Object.values(node).forEach((v) => walk(v, out));
    }
  };
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    let data;
    try { data = JSON.parse(s.textContent); } catch (e) { continue; }
    const nodes = [];
    walk(data, nodes);
    for (const n of nodes) {
      const types = [].concat(n["@type"] || []).map((t) => String(t).toLowerCase());
      if (!types.includes("product")) continue;
      result.name = result.name || n.name || null;
      const offers = [];
      walk(n.offers || [], offers);
      const av = offers.map((o) => String(o.availability || "").split("/").pop().toLowerCase()).filter(Boolean);
      const price = offers.map((o) => o.price || o.lowPrice).find(Boolean);
      if (price) result.price = parseFloat(String(price).replace(",", "."));
      if (av.some((a) => ["instock", "limitedavailability", "onlineonly", "instoreonly"].includes(a))) {
        return Object.assign(result, { status: "en_stock", source: "jsonld" });
      }
      if (av.some((a) => ["preorder", "presale", "backorder"].includes(a))) {
        return Object.assign(result, { status: "precommande", source: "jsonld" });
      }
      if (av.length) Object.assign(result, { status: "rupture", source: "jsonld" });
    }
  }
  if (!result.name) {
    const h1 = document.querySelector("h1");
    result.name = h1 ? h1.innerText.trim() : document.title;
  }
  if (result.status === "inconnu") {
    if (/(Épuisé|Rupture de stock|Indisponible|Plus disponible|M'alerter|Me prévenir)/i.test(text)) {
      Object.assign(result, { status: "rupture", source: "texte" });
    } else if (/Ajouter au panier/i.test(text)) {
      Object.assign(result, { status: "en_stock", source: "texte" });
    }
  }
  return result;
}
