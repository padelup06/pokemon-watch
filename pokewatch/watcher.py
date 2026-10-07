"""Boucle de surveillance : découverte de nouveaux produits + relevé des stocks."""

from __future__ import annotations

import os
import random
import re
import threading
import time
import tomllib
from html import unescape
from urllib.parse import urljoin

from .fetch import FetchError, Fetcher, resolve_url
from .instore import (
    PROXIMIS_RETAILERS,
    QUANTITY_RETAILERS,
    STORE_RETAILERS,
    cultura_store_stock,
    cultura_store_stock_multi,
    geocode,
    proximis_estimate_quantities,
    proximis_restock,
    proximis_store_stock,
)
from .notify import Notifier, format_alert, format_restock_alert, format_store_alert, should_alert
from .parse import UNKNOWN, parse_availability
from .retailers import retailer_for_url
from .store import Store

ENV_OVERRIDES = {
    "POKEWATCH_DISCORD_WEBHOOK": "discord_webhook",
    "POKEWATCH_TELEGRAM_TOKEN": "telegram_bot_token",
    "POKEWATCH_TELEGRAM_CHAT_ID": "telegram_chat_id",
}


def load_config(path: str) -> dict:
    config_path = path
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    cfg.setdefault("settings", {})
    alerts = cfg.setdefault("alerts", {})
    for env, key in ENV_OVERRIDES.items():
        if os.environ.get(env):
            alerts[key] = os.environ[env]
    # Secret GitHub POKEWATCH_ZONE_WEBHOOKS : une ligne par zone, « 06=https://discord.com/api/webhooks/… »
    # (sur le PC : fichier webhooks-regions.txt écrit par creer-salons-discord.bat, s'il existe).
    zone_lines = os.environ.get("POKEWATCH_ZONE_WEBHOOKS", "")
    zfile = cfg.get("settings", {}).get("zone_webhooks_file")
    if zfile:
        zpath = os.path.join(os.path.dirname(os.path.abspath(config_path)), zfile)
        if os.path.exists(zpath):
            with open(zpath, encoding="utf-8-sig") as f:
                zone_lines = f.read() + "\n" + zone_lines
    for line in zone_lines.splitlines():
        if "=" in line:
            zone, hook = line.split("=", 1)
            alerts.setdefault("zone_webhooks", {})[zone.strip()] = hook.strip()
    settings = cfg["settings"]
    if os.environ.get("POKEWATCH_CODE_POSTAL"):
        settings["code_postal"] = os.environ["POKEWATCH_CODE_POSTAL"]
    if os.environ.get("POKEWATCH_RAYON_KM"):
        settings["rayon_km"] = int(os.environ["POKEWATCH_RAYON_KM"])
    cfg.setdefault("products", [])
    cfg.setdefault("searches", [])
    # Liste de surveillance : un fichier texte, une adresse de fiche produit par ligne.
    watch_file = settings.get("watchlist_file")
    cfg["watchlist"] = []
    if watch_file:
        path = os.path.join(os.path.dirname(os.path.abspath(config_path)), watch_file)
        cfg["watchlist"] = load_watchlist(path)
    return cfg


def load_watchlist(path: str) -> list[dict]:
    """Lit produits.txt : une URL par ligne, label facultatif après « | », # pour commenter."""
    items = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("http"):  # lignes vides et commentaires
                    continue
                url, _, label = line.partition("|")
                items.append({"url": url.strip(), "label": label.strip() or None})
    except FileNotFoundError:
        pass
    return items


def extract_product_links(html: str, base_url: str) -> list[str]:
    retailer = retailer_for_url(base_url)
    text = unescape(html).replace("\\/", "/")  # URLs échappées dans du JSON embarqué
    # Les liens sont souvent relatifs ("/p-x.html", "pokemon/x.html") : on les rend absolus.
    base = re.search(r"""<base\s[^>]*href=["']([^"']+)""", text, re.I)
    root = urljoin(base_url, base.group(1)) if base else base_url
    hrefs = [urljoin(root, h) for h in re.findall(r"""href=["']([^"'#]+)""", text)]
    seen: dict[str, None] = {}
    for candidate in [*hrefs, text]:
        for m in retailer.product_url.finditer(candidate):
            seen.setdefault(m.group(0))
    return list(seen)


def ean_search(url: str) -> str | None:
    """Code-barres d'une URL de recherche par EAN (cultura.com/search/results?search_query=0196…,
    e.leclerc/recherche?q=0196…)."""
    m = re.search(r"/search/[^?]*\?(?:[^#]*&)?search_query=(\d{8,14})(?:&|$)", url) or re.search(
        r"(?:e\.leclerc/recherche|carrefour\.fr/s)\?(?:[^#]*&)?q=(\d{8,14})(?:&|$)", url
    ) or re.search(r"cdiscount\.com/search/10/(\d{8,14})\.html", url)
    return m.group(1) if m else None


def label_ean(label: str | None) -> str | None:
    m = re.search(r"\bEAN\s*(\d{13})\b", label or "", re.I)
    return m.group(1) if m else None


def matches_keywords(url: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    slug = url.lower().replace("%c3%a9", "e").replace("é", "e")
    return any(k.lower().replace("é", "e") in slug for k in keywords)


class Watcher:
    def __init__(self, cfg: dict) -> None:
        s = cfg["settings"]
        cfg.setdefault("products", [])
        cfg.setdefault("searches", [])
        cfg.setdefault("watchlist", [])
        self.cfg = cfg
        self.store = Store(s.get("database", "pokewatch.db"))
        self.fetcher = Fetcher(
            s.get("browser", "auto"),
            headless=not s.get("browser_visible", False),
            minimized=s.get("browser_minimized", True),
        )
        self.notifier = Notifier(cfg["alerts"])
        self.delay = (float(s.get("min_delay_seconds", 2)), float(s.get("max_delay_seconds", 6)))
        self.keywords = s.get("keywords", ["pokemon"])
        self.max_discovered = int(s.get("max_products_per_search", 40))
        # False : seuls vos produits (produits.txt / [[products]]) sont relevés ; les pages de
        # recherche ne servent plus qu'à signaler les nouveautés.
        self.track_discovered = bool(s.get("track_discovered", True))
        self.location = s.get("code_postal") or s.get("ville")
        self.radius_km = int(s.get("rayon_km", 30))
        self._coords: tuple[float, float] | None = None
        # Zones surveillées en magasin : [[settings.zones]] name / code_postal / rayon_km (ou
        # « points » : plusieurs cercles [code_postal, rayon]) / every_minutes. À défaut, une
        # seule zone (code_postal / rayon_km).
        zones = s.get("zones") or ([{"name": "", "code_postal": self.location, "rayon_km": self.radius_km}] if self.location else [])
        if s.get("regions"):  # les 13 régions de pokewatch/regions.py
            from .regions import REGIONS

            every = float(s.get("regions_every_minutes", 30))
            zones = list(zones) + [
                {"name": key, "label": label, "points": pts, "every_minutes": every}
                for key, label, _salon, _emoji, pts in REGIONS
            ]
        self.zones = []
        for z in zones:
            pts = z.get("points") or [(z.get("code_postal") or z.get("ville"), z.get("rayon_km", self.radius_km))]
            self.zones.append({
                "name": str(z.get("name", "")), "label": z.get("label") or str(z.get("name", "")),
                "points": [{"location": str(cp), "radius": int(r), "coords": None} for cp, r in pts],
                "every": float(z.get("every_minutes", 0)), "active": True, "fresh": False,
            })
        rr = s.get("regions_retailers")
        self.region_retailers = set(rr) if rr is not None else None
        # Zones « lentes » (every_minutes) vérifiées à tour de rôle : au plus N par passage.
        self.max_slow_zones = int(s.get("max_slow_zones_per_run", 3))
        self.store_interval = float(s.get("store_check_seconds", 0))
        self.store_backoff = float(s.get("store_error_pause_seconds", 300))
        self._store_last: dict[str, float] = {}
        self._store_pause: dict[str, float] = {}
        self._store_fails: dict[str, int] = {}  # erreurs consécutives par enseigne
        self._rate_pause: dict[str, float] = {}  # enseigne -> fin de pause après un HTTP 429
        self._unreadable: dict[str, int] = {}  # pages illisibles d'affilée par enseigne
        self._soft_blocks: dict[str, int] = {}  # séries de pages illisibles (pause croissante)
        # Recherches par code-barres (pages lourdes, produit pas encore en ligne) : espacées.
        self.ean_search_interval = float(s.get("ean_search_seconds", 0))
        self._ean_last: dict[str, float] = {}
        # GitHub : laisse la liste de surveillance au PC (vérifiée chaque minute) pour éviter les doublons.
        self.exclude_watchlist = bool(s.get("exclude_watchlist", False))
        self.watch_interval = float(s.get("watchlist_interval_seconds", 0))

    def _pause(self) -> None:
        time.sleep(random.uniform(*self.delay))

    def discover(self) -> None:
        for search in self.cfg["searches"]:
            url = search["url"]
            retailer = retailer_for_url(url)
            # Pages lourdes ou rarement mises à jour (plan du site) : every_minutes espace les passages.
            if not self.store.search_due(url, float(search.get("every_minutes", 0))):
                continue
            try:
                html = self.fetcher.get(url, retailer.needs_browser)
            except FetchError as e:
                print(f"[{retailer.name}] recherche inaccessible ({e}) : {url}")
                continue
            finally:
                self._pause()
            links = [u for u in extract_product_links(html, url) if matches_keywords(u, search.get("keywords", self.keywords))]
            # require : mots qui doivent TOUS figurer dans l'adresse (ex. "/pokemon/" chez JouéClub).
            links = [u for u in links if all(matches_keywords(u, [w]) for w in search.get("require", []))]
            limit = int(search.get("max", self.max_discovered))
            links = links[:limit] if limit else links
            first_run = not self.store.search_seen(url)
            self.store.search_due(url, 0)
            new = [u for u in links if self.store.add_product(u, retailer.key, "découverte")]
            print(f"[{retailer.name}] recherche : {len(links)} produits, {len(new)} nouveaux")
            # Premier passage : on constitue la base sans spammer. Certaines pages (JouéClub)
            # affichent une sélection différente à chaque visite : alert_new = false pour elles.
            if first_run or not search.get("alert_new", True):
                continue
            for u in new:
                self.check(u)  # nom, prix et disponibilité pour une alerte utile
                row = self.store.get(u)
                self.notifier.send(
                    format_alert("nouveau", retailer.name, row["name"], u, row["status"] or "inconnu", row["price"]),
                    image=self.store.image(u),
                )
                self._pause()

    def _too_many(self, retailer, error: Exception) -> bool:
        """HTTP 429 (« trop de demandes ») : on laisse l'enseigne tranquille 15 min."""
        if "429" not in str(error):
            return False
        self._rate_pause[retailer.key] = time.time() + 900
        print(f"[{retailer.name}] trop de demandes (HTTP 429) : pause de 15 min pour cette enseigne", flush=True)
        return True

    def check(self, url: str, label: str | None = None) -> None:
        retailer = retailer_for_url(url)
        if retailer.needs_browser and self.fetcher.browser_mode == "never":
            return  # ex. Cultura sur GitHub : bloqué sans navigateur, laissé au PC
        if time.time() < self._rate_pause.get(retailer.key, 0):
            return
        self.store.add_product(url, retailer.key, label)
        if ean_search(url):
            return self.check_ean_search(url, label)
        try:
            html = self.fetcher.get(url, retailer.needs_browser)
        except FetchError as e:
            self.store.record_error(url, retailer.key, str(e))
            if not self._too_many(retailer, e):
                print(f"[{retailer.name}] ⚠ {e} : {url}")
            return
        if retailer.use_keywords:
            av = parse_availability(html, retailer.in_stock_keywords, retailer.out_of_stock_keywords, retailer.own_seller)
        else:
            av = parse_availability(html, seller=retailer.own_seller)
        name = label or av.name
        prev = self.store.get(url)
        if av.status == UNKNOWN and prev is not None and prev["status"] not in (None, "", UNKNOWN):
            # Page lue mais illisible (site qui limite les demandes, page d'attente…) : on garde le
            # dernier état connu, sinon son retour déclencherait une fausse nouvelle alerte.
            title = re.search(r"<title[^>]*>([^<]*)", html or "", re.I)
            print(f"{time.strftime('%H:%M:%S')} [{retailer.name}] lecture incomplète, statut gardé : "
                  f"{prev['status']} — {name or url} (page reçue : « {(title.group(1).strip() if title else '?')[:60]} », "
                  f"{len(html or '')} caractères)", flush=True)
            n = self._unreadable.get(retailer.key, 0) + 1
            self._unreadable[retailer.key] = n
            if n >= 3:
                # Plusieurs pages illisibles d'affilée : le site nous freine, on le laisse respirer.
                self._soft_blocks[retailer.key] = self._soft_blocks.get(retailer.key, 0) + 1
                pause = min(600 * 2 ** (self._soft_blocks[retailer.key] - 1), 3600)
                self._rate_pause[retailer.key] = time.time() + pause
                self._unreadable[retailer.key] = 0
                print(f"[{retailer.name}] pages illisibles en série : pause de {pause // 60:.0f} min pour cette enseigne", flush=True)
            return
        if av.status != UNKNOWN:
            self._unreadable.pop(retailer.key, None)
            self._soft_blocks.pop(retailer.key, None)
        old = self.store.record(url, retailer.key, av.status, name, av.price)
        self.store.set_image(url, av.image)
        print(f"{time.strftime('%H:%M:%S')} [{retailer.name}] {av.status:<11} ({av.source or '-'}) {name or url}", flush=True)
        # old == "" : premier relevé du produit, on enregistre sans alerter.
        if old and should_alert(old, av.status):
            self.notifier.send(format_alert("stock", retailer.name, name, url, av.status, av.price), image=av.image)
        if retailer.key in PROXIMIS_RETAILERS:
            restock = self.store.set_restock(url, proximis_restock(html))
            if restock and old:
                self.notifier.send(format_restock_alert(retailer.name, name, url, restock), image=av.image)
        # Code-barres noté dans le libellé (« … EAN 0196… ») : stock magasin lisible même
        # sans fiche publiée (JouéClub, La Grande Récré).
        ean = label_ean(label) if retailer.key in PROXIMIS_RETAILERS else None
        if self.zones and retailer.key in STORE_RETAILERS and (av.status != UNKNOWN or ean):
            self.check_stores(url, retailer, name, html, ean)

    def check_ean_search(self, url: str, label: str | None) -> None:
        """Recherche par code-barres (produit sans fiche en ligne) : on guette l'apparition
        d'une fiche, puis on la suit comme les autres produits."""
        ean = ean_search(url)
        retailer = retailer_for_url(url)
        row = self.store.get(url)
        if row is not None and row["found_url"]:
            return self.check(row["found_url"], label)  # fiche déjà trouvée : on suit directement la fiche
        # Mémorisé dans la base : sur GitHub, chaque passage est un nouveau programme.
        last = self._ean_last.get(url) or float(self.store.get_meta(f"ean_last_{url}") or 0)
        if time.time() - last < self.ean_search_interval:
            return
        self._ean_last[url] = time.time()
        if self.ean_search_interval:
            self.store.set_meta(f"ean_last_{url}", str(self._ean_last[url]))
        if retailer.key == "leclerc":
            # Leclerc : e.leclerc/fp/<EAN> redirige vers la fiche si elle existe (404 sinon). Plus
            # fiable que son moteur de recherche, qui ne trouvait pas le Mini Tin 30e le 7/10.
            try:
                final = resolve_url(f"https://www.e.leclerc/fp/{ean}")
            except FetchError as e:
                if not self._too_many(retailer, e):
                    print(f"[{retailer.name}] ⚠ recherche {ean} : {e}")
                return
            return self._ean_result(url, retailer, ean, label, final.split("?")[0] if final else None)
        try:
            html = self.fetcher.get(url, retailer.needs_browser)
        except FetchError as e:
            self.store.record_error(url, retailer.key, str(e))
            print(f"[{retailer.name}] ⚠ recherche {ean} : {e}")
            return
        if re.search(r"challenge-platform|cf-chl|<title>\s*Un instant", html, re.I):
            print(f"[{retailer.name}] recherche {ean} : bloquée par la vérification Cloudflare (réessai au prochain passage)")
            return
        found = None
        # La page de résultats peut proposer d'autres produits (suggestions) : on ne retient
        # qu'une fiche dont la page contient bien le code-barres recherché.
        for link in extract_product_links(html, url)[:4]:
            try:
                # Cdiscount écrit l'EAN sans le 0 de tête (…/f-120791604-pok196214141964.html).
                page = self.fetcher.get(link, retailer.needs_browser)
                if ean in page or (ean.startswith("0") and ean.lstrip("0") in page):
                    found = link
                    break
            except FetchError:
                continue
        self._ean_result(url, retailer, ean, label, found)

    def _ean_result(self, url: str, retailer, ean: str, label: str | None, found: str | None) -> None:
        first = self.store.get(url)["last_check"] is None
        self.store.record(url, retailer.key, "en_stock" if found else "inconnu", label, None)
        appeared = self.store.set_found(url, found)
        print(f"[{retailer.name}] recherche {ean} : {'fiche trouvée ' + found if found else 'aucune fiche'}")
        if found:
            self.check(found, label)  # d'abord la fiche : nom, stock et photo pour l'alerte
            if appeared and not first:
                self.notifier.send(
                    f"🆕 FICHE EN LIGNE chez {retailer.name} : {label or ean}\n{found}", image=self.store.image(found)
                )

    def check_stores(self, url: str, retailer, name: str | None, html: str | None = None, ean: str | None = None) -> None:
        now = time.time()
        # Stock magasin moins souvent que le stock en ligne, et pause après une erreur :
        # les API de stock limitent les demandes répétées.
        if now < self._store_pause.get(retailer.key, 0):
            return
        if now - self._store_last.get(url, 0) < self.store_interval:
            return
        self._store_last[url] = now
        try:
            stocks, seen = [], set()
            # Régions (zones lentes) : seulement pour les enseignes de regions_retailers (PC : Cultura,
            # GitHub : JouéClub et La Grande Récré).
            active = [z for z in self.zones if z["active"] and (not z["every"] or self.region_retailers is None
                                                                  or retailer.key in self.region_retailers)]
            pairs = [(z, pt) for z in active for pt in z["points"]]
            if retailer.key == "cultura":
                lists = cultura_store_stock_multi(self.fetcher, url, [(pt["location"], pt["radius"]) for _, pt in pairs])
            else:
                lists = [proximis_store_stock(url, *self.point_coords(pt), radius_km=pt["radius"], html=html, ean=ean)
                         for _, pt in pairs]
            for (z, _pt), found in zip(pairs, lists):
                for st in found:  # un magasin vu par deux cercles ou zones reste au premier
                    if st.store_id not in seen:
                        seen.add(st.store_id)
                        st.zone = z["name"]
                        stocks.append(st)
        except FetchError as e:
            # Pause doublée à chaque échec consécutif (5, 10, 20, 40 min, puis 1 h) : un serveur
            # qui refuse une connexion (502 en série chez l'utilisateur) se débloque mieux sans
            # être relancé toutes les 5 min. GitHub continue de relever le stock magasin.
            fails = self._store_fails.get(retailer.key, 0) + 1
            self._store_fails[retailer.key] = fails
            pause = min(self.store_backoff * 2 ** (fails - 1), 3600)
            self._store_pause[retailer.key] = time.time() + pause
            print(f"[{retailer.name}] ⚠ magasins : {e} — stock magasin en pause {pause // 60:.0f} min", flush=True)
            return
        if self._store_fails.pop(retailer.key, 0):
            print(f"[{retailer.name}] magasins : de nouveau accessibles", flush=True)
        newly = self.store.record_store_stock(url, retailer.key, name, stocks, {z["name"] for z in active})
        in_stock = sum(1 for s in stocks if s.in_stock)
        incoming = sum(1 for s in stocks if s.incoming and not s.in_stock)
        print(f"    magasins ({', '.join(z['name'] or z['points'][0]['location'] for z in active)}) : "
              f"{in_stock}/{len(stocks)} en stock, {incoming} en arrivage")
        # Premier relevé de ce produit dans une région : on note l'existant sans alerter.
        first = {z["name"] for z in active if z["every"] and self.store.get_meta(f"zs|{url}|{z['name']}") is None}
        for name in first:
            self.store.set_meta(f"zs|{url}|{name}", "1")
        newly = [st for st in newly if not self.zone_silent(st.zone) and st.zone not in first]
        if newly:
            self.add_quantities(url, retailer, newly, html, ean)
            for zone in dict.fromkeys(st.zone for st in newly):  # une alerte par zone, dans son salon
                self.notifier.send(format_store_alert(retailer.name, name, url, [st for st in newly if st.zone == zone]), zone,
                                   image=self.store.image(url))

    def point_coords(self, pt: dict) -> tuple[float, float]:
        if pt["coords"] is None:
            pt["coords"] = geocode(pt["location"])
        return pt["coords"]

    def estimate_zone(self, url: str, z: dict, ids: set, html: str | None = None, ean: str | None = None) -> dict:
        """Quantités estimées pour les magasins `ids` d'une zone (cercle par cercle)."""
        qty: dict = {}
        for pt in z["points"]:
            rest = ids - qty.keys()
            if not rest:
                break
            qty.update(proximis_estimate_quantities(url, *self.point_coords(pt), pt["radius"], rest, html=html, ean=ean))
        return qty

    def select_zones(self) -> None:
        """Avant un passage : zones rapides toujours, zones lentes à tour de rôle (les plus en retard)."""
        now = time.time()
        due = []
        for z in self.zones:
            if not z["every"]:
                z["active"] = True
                continue
            last = float(self.store.get_meta(f"zone_last_{z['name']}") or 0)
            z["active"] = False
            if now - last >= z["every"] * 60:
                due.append((last, z))
        for _, z in sorted(due, key=lambda t: t[0])[: self.max_slow_zones]:
            z["active"] = True
            self.store.set_meta(f"zone_last_{z['name']}", str(now))
        for z in self.zones:  # premier passage d'une zone : on note l'existant sans alerter
            z["fresh"] = bool(z["every"]) and z["active"] and self.store.get_meta(f"zone_init_{z['name']}") is None
        slow = [z["name"] for z in self.zones if z["every"] and z["active"]]
        if slow:
            print(f"Zones vérifiées ce passage en plus des zones rapides : {', '.join(slow)}", flush=True)

    def add_quantities(self, url: str, retailer, stores, html: str | None, ean: str | None = None) -> None:
        """Nombre estimé d'exemplaires pour les magasins qui viennent de passer en stock."""
        targets = {s.store_id for s in stores if s.in_stock}
        if not targets or retailer.key not in QUANTITY_RETAILERS or not self.cfg["settings"].get("estimate_quantity", True):
            return
        qty = {}
        try:
            for z in self.zones:
                ids = {s.store_id for s in stores if s.in_stock and s.zone == z["name"]}
                if ids:
                    qty.update(self.estimate_zone(url, z, ids, html=html, ean=ean))
        except FetchError as e:
            print(f"[{retailer.name}] quantités non estimées : {e}", flush=True)
        for s in stores:
            if s.store_id in qty:
                s.qty, s.qty_capped = qty[s.store_id]

    def _products(self) -> dict[str, str | None]:
        configured = {p["url"]: p.get("label") for p in self.cfg["products"]}
        if not self.exclude_watchlist:
            configured.update({p["url"]: p.get("label") for p in self.cfg["watchlist"]})
        return configured

    def run_watchlist(self) -> None:
        for p in self.cfg["watchlist"]:
            self.check(p["url"], p.get("label"))
            self._pause()

    def zone_silent(self, name: str) -> bool:
        """Pas d'alerte pour cette zone : premier passage, ou région sans salon Discord."""
        z = next((z for z in self.zones if z["name"] == name), None)
        if z is None:
            return False
        return z["fresh"] or (bool(z["every"]) and name not in self.notifier.zone_webhooks)

    def run_once(self) -> None:
        self.select_zones()
        try:
            self._run_once()
        finally:
            for z in self.zones:
                if z["fresh"]:
                    self.store.set_meta(f"zone_init_{z['name']}", "1")

    def _run_once(self) -> None:
        self.discover()
        configured = self._products()
        skip = {p["url"] for p in self.cfg["watchlist"]} if self.exclude_watchlist else set()
        urls = list(configured)
        if self.track_discovered:
            urls += [u for u in sorted(self.store.known_urls()) if u not in configured and u not in skip]
        for url in urls:
            self.check(url, configured.get(url))
            self._pause()

    def run_parallel(self, make_watcher=None, stop: threading.Event | None = None, cycles: int | None = None) -> None:
        """Un fil par enseigne : chaque site est interrogé à son propre rythme (pauses
        conservées entre deux pages d'un même site), mais les sites avancent en même
        temps. Chaque fil a son propre Watcher (base, navigateur) : Playwright et
        sqlite ne se partagent pas entre fils."""
        make_watcher = make_watcher or (lambda: Watcher(self.cfg))
        stop = stop or threading.Event()
        groups: dict[str, list[dict]] = {}
        for p in self.cfg["watchlist"]:
            groups.setdefault(retailer_for_url(p["url"]).key, []).append(p)

        def worker(products: list[dict]) -> None:
            w = make_watcher()
            done = 0
            try:
                while not stop.is_set() and (cycles is None or done < cycles):
                    for p in products:
                        if stop.is_set():
                            break
                        try:
                            w.check(p["url"], p.get("label"))
                        except Exception as e:  # un site en panne ne doit pas arrêter les autres
                            print(f"⚠ {p['url']} : {e}", flush=True)
                        w._pause()
                    done += 1
                    if cycles is None or done < cycles:
                        stop.wait(self.watch_interval + random.uniform(0, 5))
            finally:
                w.fetcher.close()

        threads = [threading.Thread(target=worker, args=(prods,), name=key, daemon=True) for key, prods in groups.items()]
        for t in threads:
            t.start()
        print(f"— {len(threads)} enseignes surveillées en parallèle : {', '.join(groups)} —", flush=True)
        for t in threads:
            t.join()

    def run_forever(self) -> None:
        """Passage complet toutes les `interval_minutes` ; entre deux, la liste de
        surveillance est revérifiée toutes les `watchlist_interval_seconds`."""
        s = self.cfg["settings"]
        interval = float(s.get("interval_minutes", 10)) * 60
        jitter = float(s.get("jitter_seconds", 60))
        fast = self.watch_interval > 0 and bool(self.cfg["watchlist"]) and not self.exclude_watchlist
        if fast and s.get("parallel", False):
            # Vos produits : en continu, une enseigne par fil. Ce fil-ci ne garde que la
            # recherche de nouveautés (pages [[searches]]), s'il y en a.
            threading.Thread(target=self.run_parallel, daemon=True).start()
            try:
                while True:
                    if self.cfg["searches"]:
                        self.discover()
                    time.sleep(max(60.0, interval + random.uniform(-jitter, jitter)))
            finally:
                self.fetcher.close()
        next_full = 0.0
        try:
            while True:
                if time.time() >= next_full:
                    self.run_once()
                    next_full = time.time() + max(60.0, interval + random.uniform(-jitter, jitter))
                    print(f"— prochain passage complet dans {(next_full - time.time()) / 60:.1f} min —", flush=True)
                elif fast:
                    self.run_watchlist()
                if fast:
                    wait = min(next_full - time.time(), self.watch_interval + random.uniform(0, 10))
                else:
                    wait = next_full - time.time()
                time.sleep(max(5.0, wait))
        finally:
            self.fetcher.close()
