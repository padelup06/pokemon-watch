"""Récupération des pages : HTTP simple, ou navigateur headless (Playwright)
pour les sites protégés par un anti-bot."""

from __future__ import annotations

import gzip
import json
import random
import re
import urllib.error
import urllib.request
import zlib

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
]


class FetchError(Exception):
    pass


def fetch_http(url: str, timeout: float = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            enc = resp.headers.get("Content-Encoding", "")
            charset = resp.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as e:
        # 403/429 = presque toujours l'anti-bot
        raise FetchError(f"HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FetchError(str(getattr(e, "reason", e))) from e
    except Exception as e:  # réponse coupée (IncompleteRead), en-tête invalide…
        raise FetchError(f"réponse illisible : {e!r}") from e
    try:
        if enc == "gzip":
            body = gzip.decompress(body)
        elif enc == "deflate":
            try:
                body = zlib.decompress(body)
            except zlib.error:
                body = zlib.decompress(body, -zlib.MAX_WBITS)  # deflate « brut »
        try:
            return body.decode(charset, errors="replace")
        except LookupError:  # jeu de caractères inconnu (ex. « utf8mb4 »)
            return body.decode("utf-8", errors="replace")
    except (OSError, EOFError, zlib.error) as e:
        raise FetchError(f"réponse compressée illisible : {e!r}") from e


def resolve_url(url: str, timeout: float = 20) -> str | None:
    """Adresse finale après redirections, ou None si la page n'existe pas (404/410)."""
    req = urllib.request.Request(url, headers={"User-Agent": random.choice(USER_AGENTS), "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.geturl()
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return None
        raise FetchError(f"HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FetchError(str(getattr(e, "reason", e))) from e
    except Exception as e:
        raise FetchError(f"réponse illisible : {e!r}") from e


class BrowserFetcher:
    """Navigateur Chromium (invisible ou en fenêtre) réutilisé entre les requêtes.

    Un seul onglet sert à toutes les pages (pas de nouvel onglet à chaque vérification)
    et, en mode fenêtre, celle-ci est réduite dans la barre des tâches dès le départ.

    Nécessite : pip install playwright && playwright install chromium
    """

    # Une fenêtre réduite ne doit pas être mise au ralenti par Chrome (pages et minuteries).
    _ARGS = [
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
    ]

    def __init__(self, headless: bool = True, minimized: bool = True) -> None:
        self.headless = headless
        self.minimized = minimized
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self.last_url: str | None = None

    def _start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise FetchError(
                "Playwright non installé (pip install playwright && playwright install chromium)"
            ) from e
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(headless=self.headless, args=self._ARGS)
        except Exception as e:
            self.close()
            raise FetchError(f"navigateur impossible à démarrer : {e}") from e
        # On garde l'user-agent réel du navigateur : un faux user-agent incohérent
        # avec le reste de l'empreinte est justement ce que repèrent les anti-robots.
        self._context = self._browser.new_context(locale="fr-FR", viewport={"width": 1366, "height": 900})
        self._page = self._context.new_page()
        if not self.headless and self.minimized:
            self._minimize()

    def _minimize(self) -> None:
        try:
            cdp = self._context.new_cdp_session(self._page)
            wid = cdp.send("Browser.getWindowForTarget")["windowId"]
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}})
            state = cdp.send("Browser.getWindowBounds", {"windowId": wid})["bounds"].get("windowState")
            if state != "minimized":
                # Réduction refusée par le système : on range la fenêtre hors de l'écran.
                cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"left": -32000, "top": -32000}})
        except Exception:
            pass  # pas grave : la fenêtre reste simplement visible

    def _tab(self):
        for attempt in (1, 2):
            try:
                if self._context is None:
                    self._start()
                if self._page is None or self._page.is_closed():
                    # onglet fermé à la main : on en rouvre un, toujours réduit
                    self._page = self._context.new_page()
                    if not self.headless and self.minimized:
                        self._minimize()
                return self._page
            except FetchError:
                raise
            except Exception as e:
                # Fenêtre fermée à la main ou navigateur planté : on repart d'un navigateur neuf.
                self.close()
                if attempt == 2:
                    raise FetchError(f"navigateur indisponible : {e}") from e

    def _lost(self, e: Exception) -> None:
        if re.search(r"has been closed|Target closed|Browser closed|disconnected", str(e), re.I):
            self.close()  # relancé au prochain appel

    def fetch(self, url: str, timeout: float = 30) -> str:
        page = self._tab()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass  # certaines pages ne sont jamais "idle" (trackers) : on prend ce qu'on a
            # Vérification « Un instant… » (Cloudflare) : dans une vraie fenêtre, elle se valide
            # généralement seule en quelques secondes. On lui laisse jusqu'à 20 s.
            for _ in range(20):
                if not re.search(r"un instant|just a moment", page.title() or "", re.I):
                    break
                page.wait_for_timeout(1000)
            self.last_url = page.url  # adresse finale (une recherche peut ouvrir directement la fiche)
            return page.content()
        except Exception as e:
            self._lost(e)
            raise FetchError(str(e)) from e

    def fetch_text(self, url: str, origin: str, timeout: float = 30, headers: dict | None = None) -> tuple[int, str]:
        """Comme fetch_json, mais renvoie (code HTTP, texte brut)."""
        page = self._tab()
        if not page.url.startswith(origin):
            try:
                page.goto(origin + "/", wait_until="domcontentloaded", timeout=timeout * 1000)
                page.wait_for_timeout(3000)
            except Exception as e:
                self._lost(e)
                raise FetchError(str(e)) from e
        try:
            return tuple(page.evaluate(
                """async ([u, h]) => { const r = await fetch(u, {credentials: "include", headers: h}); return [r.status, await r.text()]; }""",
                [url, headers or {}],
            ))
        except Exception as e:
            self._lost(e)
            raise FetchError(str(e)) from e

    def fetch_json(self, url: str, origin: str, timeout: float = 30):
        """Appel d'API fait depuis une page du site (cookies et protections du site
        inclus), comme le ferait la page elle-même."""
        page = self._tab()
        if not page.url.startswith(origin):
            try:
                page.goto(origin + "/", wait_until="domcontentloaded", timeout=timeout * 1000)
                page.wait_for_timeout(3000)
            except Exception as e:
                self._lost(e)
                raise FetchError(str(e)) from e
        try:
            status, text = page.evaluate(
                """async (u) => {
                    const r = await fetch(u, {credentials: "include", headers: {"Accept": "application/json"}});
                    return [r.status, await r.text()];
                }""",
                url,
            )
        except Exception as e:
            self._lost(e)
            raise FetchError(str(e)) from e
        if status != 200:
            raise FetchError(f"HTTP {status}")
        try:
            return json.loads(text)
        except ValueError as e:
            raise FetchError("réponse non JSON (page anti-robot ?)") from e

    def close(self) -> None:
        for step in (self._browser and self._browser.close, self._pw and self._pw.stop):
            if step:
                try:
                    step()
                except Exception:
                    pass  # navigateur déjà fermé ou planté
        self._pw = self._browser = self._context = self._page = None


class Fetcher:
    def __init__(self, browser_mode: str = "auto", headless: bool = True, minimized: bool = True) -> None:
        """browser_mode : "never", "auto" (si l'enseigne l'exige ou si HTTP échoue), "always".

        headless=False ouvre une vraie fenêtre de navigateur : plus lent, mais passe
        beaucoup mieux les anti-robots (DataDome sur la Fnac, Cloudflare sur Cultura).
        """
        self.browser_mode = browser_mode
        self._browser = BrowserFetcher(headless, minimized)

    def get(self, url: str, needs_browser: bool = False) -> str:
        if self.browser_mode == "always" or (self.browser_mode == "auto" and needs_browser):
            return self._browser.fetch(url)
        try:
            return fetch_http(url)
        except FetchError:
            if self.browser_mode == "auto":
                return self._browser.fetch(url)
            raise

    def fetch_json(self, url: str, origin: str):
        return self._browser.fetch_json(url, origin)

    def fetch_text(self, url: str, origin: str, headers: dict | None = None) -> tuple[int, str]:
        return self._browser.fetch_text(url, origin, headers=headers)

    @property
    def last_url(self) -> str | None:
        """Adresse finale de la dernière page ouverte dans le navigateur (après redirection)."""
        return self._browser.last_url

    def close(self) -> None:
        self._browser.close()
