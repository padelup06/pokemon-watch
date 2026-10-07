"""Extraction de la disponibilité d'un produit depuis le HTML d'une fiche produit.

Stratégie, par ordre de fiabilité :
1. Données structurées schema.org (JSON-LD `Product` / `Offer.availability`),
   exposées par la quasi-totalité des sites e-commerce pour le SEO.
2. Balises meta (`product:availability`, `og:availability`, itemprop).
3. Mots-clés propres à l'enseigne ("Ajouter au panier", "Rupture de stock"...).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser

IN_STOCK = "en_stock"
OUT_OF_STOCK = "rupture"
PREORDER = "precommande"
UNKNOWN = "inconnu"

_SCHEMA_AVAILABILITY = {
    "instock": IN_STOCK,
    "instoreonly": IN_STOCK,
    "onlineonly": IN_STOCK,
    "limitedavailability": IN_STOCK,
    "outofstock": OUT_OF_STOCK,
    "soldout": OUT_OF_STOCK,
    "discontinued": OUT_OF_STOCK,
    "preorder": PREORDER,
    "presale": PREORDER,
    "backorder": PREORDER,
}


@dataclass
class Availability:
    status: str = UNKNOWN
    name: str | None = None
    price: float | None = None
    source: str = ""  # quelle méthode a tranché : jsonld / meta / keywords
    image: str | None = None  # photo du produit (affichée sous les alertes Discord)


class _PageScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.jsonld: list[str] = []
        self.meta: dict[str, str] = {}
        self.title: str | None = None
        self._in_jsonld = False
        self._in_title = False
        self._buf: list[str] = []
        self.text: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script":
            if a.get("type", "").lower() == "application/ld+json":
                self._in_jsonld = True
                self._buf = []
            else:
                self._skip_depth += 1
        elif tag == "style":
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("meta", "link"):
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            val = a.get("content") or a.get("href") or ""
            if key and val:
                self.meta.setdefault(key, val)

    def handle_endtag(self, tag):
        if tag == "script":
            if self._in_jsonld:
                self.jsonld.append("".join(self._buf))
                self._in_jsonld = False
            elif self._skip_depth:
                self._skip_depth -= 1
        elif tag == "style" and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_jsonld:
            self._buf.append(data)
        elif self._in_title:
            self.title = (self.title or "") + data
        elif not self._skip_depth:
            self.text.append(data)


def _walk(node):
    """Parcourt récursivement un document JSON-LD (gère @graph, listes...)."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _types(node: dict) -> set[str]:
    t = node.get("@type", [])
    return {x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}


def _norm_schema(value: str) -> str:
    key = value.rsplit("/", 1)[-1].strip().lower()
    return _SCHEMA_AVAILABILITY.get(key, UNKNOWN)


def _to_price(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ".").replace(" ", "").replace("€", "").strip())
    except ValueError:
        return None


def _seller_name(offer: dict) -> str:
    seller = offer.get("seller")
    if isinstance(seller, dict):
        return str(seller.get("name") or "")
    return str(seller or "")


def _image(value) -> str | None:
    """Champ schema.org « image » : texte, liste, ou objet ImageObject."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl")
    return value if isinstance(value, str) and value.startswith("http") else None


def _jsonld_image(blocks: list[str]) -> str | None:
    for raw in blocks:
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _walk(data):
            if "product" in _types(node) and _image(node.get("image")):
                return _image(node.get("image"))
    return None


def _from_jsonld(
    blocks: list[str], seller: re.Pattern | None = None, keep_unnamed: bool = True
) -> Availability | None:
    for raw in blocks:
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _walk(data):
            if "product" not in _types(node):
                continue
            offers = node.get("offers")
            offer_list = offers if isinstance(offers, list) else [offers] if offers else []
            # AggregateOffer : les offres détaillées sont dans "offers"
            expanded = []
            for o in offer_list:
                if isinstance(o, dict) and isinstance(o.get("offers"), list):
                    expanded.extend(o["offers"])
                expanded.append(o)
            statuses = []
            price = None
            others = 0
            sellers: list[str] = []
            for o in expanded:
                if not isinstance(o, dict):
                    continue
                # seller : seules comptent les offres de l'enseigne elle-même (pas sa marketplace) ;
                # une offre sans vendeur indiqué est gardée, sauf si keep_unnamed est faux.
                name = _seller_name(o)
                if seller is not None and o.get("availability"):
                    if (name and not seller.search(name)) or (not name and not keep_unnamed):
                        others += 1
                        continue
                    sellers.append(name or "non indiqué")
                if o.get("availability"):
                    statuses.append(_norm_schema(str(o["availability"])))
                price = price or _to_price(o.get("price") or o.get("lowPrice"))
            if not statuses:
                # Leclerc, produit épuisé : plus d'« availability », seulement un AggregateOffer à 0 offre.
                if any(isinstance(o, dict) and str(o.get("offerCount", "")) == "0" for o in expanded):
                    return Availability(OUT_OF_STOCK, node.get("name"), None, "jsonld (aucune offre)")
                if others:  # uniquement des vendeurs partenaires : rupture chez l'enseigne
                    return Availability(OUT_OF_STOCK, node.get("name"), None, "jsonld (vendeurs partenaires seulement)")
                continue
            # Une seule offre dispo suffit pour considérer le produit achetable.
            for wanted in (IN_STOCK, PREORDER, OUT_OF_STOCK):
                if wanted in statuses:
                    source = f"jsonld (vendeur : {', '.join(dict.fromkeys(sellers))})" if sellers else "jsonld"
                    return Availability(wanted, node.get("name"), price, source)
    return None


def _from_meta(meta: dict[str, str]) -> Availability | None:
    for key in ("product:availability", "og:availability", "availability"):
        if key in meta:
            v = meta[key].lower().replace(" ", "")
            status = _norm_schema(v)
            if status == UNKNOWN:
                status = {"instock": IN_STOCK, "oos": OUT_OF_STOCK, "pending": PREORDER}.get(v, UNKNOWN)
            if status != UNKNOWN:
                return Availability(
                    status,
                    meta.get("og:title"),
                    _to_price(meta.get("product:price:amount") or meta.get("price")),
                    "meta",
                )
    return None


def _from_keywords(text: str, in_kw: list[str], out_kw: list[str]) -> Availability | None:
    low = re.sub(r"\s+", " ", text).lower()
    # Les mots-clés de rupture priment : un bouton "Ajouter au panier" peut
    # rester dans le DOM (désactivé) même quand le produit est épuisé.
    if any(k.lower() in low for k in out_kw):
        return Availability(OUT_OF_STOCK, source="keywords")
    if any(k.lower() in low for k in in_kw):
        return Availability(IN_STOCK, source="keywords")
    return None


def parse_availability(
    html: str,
    in_stock_keywords: list[str] | None = None,
    out_of_stock_keywords: list[str] | None = None,
    seller: re.Pattern | None = None,
    seller_marker: re.Pattern | None = None,
) -> Availability:
    scanner = _PageScanner()
    scanner.feed(html)
    # seller_marker : texte visible prouvant que l'enseigne vend elle-même (« Vendu et expédié
    # par Cdiscount ») ; sans lui, une offre schema.org sans vendeur nommé ne compte pas.
    keep_unnamed = True
    if seller_marker is not None:
        keep_unnamed = bool(seller_marker.search(re.sub(r"\s+", " ", " ".join(scanner.text))))
    result = (
        _from_jsonld(scanner.jsonld, seller, keep_unnamed)
        or _from_meta(scanner.meta)
        or _from_keywords(" ".join(scanner.text), in_stock_keywords or [], out_of_stock_keywords or [])
        or Availability()
    )
    if not result.name:
        result.name = (scanner.meta.get("og:title") or scanner.title or "").strip() or None
    og = scanner.meta.get("og:image") or ""
    result.image = _jsonld_image(scanner.jsonld) or (og if og.startswith("http") else None)
    return result
