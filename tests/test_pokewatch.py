import json
import os
import tempfile
import unittest
from unittest import mock

from pokewatch.fetch import FetchError
from pokewatch.parse import IN_STOCK, OUT_OF_STOCK, PREORDER, UNKNOWN, parse_availability
from pokewatch.notify import should_alert
from pokewatch.retailers import RETAILERS, retailer_for_url
from pokewatch.store import Store
from pokewatch.watcher import Watcher, extract_product_links, matches_keywords


def jsonld_page(availability, price="49.99", graph=False):
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Coffret Pokémon Écarlate et Violet",
        "offers": {"@type": "Offer", "price": price, "availability": availability},
    }
    data = {"@graph": [{"@type": "WebPage"}, product]} if graph else product
    return f'<html><head><title>x</title><script type="application/ld+json">{json.dumps(data)}</script></head><body>Ajouter au panier</body></html>'


class ParseTests(unittest.TestCase):
    def test_jsonld_in_stock(self):
        av = parse_availability(jsonld_page("https://schema.org/InStock"))
        self.assertEqual((av.status, av.source, av.price), (IN_STOCK, "jsonld", 49.99))
        self.assertEqual(av.name, "Coffret Pokémon Écarlate et Violet")

    def test_jsonld_out_of_stock_wins_over_keywords(self):
        av = parse_availability(jsonld_page("http://schema.org/OutOfStock"), ["Ajouter au panier"], [])
        self.assertEqual(av.status, OUT_OF_STOCK)

    def test_jsonld_graph_and_preorder(self):
        self.assertEqual(parse_availability(jsonld_page("PreOrder", graph=True)).status, PREORDER)

    def test_aggregate_offer_any_in_stock(self):
        data = {"@type": "Product", "name": "ETB", "offers": {"@type": "AggregateOffer", "lowPrice": "54,90",
                "offers": [{"availability": "OutOfStock"}, {"availability": "InStock"}]}}
        av = parse_availability(f'<script type="application/ld+json">{json.dumps(data)}</script>')
        self.assertEqual((av.status, av.price), (IN_STOCK, 54.90))

    def test_meta(self):
        html = '<meta property="product:availability" content="out of stock"><meta property="og:title" content="Booster">'
        av = parse_availability(html)
        self.assertEqual((av.status, av.name, av.source), (OUT_OF_STOCK, "Booster", "meta"))

    def test_keywords_out_beats_in(self):
        html = "<body><button disabled>Ajouter au panier</button><p>Rupture  de\n stock</p></body>"
        r = RETAILERS["cultura"]
        self.assertEqual(parse_availability(html, r.in_stock_keywords, r.out_of_stock_keywords).status, OUT_OF_STOCK)

    def test_keywords_ignore_scripts(self):
        html = "<body><script>var t='Rupture de stock'</script><button>Ajouter au panier</button></body>"
        r = RETAILERS["cultura"]
        self.assertEqual(parse_availability(html, r.in_stock_keywords, r.out_of_stock_keywords).status, IN_STOCK)

    def test_unknown_and_broken_json(self):
        av = parse_availability('<script type="application/ld+json">{oops</script><title> Page </title>')
        self.assertEqual((av.status, av.name), (UNKNOWN, "Page"))


class RetailerTests(unittest.TestCase):
    def test_lookup(self):
        self.assertEqual(retailer_for_url("https://www.cultura.com/p-x.html").key, "cultura")
        self.assertEqual(retailer_for_url("https://www.fnac.com/a123/x").key, "fnac")
        self.assertEqual(retailer_for_url("https://exemple.com").key, "autre")
        self.assertEqual(retailer_for_url("https://notcultura.com").key, "autre")

    def test_extract_links(self):
        html = ('<a href="/p-coffret-pokemon-123.html">a</a><a href="https://www.cultura.com/p-livre-1.html">b</a>'
                '<a href="/p-coffret-pokemon-123.html">dup</a>')
        links = extract_product_links(html, "https://www.cultura.com/search/results?q=pokemon")
        self.assertEqual(links, ["https://www.cultura.com/p-coffret-pokemon-123.html", "https://www.cultura.com/p-livre-1.html"])
        self.assertTrue(matches_keywords(links[0], ["pokémon"]))
        self.assertFalse(matches_keywords(links[1], ["pokemon"]))


class RealPagePatternsTests(unittest.TestCase):
    """Motifs relevés sur les vrais sites (octobre 2026)."""

    def test_joueclub_links(self):
        base = "https://www.joueclub.fr/nos-heros/pokemon.html"
        html = ('<base href="https://www.joueclub.fr/" target="_self" />'
                '<a href="https://www.joueclub.fr/pokemon/pokebox-mega-puissances-mega-dracolosse-0196214141735.html">'
                '<a href="contenu/les-cartes-pokemon.html"><a href="nos-heros/pokemon.html">'
                '<a href="figurines/pokemon-clip-n-go-0889933950572.html">')
        links = extract_product_links(html, base)
        self.assertEqual(len(links), 2)
        kept = [u for u in links if matches_keywords(u, ["joueclub.fr/pokemon/"])]
        self.assertEqual(kept, ["https://www.joueclub.fr/pokemon/pokebox-mega-puissances-mega-dracolosse-0196214141735.html"])

    def test_lagranderecre_links(self):
        base = "https://www.lagranderecre.fr/cartes-a-collectionner/"
        html = ('<a href="https://www.lagranderecre.fr/jeux-de-societe/cartes-a-collectionner/kit-d-initiation-pokemon-fevrier.html">'
                '<a href="https://www.lagranderecre.fr/jouet-pokemon.html">'
                '<a href="https://www.lagranderecre.fr/magasins/la-grande-recre-poissonniere.html">')
        self.assertEqual(extract_product_links(html, base),
                         ["https://www.lagranderecre.fr/jeux-de-societe/cartes-a-collectionner/kit-d-initiation-pokemon-fevrier.html"])

    def test_proximis_context(self):
        from pokewatch.instore import _context
        ctx = '{"websiteId":100052,"sectionId":103089,"pageId":100312}'
        other = '"stock":{"showStoreAvailability":true,"sku":"111","skuId":1,"ean13":"0000000000111"}'
        mine = '"stock":{"showStoreAvailability":true,"storeLocatorDistance":"100kilometers","sku":"896744","skuId":74210676,"ean13":"0820650557446"}'
        jsonld = '{"@context":"https://schema.org","@type":"Product","name":"Académie","sku":"0820650557446"}'
        self.assertEqual(_context(ctx + jsonld + other + mine)[1], "896744")  # code via l'EAN
        # page catégorie (fiche dépubliée) : pas de Product schema.org -> refus
        with self.assertRaises(FetchError):
            _context(ctx + other + mine)
        # ... sauf si l'on connaît le code-barres du produit : il sert alors de code article
        self.assertEqual(_context(ctx + other, ean="0196214147225")[1], "0196214147225")

    def test_label_ean(self):
        from pokewatch.watcher import label_ean
        self.assertEqual(label_ean("Coffret Poster (LGR) — EAN 0196214147225"), "0196214147225")
        self.assertIsNone(label_ean("Mini Tin"))


class ArrivalTests(unittest.TestCase):
    """Structure réelle des réponses La Grande Récré / JouéClub (5 octobre 2026)."""

    def item(self, shipping):
        return {"common": {"id": 1, "title": "La grande récré NICE"}, "coordinates": {"distance": 1.5},
                "storeShipping": shipping}

    def test_in_store(self):
        from pokewatch.instore import _proximis_item
        st = _proximis_item(self.item({"stock": {"available": True, "thresholdTitle": "En stock"}, "hasStoreStock": True,
                                       "formattedPickUpDateTime": "aujourd'hui à partir de 15h00"}))
        self.assertEqual((st.code, st.label), (1, "En stock, retrait aujourd'hui à partir de 15h00"))

    def test_warehouse_pickup_is_arrival(self):
        from pokewatch.instore import _proximis_item
        st = _proximis_item(self.item({"stock": {"available": True}, "hasStoreStock": False,
                                       "formattedPickUpDateTime": "jeudi 8 octobre"}))
        self.assertEqual((st.code, st.label), (2, "Arrivage : retrait jeudi 8 octobre"))

    def test_out_of_stock(self):
        from pokewatch.instore import _proximis_item
        st = _proximis_item(self.item({"stock": {"available": False, "thresholdTitle": "En rupture"}}))
        self.assertEqual((st.code, st.label), (0, "En rupture"))

    def test_restock(self):
        from pokewatch.instore import proximis_restock
        base = '"cartBox":{"allCategories":{"restockDescription":null,"restockDate":%s,"restockPlanned":%s,"formattedRestockDate":%s}'
        self.assertIsNone(proximis_restock(base % ("null", "false", "null")))
        self.assertEqual(proximis_restock(base % ('"2026-10-20"', "true", '"20 octobre"')), "20 octobre")

    def test_watchlist_file(self):
        from pokewatch.watcher import load_watchlist
        path = os.path.join(tempfile.mkdtemp(), "produits.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# mes produits\n\nhttps://www.joueclub.fr/pokemon/x-0196214141735.html | Pokébox Dracolosse\n"
                    "https://www.cultura.com/p-y-1.html\n")
        self.assertEqual(load_watchlist(path), [
            {"url": "https://www.joueclub.fr/pokemon/x-0196214141735.html", "label": "Pokébox Dracolosse"},
            {"url": "https://www.cultura.com/p-y-1.html", "label": None}])

    def test_store_arrival_transitions(self):
        from pokewatch.instore import StoreStock
        from pokewatch.notify import format_store_alert
        s = Store(os.path.join(tempfile.mkdtemp(), "t.db"))
        u = "https://www.joueclub.fr/pokemon/x-0196214141735.html"
        s.add_product(u, "joueclub")
        out = StoreStock("1", "JouéClub Nice", 1.4, False, "En rupture")
        arr = StoreStock("1", "JouéClub Nice", 1.4, False, "Arrivage : retrait jeudi", incoming=True)
        ok = StoreStock("1", "JouéClub Nice", 1.4, True, "En stock")
        s.record_store_stock(u, "joueclub", "X", [out])
        newly = s.record_store_stock(u, "joueclub", "X", [arr])
        self.assertEqual([x.code for x in newly], [2])
        self.assertIn("ARRIVAGE", format_store_alert("JouéClub", "X", u, newly))
        self.assertEqual([r["store_name"] for r in s.stores_incoming(u)], ["JouéClub Nice"])
        self.assertEqual([x.code for x in s.record_store_stock(u, "joueclub", "X", [ok])], [1])
        self.assertEqual(s.record_store_stock(u, "joueclub", "X", [arr]), [])  # en stock -> arrivage : pas d'alerte


class TrackDiscoveredTests(unittest.TestCase):
    def test_only_my_products(self):
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        search = "https://www.cultura.com/search/results?search_query=pokemon"
        mine = "https://www.cultura.com/p-mon-produit-1.html"
        other = "https://www.cultura.com/p-coffret-pokemon-2.html"
        pages = {search: f'<a href="{other}">x</a>', mine: jsonld_page("OutOfStock"), other: jsonld_page("InStock")}
        cfg = {"settings": {"database": db, "min_delay_seconds": 0, "max_delay_seconds": 0, "track_discovered": False},
               "alerts": {}, "searches": [{"url": search}], "watchlist": [{"url": mine, "label": "Mon produit"}]}
        w = Watcher(cfg)
        visited = []
        w.fetcher.get = lambda url, needs_browser=False: visited.append(url) or pages[url]
        with mock.patch("builtins.print"):
            w.run_once()
        self.assertEqual(visited, [search, mine])  # le produit trouvé par la recherche n'est pas relevé


class LeclercTests(unittest.TestCase):
    def test_marketplace_offers_ignored(self):
        from pokewatch.retailers import RETAILERS
        own = RETAILERS["leclerc"].own_seller
        def page(*offers):
            o = ",".join('{"@type":"Offer","price":"%s","availability":"https://schema.org/%s","seller":{"@type":"Organization","name":"%s"}}' % x for x in offers)
            return '<script type="application/ld+json">{"@type":"Product","name":"Coffret","offers":[%s]}</script>' % o
        only_partner = page(("138.41", "InStock", "Stock e-commerce"))
        self.assertEqual(parse_availability(only_partner, seller=own).status, "rupture")
        self.assertEqual(parse_availability(page(("23.90", "InStock", "E.Leclerc")), seller=own).status, "en_stock")
        self.assertEqual(parse_availability(only_partner).status, "en_stock")  # sans filtre : comportement inchangé

    def test_ean_search_url(self):
        from pokewatch.watcher import ean_search
        self.assertEqual(ean_search("https://www.e.leclerc/recherche?q=0196214146297"), "0196214146297")
        self.assertIsNone(ean_search("https://www.e.leclerc/recherche?q=pokemon"))


class NewListingTests(unittest.TestCase):
    def test_sitemap_new_pokemon_listing(self):
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        sm = "https://www.joueclub.fr/Assets/Rbs/Seo/100185/fr_FR/Rbs_Catalog_Product.1.xml"
        old = "https://www.joueclub.fr/pokemon/pokemon-booster-0196214142763.html"
        plush = "https://www.joueclub.fr/peluche/pokemon-peluche-0191726957294.html"
        new = "https://www.joueclub.fr/pokemon/pokemon-coffret-nouveau-0196214150000.html"
        loc = lambda *u: "".join(f"<url><loc>{x}</loc></url>" for x in u)
        pages = {sm: loc(old), new: jsonld_page("OutOfStock")}
        cfg = {"settings": {"database": db, "min_delay_seconds": 0, "max_delay_seconds": 0, "track_discovered": False},
               "alerts": {}, "watchlist": [],
               "searches": [{"url": sm, "require": ["/pokemon/"], "max": 0, "every_minutes": 360}]}
        w = Watcher(cfg)
        visited = []
        w.fetcher.get = lambda url, needs_browser=False: visited.append(url) or pages[url]
        w.check_stores = lambda *a, **k: None
        sent = []
        w.notifier.send = sent.append
        with mock.patch("builtins.print"):
            w.run_once()  # premier passage : silencieux
            pages[sm] = loc(old, plush, new)
            w.run_once()  # moins de 6 h après : plan du site pas relu
            self.assertEqual((sent, visited), ([], [sm]))
            w.store.db.execute("UPDATE searches SET last_check = '2000-01-01T00:00:00+00:00'")
            w.run_once()
        self.assertEqual(len(sent), 1)  # la peluche (hors rubrique /pokemon/) est ignorée
        self.assertIn("Nouveau produit", sent[0])
        self.assertIn(new, sent[0])


class ParallelTests(unittest.TestCase):
    def test_sites_checked_concurrently(self):
        import threading, time as _t
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        urls = ["https://www.joueclub.fr/pokemon/a-0196214147164.html", "https://www.joueclub.fr/pokemon/b-0196214147102.html",
                "https://www.lagranderecre.fr/x/c.html", "https://www.lagranderecre.fr/x/d.html"]
        cfg = {"settings": {"database": db, "min_delay_seconds": 0.2, "max_delay_seconds": 0.2, "watchlist_interval_seconds": 0},
               "alerts": {}, "watchlist": [{"url": u, "label": None} for u in urls]}
        log, lock = [], threading.Lock()

        def make():
            w = Watcher(cfg)
            def get(url, needs_browser=False):
                with lock:
                    log.append((threading.current_thread().name, url))
                return jsonld_page("OutOfStock")
            w.fetcher.get = get
            w.check_stores = lambda *a: None
            return w

        start = _t.time()
        with mock.patch("builtins.print"):
            Watcher(cfg).run_parallel(make_watcher=make, cycles=1)
        elapsed = _t.time() - start
        self.assertEqual(sorted(u for _, u in log), sorted(urls))
        self.assertEqual({n for n, _ in log}, {"joueclub", "lagranderecre"})
        self.assertLess(elapsed, 0.75)  # en série : 4 pauses de 0,2 s ; en parallèle : 2
        self.assertEqual(len(Store(db).products()), 4)


class EanSearchTests(unittest.TestCase):
    def test_cloudflare_page_is_not_no_result(self):
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        search = "https://www.cultura.com/search/results?search_query=0196214147225"
        w = Watcher({"settings": {"database": db}, "alerts": {}})
        w.fetcher.get = lambda url, needs_browser=False: "<html><head><title>Un instant…</title></head></html>"
        with mock.patch("builtins.print") as p:
            w.check(search, "Coffret Poster")
        self.assertIn("Cloudflare", p.call_args[0][0])

    def test_product_appears(self):
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        search = "https://www.cultura.com/search/results?search_query=0196214147225"
        prod = "https://www.cultura.com/p-coffret-collection-poster-pokemon-30-ans-13400000.html"
        sugg = "https://www.cultura.com/p-autre-produit-1.html"
        pages = {
            search: f'<a href="{sugg}">suggestion</a>',
            sugg: jsonld_page("InStock"),  # suggestion sans le code-barres : ignorée
            prod: jsonld_page("OutOfStock") + "0196214147225",
        }
        cfg = {"settings": {"database": db, "min_delay_seconds": 0, "max_delay_seconds": 0}, "alerts": {}}
        w = Watcher(cfg)
        w.fetcher.get = lambda url, needs_browser=False: pages[url]
        sent = []
        w.notifier.send = sent.append
        with mock.patch("builtins.print"):
            w.check(search, "Coffret Poster")
            w.check(search, "Coffret Poster")
            self.assertEqual(sent, [])
            pages[search] = f'<a href="{sugg}">s</a><a href="{prod}">le produit</a>'
            w.check(search, "Coffret Poster")
            self.assertEqual(len(sent), 1)
            self.assertIn("FICHE EN LIGNE", sent[0])
            self.assertIn(prod, sent[0])
            pages[prod] = jsonld_page("InStock") + "0196214147225"
            w.check(search, "Coffret Poster")  # suit désormais la fiche directement
        self.assertIn("EN STOCK", sent[-1])
        self.assertEqual(len(sent), 2)


class QuantityTests(unittest.TestCase):
    def test_estimate_by_dichotomy(self):
        from pokewatch.instore import StoreStock, proximis_estimate_quantities
        real = {"nice": 2, "cagnes": 13, "grasse": 19, "loin": 80}
        calls = []

        def ask(q):
            calls.append(q)
            return [StoreStock(k, k, 1.0, v >= q, "") for k, v in real.items()]

        res = proximis_estimate_quantities("u", 0, 0, 45, set(real), cap=50, pause=0, ask=ask)
        self.assertEqual(res, {"nice": (2, False), "cagnes": (13, False), "grasse": (19, False), "loin": (50, True)})
        self.assertLess(len(set(calls)), 16)  # requêtes partagées entre magasins

    def test_alert_shows_quantity(self):
        from pokewatch.instore import StoreStock
        from pokewatch.notify import format_store_alert
        st = StoreStock("1", "La grande recré GRASSE", 25.9, True, "En stock", qty=19)
        self.assertIn("GRASSE (25.9 km) : En stock — ~19 en stock", format_store_alert("La Grande Récré", "Mini Tin", "u", [st]))


class CulturaTests(unittest.TestCase):
    """Réponses réelles de l'API GraphQL de Cultura (capturées le 5 octobre 2026, recherche 06400)."""

    def test_store_stock(self):
        from pokewatch import instore
        fx = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "cultura_graphql.json")))
        calls = []

        class FakeFetcher:
            def fetch_json(self, url, origin):
                calls.append(url)
                return fx["stores"] if "stores(" in url else fx["product"]

        instore._cultura_stores_cache.clear()
        url = "https://www.cultura.com/p-booster-pokemon-m6-storm-emeralda-import-japon-13319873.html"
        stocks = instore.cultura_store_stock(FakeFetcher(), url, "06400", radius_km=100)
        self.assertEqual([(s.name, s.in_stock) for s in stocks], [
            ("Cultura Mandelieu", False), ("Cultura Nice", False), ("Cultura Puget", False), ("Cultura Toulon", True)])
        self.assertIn('url_key:{eq:"booster-pokemon-m6-storm-emeralda-import-japon-13319873"}', calls[1])
        # liste des magasins mise en cache : un seul appel "stores" pour deux produits
        instore.cultura_store_stock(FakeFetcher(), url, "06400", radius_km=100)
        self.assertEqual(sum("stores(" in c for c in calls), 1)
        instore._cultura_stores_cache.clear()
        near = instore.cultura_store_stock(FakeFetcher(), url, "06400", radius_km=45)
        self.assertEqual([s.name for s in near], ["Cultura Mandelieu", "Cultura Nice", "Cultura Puget"])


class StoreAndAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")

    def test_record_transitions(self):
        s = Store(self.db)
        u = "https://www.cultura.com/p-a.html"
        self.assertEqual(s.record(u, "cultura", OUT_OF_STOCK, "A", 10.0), "")
        self.assertIsNone(s.record(u, "cultura", OUT_OF_STOCK, "A", 10.0))
        self.assertEqual(s.record(u, "cultura", IN_STOCK, None, None), OUT_OF_STOCK)
        row = s.get(u)
        self.assertEqual((row["name"], row["price"], row["status"]), ("A", 10.0, IN_STOCK))
        self.assertEqual(len(s.events()), 2)

    def test_store_stock_transitions(self):
        from pokewatch.instore import StoreStock
        s = Store(self.db)
        u = "https://www.lagranderecre.fr/a/b.html"
        s.add_product(u, "lagranderecre")
        a_out = StoreStock("1", "LGR Paris", 1.5, False, "En rupture")
        a_in = StoreStock("1", "LGR Paris", 1.5, True, "En stock")
        b_in = StoreStock("2", "LGR Lyon", 9.0, True, "En stock")
        self.assertEqual(s.record_store_stock(u, "lagranderecre", "X", [a_out, b_in]), [])  # 1er relevé : silence
        self.assertEqual([x.name for x in s.record_store_stock(u, "lagranderecre", "X", [a_in, b_in])], ["LGR Paris"])
        self.assertEqual([r["store_name"] for r in s.stores_in_stock(u)], ["LGR Paris", "LGR Lyon"])
        # Lyon disparaît de la réponse => rupture
        self.assertEqual(s.record_store_stock(u, "lagranderecre", "X", [a_in]), [])
        self.assertEqual([r["store_name"] for r in s.stores_in_stock(u)], ["LGR Paris"])
        # Lyon revient => alerte
        self.assertEqual([x.name for x in s.record_store_stock(u, "lagranderecre", "X", [a_in, b_in])], ["LGR Lyon"])

    def test_should_alert(self):
        self.assertTrue(should_alert(OUT_OF_STOCK, IN_STOCK))
        self.assertTrue(should_alert("", IN_STOCK))
        self.assertFalse(should_alert(IN_STOCK, PREORDER))
        self.assertFalse(should_alert(IN_STOCK, OUT_OF_STOCK))

    def test_watcher_end_to_end(self):
        search = "https://www.cultura.com/search/results?search_query=pokemon"
        prod = "https://www.cultura.com/p-display-pokemon-1.html"
        pages = {
            search: '<a href="/p-display-pokemon-1.html">x</a>',
            prod: jsonld_page("OutOfStock"),
        }
        already = "https://www.cultura.com/p-coffret-pokemon-3.html"
        pages[search] += '<a href="/p-coffret-pokemon-3.html">z</a>'
        pages[already] = jsonld_page("InStock")  # déjà en stock au 1er passage : pas d'alerte
        cfg = {"settings": {"database": self.db, "min_delay_seconds": 0, "max_delay_seconds": 0},
               "alerts": {}, "products": [], "searches": [{"url": search}]}
        w = Watcher(cfg)
        w.fetcher.get = lambda url, needs_browser=False: pages[url]
        sent = []
        w.notifier.send = sent.append
        with mock.patch("builtins.print"):
            w.run_once()
            self.assertEqual(sent, [])  # premier passage : base constituée sans alerte
            pages[search] += '<a href="/p-coffret-pokemon-2.html">y</a>'
            pages["https://www.cultura.com/p-coffret-pokemon-2.html"] = jsonld_page("OutOfStock")
            pages[prod] = jsonld_page("InStock")
            w.run_once()
        self.assertEqual(len(sent), 2)
        self.assertIn("Nouveau produit", sent[0])
        self.assertIn("EN STOCK", sent[1])
        self.assertIn(prod, sent[1])

    def test_dashboard_renders(self):
        from pokewatch.dashboard import render
        s = Store(self.db)
        s.record("https://www.cultura.com/p-a.html", "cultura", IN_STOCK, "Display <b>", 5.0)
        html = render(s)
        self.assertIn("Display &lt;b&gt;", html)
        self.assertIn("1</b> achetables", html)


if __name__ == "__main__":
    unittest.main()
