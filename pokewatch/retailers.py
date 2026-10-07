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
    # False quand le site expose toujours des données schema.org fiables : une page
    # sans ces données est alors une redirection (produit retiré), pas une fiche.
    use_keywords: bool = True
    # Nom du vendeur « maison » dans les offres schema.org : les offres des vendeurs
    # partenaires (marketplace) sont alors ignorées.
    own_seller: re.Pattern | None = None
    # Texte de la fiche qui prouve que l'enseigne vend elle-même : sans lui, les offres
    # schema.org sans nom de vendeur sont considérées comme venant de la marketplace.
    seller_marker: re.Pattern | None = None


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
            needs_browser=True,  # Cloudflare
        ),
        Retailer(
            key="joueclub",
            name="JouéClub",
            domains=("joueclub.fr",),
            # Les fiches produit finissent par le code EAN à 13 chiffres.
            product_url=re.compile(r"https://www\.joueclub\.fr/[a-z0-9-]+/[^\"'?#\s/]+-\d{13}\.html"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
            use_keywords=False,
        ),
        Retailer(
            key="lagranderecre",
            name="La Grande Récré",
            domains=("lagranderecre.fr",),
            # Au moins un dossier avant la fiche ; on écarte les pages magasins et éditoriales.
            product_url=re.compile(
                r"https://www\.lagranderecre\.fr/(?!magasins/|contenu/)(?:[^\"'?#\s/]+/)+[^\"'?#\s/]+\.html"
            ),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
            use_keywords=False,
        ),
        Retailer(
            key="carrefour",
            name="Carrefour",
            domains=("carrefour.fr",),
            product_url=re.compile(r"https://www\.carrefour\.fr/p/[^\"'?#\s]+"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
            needs_browser=True,  # Cloudflare : passe seulement dans la fenêtre de navigateur du PC
            # Fiches avec schema.org (vérifié le 7/10 : coffret Victini, en stock, 25,99 €) :
            # pas de devinette par mots-clés, source de fausses alertes.
            use_keywords=False,
            # Marketplace Carrefour : seules les offres vendues par Carrefour comptent.
            own_seller=re.compile(r"carrefour", re.I),
        ),
        Retailer(
            key="leclerc",
            name="E.Leclerc",
            domains=("e.leclerc",),
            # Les fiches finissent par le code EAN (ex. /fp/pokemon-coffret-…-0196214105973).
            product_url=re.compile(r"https://www\.e\.leclerc/fp/[^\"'?#\s]+-\d{8,14}"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
            use_keywords=False,
            # Vendeur « E.Leclerc » = Leclerc lui-même (Académie de Combat à 23,90 €) ; les autres,
            # « Stock e-commerce » compris (coffret à 138 €), sont des vendeurs partenaires.
            own_seller=re.compile(r"^\s*e\.?\s*leclerc\s*$", re.I),
        ),
        Retailer(
            key="cdiscount",
            name="Cdiscount",
            domains=("cdiscount.com",),
            # Fiches : https://www.cdiscount.com/<rayon>/.../f-<catégorie>-<référence>.html
            product_url=re.compile(r"https://www\.cdiscount\.com/[^\"'?#\s]+/f-\d+-[^\"'?#\s/]+\.html"),
            in_stock_keywords=_COMMON_IN,
            out_of_stock_keywords=_COMMON_OUT,
            needs_browser=True,  # Cloudflare : passe seulement dans la fenêtre de navigateur du PC
            use_keywords=False,
            # Surtout de la marketplace : seules les offres vendues par Cdiscount comptent.
            # « Expédié par Cdiscount » seul = vendeur partenaire stocké chez Cdiscount : ne compte pas.
            own_seller=re.compile(r"^\s*cdiscount(?:\.com)?\s*$", re.I),
            seller_marker=re.compile(r"vendu\s+et\s+exp[ée]di[ée]\s+par\s+cdiscount", re.I),
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
