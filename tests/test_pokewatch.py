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


class DailyTests(unittest.TestCase):
    def watcher(self):
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        lgr = "https://www.lagranderecre.fr/jeux-de-societe/cartes-a-collectionner/mini-tin.html"
        cfg = {"settings": {"database": db, "min_delay_seconds": 0, "max_delay_seconds": 0, "code_postal": "06000"},
               "alerts": {"discord_webhook": "https://discord.com/api/webhooks/1/x"},
               "watchlist": [{"url": lgr, "label": "Mini Tin (LGR)"},
                             {"url": "https://www.joueclub.fr/pokemon/x-0196214146297.html", "label": "Mini Tin (JC)"},
                             {"url": "https://www.e.leclerc/recherche?q=0196214146297", "label": "Mini Tin (Leclerc)"}]}
        w = Watcher(cfg)
        w.zones[0]["points"][0]["coords"] = (43.7, 7.26)
        w.store.add_product(lgr, "lagranderecre")
        w.store.record(lgr, "lagranderecre", "rupture", "Mini Tin", None)
        from pokewatch.instore import StoreStock
        w.store.record_store_stock(lgr, "lagranderecre", "Mini Tin", [
            StoreStock("g", "La grande recré GRASSE", 25.9, True, "En stock", None),
            StoreStock("c", "La Grande Récré CAGNES", 11.5, True, "En stock", None)])
        return w, lgr

    def test_recap_with_quantities_and_trend(self):
        from datetime import datetime
        from pokewatch import daily
        w, lgr = self.watcher()
        qty = [{"g": (19, False), "c": (13, False)}, {"g": (19, False), "c": (11, False)}]
        with mock.patch("pokewatch.watcher.proximis_estimate_quantities", side_effect=lambda *a, **k: qty.pop(0)):
            daily.build_recap(w, datetime(2026, 10, 6, 9, tzinfo=daily.PARIS))
            text = daily.build_recap(w, datetime(2026, 10, 7, 9, tzinfo=daily.PARIS))
        self.assertIn("mer. 7 oct.", text)
        self.assertIn("GRASSE : ~19 (= hier)", text)
        self.assertIn("CAGNES : ~11 (-2 depuis hier)", text)
        self.assertIn("• Mini Tin (JC) (JouéClub)", text)
        self.assertIn("Pas encore de fiche : E.Leclerc (1)", text)

    def test_store_alerts_routed_by_zone(self):
        from pokewatch.instore import StoreStock
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        u = "https://www.lagranderecre.fr/x/mini-tin.html"
        cfg = {"settings": {"database": db, "zones": [{"name": "06", "code_postal": "06000", "rayon_km": 45},
                                                      {"name": "83", "code_postal": "83000", "rayon_km": 40}],
                            "estimate_quantity": False},
               "alerts": {"discord_webhook": "main", "zone_webhooks": {"06": "hook06", "83": "hook83"}}, "watchlist": []}
        w = Watcher(cfg)
        for z, c in zip(w.zones, [(43.7, 7.26), (43.12, 5.93)]):
            z["points"][0]["coords"] = c
        answers = {(43.7, 7.26): [StoreStock("n", "NICE", 1, False, "Rupture")],
                   (43.12, 5.93): [StoreStock("t", "TOULON", 2, False, "Rupture")]}
        posted = []
        with mock.patch("pokewatch.watcher.proximis_store_stock", side_effect=lambda u, lat, lon, **k: [
                StoreStock(s.store_id, s.name, s.distance_km, s.in_stock, s.label) for s in answers[(lat, lon)]]), \
             mock.patch("pokewatch.notify._post_json", side_effect=lambda hook, payload: posted.append((hook, payload["content"]))), \
             mock.patch("builtins.print"):
            w.store.add_product(u, "lagranderecre")
            w.check_stores(u, RETAILERS["lagranderecre"], "Mini Tin")  # premier relevé : silencieux
            answers[(43.12, 5.93)] = [StoreStock("t", "TOULON", 2, True, "En stock")]
            w._store_last.clear()
            w.check_stores(u, RETAILERS["lagranderecre"], "Mini Tin")
        self.assertEqual([h for h, _ in posted], ["hook83"])
        self.assertIn("TOULON", posted[0][1])
        self.assertEqual({r["store_id"]: r["zone"] for r in w.store.db.execute("SELECT * FROM store_stock")}, {"n": "06", "t": "83"})

    def test_regions_round_robin_and_untouched_zones(self):
        from pokewatch.instore import StoreStock
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        w = Watcher({"settings": {"database": db, "zones": [{"name": "06", "code_postal": "06000", "rayon_km": 45}],
                                  "regions": True, "max_slow_zones_per_run": 3}, "alerts": {}, "watchlist": []})
        self.assertEqual(len(w.zones), 14)
        self.assertEqual([p["location"] for p in w.zones[5]["points"]], ["33000", "87000", "86000"])  # Nouvelle-Aquitaine
        seen = []
        with mock.patch("builtins.print"):
            for _ in range(5):
                w.select_zones()
                seen.append([z["name"] for z in w.zones if z["active"]])
        self.assertTrue(all(r[0] == "06" and len(r) == 4 for r in seen[:4]))  # 06 + 3 régions par passage
        self.assertEqual(len({n for r in seen[:5] for n in r[1:]}), 13)  # toutes les régions en 5 passages
        # Un magasin d'une zone non vérifiée ce passage garde son état « en stock ».
        u = "https://www.lagranderecre.fr/x/y.html"
        w.store.add_product(u, "lagranderecre")
        t = StoreStock("t", "TOULON", 60, True, "En stock"); t.zone = "paca"
        n = StoreStock("n", "NICE", 1, True, "En stock"); n.zone = "06"
        w.store.record_store_stock(u, "lagranderecre", "X", [t, n], {"06", "paca"})
        w.store.record_store_stock(u, "lagranderecre", "X", [], {"06"})
        self.assertEqual({r["store_id"]: r["in_stock"] for r in w.store.db.execute("SELECT * FROM store_stock")}, {"t": 1, "n": 0})

    def test_region_first_pass_and_missing_channel_are_silent(self):
        from pokewatch.instore import StoreStock
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        w = Watcher({"settings": {"database": db, "zones": [{"name": "06", "code_postal": "06000", "rayon_km": 45}],
                                  "regions": True, "max_slow_zones_per_run": 13, "estimate_quantity": False},
                     "alerts": {"zone_webhooks": {"idf": "hook-idf"}}, "watchlist": []})
        for z in w.zones:
            for p in z["points"]:
                p["coords"] = (48.8, 2.3) if z["name"] == "idf" else (0.0, 0.0)
        u = "https://www.lagranderecre.fr/x/y.html"
        stock = {"paris": False}
        def answer(url, lat, lon, **k):
            if (lat, lon) != (48.8, 2.3):
                return []
            return [StoreStock("p", "PARIS", 3, stock["paris"], "x"), StoreStock("q", "VERSAILLES", 20, True, "x")]
        sent = []
        w.notifier.send = lambda m, zone=None, **k: sent.append((zone, m))
        with mock.patch("pokewatch.watcher.proximis_store_stock", side_effect=answer), mock.patch("builtins.print"):
            w.store.add_product(u, "lagranderecre")
            w.store.record_store_stock(u, "lagranderecre", "X", [], {"06"})  # produit déjà suivi (06)
            w.select_zones()
            w.check_stores(u, RETAILERS["lagranderecre"], "X")  # 1er passage idf : Versailles déjà en stock, silence
            for z in w.zones:
                if z["fresh"]:
                    w.store.set_meta(f"zone_init_{z['name']}", "1")
            for z in w.zones:
                w.store.set_meta(f"zone_last_{z['name']}", "0")
            w.select_zones()
            stock["paris"] = True
            w._store_last.clear()
            w.check_stores(u, RETAILERS["lagranderecre"], "X")
        self.assertEqual([z for z, _ in sent], ["idf"])
        self.assertIn("PARIS", sent[0][1])
        self.assertNotIn("VERSAILLES", sent[0][1])

    def test_pc_regions_only_for_cultura(self):
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        w = Watcher({"settings": {"database": db, "zones": [{"name": "06", "code_postal": "06000", "rayon_km": 45}],
                                  "regions": True, "regions_retailers": ["cultura"]}, "alerts": {}, "watchlist": []})
        for z in w.zones:
            for p in z["points"]:
                p["coords"] = (0.0, 0.0)
        calls = []
        cult = []
        with mock.patch("pokewatch.watcher.proximis_store_stock", side_effect=lambda *a, **k: calls.append(1) or []), \
             mock.patch("pokewatch.watcher.cultura_store_stock_multi", side_effect=lambda f, u, pts: cult.append(len(pts)) or [[] for _ in pts]), \
             mock.patch("builtins.print"):
            w.check_stores("https://www.lagranderecre.fr/x/y.html", RETAILERS["lagranderecre"], "X")
            w.check_stores("https://www.cultura.com/p-x-1.html", RETAILERS["cultura"], "X")
        self.assertEqual(len(calls), 1)  # La Grande Récré : le 06 seulement sur le PC
        self.assertEqual(cult, [1 + sum(len(r[4]) for r in __import__("pokewatch.regions").regions.REGIONS)])  # Cultura : partout

    def test_pc_down_then_up(self):
        import io, json as _json, time as _t
        from pokewatch import daily
        w, _ = self.watcher()
        sent = []
        w.notifier.send = lambda m, *a, **k: sent.append(m)
        def ntfy(ts):
            body = "\n".join(_json.dumps({"time": t}) for t in ts).encode()
            return mock.patch.object(daily.urllib.request, "urlopen", return_value=io.BytesIO(body))
        with mock.patch("builtins.print"):
            with ntfy([]):
                daily.check_pc(w)  # jamais vu : rien
            with ntfy([_t.time() - 3600]):
                daily.check_pc(w)
                daily.check_pc(w)  # une seule alerte par panne
            with ntfy([_t.time() - 60]):
                daily.check_pc(w)
        self.assertEqual(len(sent), 2)
        self.assertIn("ne tourne plus", sent[0])
        self.assertIn("a repris", sent[1])

    def test_long_discord_message_split(self):
        from pokewatch.notify import _chunks
        parts = _chunks("\n".join(f"ligne {i} " + "x" * 50 for i in range(100)), 1900)
        self.assertTrue(len(parts) > 1 and all(len(p) <= 1900 for p in parts))
        self.assertEqual("\n".join(parts).count("ligne"), 100)


class DiscordSetupTests(unittest.TestCase):
    def fake(self):
        st = {"roles": [{"id": "1", "name": "@everyone"}, {"id": "60", "name": "06"}],
              "channels": [{"id": "c06", "name": "alertes-06", "type": 0}], "hooks": {}, "n": 100,
              "onboarding": {"prompts": [{"id": "p1", "type": 0, "title": "Quelle est ta région ?", "single_select": False,
                                          "required": True, "in_onboarding": True,
                                          "options": [{"id": "o1", "title": "06 – Alpes-Maritimes", "role_ids": ["60"],
                                                       "channel_ids": [], "emoji": {"name": "🌴"}}]}],
                             "default_channel_ids": ["g"], "enabled": True, "mode": 0}, "calls": []}

        def api(method, path, body=None):
            st["calls"].append((method, path))
            st["n"] += 1
            nid = str(st["n"])
            if path == "/users/@me":
                return {"id": "bot"}
            if path.endswith("/roles"):
                if method == "GET":
                    return list(st["roles"])
                st["roles"].append({"id": nid, "name": body["name"]})
                return st["roles"][-1]
            if path.endswith("/channels"):
                if method == "GET":
                    return list(st["channels"])
                st["channels"].append({"id": nid, **body})
                return st["channels"][-1]
            if path.endswith("/webhooks"):
                cid = path.split("/")[2]
                if method == "GET":
                    return [st["hooks"][cid]] if cid in st["hooks"] else []
                st["hooks"][cid] = {"id": nid, "token": "t" + nid, "name": body["name"]}
                return st["hooks"][cid]
            if path.endswith("/onboarding"):
                if method == "GET":
                    return json.loads(json.dumps(st["onboarding"]))
                st["onboarding"] = body
                return body
            raise AssertionError(path)
        return st, api

    def test_creates_everything_once(self):
        from pokewatch import discord_setup
        st, api = self.fake()
        hooks = discord_setup.setup(api, "1", log=lambda *a: None)
        self.assertEqual(len(hooks), 14)
        self.assertTrue(hooks["idf"].startswith("https://discord.com/api/webhooks/"))
        names = {c["name"] for c in st["channels"]}
        self.assertIn("alertes-ile-de-france", names)
        self.assertIn("🗺️ Alertes régions", names)
        chan = next(c for c in st["channels"] if c["name"] == "alertes-corse")
        corse = next(r for r in st["roles"] if r["name"] == "Corse")
        perms = {o["id"]: o for o in chan["permission_overwrites"]}
        self.assertEqual(perms["1"]["deny"], str(1 << 10))  # @everyone ne voit pas
        self.assertEqual(perms[corse["id"]]["allow"], str((1 << 10) | (1 << 16)))
        prompts = st["onboarding"]["prompts"]
        self.assertEqual([len(p["options"]) for p in prompts], [6, 8])  # sud (avec le 06) + nord
        self.assertEqual(prompts[0]["id"], "p1")  # l'ancienne question est réutilisée
        self.assertEqual(prompts[0]["options"][0]["id"], "o1")  # et la réponse 06 aussi
        # Deuxième lancement : rien de neuf, mêmes webhooks
        before = (len(st["roles"]), len(st["channels"]))
        again = discord_setup.setup(api, "1", log=lambda *a: None)
        self.assertEqual((len(st["roles"]), len(st["channels"])), before)
        self.assertEqual(again, hooks)
        self.assertEqual([len(p["options"]) for p in st["onboarding"]["prompts"]], [6, 8])


class FlappingTests(unittest.TestCase):
    def test_unreadable_page_keeps_last_status(self):
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        u = "https://www.e.leclerc/fp/pokemon-30a-mini-tin-modele-aleatoire-0196214146297"
        w = Watcher({"settings": {"database": db, "min_delay_seconds": 0, "max_delay_seconds": 0}, "alerts": {}, "watchlist": []})
        pages = [jsonld_page("OutOfStock"), jsonld_page("InStock"), "<html>Trop de demandes</html>", jsonld_page("InStock")]
        w.fetcher.get = lambda url, needs_browser=False: pages.pop(0)
        sent = []
        w.notifier.send = lambda m, *a, **k: sent.append(m)
        with mock.patch("builtins.print"):
            for _ in range(4):
                w.check(u, "Mini Tin")
        self.assertEqual(len(sent), 1)  # une seule alerte « en stock », pas de seconde après la page illisible


class RateLimitTests(unittest.TestCase):
    def test_429_pauses_retailer(self):
        from pokewatch.fetch import FetchError
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        w = Watcher({"settings": {"database": db}, "alerts": {}, "watchlist": []})
        calls = []
        def boom(url):
            calls.append(url)
            raise FetchError("HTTP 429")
        with mock.patch("pokewatch.watcher.resolve_url", side_effect=boom), mock.patch("builtins.print"):
            w.check("https://www.e.leclerc/recherche?q=0196214147225")
            w.check("https://www.e.leclerc/recherche?q=0196214147102")
        self.assertEqual(len(calls), 1)  # après le 429, Leclerc est laissé tranquille


class ImageTests(unittest.TestCase):
    def test_image_found_and_sent_to_discord(self):
        html = ('<script type="application/ld+json">{"@type":"Product","name":"Mini Tin","image":["https://img.example/tin.jpg"],'
                '"offers":{"@type":"Offer","availability":"https://schema.org/InStock"}}</script>')
        self.assertEqual(parse_availability(html).image, "https://img.example/tin.jpg")
        self.assertEqual(parse_availability('<meta property="og:image" content="https://img.example/og.jpg">').image,
                         "https://img.example/og.jpg")
        from pokewatch.notify import Notifier
        posted = []
        with mock.patch("pokewatch.notify._post_json", side_effect=lambda h, p: posted.append(p)), mock.patch("builtins.print"):
            Notifier({"discord_webhook": "h"}).send("✅ EN STOCK", image="https://img.example/tin.jpg")
        self.assertEqual(posted, [{"content": "✅ EN STOCK", "embeds": [{"image": {"url": "https://img.example/tin.jpg"}}]}])


class SoftBlockTests(unittest.TestCase):
    def test_three_unreadable_pages_pause_retailer(self):
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        w = Watcher({"settings": {"database": db, "min_delay_seconds": 0, "max_delay_seconds": 0}, "alerts": {}, "watchlist": []})
        u = "https://www.joueclub.fr/pokemon/pokemon-mini-tin-0196214146297.html"
        fetched = []
        pages = [jsonld_page("OutOfStock")] + ["<html><title>Salle d'attente</title></html>"] * 10
        w.fetcher.get = lambda url, needs_browser=False: fetched.append(url) or pages.pop(0)
        with mock.patch("builtins.print"):
            for _ in range(6):
                w.check(u, "Mini Tin")
        self.assertEqual(len(fetched), 4)  # 1 lecture normale + 3 illisibles, puis pause
        self.assertEqual(w.store.get(u)["status"], "rupture")


class DirectHitTests(unittest.TestCase):
    def test_search_opening_product_page_directly(self):
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        w = Watcher({"settings": {"database": db, "min_delay_seconds": 0, "max_delay_seconds": 0}, "alerts": {}, "watchlist": []})
        search = "https://www.cdiscount.com/search/10/0196214146297.html"
        fiche = "https://www.cdiscount.com/juniors/cartes/mini-tin-pokemon-30a/f-1220618-pok196214146297.html"
        page = jsonld_page("InStock").replace("</body>", "réf. pok196214146297</body>")
        w.fetcher.get = lambda url, needs_browser=False: page
        w.fetcher._browser.last_url = fiche + "?mpos=1"
        with mock.patch("builtins.print"):
            w.check(search, "Mini Tin (Cdiscount)")
        self.assertEqual(w.store.get(search)["found_url"], fiche)


class EanInLinkTests(unittest.TestCase):
    def test_link_containing_ean_found_behind_sponsored(self):
        db = os.path.join(tempfile.mkdtemp(), "t.db")
        w = Watcher({"settings": {"database": db, "min_delay_seconds": 0, "max_delay_seconds": 0}, "alerts": {}, "watchlist": []})
        search = "https://www.cdiscount.com/search/10/0196214146297.html"
        sponsored = "".join(f'<a href="/juniors/cartes/sponso-{i}/f-1220618-abc{i}.html">x</a>' for i in range(6))
        fiche = "https://www.cdiscount.com/juniors/jeux-de-societe-cartes/pokemon-30eme-anniversaire-mini-tin-10-visuel/f-120791604-pok196214146297.html"
        pages = {search: sponsored + f'<a href="{fiche}?sw=abc#cm">Mini Tin</a>', fiche: jsonld_page("OutOfStock")}
        w.fetcher.get = lambda url, needs_browser=False: pages.get(url, "<html></html>")
        with mock.patch("builtins.print"):
            w.check(search, "Mini Tin (Cdiscount)")
        self.assertEqual(w.store.get(search)["found_url"], fiche)


class CdiscountTests(unittest.TestCase):
    def test_unnamed_seller_needs_page_marker(self):
        from pokewatch.retailers import RETAILERS
        r = RETAILERS["cdiscount"]
        offer = '<script type="application/ld+json">{"@type":"Product","name":"Mini Tin","offers":{"@type":"Offer","price":"14.99","availability":"https://schema.org/InStock"}}</script>'
        parse = lambda html: parse_availability(html, seller=r.own_seller, seller_marker=r.seller_marker)
        self.assertEqual(parse(offer + "<p>Vendu par CARDS-SHOP et expédié par Cdiscount</p>").status, "rupture")
        av = parse(offer + "<p>Vendu et expédié par Cdiscount</p>")
        self.assertEqual((av.status, av.source), ("en_stock", "jsonld (vendeur : non indiqué)"))

    def test_named_seller(self):
        from pokewatch.retailers import RETAILERS
        r = RETAILERS["cdiscount"]
        page = lambda name: ('<script type="application/ld+json">{"@type":"Product","name":"Tin","offers":{"@type":"Offer",'
                             '"availability":"https://schema.org/InStock","seller":{"name":"%s"}}}</script>' % name)
        parse = lambda html: parse_availability(html, seller=r.own_seller, seller_marker=r.seller_marker).status
        self.assertEqual(parse(page("Cdiscount")), "en_stock")
        self.assertEqual(parse(page("Expédié par Cdiscount")), "rupture")
        self.assertEqual(parse(page("POKE-STORE")), "rupture")


class LeclercTests(unittest.TestCase):
    def test_sold_out_page_without_availability(self):
        html = ('<script type="application/ld+json">{"@type":"Product","name":"Mini Tin","offers":[{"@type":"Offer",'
                '"url":"fp/x"},{"@type":"AggregateOffer","offerCount":0,"lowPrice":0}]}</script>')
        self.assertEqual(parse_availability(html).status, "rupture")

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
        w.notifier.send = lambda m, *a, **k: sent.append(m)
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
        w.notifier.send = lambda m, *a, **k: sent.append(m)
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
        self.assertIn('url_key:{eq:"booster-pokemon-m6-storm-emeralda-import-japon-13319873"}', calls[0])
        # liste des magasins mise en cache : un seul appel "stores" pour deux produits
        instore.cultura_store_stock(FakeFetcher(), url, "06400", radius_km=100)
        self.assertEqual(sum("stores(" in c for c in calls), 1)
        # Plusieurs régions : un seul appel « produit » pour tous les cercles
        before = sum("products(" in c for c in calls)
        multi = instore.cultura_store_stock_multi(FakeFetcher(), url, [("06400", 100), ("06400", 10)])
        self.assertEqual(sum("products(" in c for c in calls) - before, 1)
        self.assertEqual([len(m) for m in multi], [4, 1])
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
        w.notifier.send = lambda m, *a, **k: sent.append(m)
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
