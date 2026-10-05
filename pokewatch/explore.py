"""Exploration d'un site : ouvre une vraie fenêtre de navigateur sur une fiche
produit, vous laisse cliquer sur « disponibilité en magasin » et saisir votre
code postal, et enregistre les requêtes de données (XHR / fetch) que fait le
site. Le fichier produit sert à brancher le stock par magasin d'une nouvelle
enseigne (Fnac, Cultura...).

Les cookies et en-têtes d'authentification ne sont pas enregistrés.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

SKIP_HOSTS = (
    "google", "doubleclick", "facebook", "tiktok", "criteo", "abtasty", "didomi", "hotjar",
    "datadome", "captcha", "cloudflare", "contentsquare", "bing", "snapchat", "pinterest",
    "sentry", "newrelic", "optimizely", "trustpilot", "skeepers", "iadvize", "scalapay",
)
SECRET_HEADERS = {"cookie", "set-cookie", "authorization", "x-csrf-token", "x-xsrf-token"}


def _keep(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return not any(s in host for s in SKIP_HOSTS)


def explore(url: str, out_path: str, headless: bool = False, wait=None, launch_options: dict | None = None) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright non installé : pip install playwright && python -m playwright install chromium")
        return 1

    captured: list[dict] = []

    def on_response(resp):
        req = resp.request
        if req.resource_type not in ("xhr", "fetch") or not _keep(req.url):
            return
        try:
            body = resp.text()
        except Exception:
            body = None
        captured.append(
            {
                "method": req.method,
                "url": req.url,
                "request_headers": {k: v for k, v in req.headers.items() if k.lower() not in SECRET_HEADERS},
                "post_data": req.post_data,
                "status": resp.status,
                "content_type": resp.headers.get("content-type", ""),
                "body": body[:200_000] if body else body,
            }
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, **(launch_options or {}))
        page = browser.new_context(locale="fr-FR").new_page()
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        print(
            "\nUne fenêtre de navigateur est ouverte.\n"
            "  1. Acceptez les cookies si besoin.\n"
            "  2. Cliquez sur « Voir la disponibilité en magasin » / « Retrait en magasin ».\n"
            "  3. Tapez votre code postal et lancez la recherche, attendez la liste des magasins.\n"
            "  4. Revenez ici et appuyez sur Entrée.\n"
        )
        if wait:
            wait(page)  # utilisé par les tests pour piloter la page
        else:
            input("Entrée quand la liste des magasins est affichée… ")
        browser.close()

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"page": url, "requests": captured}, f, ensure_ascii=False, indent=1)
    print(f"{len(captured)} requêtes enregistrées dans {out_path} — envoyez-moi ce fichier.")
    return 0
