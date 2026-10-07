"""Création automatique des salons de région sur votre serveur Discord (avec un bot).

Pour chaque région (et le 06) : un rôle, un salon privé visible de ce seul rôle, un webhook ;
la question d'accueil « Quelle est ta région ? » reçoit une réponse par région. Relancer le
programme ne crée pas de doublons : ce qui existe déjà est réutilisé.

À la fin, webhooks-regions.txt contient le texte à coller dans le secret GitHub
POKEWATCH_ZONE_WEBHOOKS. Le jeton du bot reste sur ce PC (bot-token.txt).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

from .regions import REGIONS

API = "https://discord.com/api/v10"
VIEW, SEND, HISTORY, WEBHOOKS = 1 << 10, 1 << 11, 1 << 16, 1 << 29
CATEGORY = "🗺️ Alertes régions"
HOOK_NAME = "Pokémon Watch"
ZONES = [("06", "06", "alertes-06", "🌴")] + [(k, label, salon, emoji) for k, label, salon, emoji, _ in REGIONS]


class Discord:
    def __init__(self, token: str) -> None:
        self.token = token

    def __call__(self, method: str, path: str, body=None):
        for _ in range(5):
            req = urllib.request.Request(
                API + path, method=method,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Authorization": f"Bot {self.token}", "Content-Type": "application/json",
                         "User-Agent": "DiscordBot (https://github.com/padelup06/pokemon-watch, 1.0)"},
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    text = r.read().decode()
                    return json.loads(text) if text else None
            except urllib.error.HTTPError as e:
                if e.code == 429:  # trop de demandes : Discord dit combien attendre
                    time.sleep(float(json.loads(e.read().decode() or "{}").get("retry_after", 2)) + 0.5)
                    continue
                raise RuntimeError(f"Discord {method} {path} : HTTP {e.code} {e.read().decode()[:300]}") from e
        raise RuntimeError("Discord : trop de demandes, réessayez dans une minute")


def _snowflake(i: int) -> str:
    """Identifiant temporaire pour une nouvelle question/réponse d'accueil (format Discord)."""
    return str(((int(time.time() * 1000) - 1420070400000) << 22) + i)


def setup(api, guild_id: str, log=print) -> dict[str, str]:
    me = api("GET", "/users/@me")
    roles = {r["name"]: r for r in api("GET", f"/guilds/{guild_id}/roles")}
    channels = api("GET", f"/guilds/{guild_id}/channels")
    by_name = {c["name"]: c for c in channels}

    cat = next((c for c in channels if c["type"] == 4 and c["name"] == CATEGORY), None)
    if cat is None:
        cat = api("POST", f"/guilds/{guild_id}/channels", {
            "name": CATEGORY, "type": 4,
            "permission_overwrites": [{"id": guild_id, "type": 0, "deny": str(VIEW)},
                                      {"id": me["id"], "type": 1, "allow": str(VIEW | WEBHOOKS)}],
        })
        log(f"Catégorie créée : {CATEGORY}")

    hooks: dict[str, str] = {}
    role_ids: dict[str, str] = {}
    for key, label, salon, _emoji in ZONES:
        role = roles.get(label)
        if role is None:
            role = api("POST", f"/guilds/{guild_id}/roles", {"name": label, "mentionable": False})
            log(f"Rôle créé : {label}")
        role_ids[key] = role["id"]
        chan = by_name.get(salon)
        if chan is None:
            chan = api("POST", f"/guilds/{guild_id}/channels", {
                "name": salon, "type": 0, "parent_id": cat["id"],
                "topic": f"Alertes magasin Pokémon — {label}",
                "permission_overwrites": [
                    {"id": guild_id, "type": 0, "deny": str(VIEW)},
                    {"id": role["id"], "type": 0, "allow": str(VIEW | HISTORY), "deny": str(SEND)},
                    {"id": me["id"], "type": 1, "allow": str(VIEW | SEND | WEBHOOKS)},
                ],
            })
            log(f"Salon créé : #{salon} (visible du rôle {label})")
        hook = next((h for h in api("GET", f"/channels/{chan['id']}/webhooks")
                     if h.get("name") == HOOK_NAME and h.get("token")), None)
        if hook is None:
            hook = api("POST", f"/channels/{chan['id']}/webhooks", {"name": HOOK_NAME})
            log(f"Webhook créé dans #{salon}")
        hooks[key] = f"https://discord.com/api/webhooks/{hook['id']}/{hook['token']}"

    try:
        _onboarding(api, guild_id, role_ids, log)
    except RuntimeError as e:
        log(f"⚠ Question d'accueil non mise à jour automatiquement ({e}).\n"
            "  Ajoutez les régions à la main : Paramètres du serveur > Processus d'accueil > Questions.")
    return hooks


# Discord limite le nombre de réponses d'une question posée avant l'entrée sur le serveur
# (14 refusées) : deux questions, moitié sud (avec le 06) et moitié nord.
GROUPS = [
    ("Quelle est ta région ? (moitié sud)", ["06", "paca", "cor", "occ", "naq", "ara"]),
    ("Quelle est ta région ? (moitié nord)", ["idf", "hdf", "ge", "nor", "bre", "pdl", "cvl", "bfc"]),
]


def _onboarding(api, guild_id: str, role_ids: dict[str, str], log) -> None:
    ob = api("GET", f"/guilds/{guild_id}/onboarding")
    prompts = ob.get("prompts", [])
    regional = [p for p in prompts if "région" in (p.get("title") or "").lower()]
    others = [p for p in prompts if p not in regional]
    old_opts = {rid: o for p in regional for o in p.get("options", []) for rid in o.get("role_ids", [])}
    info = {key: (label, emoji) for key, label, _salon, emoji in ZONES}
    n = 0
    new_prompts = []
    for i, (title, keys) in enumerate(GROUPS):
        existing = next((p for p in regional if p.get("title") == title), None) or (regional[i] if i < len(regional) else None)
        options = []
        for key in keys:
            label, emoji = info[key]
            o = old_opts.get(role_ids[key])
            n += 1
            options.append({
                "id": o["id"] if o else _snowflake(n), "title": "06 – Alpes-Maritimes" if key == "06" else label,
                "description": "", "role_ids": [role_ids[key]], "channel_ids": [], "emoji_name": emoji,
            })
        new_prompts.append({"id": existing["id"] if existing else _snowflake(100 + i), "type": 0, "title": title,
                            "options": options, "single_select": False, "required": False, "in_onboarding": True})
    clean = [{k: p[k] for k in ("id", "type", "title", "options", "single_select", "required", "in_onboarding") if k in p}
             for p in others] + new_prompts
    api("PUT", f"/guilds/{guild_id}/onboarding", {
        "prompts": clean, "default_channel_ids": ob.get("default_channel_ids", []),
        "enabled": ob.get("enabled", True), "mode": ob.get("mode", 0),
    })
    log("Questions d'accueil : « moitié sud » (06, PACA, Corse, Occitanie, Nouvelle-Aquitaine, "
        "Auvergne-Rhône-Alpes) et « moitié nord » (les 8 autres régions).")


def main() -> int:
    token = open("bot-token.txt", encoding="utf-8").read().strip()
    api = Discord(token)
    guilds = api("GET", "/users/@me/guilds")
    if not guilds:
        print("Le bot n'est sur aucun serveur : invitez-le d'abord (lien OAuth2, permission Administrateur).")
        return 1
    guild = guilds[0]
    if len(guilds) > 1:
        for i, g in enumerate(guilds, 1):
            print(f"  {i}. {g['name']}")
        guild = guilds[int(input("Numéro du serveur : ")) - 1]
    print(f"Serveur : {guild['name']}\n")
    hooks = setup(api, guild["id"])
    with open("webhooks-regions.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(f"{k}={v}" for k, v in hooks.items()) + "\n")
    with open("webhook-06.txt", "w", encoding="utf-8") as f:
        f.write(hooks["06"] + "\n")
    print(f"\n✅ Terminé : {len(hooks)} salons prêts.")
    print("Copiez TOUT le contenu de webhooks-regions.txt dans le secret GitHub POKEWATCH_ZONE_WEBHOOKS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
