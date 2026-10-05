"""Boucle de surveillance : découverte de nouveaux produits + relevé des stocks."""

from __future__ import annotations

import os
import random
import re
import time
import tomllib
from html import unescape
from urllib.parse import urljoin

from .fetch import FetchError, Fetcher
from .instore import PROXIMIS_RETAILERS, geocode, proximis_store_stock
from .notify import Notifier, format_alert, format_store_alert, should_alert
from .parse import UNKNOWN, parse_availability
from .retailers import retailer_for_url
from .store import Store

ENV_OVERRIDES = {
    "POKEWATCH_DISCORD_WEBHOOK": "discord_webhook",
    "POKEWATCH_TELEGRAM_TOKEN": "telegram_bot_token",
    "POKEWATCH_TELEGRAM_CHAT_ID": "telegram_chat_id",
}


def load_config(path: str) -> dict:
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
    return cfg


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


def matches_keywords(url: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    slug = url.lower().replace("%c3%a9", "e").replace("é", "e")
    return any(k.lower().replace("é", "e") in slug for k in keywords)


class Watcher:
    def __init__(self, cfg: dict) -> None:
        s = cfg["settings"]
        self.cfg = cfg
        self.store = Store(s.get("database", "pokewatch.db"))
        self.fetcher = Fetcher(s.get("browser", "auto"), headless=not s.get("browser_visible", False))
        self.notifier = Notifier(cfg["alerts"])
        self.delay = (float(s.get("min_delay_seconds", 2)), float(s.get("max_delay_seconds", 6)))
        self.keywords = s.get("keywords", ["pokemon"])
        self.max_discovered = int(s.get("max_products_per_search", 40))
        self.location = s.get("code_postal") or s.get("ville")
        self.radius_km = int(s.get("rayon_km", 30))
        self._coords: tuple[float, float] | None = None

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
            if first_run:
                continue  # premier passage : on constitue la base sans spammer
            for u in new:
                self.notifier.send(format_alert("nouveau", retailer.name, None, u, "inconnu", None))

    def check(self, url: str, label: str | None = None) -> None:
        retailer = retailer_for_url(url)
        self.store.add_product(url, retailer.key, label)
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
        print(f"[{retailer.name}] {av.status:<11} ({av.source or '-'}) {name or url}")
        # old == "" : premier relevé du produit, on enregistre sans alerter.
        if old and should_alert(old, av.status):
            self.notifier.send(format_alert("stock", retailer.name, name, url, av.status, av.price))
        if self.location and retailer.key in PROXIMIS_RETAILERS and av.status != UNKNOWN:
            self.check_stores(url, retailer, name)

    def check_stores(self, url: str, retailer, name: str | None) -> None:
        try:
            if self._coords is None:
                self._coords = geocode(str(self.location))
            stocks = proximis_store_stock(url, *self._coords, radius_km=self.radius_km)
        except FetchError as e:
            print(f"[{retailer.name}] ⚠ magasins : {e}")
            return
        newly = self.store.record_store_stock(url, retailer.key, name, stocks)
        in_stock = [s for s in stocks if s.in_stock]
        print(f"    magasins à {self.radius_km} km : {len(in_stock)}/{len(stocks)} en stock")
        if newly:
            self.notifier.send(format_store_alert(retailer.name, name, url, newly))

    def run_once(self) -> None:
        self.discover()
        configured = {p["url"]: p.get("label") for p in self.cfg["products"]}
        urls = list(configured) + [u for u in sorted(self.store.known_urls()) if u not in configured]
        for url in urls:
            self.check(url, configured.get(url))
            self._pause()

    def run_forever(self) -> None:
        s = self.cfg["settings"]
        interval = float(s.get("interval_minutes", 10)) * 60
        jitter = float(s.get("jitter_seconds", 60))
        try:
            while True:
                start = time.time()
                self.run_once()
                wait = max(30.0, interval - (time.time() - start) + random.uniform(-jitter, jitter))
                print(f"— prochain passage dans {wait / 60:.1f} min —", flush=True)
                time.sleep(wait)
        finally:
            self.fetcher.close()
