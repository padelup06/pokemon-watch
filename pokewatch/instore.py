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
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .fetch import USER_AGENTS, FetchError

# Enseignes dont le stock magasin est lisible via la plateforme Proximis.
PROXIMIS_RETAILERS = {"joueclub", "lagranderecre"}
# Enseignes dont le stock magasin passe par le navigateur (site protégé par un anti-robot).
BROWSER_STORE_RETAILERS = {"cultura"}
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


def _context(html: str) -> tuple[dict, str]:
    ctx = {}
    for key in ("websiteId", "sectionId", "pageId"):
        m = re.search(rf'"{key}":(\d+)', html)
        if not m:
            raise FetchError(f"{key} introuvable dans la page")
        ctx[key] = int(m.group(1))
    m = re.search(r'"stock":\{"showStoreAvailability":true[^{}]*?"sku":"([^"]+)"', html)
    if not m:
        raise FetchError("ce produit n'a pas de disponibilité en magasin")
    return ctx, m.group(1)


def proximis_store_stock(product_url: str, lat: float, lon: float, radius_km: int = 30) -> list[StoreStock]:
    # L'API renvoie des 502 quand on l'interroge trop vite : on réessaie en espaçant.
    for wait in (5, 15, None):
        try:
            return _proximis_store_stock(product_url, lat, lon, radius_km)
        except FetchError as e:
            if wait is None or "HTTP Error 5" not in str(e):
                raise
            time.sleep(wait)


def _proximis_store_stock(product_url: str, lat: float, lon: float, radius_km: int) -> list[StoreStock]:
    origin = re.match(r"https://[^/]+", product_url).group(0)
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        with opener.open(urllib.request.Request(product_url, headers=_HTML_HEADERS), timeout=20) as r:
            html = r.read().decode("utf-8", errors="replace")
        ctx, sku = _context(html)
        cookies = {c.name: c.value for c in jar}
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
                "skuQuantities": {sku: 1},
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
        raise FetchError(f"stock magasin indisponible : {e}") from e

    result = []
    for item in data.get("items", []):
        stock = (item.get("storeShipping") or {}).get("stock") or {}
        common = item.get("common") or {}
        coords = item.get("coordinates") or {}
        result.append(
            StoreStock(
                store_id=str(common.get("id") or common.get("code")),
                name=common.get("title") or "?",
                distance_km=round(coords["distance"], 1) if coords.get("distance") is not None else None,
                in_stock=bool(stock.get("available")),
                label=stock.get("thresholdTitle") or ("En stock" if stock.get("available") else "En rupture"),
                url=(common.get("URL") or {}).get("canonical"),
            )
        )
    return result


# --- Cultura ----------------------------------------------------------------
#
# Le site (Magento) expose une API GraphQL publique en GET :
# - stores(search:"<code postal>") : magasins triés par distance, avec leur seller_code ;
# - products(filter:{url_key:...}) : stock_item_extra.offer = une offre par magasin qui a
#   le produit (seller_code + front_availability). Un magasin absent n'a pas le produit.
# Le site étant derrière Cloudflare, les appels sont faits depuis le navigateur.

CULTURA = "https://www.cultura.com"
_cultura_stores_cache: dict[tuple[str, int], list[dict]] = {}


def _graphql_url(query: str) -> str:
    return f"{CULTURA}/magento/graphql?query=" + urllib.parse.quote(query, safe="{}(),:\"")


def cultura_url_key(product_url: str) -> str:
    m = re.search(r"/p-([^/?#]+)\.html", product_url)
    if not m:
        raise FetchError("adresse de fiche Cultura inattendue")
    return m.group(1)


def cultura_nearby_stores(fetcher, location: str, radius_km: int) -> list[dict]:
    key = (location, radius_km)
    if key not in _cultura_stores_cache:
        q = (
            '{stores(search:"%s",sort:{distance:ASC},limit:20){items{seller_code,name,distance,url_key}}}'
            % location.replace('"', "")
        )
        data = fetcher.fetch_json(_graphql_url(q), CULTURA)
        items = ((data.get("data") or {}).get("stores") or {}).get("items") or []
        near = []
        for it in items:
            try:
                dist = float(it.get("distance"))
            except (TypeError, ValueError):
                dist = None
            if dist is None or dist <= radius_km:
                near.append({**it, "distance": dist})
        _cultura_stores_cache[key] = near
    return _cultura_stores_cache[key]


def cultura_store_stock(fetcher, product_url: str, location: str, radius_km: int = 30) -> list[StoreStock]:
    stores = cultura_nearby_stores(fetcher, location, radius_km)
    q = (
        '{products(filter:{url_key:{eq:"%s"}},getDisabledProduct:1,resolverLight:1)'
        "{items{stock_item_extra{offer{front_availability,seller_code,qty}}}}}" % cultura_url_key(product_url)
    )
    data = fetcher.fetch_json(_graphql_url(q), CULTURA)
    items = ((data.get("data") or {}).get("products") or {}).get("items") or []
    if not items:
        raise FetchError("produit introuvable dans l'API Cultura")
    offers = {
        o.get("seller_code"): (o.get("front_availability") or "")
        for o in ((items[0].get("stock_item_extra") or {}).get("offer") or [])
    }
    result = []
    for st in stores:
        avail = offers.get(st["seller_code"], "")
        in_stock = avail == "available" or avail.startswith("available")
        result.append(
            StoreStock(
                store_id=st["seller_code"],
                name=st.get("name") or st["seller_code"],
                distance_km=st.get("distance"),
                in_stock=in_stock,
                label="En stock" if in_stock else (f"Indisponible ({avail})" if avail else "Pas en stock"),
                url=f"{CULTURA}/magasins/{st['url_key']}.html" if st.get("url_key") else None,
            )
        )
    return result
