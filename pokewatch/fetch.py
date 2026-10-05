"""Récupération des pages : HTTP simple, ou navigateur headless (Playwright)
pour les sites protégés par un anti-bot."""

from __future__ import annotations

import gzip
import json
import random
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
    if enc == "gzip":
        body = gzip.decompress(body)
    elif enc == "deflate":
        body = zlib.decompress(body)
    return body.decode(charset, errors="replace")


class BrowserFetcher:
    """Navigateur Chromium (invisible ou en fenêtre) réutilisé entre les requêtes.

    Nécessite : pip install playwright && playwright install chromium
    """

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._api_pages: dict = {}
        self._pw = None
        self._browser = None
        self._context = None

    def _start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise FetchError(
                "Playwright non installé (pip install playwright && playwright install chromium)"
            ) from e
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        # On garde l'user-agent réel du navigateur : un faux user-agent incohérent
        # avec le reste de l'empreinte est justement ce que repèrent les anti-robots.
        self._context = self._browser.new_context(locale="fr-FR", viewport={"width": 1366, "height": 900})

    def fetch(self, url: str, timeout: float = 30) -> str:
        if self._context is None:
            self._start()
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass  # certaines pages ne sont jamais "idle" (trackers) : on prend ce qu'on a
            return page.content()
        except Exception as e:
            raise FetchError(str(e)) from e
        finally:
            page.close()

    def fetch_json(self, url: str, origin: str, timeout: float = 30):
        """Appel d'API fait depuis une page du site (cookies et protections du site
        inclus), comme le ferait la page elle-même."""
        if self._context is None:
            self._start()
        page = self._api_pages.get(origin)
        if page is None or page.is_closed():
            page = self._context.new_page()
            try:
                page.goto(origin + "/", wait_until="domcontentloaded", timeout=timeout * 1000)
                page.wait_for_timeout(3000)
            except Exception as e:
                page.close()
                raise FetchError(str(e)) from e
            self._api_pages[origin] = page
        try:
            status, text = page.evaluate(
                """async (u) => {
                    const r = await fetch(u, {credentials: "include", headers: {"Accept": "application/json"}});
                    return [r.status, await r.text()];
                }""",
                url,
            )
        except Exception as e:
            raise FetchError(str(e)) from e
        if status != 200:
            self._api_pages.pop(origin, None)
            page.close()
            raise FetchError(f"HTTP {status}")
        try:
            return json.loads(text)
        except ValueError as e:
            raise FetchError("réponse non JSON (page anti-robot ?)") from e

    def close(self) -> None:
        self._api_pages = {}
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._pw = self._browser = self._context = None


class Fetcher:
    def __init__(self, browser_mode: str = "auto", headless: bool = True) -> None:
        """browser_mode : "never", "auto" (si l'enseigne l'exige ou si HTTP échoue), "always".

        headless=False ouvre une vraie fenêtre de navigateur : plus lent, mais passe
        beaucoup mieux les anti-robots (DataDome sur la Fnac, Cloudflare sur Cultura).
        """
        self.browser_mode = browser_mode
        self._browser = BrowserFetcher(headless)

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

    def close(self) -> None:
        self._browser.close()
