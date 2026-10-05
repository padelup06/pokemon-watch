"""Profils des enseignes surveillées.

Chaque profil donne :
- les mots-clés qui signalent une dispo / une rupture sur une fiche produit
  (utilisés seulement si la page n'expose pas de données schema.org) ;
- un motif d'URL de fiche produit, pour repérer les nouveautés sur une page
  de recherche ou de catégorie.

Les sites changent régulièrement : si une enseigne renvoie toujours
"inconnu", c'est ici qu'il faut ajuster.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class Retailer:
    key: str
    name: str
    domains: tuple[str, ...]
    product_url: re.Pattern
    in_stock_keywords: list[str] = field(default_factory=list)
    out_of_stock_keywords: list[str] = field(default_factory=list)
    # Sites protégés par un anti-bot (DataDome, Cloudflare...) : un simple
    # appel HTTP est souvent bloqué, le navigateur headless passe mieux.
    needs_browser: bool = False


_COMMON_IN = ["Ajouter au panier", "En stock", "Disponible en ligne", "Livraison à domicile"]
_COMMON_OUT = [
    "Rupture de stock",
    "Épuisé",
    "Produit indisponible",
    "Indisponible en ligne",
    "M'alerter",
    "Me prévenir",
    "Bientôt disponible",
]

RETAILERS: dict[str, Retailer] = {
    r.key: r
    for r in [
        Retailer(
            key="cultura",
            name="Cultura",
            domains=("cultura.com",),
            product_url=re.compile(r"https://www\.cultura\.com/p-[^\"'?#\s]+\.html"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
        ),
        Retailer(
            key="joueclub",
            name="JouéClub",
            domains=("joueclub.fr",),
            product_url=re.compile(r"https://www\.joueclub\.fr/[^\"'?#\s]+\.html"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
        ),
        Retailer(
            key="lagranderecre",
            name="La Grande Récré",
            domains=("lagranderecre.fr",),
            product_url=re.compile(r"https://www\.lagranderecre\.fr/[^\"'?#\s]+\.html"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
        ),
        Retailer(
            key="auchan",
            name="Auchan",
            domains=("auchan.fr",),
            product_url=re.compile(r"https://www\.auchan\.fr/[^\"'?#\s]+/pr-[A-Z0-9]+"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT + ["Victime de son succès"],
            needs_browser=True,
        ),
        Retailer(
            key="carrefour",
            name="Carrefour",
            domains=("carrefour.fr",),
            product_url=re.compile(r"https://www\.carrefour\.fr/p/[^\"'?#\s]+"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
            needs_browser=True,
        ),
        Retailer(
            key="leclerc",
            name="E.Leclerc",
            domains=("e.leclerc",),
            product_url=re.compile(r"https://www\.e\.leclerc/fp/[^\"'?#\s]+"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
            needs_browser=True,
        ),
        Retailer(
            key="fnac",
            name="Fnac",
            domains=("fnac.com",),
            product_url=re.compile(r"https://www\.fnac\.com/a\d+/[^\"'?#\s]+"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
            needs_browser=True,
        ),
        Retailer(
            key="micromania",
            name="Micromania",
            domains=("micromania.fr",),
            product_url=re.compile(r"https://www\.micromania\.fr/[^\"'?#\s]+\.html"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
        ),
    ]
}

GENERIC = Retailer(
    key="autre",
    name="Autre",
    domains=(),
    product_url=re.compile(r"$^"),
    in_stock_keywords=_COMMON_IN,
    out_of_stock_keywords=_COMMON_OUT,
)


def retailer_for_url(url: str) -> Retailer:
    host = (urlparse(url).hostname or "").lower()
    for r in RETAILERS.values():
        if any(host == d or host.endswith("." + d) for d in r.domains):
            return r
    return GENERIC
