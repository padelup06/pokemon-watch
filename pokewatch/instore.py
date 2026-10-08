"""Stock magasin par magasin.

JouéClub et La Grande Récré tournent sur la même plateforme e-commerce
(Proximis / RBS Change). Le bloc « Retirer en magasin » de leurs fiches produit
interroge l'API `ajax.V1.php/fr_FR/Rbs/Storeshipping/Store/`, qui renvoie les
magasins autour d'un point avec, pour chacun, l'état du stock du produit.
On rejoue cette requête, avec la session (cookies + jeton CSRF) obtenue en
chargeant la fiche produit.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .fetch import USER_AGENTS, FetchError

# Enseignes dont le stock magasin est lisible via la plateforme Proximis.
PROXIMIS_RETAILERS = {"joueclub", "lagranderecre"}
# Enseignes dont le stock magasin passe par le navigateur (site protégé par un anti-robot).
BROWSER_STORE_RETAILERS = {"cultura"}
# Enseignes dont l'API magasin tient compte de la quantité demandée (vérifié le 5/10/2026 :
# La Grande Récré oui — 2/13/19 selon les magasins ; JouéClub non — « 50+ » partout).
QUANTITY_RETAILERS = {"lagranderecre"}
STORE_RETAILERS = PROXIMIS_RETAILERS | BROWSER_STORE_RETAILERS

_UA = USER_AGENTS[0]
_HTML_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


@dataclass
class StoreStock:
    store_id: str
    name: str
    distance_km: float | None
    in_stock: bool
    label: str  # libellé du site : "En stock", "En rupture", "Stock limité"...
    url: str | None = None
    # Pas en rayon mais commandable en retrait dans ce magasin (envoi depuis l'entrepôt) :
    # c'est le signal d'un arrivage.
    incoming: bool = False
    # Nombre estimé d'exemplaires (voir proximis_estimate_quantities) ; None = non estimé.
    qty: int | None = None
    qty_capped: bool = False  # True : au moins `qty`, la recherche s'est arrêtée au plafond
    zone: str = ""  # zone (ex. "06") dont la recherche a trouvé ce magasin

    @property
    def code(self) -> int:
        return 1 if self.in_stock else 2 if self.incoming else 0


def proximis_restock(html: str) -> str | None:
    """Réassort planifié affiché par JouéClub / La Grande Récré (champ restockPlanned)."""
    m = re.search(r'"restockPlanned":true[^{}]*?"formattedRestockDate":"([^"]*)"', html)
    if m:
        return m.group(1) or "date non communiquée"
    m = re.search(r'"restockDescription":"([^"]+)"', html)
    return m.group(1) if m else None


def geocode(query: str) -> tuple[float, float]:
    """Code postal ou ville -> (latitude, longitude), via le géocodeur officiel de l'IGN."""
    q = urllib.parse.urlencode({"q": query, "limit": 1, "index": "address"})
    req = urllib.request.Request(f"https://data.geopf.fr/geocodage/search?{q}", headers={"User-Agent": _UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                features = json.load(r).get("features") or []
            break
        except Exception as e:
            if attempt == 2:
                raise FetchError(f"géocodage impossible pour {query!r} : {e}") from e
            time.sleep(2)
    if not features:
        raise FetchError(f"lieu introuvable : {query!r}")
    lon, lat = features[0]["geometry"]["coordinates"]
    return lat, lon


def _context(html: str, ean: str | None = None) -> tuple[dict, str]:
    """(contexte de la page, code article). `ean` : code-barres connu du produit, qui sert
    de code article quand sa fiche n'est pas (ou plus) publiée : l'API magasin le connaît
    quand même (vérifié le 6/10 chez La Grande Récré)."""
    ctx = {}
    for key in ("websiteId", "sectionId", "pageId"):
        m = re.search(rf'"{key}"\s*:\s*(\d+)', html)
        if not m:
            raise FetchError(f"{key} introuvable dans la page")
        ctx[key] = int(m.group(1))
    # Une fiche dépubliée redirige vers une page catégorie, qui contient les blocs de stock
    # d'autres produits : on exige la fiche produit (schema.org) et on prend le bloc de stock
    # dont le code correspond au sien.
    blocks = re.findall(r'"stock":\{"showStoreAvailability":true[^{}]*?"sku":"([^"]+)"(?:[^{}]*?"ean13":"([^"]*)")?', html)
    if ean:
        # Code-barres connu : c'est lui qui désigne le produit, jamais un autre produit de la
        # page (carrousel, page catégorie après dépublication).
        for sku, code in blocks:
            if ean in (sku, code):
                return ctx, sku
        return ctx, ean
    product_skus = set(re.findall(r'"@type"\s*:\s*"Product".*?"sku"\s*:\s*"([^"]+)"', html, re.S)[:1])
    if not product_skus:
        raise FetchError("fiche produit non publiée (redirection)")
    for sku, code in blocks:
        if sku in product_skus or code in product_skus:
            return ctx, sku
    raise FetchError("ce produit n'a pas de disponibilité en magasin")


# Une session (cookies + jeton CSRF) par site, réutilisée : ouvrir une nouvelle session à
# chaque produit fait répondre l'API en 502 quand on l'interroge souvent (constaté chez
# JouéClub depuis une connexion personnelle).
_sessions: dict[str, tuple] = {}
_sessions_lock = threading.Lock()


def _session(origin: str, page_url: str, fresh: bool = False):
    """(opener, cookies, html de la page si elle vient d'être chargée)."""
    with _sessions_lock:
        if not fresh and origin in _sessions:
            opener, jar = _sessions[origin]
            return opener, {c.name: c.value for c in jar}, None
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    with opener.open(urllib.request.Request(page_url, headers=_HTML_HEADERS), timeout=20) as r:
        html = r.read().decode("utf-8", errors="replace")
    with _sessions_lock:
        _sessions[origin] = (opener, jar)
    return opener, {c.name: c.value for c in jar}, html


def proximis_store_stock(
    product_url: str, lat: float, lon: float, radius_km: int = 30, html: str | None = None, quantity: int = 1,
    ean: str | None = None,
) -> list[StoreStock]:
    """Stock magasin. `html` : la fiche déjà chargée (évite de la recharger).
    `quantity` : nombre d'exemplaires demandés (un magasin qui en a moins n'est pas « en stock »)."""
    try:
        return _proximis_store_stock(product_url, lat, lon, radius_km, html, fresh=False, quantity=quantity, ean=ean)
    except FetchError as e:
        if "HTTP Error 5" not in str(e):
            raise
    # Erreur serveur : une seule nouvelle tentative, avec une session neuve.
    time.sleep(3)
    return _proximis_store_stock(product_url, lat, lon, radius_km, None, fresh=True, quantity=quantity, ean=ean)


def proximis_estimate_quantities(
    product_url: str, lat: float, lon: float, radius_km: int, store_ids: set[str],
    html: str | None = None, cap: int = 50, pause: float = 1.0, ask=None, ean: str | None = None,
) -> dict[str, tuple[int, bool]]:
    """Estime le nombre d'exemplaires par magasin.

    Le site n'affiche pas de quantité, mais l'API répond à « ce magasin peut-il fournir
    N exemplaires ? ». Pour chaque magasin, on cherche le plus grand N accepté
    (dichotomie ; une requête répond pour tous les magasins à la fois).
    Retourne {store_id: (quantité, plafonné)} ; plafonné = « au moins `cap` ».
    """
    ask = ask or (lambda q: proximis_store_stock(product_url, lat, lon, radius_km, html=html, quantity=q, ean=ean))
    cache: dict[int, set[str]] = {}

    def ok_at(q: int) -> set[str]:
        if q not in cache:
            if cache:
                time.sleep(pause)
            cache[q] = {s.store_id for s in ask(q) if s.in_stock}
        return cache[q]

    result = {}
    for sid in store_ids:
        if sid not in ok_at(1):
            continue
        lo, hi = 1, None  # lo : accepté ; hi : refusé
        q = 2
        while hi is None:
            if q >= cap:
                if sid in ok_at(cap):
                    lo = cap
                    break
                hi = cap
            elif sid in ok_at(q):
                lo, q = q, q * 2
            else:
                hi = q
        while hi is not None and hi - lo > 1:
            mid = (lo + hi) // 2
            if sid in ok_at(mid):
                lo = mid
            else:
                hi = mid
        result[sid] = (lo, hi is None)
    return result


def _proximis_store_stock(
    product_url: str, lat: float, lon: float, radius_km: int, html: str | None, fresh: bool, quantity: int = 1,
    ean: str | None = None,
) -> list[StoreStock]:
    origin = re.match(r"https://[^/]+", product_url).group(0)
    try:
        opener, cookies, page = _session(origin, product_url, fresh=fresh)
        html = page or html
        if html is None:
            with opener.open(urllib.request.Request(product_url, headers=_HTML_HEADERS), timeout=20) as r:
                html = r.read().decode("utf-8", errors="replace")
        ctx, sku = _context(html, ean)
        body = {
            **ctx,
            "data": {
                "search": {
                    "address": None,
                    "country": None,
                    "coordinates": {"latitude": lat, "longitude": lon},
                    "processId": 0,
                    "storeId": None,
                    "useAsDefault": True,
                    "distance": f"{radius_km}kilometers",
                },
                "skuQuantities": {sku: quantity},
                "forReservation": False,
                "forPickUp": False,
                "allowSelect": True,
            },
            "URLFormats": "canonical",
            "dataSetNames": "address,coordinates",
            "referer": product_url,
        }
        headers = {
            "User-Agent": _UA,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "X-HTTP-Method-Override": "GET",
            "Origin": origin,
            "Referer": product_url,
        }
        if "CsrfToken" in cookies:  # JouéClub l'exige ; un en-tête vide fait planter La Grande Récré
            headers["X-CSRF-Token"] = cookies["CsrfToken"]
        req = urllib.request.Request(
            f"{origin}/ajax.V1.php/fr_FR/Rbs/Storeshipping/Store/", data=json.dumps(body).encode(), headers=headers
        )
        with opener.open(req, timeout=20) as r:
            data = json.load(r)
    except FetchError:
        raise
    except Exception as e:
        with _sessions_lock:
            _sessions.pop(origin, None)
        raise FetchError(f"stock magasin indisponible : {e}") from e

    return [_proximis_item(item) for item in data.get("items", [])]


def _km(value) -> float | None:
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _proximis_item(item: dict) -> StoreStock:
    shipping = item.get("storeShipping") or {}
    stock = shipping.get("stock") or {}
    common = item.get("common") or {}
    coords = item.get("coordinates") or {}
    available = bool(stock.get("available"))
    pickup = shipping.get("formattedPickUpDateTime") or shipping.get("storeFormattedPickUpDateTime")
    # hasStoreStock (La Grande Récré) distingue le stock en rayon de l'envoi depuis l'entrepôt.
    in_store = available and shipping.get("hasStoreStock") is not False
    incoming = not in_store and bool(pickup or available)
    if in_store:
        label = stock.get("thresholdTitle") or "En stock"
        if pickup:
            label += f", retrait {pickup}"
    elif incoming:
        label = f"Arrivage : retrait {pickup}" if pickup else "Arrivage : commandable en retrait"
    else:
        label = stock.get("thresholdTitle") or "En rupture"
    return StoreStock(
        store_id=str(common.get("id") or common.get("code")),
        name=common.get("title") or "?",
        distance_km=_km(coords.get("distance")),
        in_stock=in_store,
        label=label,
        url=(common.get("URL") or {}).get("canonical"),
        incoming=incoming,
    )


# --- Cultura ----------------------------------------------------------------
#
# Le site (Magento) expose une API GraphQL publique en GET :
# - stores(search:"<code postal>") : magasins triés par distance, avec leur seller_code ;
# - products(filter:{url_key:...}) : stock_item_extra.offer = une offre par magasin qui a
#   le produit (seller_code + front_availability). Un magasin absent n'a pas le produit.
# Le site étant derrière Cloudflare, les appels sont faits depuis le navigateur.

CULTURA = "https://www.cultura.com"
_cultura_stores_cache: dict[tuple[str, int], tuple[float, list[dict]]] = {}


def _graphql_url(query: str) -> str:
    return f"{CULTURA}/magento/graphql?query=" + urllib.parse.quote(query, safe="{}(),:\"")


def cultura_url_key(product_url: str) -> str:
    m = re.search(r"/p-([^/?#]+)\.html", product_url)
    if not m:
        raise FetchError("adresse de fiche Cultura inattendue")
    return m.group(1)


def cultura_nearby_stores(fetcher, location: str, radius_km: int) -> list[dict]:
    key = (location, radius_km)
    cached = _cultura_stores_cache.get(key)
    if cached is None or time.time() - cached[0] > 86400:  # liste des magasins : relue chaque jour
        q = (
            '{stores(search:"%s",sort:{distance:ASC},limit:20){items{seller_code,name,distance,url_key}}}'
            % location.replace('"', "")
        )
        data = fetcher.fetch_json(_graphql_url(q), CULTURA)
        stores = ((data.get("data") or {}) if isinstance(data, dict) else {}).get("stores")
        if not isinstance(stores, dict):  # erreur GraphQL, page anti-robot… : rien en cache
            raise FetchError("liste des magasins Cultura illisible")
        items = stores.get("items") or []
        near = []
        for it in items:
            try:
                dist = float(it.get("distance"))
            except (TypeError, ValueError):
                dist = None
            if dist is None or dist <= radius_km:
                near.append({**it, "distance": dist})
        if not near:
            return near  # pas mis en cache : réessayé au prochain passage
        _cultura_stores_cache[key] = cached = (time.time(), near)
    return cached[1]


def cultura_store_stock(fetcher, product_url: str, location: str, radius_km: int = 30) -> list[StoreStock]:
    return cultura_store_stock_multi(fetcher, product_url, [(location, radius_km)])[0]


def cultura_store_stock_multi(fetcher, product_url: str, points: list[tuple[str, int]]) -> list[list[StoreStock]]:
    """Stock Cultura pour plusieurs cercles (code postal, rayon). L'API donne la disponibilité du
    produit dans TOUS les magasins de France en une seule demande : un seul appel produit, quel
    que soit le nombre de cercles (les listes de magasins, elles, sont gardées en mémoire)."""
    q = (
        '{products(filter:{url_key:{eq:"%s"}},getDisabledProduct:1,resolverLight:1)'
        "{items{stock_item_extra{offer{front_availability,seller_code,qty}}}}}" % cultura_url_key(product_url)
    )
    data = fetcher.fetch_json(_graphql_url(q), CULTURA)
    items = ((data.get("data") or {}).get("products") or {}).get("items") or []
    if not items:
        raise FetchError("produit introuvable dans l'API Cultura")
    offers = {
        o.get("seller_code"): (o.get("front_availability") or "", o.get("qty"))
        for o in ((items[0].get("stock_item_extra") or {}).get("offer") or [])
    }
    return [_cultura_result(cultura_nearby_stores(fetcher, loc, r), offers) for loc, r in points]


def _cultura_result(stores: list[dict], offers: dict) -> list[StoreStock]:
    result = []
    for st in stores:
        avail, qty = offers.get(st["seller_code"], ("", None))
        in_stock = avail == "available" or avail.startswith("available")
        # « qty » : 10000 pour « en stock » sans précision (cas relevé en août 2026) ; une
        # autre valeur est un vrai nombre d'exemplaires annoncé par Cultura.
        real_qty = qty if in_stock and isinstance(qty, (int, float)) and 0 < qty < 10000 else None
        result.append(
            StoreStock(
                qty=int(real_qty) if real_qty else None,
                store_id=st["seller_code"],
                name=st.get("name") or st["seller_code"],
                distance_km=st.get("distance"),
                in_stock=in_stock,
                label="En stock" if in_stock else (f"Indisponible ({avail})" if avail else "Pas en stock"),
                url=f"{CULTURA}/magasins/{st['url_key']}.html" if st.get("url_key") else None,
            )
        )
    return result
