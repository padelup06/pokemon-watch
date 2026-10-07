"""Récapitulatif du matin et surveillance du PC (lancés depuis GitHub à chaque passage).

- Récap : une fois par jour, vers `recap_hour` (heure de Paris), un message Discord qui
  dit, produit par produit, où il y en a, combien, et l'évolution depuis la veille.
- PC : le PC envoie « je tourne » toutes les 5 min sur ntfy.sh ; GitHub prévient sur
  Discord si plus rien n'arrive depuis `pc_silence_minutes`, puis à la reprise.
  L'adresse ntfy est tirée du webhook Discord, connu des deux côtés : rien à configurer.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from .fetch import FetchError
from .instore import QUANTITY_RETAILERS, proximis_estimate_quantities
from .retailers import retailer_for_url

PARIS = ZoneInfo("Europe/Paris")
NTFY = "https://ntfy.sh"
_JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
_MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
_ONLINE = {"en_stock": "✅ en stock", "precommande": "🕒 précommande", "rupture": "❌ rupture", "inconnu": "❔ pas de fiche"}


def _topic(webhook: str) -> str:
    return "pokewatch" + hashlib.sha256(webhook.strip().encode()).hexdigest()[:24]


# ---------------------------------------------------------------- PC : « je tourne »

def start_heartbeat(webhook: str | None, every: float = 300) -> None:
    """Sur le PC : signale toutes les `every` secondes que la surveillance tourne."""
    if not webhook:
        return
    url = f"{NTFY}/{_topic(webhook)}"

    def beat() -> None:
        while True:
            try:
                urllib.request.urlopen(urllib.request.Request(url, data=b"pc ok", method="POST"), timeout=15).read()
            except Exception:
                pass  # pas d'internet : GitHub s'en apercevra, c'est justement le but
            time.sleep(every)

    threading.Thread(target=beat, daemon=True).start()


def check_pc(watcher, silence_minutes: float = 15) -> None:
    """Sur GitHub : alerte si le PC ne s'est pas signalé depuis `silence_minutes`."""
    webhook = watcher.cfg["alerts"].get("discord_webhook")
    if not webhook:
        return
    store = watcher.store
    try:
        with urllib.request.urlopen(f"{NTFY}/{_topic(webhook)}/json?poll=1&since=12h", timeout=20) as r:
            times = [json.loads(line).get("time", 0) for line in r.read().decode().splitlines() if line.strip()]
    except Exception as e:
        print(f"[PC] état inconnu (ntfy injoignable : {e})")
        return
    if times:
        store.set_meta("pc_last_seen", str(max(times)))
    last = store.get_meta("pc_last_seen")
    if not last:
        return  # le PC ne s'est encore jamais signalé : rien à surveiller
    last = float(last)
    silent = time.time() - last > silence_minutes * 60
    down = store.get_meta("pc_state") == "down"
    since = datetime.fromtimestamp(last, PARIS).strftime("%H:%M")
    if silent and not down:
        watcher.notifier.send(
            f"⚠️ La surveillance du PC ne tourne plus (dernier signe de vie à {since}).\n"
            "PC éteint, en veille, sans internet, ou fenêtre noire fermée ? Relancez 3-surveiller.bat.\n"
            "GitHub continue de surveiller toutes les 5 min (sauf Cultura, Carrefour, Cdiscount)."
        )
        store.set_meta("pc_state", "down")
    elif not silent and down:
        watcher.notifier.send("✅ La surveillance du PC a repris.")
        store.set_meta("pc_state", "up")
    print(f"[PC] dernier signe de vie : {since}{' (silencieux)' if silent else ''}")


# ---------------------------------------------------------------- récap du matin

def _short(name: str, retailer: str) -> str:
    """« 30e anniv. — Mini Tin (LGR) — EAN 0196… » -> « 30e anniv. — Mini Tin (La Grande Récré) »."""
    name = re.sub(r"\s*—\s*EAN\s*\d+", "", name)
    name = re.sub(r"\s*\((?:LGR|Leclerc|Cultura|Carrefour|Cdiscount|JouéClub)\)\s*$", "", name)
    return f"{name} ({retailer})"


def maybe_send_recap(watcher, hour: int) -> None:
    now = datetime.now(PARIS)
    today = now.strftime("%Y-%m-%d")
    # Fenêtre de 3 h : un passage GitHub manqué ou retardé ne fait pas sauter le récap.
    if not (hour <= now.hour < hour + 3) or watcher.store.get_meta("recap_date") == today:
        return
    zones = watcher.zones if len(watcher.zones) > 1 else [None]
    yesterday = json.loads(watcher.store.get_meta("recap_qty") or "{}")
    today_qty: dict[str, int] = {}
    for z in zones:  # plusieurs zones : un récap par zone, dans le salon de la zone
        name = z["name"] if z else None
        watcher.notifier.send(build_recap(watcher, now, z, yesterday, today_qty), name)
    watcher.store.set_meta("recap_qty", json.dumps(today_qty))
    watcher.store.set_meta("recap_date", today)


def build_recap(watcher, now: datetime, zone: dict | None = None, yesterday: dict | None = None,
                today_qty: dict | None = None) -> str:
    from .watcher import ean_search, label_ean  # import local : watcher importe ce module

    store = watcher.store
    save = yesterday is None
    yesterday = json.loads(store.get_meta("recap_qty") or "{}") if yesterday is None else yesterday
    today_qty = {} if today_qty is None else today_qty
    where = f" — zone {zone['name']}" if zone else ""
    lines = [f"☀️ **Récap du matin**{where} — {_JOURS[now.weekday()]} {now.day} {_MOIS[now.month - 1]}"]
    nothing: list[str] = []
    no_page: dict[str, int] = {}
    for p in watcher.cfg["watchlist"]:
        url, label = p["url"], p.get("label")
        retailer = retailer_for_url(url)
        row = store.get(url)
        if retailer.needs_browser and watcher.fetcher.browser_mode == "never":
            continue  # Cultura, Carrefour… : vus seulement par le PC, pas d'info ici
        if ean_search(url):
            if not row or not row["found_url"]:
                no_page[retailer.name] = no_page.get(retailer.name, 0) + 1
                continue
            url, row = row["found_url"], store.get(row["found_url"])
        name = _short(label or (row["name"] if row else None) or url, retailer.name)
        status = (row["status"] if row else None) or "inconnu"
        in_zone = (lambda r: (r["zone"] or "") == zone["name"]) if zone else (lambda r: True)
        stores = [r for r in store.stores_in_stock(url) if in_zone(r)]
        incoming = [r for r in store.stores_incoming(url) if in_zone(r)]
        if not stores and not incoming and status not in ("en_stock", "precommande"):
            nothing.append(name)
            continue
        qty = {}
        if stores and retailer.key in QUANTITY_RETAILERS:
            try:
                z = zone or watcher.zones[0]
                qty = proximis_estimate_quantities(
                    url, *watcher.zone_coords(z), z["radius"], {s["store_id"] for s in stores}, ean=label_ean(label)
                )
            except FetchError as e:
                print(f"[récap] quantités non estimées pour {name} : {e}")
        lines.append(f"\n**{name}** — en ligne : {_ONLINE.get(status, status)}")
        for s in stores:
            key = f"{url}|{s['store_id']}"
            q = ""
            if s["store_id"] in qty:
                n, capped = qty[s["store_id"]]
                today_qty[key] = n
                q = f" : ~{n}{'+' if capped else ''}"
                if key in yesterday:
                    d = n - yesterday[key]
                    q += " (= hier)" if d == 0 else f" ({d:+d} depuis hier)"
            lines.append(f"  • {s['store_name']}{q}")
        for s in incoming:
            lines.append(f"  • 🚚 {s['store_name']} : arrivage")
    if nothing:
        lines.append("\nRien en stock :\n" + "\n".join(f"  • {n}" for n in nothing))
    if no_page:
        lines.append("Pas encore de fiche : " + ", ".join(f"{k} ({v})" for k, v in no_page.items()))
    lines.append("\n(Fnac : voir l'extension Chrome. Cultura, Carrefour, Cdiscount : suivis par le PC.)")
    if save:
        store.set_meta("recap_qty", json.dumps(today_qty))
    return "\n".join(lines)
