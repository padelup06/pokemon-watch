// Exécuté DANS la fiche produit Fnac : renvoie ce que la page affiche dans son bloc d'achat.
// Repères relevés sur une vraie fiche (5 octobre 2026) : attributs data-automation-id
//   pdp-buyBox-webAvailability-status    -> « Stock en ligne épuisé », « En stock »…
//   pdp-buyBox-storeShipping-shippingPlace -> magasin choisi sur fnac.com (« Fnac Cannes »)
//   pdp-buyBox-storeAvailability-status  -> « Indisponible en magasin », « Retrait 1h »…
// Les offres de vendeurs tiers (marketplace) et les « Ajouter au panier » des produits
// recommandés sont ignorés : seul le bloc d'achat Fnac compte.
function pokewatchExtract() {
  // Tout doit être DANS cette fonction : Chrome n'injecte dans la page que son code,
  // pas les autres fonctions du fichier.
  const pokewatchClassify = function (text, kind) {
    const t = (text || "").toLowerCase();
    if (!t) return "inconnu";
    if (/épuisé|epuise|indisponible|rupture|plus disponible|non disponible/.test(t)) return "rupture";
    if (/précommande|precommande|pré-commande|disponible le|à paraître|a paraitre/.test(t)) return "precommande";
    if (kind === "store" && /sous \d+|jours|à partir du|a partir du|commande/.test(t)) return "arrivage";
    if (/en stock|disponible|retrait|expédié|expedie|livré|livre/.test(t)) return "en_stock";
    return "inconnu";
  };

  const html = document.documentElement.outerHTML;
  const bodyText = document.body ? document.body.innerText : "";
  if (/captcha-delivery|geo\.captcha|Accès temporairement restreint/i.test(html + bodyText)) {
    return { status: "blocked" };
  }
  const pick = (id) => {
    const el = document.querySelector(`[data-automation-id="${id}"]`);
    return el ? el.textContent.replace(/\s+/g, " ").trim() : null;
  };
  const title = pick("pdp-productInformation-title");
  const h1 = document.querySelector("h1");
  const result = {
    name: title || (h1 ? h1.textContent.trim() : document.title),
    price: null,
    web: pick("pdp-buyBox-webAvailability-status"),
    storeName: pick("pdp-buyBox-storeShipping-shippingPlace"),
    storeText: pick("pdp-buyBox-storeAvailability-status"),
    source: "bloc d'achat",
  };
  result.status = pokewatchClassify(result.web, "web");
  result.storeStatus = result.storeText ? pokewatchClassify(result.storeText, "store") : null;
  // Pas de lecture de prix : dans le bloc d'achat, le prix affiché peut être celui d'un
  // vendeur tiers (ex. 296,10 € chez SuperPromos pour un coffret à 64,99 €).
  if (!result.web) {
    // Page sans bloc d'achat reconnu (mise en page changée ?) : on se rabat sur schema.org.
    result.source = null;
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const d = JSON.parse(s.textContent);
        const offers = [].concat((d && d.offers) || []);
        const av = offers.map((o) => String(o.availability || "").split("/").pop().toLowerCase());
        if (av.some((a) => a === "instock")) { result.status = "en_stock"; result.source = "jsonld"; }
        else if (av.some((a) => a === "outofstock")) { result.status = "rupture"; result.source = "jsonld"; }
      } catch (e) { /* bloc JSON-LD illisible */ }
    }
  }
  return result;
}
