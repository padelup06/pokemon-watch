import json
import os
import tempfile
import unittest
from unittest import mock

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
        html = ('{"websiteId":100052,"sectionId":103089,"pageId":100312}'
                '"stock":{"showStoreAvailability":true,"storeLocatorDistance":"100kilometers","sku":"896744","skuId":74210676}')
        self.assertEqual(_context(html), ({"websiteId": 100052, "sectionId": 103089, "pageId": 100312}, "896744"))


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
