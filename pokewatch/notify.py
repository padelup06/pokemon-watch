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
    price_txt = f" — {price:.2f} €" if price is not None else ""
    if kind == "nouveau":
        head = f"🆕 Nouveau produit chez {retailer} ({STATUS_LABEL.get(status, status)})"
    else:
        head = f"{STATUS_LABEL.get(status, status)} chez {retailer}"
    title = f"\n{name}{price_txt}" if name else ""
    return f"{head}{title}\n{url}"


def format_store_alert(retailer: str, name: str | None, url: str, stores) -> str:
    in_stock = [st for st in stores if st.in_stock]
    incoming = [st for st in stores if not st.in_stock]
    head = "🏬 EN STOCK EN MAGASIN" if in_stock else "🚚 ARRIVAGE EN MAGASIN"
    lines = [f"{head} — {retailer}", name or url]
    for st in (in_stock + incoming)[:10]:
        dist = f" ({st.distance_km:g} km)" if st.distance_km is not None else ""
        qty = ""
        if getattr(st, "qty", None):
            qty = f" — ~{st.qty}{'+' if st.qty_capped else ''} en stock"
        lines.append(f"  • {st.name}{dist} : {st.label}{qty}")
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


def _chunks(message: str, limit: int) -> list[str]:
    """Découpe un long message en morceaux, entre deux lignes."""
    parts, cur = [], ""
    for line in message.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + 1 + len(line) > limit:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    return parts or [""]


class Notifier:
    def __init__(self, cfg: dict) -> None:
        self.discord = cfg.get("discord_webhook") or None
        # Un salon Discord par zone (ex. {"06": webhook, "83": webhook}) pour les alertes magasin ;
        # le reste (en ligne, nouveautés, système) va dans le salon principal.
        self.zone_webhooks = {str(k): v for k, v in (cfg.get("zone_webhooks") or {}).items() if v}
        self.tg_token = cfg.get("telegram_bot_token") or None
        self.tg_chat = cfg.get("telegram_chat_id") or None

    def send(self, message: str, zone: str | None = None) -> None:
        print(f"\n🔔 {f'[{zone}] ' if zone else ''}{message}\n", flush=True)
        hook = self.zone_webhooks.get(zone or "") or self.discord
        if hook:
            try:
                for part in _chunks(message, 1900):  # Discord refuse les messages de plus de 2000 caractères
                    _post_json(hook, {"content": part})
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
