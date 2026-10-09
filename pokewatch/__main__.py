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
import re
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
    for stream in (sys.stdout, sys.stderr):
        # Windows : sortie redirigée vers un fichier (tester-*.bat) = cp1252, sans émojis.
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
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
    t.add_argument("--premiere-fiche", action="store_true", help="page de recherche : teste aussi la première fiche trouvée")
    d = sub.add_parser("dashboard")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8000)
    sub.add_parser("notify-test")
    ce = sub.add_parser("cultura-ean", help="cherche un code-barres dans l'API Cultura (diagnostic)")
    ce.add_argument("ean")
    ce.add_argument("--visible", action="store_true")
    ce.add_argument("--nom", help="cherche aussi ce nom de produit")
    cx = sub.add_parser("cultura-explorer", help="diagnostic : comment trouver les produits Cultura")
    cx.add_argument("--visible", action="store_true")
    mg = sub.add_parser("magasin", help="dernier stock connu dans un magasin (ex. Mandelieu)")
    mg.add_argument("nom")
    mg.add_argument("--tout", action="store_true", help="tous les produits, pas seulement les 30 ans")
    e = sub.add_parser("explorer")
    e.add_argument("url")
    e.add_argument("-o", "--output", default="exploration.json")
    args = ap.parse_args(argv)

    if args.cmd == "explorer":
        from .explore import explore

        return explore(args.url, args.output)

    if args.cmd == "cultura-explorer":
        import json as _json
        import re as _re

        from .instore import CULTURA, _graphql_url

        fetcher = Fetcher("always", headless=not args.visible)

        def gql(title, q):
            try:
                res = fetcher.fetch_json(_graphql_url(q), CULTURA)
                print(f"--- {title} ---\n{_json.dumps(res, ensure_ascii=False)[:3000]}")
                return res
            except Exception as e:
                print(f"--- {title} ---\nerreur : {e}")
                return None

        try:
            cats = gql("rayons « pokemon »", '{categoryList(filters:{name:{match:"pokemon"}}){id,uid,name,url_path,product_count}}')
            gql("rayons « cartes »", '{categoryList(filters:{name:{match:"cartes a collectionner"}}){id,uid,name,url_path,product_count}}')
            found = []
            for c in ((cats or {}).get("data") or {}).get("categoryList") or []:
                if isinstance(c, dict) and c.get("id") and c.get("product_count"):
                    found.append(c)
            for c in found[:3]:
                gql(f"produits du rayon {c.get('name')} ({c['id']})",
                    '{products(filter:{category_id:{eq:"%s"}},pageSize:30){total_count,items{sku,name,url_key}}}' % c["id"])
            gql("recherche « pokemon »", '{products(search:"pokemon",pageSize:10){total_count,items{sku,name,url_key}}}')
            for u in (f"{CULTURA}/robots.txt", f"{CULTURA}/sitemap.xml"):
                try:
                    code, text = fetcher.fetch_text(u, CULTURA)
                    print(f"--- {u} (HTTP {code}) ---\n{text[:1500]}")
                except Exception as e:
                    print(f"--- {u} ---\nerreur : {e}")
            try:
                html = fetcher.get(f"{CULTURA}/search/results?search_query=pokemon%20mini%20tin", True)
                links = sorted(set(_re.findall(r"/p-[^\"'?#\s]+\.html", html)))
                print(f"--- page de recherche (rendue) : {len(html)} caractères, {len(links)} liens /p- ---")
                print("\n".join(links[:15]))
                print("titre :", (_re.findall(r"<title[^>]*>([^<]*)", html) or ["?"])[0])
            except Exception as e:
                print(f"--- page de recherche ---\nerreur : {e}")
        finally:
            fetcher.close()
        return 0

    if args.cmd == "cultura-ean":
        import json as _json

        from .instore import cultura_ean_probe, cultura_find_by_ean, cultura_name_probe, cultura_store_stock

        fetcher = Fetcher("always", headless=not args.visible)
        try:
            for how, res in cultura_ean_probe(fetcher, args.ean):
                print(f"--- {how} ---\n{_json.dumps(res, ensure_ascii=False)[:1500]}")
            hit = cultura_find_by_ean(fetcher, args.ean)
            print(f"\nRésultat : {hit}")
            keys = [hit[0]] if hit else []
            if args.nom:
                for how, res in cultura_name_probe(fetcher, args.nom):
                    print(f"--- nom / {how} ---\n{_json.dumps(res, ensure_ascii=False)[:3000]}")
                    items = (((res or {}).get("data") or {}).get("products") or {}).get("items") if isinstance(res, dict) else None
                    keys += [it["url_key"] for it in items or [] if isinstance(it, dict) and it.get("url_key")
                             and "tin" in str(it.get("name", "")).lower()]
            for key in list(dict.fromkeys(keys))[:3]:
                url = f"https://www.cultura.com/p-{key}.html"
                print(f"\nStock magasins pour {url}")
                for cp in ("06000", "38300", "75001"):
                    try:
                        stores = cultura_store_stock(fetcher, url, cp, 40)
                        print(f"{cp} : " + ", ".join(f"{s.name} {'OUI' if s.in_stock else 'non'}"
                                                     f"{f' ({s.qty})' if s.qty else ''}" for s in stores))
                    except Exception as e:
                        print(f"{cp} : erreur {e!r}")
        finally:
            fetcher.close()
        return 0

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
            av = parse_availability(html, retailer.in_stock_keywords, retailer.out_of_stock_keywords, retailer.own_seller, retailer.seller_marker)
        else:
            av = parse_availability(html, seller=retailer.own_seller, seller_marker=retailer.seller_marker)
        print(f"Enseigne : {retailer.name}\nProduit  : {av.name}\nStatut   : {av.status} (via {av.source or 'rien'})")
        print(f"Prix     : {av.price}")
        if not args.cp:
            fetcher.close()
        links = extract_product_links(html, args.url)
        if links:
            print(f"Liens produits trouvés sur la page : {len(links)} (ex. {links[0]})")
            if args.premiere_fiche and not args.cp:
                f2 = Fetcher(args.browser, headless=not args.visible)
                try:
                    html2 = f2.get(links[0], retailer.needs_browser)
                    av2 = parse_availability(html2, seller=retailer.own_seller, seller_marker=retailer.seller_marker)
                    print(f"\nPremière fiche : {links[0]}\nProduit  : {av2.name}\nStatut   : {av2.status} (via {av2.source or 'rien'})\nPrix     : {av2.price}")
                except FetchError as e:
                    print(f"Première fiche : échec ({e})")
                finally:
                    f2.close()
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

    if args.cmd == "magasin":
        from .store import Store

        rows = Store(cfg["settings"].get("database", "pokewatch.db")).store_report(args.nom)
        if not args.tout:
            rows = [r for r in rows if re.search(r"30\s*(e|è|ème|eme)?\s*anniv|30\s*ans|30th|30A", r["product"], re.I)]
        if not rows:
            print(f"Aucun relevé pour un magasin « {args.nom} » (le stock magasin n'a peut-être pas encore été lu).")
            return 0
        icon = {1: "✅ EN STOCK", 2: "🚚 arrivage", 0: "❌ rupture"}
        for store in dict.fromkeys(r["store_name"] for r in rows):
            print(f"\n{store}")
            for r in (r for r in rows if r["store_name"] == store):
                qty = f" — ~{r['qty']} ex." if r["qty"] else ""
                print(f"  {icon.get(r['in_stock'], '?'):<12} {r['product']}{qty}  ({r['label'] or ''}, relevé {r['last_check'][:16].replace('T', ' ')})")
        return 0

    if args.cmd == "dashboard":
        from .dashboard import serve

        serve(cfg["settings"].get("database", "pokewatch.db"), args.host, args.port)
    elif args.cmd == "notify-test":
        Notifier(cfg["alerts"]).send("Test Pokémon Watch : les alertes fonctionnent ✅")
    else:
        w = Watcher(cfg)
        if args.cmd == "check":
            from .daily import check_pc, greet_zones, maybe_send_recap, pc_alive

            s = cfg["settings"]
            try:
                greet_zones(w)
                if s.get("watch_pc"):
                    # Avant le passage : si le PC tourne, il alerte déjà pour produits.txt.
                    check_pc(w, float(s.get("pc_silence_minutes", 15)))
                    w.defer_to_pc = pc_alive(w, float(s.get("pc_silence_minutes", 15)))
                    if w.defer_to_pc:
                        print("[PC] actif : alertes de produits.txt (en ligne et magasins du 06) laissées au PC")
                w.run_once()
                if s.get("recap_hour") is not None:
                    maybe_send_recap(w, int(s["recap_hour"]))
            finally:
                w.fetcher.close()
        else:
            if cfg["settings"].get("heartbeat"):
                from .daily import start_heartbeat

                start_heartbeat(cfg["alerts"].get("discord_webhook"))
            w.run_forever()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
