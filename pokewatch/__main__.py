"""Ligne de commande.

  python -m pokewatch check            un passage complet, puis s'arrête
  python -m pokewatch watch            surveillance en continu
  python -m pokewatch test URL         teste la détection sur une fiche produit
  python -m pokewatch test URL --cp 69002   ... et le stock des magasins proches
  python -m pokewatch dashboard        tableau de bord web
  python -m pokewatch notify-test      envoie une alerte de test
  python -m pokewatch explorer URL     enregistre les requêtes « stock magasin » d'un site
"""

from __future__ import annotations

import argparse
import sys

from .fetch import FetchError, Fetcher
from .instore import (
    QUANTITY_RETAILERS,
    STORE_RETAILERS,
    cultura_store_stock,
    geocode,
    proximis_estimate_quantities,
    proximis_store_stock,
)
from .notify import Notifier
from .parse import parse_availability
from .retailers import retailer_for_url
from .watcher import Watcher, extract_product_links, load_config


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pokewatch", description="Veille des stocks Pokémon TCG")
    ap.add_argument("-c", "--config", default="config.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("watch")
    t = sub.add_parser("test")
    t.add_argument("url")
    t.add_argument("--browser", choices=["never", "auto", "always"], default="auto")
    t.add_argument("--visible", action="store_true", help="ouvre une vraie fenêtre de navigateur (Fnac, Cultura)")
    t.add_argument("--cp", help="code postal ou ville : affiche aussi le stock des magasins proches")
    t.add_argument("--rayon", type=int, default=30, help="rayon en km autour du code postal (défaut 30)")
    t.add_argument("--quantite", action="store_true", help="estime le nombre d'exemplaires par magasin (La Grande Récré)")
    d = sub.add_parser("dashboard")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8000)
    sub.add_parser("notify-test")
    e = sub.add_parser("explorer")
    e.add_argument("url")
    e.add_argument("-o", "--output", default="exploration.json")
    args = ap.parse_args(argv)

    if args.cmd == "explorer":
        from .explore import explore

        return explore(args.url, args.output)

    if args.cmd == "test":
        retailer = retailer_for_url(args.url)
        fetcher = Fetcher(args.browser, headless=not args.visible)
        try:
            html = fetcher.get(args.url, retailer.needs_browser)
        except FetchError as e:
            fetcher.close()
            print(f"Échec de récupération : {e}")
            return 1
        if retailer.use_keywords:
            av = parse_availability(html, retailer.in_stock_keywords, retailer.out_of_stock_keywords)
        else:
            av = parse_availability(html)
        print(f"Enseigne : {retailer.name}\nProduit  : {av.name}\nStatut   : {av.status} (via {av.source or 'rien'})")
        print(f"Prix     : {av.price}")
        if not args.cp:
            fetcher.close()
        links = extract_product_links(html, args.url)
        if links:
            print(f"Liens produits trouvés sur la page : {len(links)} (ex. {links[0]})")
        if args.cp:
            if retailer.key not in STORE_RETAILERS:
                print(f"Stock magasin : pas encore géré pour {retailer.name}")
                fetcher.close()
                return 0
            try:
                if retailer.key == "cultura":
                    stocks = cultura_store_stock(fetcher, args.url, args.cp, args.rayon)
                else:
                    stocks = proximis_store_stock(args.url, *geocode(args.cp), radius_km=args.rayon)
            except FetchError as e:
                print(f"Stock magasin : {e}")
                return 1
            finally:
                fetcher.close()
            print(f"Magasins à moins de {args.rayon} km de {args.cp} : {len(stocks)}")
            qty = {}
            if args.quantite and retailer.key not in QUANTITY_RETAILERS:
                print(f"Quantités : non disponibles pour {retailer.name} (son API ne tient pas compte de la quantité)")
            elif args.quantite:
                qty = proximis_estimate_quantities(
                    args.url, *geocode(args.cp), args.rayon, {s.store_id for s in stocks if s.in_stock}, html=html
                )
            for st in stocks:
                dist = f" ({st.distance_km:g} km)" if st.distance_km is not None else ""
                q = ""
                if st.store_id in qty:
                    n, capped = qty[st.store_id]
                    q = f" — ~{n}{'+' if capped else ''} exemplaires"
                print(f"  {'✅' if st.in_stock else '❌'} {st.name}{dist} : {st.label}{q}")
        return 0

    try:
        cfg = load_config(args.config)
    except FileNotFoundError:
        print(f"Fichier {args.config} introuvable : copiez config.example.toml en config.toml.")
        return 1

    if args.cmd == "dashboard":
        from .dashboard import serve

        serve(cfg["settings"].get("database", "pokewatch.db"), args.host, args.port)
    elif args.cmd == "notify-test":
        Notifier(cfg["alerts"]).send("Test Pokémon Watch : les alertes fonctionnent ✅")
    else:
        w = Watcher(cfg)
        if args.cmd == "check":
            try:
                w.run_once()
            finally:
                w.fetcher.close()
        else:
            w.run_forever()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
