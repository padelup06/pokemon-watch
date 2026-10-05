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

from .fetch import FetchError, Fetcher
from .instore import (
    PROXIMIS_RETAILERS,
    STORE_RETAILERS,
    cultura_store_stock,
    geocode,
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
    """Code-barres d'une URL de recherche par EAN (ex. cultura.com/search/results?search_query=0196…)."""
    m = re.search(r"/search/[^?]*\?(?:[^#]*&)?search_query=(\d{8,14})(?:&|$)", url)
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
        self.store_interval = float(s.get("store_check_seconds", 0))
        self.store_backoff = float(s.get("store_error_pause_seconds", 300))
        self._store_last: dict[str, float] = {}
        self._store_pause: dict[str, float] = {}
        # GitHub : laisse la liste de surveillance au PC (vérifiée chaque minute) pour éviter les doublons.
        self.exclude_watchlist = bool(s.get("exclude_watchlist", False))
        self.watch_interval = float(s.get("watchlist_interval_seconds", 0))

    def _pause(self) -> None:
        time.sleep(random.uniform(*self.delay))

    def discover(self) -> None:
        for search in self.cfg["searches"]:
            url = search["url"]
            retailer = retailer_for_url(url)
            try:
                html = self.fetcher.get(url, retailer.needs_browser)
            except FetchError as e:
                print(f"[{retailer.name}] recherche inaccessible ({e}) : {url}")
                continue
            finally:
                self._pause()
            links = [u for u in extract_product_links(html, url) if matches_keywords(u, search.get("keywords", self.keywords))]
            links = links[: self.max_discovered]
            first_run = not self.store.search_seen(url)
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
                    format_alert("nouveau", retailer.name, row["name"], u, row["status"] or "inconnu", row["price"])
                )
                self._pause()

    def check(self, url: str, label: str | None = None) -> None:
        retailer = retailer_for_url(url)
        if retailer.needs_browser and self.fetcher.browser_mode == "never":
            return  # ex. Cultura sur GitHub : bloqué sans navigateur, laissé au PC
        self.store.add_product(url, retailer.key, label)
        if ean_search(url):
            return self.check_ean_search(url, label)
        try:
            html = self.fetcher.get(url, retailer.needs_browser)
        except FetchError as e:
            self.store.record_error(url, retailer.key, str(e))
            print(f"[{retailer.name}] ⚠ {e} : {url}")
            return
        if retailer.use_keywords:
            av = parse_availability(html, retailer.in_stock_keywords, retailer.out_of_stock_keywords)
        else:
            av = parse_availability(html)
        name = label or av.name
        old = self.store.record(url, retailer.key, av.status, name, av.price)
        print(f"{time.strftime('%H:%M:%S')} [{retailer.name}] {av.status:<11} ({av.source or '-'}) {name or url}", flush=True)
        # old == "" : premier relevé du produit, on enregistre sans alerter.
        if old and should_alert(old, av.status):
            self.notifier.send(format_alert("stock", retailer.name, name, url, av.status, av.price))
        if retailer.key in PROXIMIS_RETAILERS:
            restock = self.store.set_restock(url, proximis_restock(html))
            if restock and old:
                self.notifier.send(format_restock_alert(retailer.name, name, url, restock))
        if self.location and retailer.key in STORE_RETAILERS and av.status != UNKNOWN:
            self.check_stores(url, retailer, name, html)

    def check_ean_search(self, url: str, label: str | None) -> None:
        """Recherche par code-barres (produit sans fiche en ligne) : on guette l'apparition
        d'une fiche, puis on la suit comme les autres produits."""
        ean = ean_search(url)
        retailer = retailer_for_url(url)
        row = self.store.get(url)
        if row is not None and row["found_url"]:
            return self.check(row["found_url"], label)  # fiche déjà trouvée : on suit directement la fiche
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
                if ean in self.fetcher.get(link, retailer.needs_browser):
                    found = link
                    break
            except FetchError:
                continue
        first = self.store.get(url)["last_check"] is None
        self.store.record(url, retailer.key, "en_stock" if found else "inconnu", label, None)
        appeared = self.store.set_found(url, found)
        print(f"[{retailer.name}] recherche {ean} : {'fiche trouvée ' + found if found else 'aucune fiche'}")
        if found:
            if appeared and not first:
                self.notifier.send(
                    f"🆕 FICHE EN LIGNE chez {retailer.name} : {label or ean}\n{found}"
                )
            self.check(found, label)

    def check_stores(self, url: str, retailer, name: str | None, html: str | None = None) -> None:
        now = time.time()
        # Stock magasin moins souvent que le stock en ligne, et pause après une erreur :
        # les API de stock limitent les demandes répétées.
        if now < self._store_pause.get(retailer.key, 0):
            return
        if now - self._store_last.get(url, 0) < self.store_interval:
            return
        self._store_last[url] = now
        try:
            if retailer.key == "cultura":
                stocks = cultura_store_stock(self.fetcher, url, str(self.location), self.radius_km)
            else:
                if self._coords is None:
                    self._coords = geocode(str(self.location))
                stocks = proximis_store_stock(url, *self._coords, radius_km=self.radius_km, html=html)
        except FetchError as e:
            self._store_pause[retailer.key] = time.time() + self.store_backoff
            print(f"[{retailer.name}] ⚠ magasins : {e} — stock magasin en pause {self.store_backoff // 60:.0f} min", flush=True)
            return
        newly = self.store.record_store_stock(url, retailer.key, name, stocks)
        in_stock = sum(1 for s in stocks if s.in_stock)
        incoming = sum(1 for s in stocks if s.incoming and not s.in_stock)
        print(f"    magasins à {self.radius_km} km : {in_stock}/{len(stocks)} en stock, {incoming} en arrivage")
        if newly:
            self.notifier.send(format_store_alert(retailer.name, name, url, newly))

    def _products(self) -> dict[str, str | None]:
        configured = {p["url"]: p.get("label") for p in self.cfg["products"]}
        if not self.exclude_watchlist:
            configured.update({p["url"]: p.get("label") for p in self.cfg["watchlist"]})
        return configured

    def run_watchlist(self) -> None:
        for p in self.cfg["watchlist"]:
            self.check(p["url"], p.get("label"))
            self._pause()

    def run_once(self) -> None:
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
