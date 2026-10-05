"""Canaux d'alerte : console, Discord (webhook), Telegram (bot)."""

from __future__ import annotations

import json
import urllib.request

from .parse import IN_STOCK, PREORDER

STATUS_LABEL = {
    "en_stock": "✅ EN STOCK",
    "precommande": "🕒 PRÉCOMMANDE",
    "rupture": "❌ rupture",
    "inconnu": "❔ inconnu",
}


def format_alert(kind: str, retailer: str, name: str | None, url: str, status: str, price: float | None) -> str:
    title = name or url
    price_txt = f" — {price:.2f} €" if price is not None else ""
    if kind == "nouveau":
        head = f"🆕 Nouveau produit chez {retailer}"
    else:
        head = f"{STATUS_LABEL.get(status, status)} chez {retailer}"
    return f"{head}\n{title}{price_txt}\n{url}"


def format_store_alert(retailer: str, name: str | None, url: str, stores) -> str:
    in_stock = [st for st in stores if st.in_stock]
    incoming = [st for st in stores if not st.in_stock]
    head = "🏬 EN STOCK EN MAGASIN" if in_stock else "🚚 ARRIVAGE EN MAGASIN"
    lines = [f"{head} — {retailer}", name or url]
    for st in (in_stock + incoming)[:10]:
        dist = f" ({st.distance_km:g} km)" if st.distance_km is not None else ""
        lines.append(f"  • {st.name}{dist} : {st.label}")
    if len(stores) > 10:
        lines.append(f"  • … et {len(stores) - 10} autres magasins")
    lines.append(url)
    return "\n".join(lines)


def format_restock_alert(retailer: str, name: str | None, url: str, restock: str) -> str:
    return f"📦 RÉASSORT PRÉVU chez {retailer} : {restock}\n{name or url}\n{url}"


def should_alert(old: str, new: str) -> bool:
    """On n'alerte que quand un produit devient achetable."""
    return new in (IN_STOCK, PREORDER) and old not in (IN_STOCK, PREORDER)


def _post_json(url: str, payload: dict) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        # Discord (Cloudflare) refuse les requêtes avec l'user-agent par défaut de Python (erreur 1010).
        headers={"Content-Type": "application/json", "User-Agent": "pokemon-watch (+https://github.com/padelup06/pokemon-watch)"},
    )
    urllib.request.urlopen(req, timeout=15).read()


class Notifier:
    def __init__(self, cfg: dict) -> None:
        self.discord = cfg.get("discord_webhook") or None
        self.tg_token = cfg.get("telegram_bot_token") or None
        self.tg_chat = cfg.get("telegram_chat_id") or None

    def send(self, message: str) -> None:
        print(f"\n🔔 {message}\n", flush=True)
        if self.discord:
            try:
                _post_json(self.discord, {"content": message})
            except Exception as e:
                print(f"[discord] échec : {e}")
        if self.tg_token and self.tg_chat:
            try:
                _post_json(
                    f"https://api.telegram.org/bot{self.tg_token}/sendMessage",
                    {"chat_id": self.tg_chat, "text": message, "disable_web_page_preview": False},
                )
            except Exception as e:
                print(f"[telegram] échec : {e}")
