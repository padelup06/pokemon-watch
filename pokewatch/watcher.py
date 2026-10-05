"""Boucle de surveillance : découverte de nouveaux produits + relevé des stocks."""

from __future__ import annotations

import os
import random
import re
import time
import tomllib
from html import unescape

from .fetch import FetchError, Fetcher
from .notify import Notifier, format_alert, should_alert
from .parse import parse_availability
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
    cfg.setdefault("products", [])
    cfg.setdefault("searches", [])
    return cfg


def extract_product_links(html: str, base_url: str) -> list[str]:
    retailer = retailer_for_url(base_url)
    # Les liens sont souvent relatifs : on les rend absolus avant d'appliquer le motif.
    origin = re.match(r"https?://[^/]+", base_url).group(0)
    text = unescape(html).replace('href="/', f'href="{origin}/').replace("href='/", f"href='{origin}/")
    text = text.replace("\\/", "/")  # URLs dans du JSON embarqué
    seen: dict[str, None] = {}
    for m in retailer.product_url.finditer(text):
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
        self.fetcher = Fetcher(s.get("browser", "auto"))
        self.notifier = Notifier(cfg["alerts"])
        self.delay = (float(s.get("min_delay_seconds", 2)), float(s.get("max_delay_seconds", 6)))
        self.keywords = s.get("keywords", ["pokemon"])
        self.max_discovered = int(s.get("max_products_per_search", 40))

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
        av = parse_availability(html, retailer.in_stock_keywords, retailer.out_of_stock_keywords)
        name = label or av.name
        old = self.store.record(url, retailer.key, av.status, name, av.price)
        print(f"[{retailer.name}] {av.status:<11} ({av.source or '-'}) {name or url}")
        if old is not None and should_alert(old, av.status):
            self.notifier.send(format_alert("stock", retailer.name, name, url, av.status, av.price))

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
