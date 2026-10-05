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
