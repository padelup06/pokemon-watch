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
    cr = sub.add_parser("cultura-refs", help="diagnostic : produits Cultura autour d'une référence")
    cr.add_argument("--debut", type=int, default=13485900)
    cr.add_argument("--fin", type=int, default=13486300)
    cr.add_argument("--visible", action="store_true")
    c5 = sub.add_parser("cultura-pistes", help="diagnostic : plan du site et noms exacts")
    c5.add_argument("--visible", action="store_true")
    c6 = sub.add_parser("cultura-boutiques", help="diagnostic : vues magasin du catalogue Cultura")
    c6.add_argument("--visible", action="store_true")
    c7 = sub.add_parser("cultura-reseau", help="diagnostic : services que le site Cultura appelle lui-même")
    c7.add_argument("--pages", nargs="*", help="pages à visiter (défaut : accueil, fiche, recherche)")
    c7.add_argument("--sortie", default="test-cultura-m2.json")
    c9 = sub.add_parser("cultura-filtres", help="diagnostic : filtres du catalogue Cultura")
    c9.add_argument("--visible", action="store_true")
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

    if args.cmd == "cultura-filtres":
        import json as _json
        import urllib.parse as _up

        fetcher = Fetcher("always", headless=not args.visible)
        fields = "total_count,items{sku,name,ean,url_key,stock_item_extra{front_availability,offer{seller_code,qty}}}"

        def ask(title, q):
            url = "https://www.cultura.com/m2/graphql?query=" + _up.quote(q, safe="{}(),:\"")
            try:
                code, text = fetcher.fetch_text(url, "https://www.cultura.com", headers={"Store": "cultura_b2c_fr_FR"})
            except Exception as e:
                print(f"--- {title} : erreur {e}")
                return
            try:
                data = _json.loads(text)
            except ValueError:
                print(f"--- {title} (HTTP {code}) : {text[:300]}")
                return
            prods = ((data.get("data") or {}).get("products") or {})
            items = prods.get("items") or []
            err = data.get("errors")
            print(f"--- {title} (HTTP {code}) : {prods.get('total_count')} résultat(s){' ERREUR ' + str(err)[:300] if err else ''}")
            for it in items:
                offers = (it.get("stock_item_extra") or {}).get("offer") or []
                dispo = [o for o in offers if o.get("qty")]
                print(f"   {it.get('sku')} | {it.get('name')} | EAN {it.get('ean')} | {len(offers)} magasins, "
                      f"{len(dispo)} avec stock | {it.get('url_key')}")

        eans = ["0196214146297", "0196214145221", "0196214144835", "0196214147225", "0196214147102",
                "0196214147164", "0196214152311", "0196214144972", "0196214145153"]
        try:
            ask("EAN 30 ans (tous)", '{products(filter:{ean:{in:[%s]}},pageSize:50,getDisabledProduct:1){%s}}'
                % (",".join(f'"{e}"' for e in eans + [e[1:] for e in eans]), fields))
            for extra in ('sellable:{eq:"0"}', 'sellable:{eq:"1"}', 'status:{eq:"out_of_stock"}', 'has_cultura_stock:{eq:"1"}'):
                ask(f"EAN 30 ans + {extra}", '{products(filter:{ean:{in:[%s]},%s},pageSize:50,getDisabledProduct:1){%s}}'
                    % (",".join(f'"{e}"' for e in eans), extra, fields))
            ask("nom « anniversaire » + stock Cultura",
                '{products(search:"pokemon anniversaire",filter:{has_cultura_stock:{eq:"1"}},pageSize:50){%s}}' % fields)
            ask("rayon Cartes Pokémon + stock Cultura",
                '{products(filter:{category_id:{eq:"30120"},has_cultura_stock:{eq:"1"}},pageSize:100){%s}}' % fields)
            ask("rayon Cartes Pokémon + non vendable en ligne",
                '{products(filter:{category_id:{eq:"30120"},sellable:{eq:"0"}},pageSize:100,getDisabledProduct:1){%s}}' % fields)
            ask("recherche « pokemon » + non vendable en ligne",
                '{products(search:"pokemon",filter:{sellable:{eq:"0"}},pageSize:100,getDisabledProduct:1){%s}}' % fields)
        finally:
            fetcher.close()
        return 0

    if args.cmd == "cultura-reseau":
        from urllib.parse import urlparse

        from playwright.sync_api import sync_playwright

        from .explore import _keep

        pages = args.pages or [
            "https://www.cultura.com/",
            "https://www.cultura.com/p-mini-tin-pokemon-mega-heroisme-modeles-aleatoires-vendu-a-l-unite-12369064.html",
            "https://www.cultura.com/search/results?search_query=pokemon%2030e%20anniversaire",
        ]
        seen: dict[str, int] = {}
        hits: list[str] = []
        saved: list[dict] = []  # appels au 2e catalogue (/m2/graphql), encarts, config : en entier

        def on_response(resp):
            req = resp.request
            if req.resource_type not in ("xhr", "fetch") or not _keep(req.url):
                return
            u = urlparse(req.url)
            key = f"{req.method} {u.scheme}://{u.netloc}{u.path}"
            seen[key] = seen.get(key, 0) + 1
            try:
                body = resp.text()
            except Exception:
                return
            if any(x in u.path for x in ("/m2/graphql", "/fragments/encart-produit", "/config.json", "product.model.json")) \
                    or "eresa" in u.netloc:
                saved.append({"method": req.method, "url": req.url, "post_data": req.post_data,
                              "status": resp.status, "body": body[:60000]})
            for word in ("13200180", "anniversaire", "Anniversaire", "instore", "Instore"):
                if word in body:
                    hits.append(f"{key} contient « {word} »")
                    break

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_context(locale="fr-FR").new_page()
            page.on("response", on_response)
            for url in pages:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    for _ in range(20):  # vérification « Un instant » puis chargement des données
                        page.wait_for_timeout(1000)
                    page.mouse.wheel(0, 3000)
                    page.wait_for_timeout(4000)
                    print(f"--- {url} → {page.url} (titre : {page.title()[:60]})")
                    if "eresa" in url:
                        html = page.content()
                        saved.append({"method": "PAGE", "url": page.url, "post_data": None, "status": 200,
                                      "body": html[:60000]})
                        links = sorted(set(re.findall(r'(?:href|src)="([^"]+)"', html)))
                        print("    liens / scripts : " + " ".join(links[:60]))
                except Exception as e:
                    print(f"--- {url} : erreur {e}")
            browser.close()
        import json as _json

        with open(args.sortie, "w", encoding="utf-8") as f:
            _json.dump(saved, f, ensure_ascii=False, indent=1)
        print(f"\n{len(saved)} réponses enregistrées dans {args.sortie}")
        print("\n--- services appelés par le site (nombre d'appels) ---")
        for k, n in sorted(seen.items()):
            print(f"{n:3d}  {k}")
        print("\n--- réponses intéressantes ---")
        print("\n".join(dict.fromkeys(hits)) or "(aucune)")
        return 0

    if args.cmd == "cultura-boutiques":
        import json as _json

        from .instore import CULTURA, _graphql_url

        fetcher = Fetcher("always", headless=not args.visible)

        def ask(title, q, headers=None):
            try:
                code, text = fetcher.fetch_text(_graphql_url(q), CULTURA, headers=headers)
                print(f"--- {title} (HTTP {code}) ---\n{text[:2500]}")
                return _json.loads(text)
            except Exception as e:
                print(f"--- {title} : erreur {e}")
                return None

        try:
            ask("boutique actuelle", "{storeConfig{store_code,store_name,website_code,root_category_id}}")
            res = ask("boutiques disponibles", "{availableStores{store_code,store_name,website_code,is_default_store}}")
            codes = [st.get("store_code") for st in (((res or {}).get("data") or {}).get("availableStores") or [])
                     if isinstance(st, dict) and st.get("store_code")]
            for code in codes[:8]:
                for term in ("pokemon 30e anniversaire", "mini tin pokemon"):
                    ask(f"boutique {code} — recherche « {term} »",
                        '{products(search:"%s",pageSize:10){total_count,items{sku,name,url_key}}}' % term, {"Store": code})
        finally:
            fetcher.close()
        return 0

    if args.cmd == "cultura-pistes":
        import json as _json

        from .instore import CULTURA, _graphql_url

        fetcher = Fetcher("always", headless=not args.visible)
        try:
            # 1. Plan du site (publié pour Google) : toutes les fiches, même absentes de la recherche.
            try:
                code, text = fetcher.fetch_text(f"{CULTURA}/sitemap.xml?param=one", CULTURA)
                urls = re.findall(r"<loc>([^<]+)</loc>", text)
                print(f"--- plan du site « one » : HTTP {code}, {len(text)} caractères, {len(urls)} adresses ---")
                print("\n".join(urls[:10]))
                subs = [u for u in urls if "sitemap" in u][:40]
                hits = [u for u in urls if "pokemon" in u.lower() and ("anniv" in u.lower() or "30" in u)]
                for sm in subs:
                    try:
                        c2, t2 = fetcher.fetch_text(sm.replace("&amp;", "&"), CULTURA)
                        locs = re.findall(r"<loc>([^<]+)</loc>", t2)
                        h = [u for u in locs if "pokemon" in u.lower() and ("anniv" in u.lower() or "30e" in u.lower() or "30-ans" in u.lower())]
                        print(f"  {sm} : HTTP {c2}, {len(locs)} adresses, {len(h)} Pokémon 30 ans")
                        hits += h
                    except Exception as e:
                        print(f"  {sm} : erreur {e}")
                print("--- fiches Pokémon 30 ans dans le plan du site ---")
                print("\n".join(dict.fromkeys(hits)) or "(aucune)")
            except Exception as e:
                print(f"--- plan du site : erreur {e}")
            # 2. Noms exacts vus dans les alertes Pokecop.
            for name in ("Mini Tin contenant 2 boosters", "Bundle de 6 boosters de cartes a collectionner",
                         "Duopack de 2 boosters de cartes a collectionner", "30e Anniversaire"):
                for how, q in (
                    ("recherche", '{products(search:"%s",pageSize:20){total_count,items{sku,name,url_key}}}'),
                    ("nom", '{products(filter:{name:{match:"%s"}},pageSize:20,getDisabledProduct:1){total_count,items{sku,name,url_key}}}'),
                ):
                    try:
                        res = fetcher.fetch_json(_graphql_url(q % name), CULTURA)
                        print(f"--- {how} « {name} » ---\n{_json.dumps(res, ensure_ascii=False)[:1500]}")
                    except Exception as e:
                        print(f"--- {how} « {name} » : erreur {e}")
        finally:
            fetcher.close()
        return 0

    if args.cmd == "cultura-refs":
        from .instore import CULTURA, _graphql_url

        fetcher = Fetcher("always", headless=not args.visible)
        try:
            refs = list(range(args.debut, args.fin + 1))
            for i in range(0, len(refs), 100):
                chunk = ",".join(f'"{r}"' for r in refs[i:i + 100])
                q = ('{products(filter:{sku:{in:[%s]}},pageSize:100,getDisabledProduct:1,resolverLight:1)'
                     "{items{sku,name,url_key,stock_item_extra{offer{front_availability,seller_code,qty}}}}}" % chunk)
                try:
                    data = fetcher.fetch_json(_graphql_url(q), CULTURA)
                except FetchError as e:
                    print(f"{refs[i]}… : erreur {e}")
                    continue
                for it in ((data.get("data") or {}).get("products") or {}).get("items") or []:
                    offers = (it.get("stock_item_extra") or {}).get("offer") or []
                    dispo = sum(1 for o in offers if str(o.get("front_availability", "")).startswith("available"))
                    print(f"{it.get('sku')} | {it.get('name')} | {len(offers)} magasins, {dispo} dispo | {it.get('url_key')}")
            if args.debut == args.fin:
                from .instore import cultura_store_stock

                for cp in ("06210", "06000"):
                    try:
                        stores = cultura_store_stock(fetcher, f"https://www.cultura.com/p-ref-{args.debut}.html", cp, 30)
                        print(f"\nAutour de {cp} :")
                        for st in stores:
                            q = f" — ~{st.qty} exemplaires" if st.qty else ""
                            print(f"  {'✅' if st.in_stock else '❌'} {st.name} : {st.label}{q}")
                    except Exception as e:
                        print(f"{cp} : erreur {e!r}")
        finally:
            fetcher.close()
        return 0

    if args.cmd == "cultura-ean":
        import json as _json

        from .instore import cultura_ean_probe, cultura_find_by_ean, cultura_name_probe

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
        if "cultura.com" in args.url:
            args.url = args.url.split("?")[0].split("#")[0]  # lien copié avec « ?__cf_chl_tk=… »
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
                elif st.qty:
                    q = f" — ~{st.qty} exemplaires"
                print(f"  {'✅' if st.in_stock else '❌'} {st.name}{dist} : {st.label}{q}")
        return 0

    try:
        cfg = load_config(args.config)
    except FileNotFoundError:
        print(f"Fichier {args.config} introuvable : copiez config.example.toml en config.toml.")
        return 1

    if args.cmd == "magasin":
        from .store import Store

        store = Store(cfg["settings"].get("database", "pokewatch.db"))
        rows = store.store_report(args.nom)
        # État de la surveillance Cultura, pour comprendre une absence.
        n_cult = store.db.execute(
            "SELECT COUNT(DISTINCT s.url) FROM store_stock s JOIN products p ON p.url = s.url WHERE p.retailer = 'cultura'"
        ).fetchone()[0]
        import json as _json
        tracked = _json.loads(store.get_meta("cultura_tracked") or "{}")
        print(f"Cultura : {len(tracked)} produit(s) 30 ans suivis, stock magasin déjà relevé pour {n_cult} produit(s).")
        for u, n in tracked.items():
            row = store.db.execute("SELECT status, store_check, last_error FROM products WHERE url = ?", (u,)).fetchone()
            etat = "jamais lu" if row is None or not row["store_check"] else f"magasins lus {row['store_check'][11:16]}"
            err = f", erreur : {row['last_error'][:60]}" if row is not None and row["last_error"] else ""
            print(f"   - {n} [{(row['status'] if row else None) or '?'}, {etat}{err}]")
        if not args.tout:
            from .watcher import _plain

            words = [_plain(w) for w in cfg["settings"].get("cultura_track", [])] + ["30e anniv", "30 anniv", "30a "]
            rows = [r for r in rows if any(w in _plain(r["product"]) for w in words)]
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
