# pokemon-watch

Veille des **restocks et nouveautés Pokémon TCG** chez les enseignes françaises :
JouéClub, La Grande Récré, Fnac, Cultura (+ Carrefour, E.Leclerc, Micromania).

Le logiciel :

1. **repère les nouveaux produits** sur les pages de recherche des enseignes (nouvelle extension, nouveau coffret…) ;
2. **relève la disponibilité en ligne** de chaque fiche produit à intervalle régulier (en stock / précommande / rupture + prix) ;
3. **relève le stock magasin par magasin** autour de votre code postal (JouéClub et La Grande Récré) ;
4. **vous alerte** (console, Discord, Telegram) dès qu'un produit **devient achetable**, en ligne ou dans un magasin proche ;
5. affiche tout dans un **tableau de bord web** avec l'historique des mouvements.

## État par enseigne (testé sur les vrais sites le 5 octobre 2026)

| Enseigne | Nouveautés | Stock en ligne | Stock par magasin |
|---|---|---|---|
| JouéClub | ✅ | ✅ | ✅ |
| La Grande Récré | ✅ | ✅ | ✅ |
| Fnac | — | ✅ extension Chrome | ✅ magasin choisi sur fnac.com (extension Chrome) |
| Cultura | ✅ depuis votre PC | ✅ depuis votre PC | ✅ depuis votre PC |

⚠️ = bloqué depuis un serveur. Depuis votre PC, avec `browser_visible = true` (une vraie fenêtre
de navigateur s'ouvre), ça passe en général. À vérifier chez vous avec
`python -m pokewatch test --visible "<url>"`.

## Ce qui déclenche une alerte

- ✅ **En stock en ligne** : un produit passe de rupture à disponible sur le site ;
- 📦 **Réassort prévu** : JouéClub / La Grande Récré affichent une date de réassort ;
- 🏬 **En stock en magasin** : un magasin proche l'a en rayon ;
- 🚚 **Arrivage en magasin** : pas encore en rayon, mais commandable en retrait dans ce magasin
  (envoi depuis l'entrepôt), avec la date de retrait annoncée ;
- 🆕 **Nouveau produit** apparu sur les pages surveillées.

Les enseignes ne publient pas leurs livraisons prévues en magasin : le réassort affiché et le
retrait « sous X jours » sont les seuls signaux d'arrivage accessibles de l'extérieur.

## Fnac : extension Chrome (`extension-fnac/`)

La Fnac (DataDome) bloque aussi les navigateurs pilotés par un programme. L'extension tourne
dans **votre** Chrome habituel : toutes les N minutes elle ouvre vos fiches Fnac dans un onglet
en arrière-plan, lit la disponibilité (schema.org puis textes de la page), referme l'onglet et
alerte sur Discord. Elle lit le bloc d'achat de la fiche (`data-automation-id` :
`pdp-buyBox-webAvailability-status` pour le stock en ligne, `pdp-buyBox-storeAvailability-status`
pour le magasin choisi sur fnac.com) et ignore les vendeurs tiers. Si la Fnac demande une vérification, l'extension vous prévient et c'est vous
qui la validez — rien n'est contourné.

Installation : `chrome://extensions` → activer le *Mode développeur* → *Charger l'extension non
empaquetée* → choisir le dossier `extension-fnac`. Puis cliquer sur l'icône de l'extension :
coller le webhook Discord, les fiches Fnac, *Enregistrer*, *Tester Discord*, *Vérifier maintenant*.

## Cultura : sur votre PC (Windows)

Son anti-robot bloque tous les serveurs (GitHub compris) : Cultura est relevée depuis votre PC,
avec une vraie fenêtre de navigateur. La Fnac bloque même les navigateurs pilotés depuis un PC
personnel : pour elle, utilisez l'alerte de disponibilité intégrée au site / à l'application Fnac. Téléchargez le dépôt (bouton vert *Code* →
*Download ZIP*), décompressez-le, puis double-cliquez dans l'ordre :

1. `1-installer.bat` — installe ce qu'il faut (une seule fois) ;
2. `2-tester-cultura.bat` — un passage complet de test, résultat dans `test-cultura.txt` ;
3. `3-surveiller.bat` — surveillance continue (laissez la fenêtre ouverte) : vos produits
   prioritaires chaque minute, plus Cultura.

`modifier-mes-produits.bat` ouvre `produits.txt` : une adresse de fiche produit par ligne
(JouéClub, La Grande Récré ou Cultura). Ce sont les produits vérifiés chaque minute.

## Installation

```bash
python3 --version                # 3.11 minimum
cp config.example.toml config.toml
# nécessaire pour la Fnac et Cultura (sites protégés par un anti-robot) :
pip install playwright && playwright install chromium
```

## Utilisation

```bash
python -m pokewatch test "https://www.joueclub.fr/pokemon/....html"            # vérifier qu'une fiche est bien lue
python -m pokewatch test --cp 69002 "https://www.lagranderecre.fr/....html"  # + stock des magasins proches
python -m pokewatch test --visible "https://www.fnac.com/a.../..."           # Fnac / Cultura : vraie fenêtre
python -m pokewatch notify-test     # vérifier les alertes Discord/Telegram
python -m pokewatch check           # un passage complet
python -m pokewatch watch           # surveillance continue (toutes les 10 min par défaut)
python -m pokewatch dashboard       # http://127.0.0.1:8000
```

Lancez `watch` dans un terminal et `dashboard` dans un autre. Le premier passage constitue
la base **sans aucune alerte** pour ne pas vous inonder ; ensuite seuls les vrais nouveaux
produits et les retours en stock (en ligne ou en magasin) vous sont signalés.

Réglez votre zone dans `config.toml` : `code_postal = "69002"` et `rayon_km = 30`.

### Alertes

- **Discord** : Paramètres du salon → Intégrations → Webhooks → copier l'URL dans `discord_webhook`.
- **Telegram** : créez un bot avec @BotFather (`telegram_bot_token`), envoyez-lui un message, puis récupérez
  votre `chat_id` via `https://api.telegram.org/bot<TOKEN>/getUpdates`.

Les secrets peuvent aussi être passés par variables d'environnement
(`POKEWATCH_DISCORD_WEBHOOK`, `POKEWATCH_TELEGRAM_TOKEN`, `POKEWATCH_TELEGRAM_CHAT_ID`).

## Comment la disponibilité est détectée

Par ordre de fiabilité (`pokewatch/parse.py`) :

1. données structurées **schema.org** (`Product` → `offers.availability`) que la plupart des sites exposent pour Google ;
2. balises meta `product:availability` ;
3. mots-clés propres à l'enseigne (« Ajouter au panier », « Rupture de stock », « M'alerter »…) — `pokewatch/retailers.py`.

La commande `test` indique quelle méthode a tranché. Si une enseigne renvoie toujours `inconnu`,
ajustez ses mots-clés ou son motif d'URL dans `retailers.py`.

### Stock par magasin

JouéClub et La Grande Récré utilisent la même plateforme e-commerce (Proximis). Le bouton
« Retirer en magasin » de leurs fiches interroge une API qui renvoie les magasins proches avec
l'état du stock de chacun ; `pokewatch/instore.py` rejoue cette requête. Le code postal est
converti en coordonnées par le géocodeur officiel de l'IGN (data.geopf.fr).

Cultura (Magento) expose une API GraphQL : `stores(search:"<code postal>")` donne les magasins
proches et leur `seller_code`, et `products(filter:{url_key:…})` liste une offre par magasin qui a
le produit. Le site étant derrière Cloudflare, ces appels sont faits depuis la fenêtre de navigateur
ouverte sur votre PC, comme le fait la page elle-même. `explorer-cultura.bat` (commande
`explorer`) sert à capter ces requêtes si le site change.

## Limites à connaître

- **Anti-robots.** La Fnac (DataDome) et Cultura (Cloudflare) bloquent les accès automatisés depuis
  un serveur, même avec un navigateur. Depuis une connexion à la maison avec une fenêtre visible,
  ça passe en général, sans garantie.
- **Les sites changent.** Si une enseigne ne renvoie plus rien, vérifiez avec `python -m pokewatch test "<url>"`
  et ajustez `retailers.py`.
- Respectez les conditions d'utilisation des sites : usage personnel, fréquence modérée (≥ 5 min).

## Structure

```
pokewatch/
  parse.py       détection de la disponibilité dans le HTML
  retailers.py   profils des enseignes (domaines, motifs d'URL, mots-clés)
  instore.py     stock magasin par magasin (JouéClub, La Grande Récré)
  fetch.py       récupération HTTP / navigateur
  store.py       historique SQLite
  notify.py      alertes console / Discord / Telegram
  watcher.py     boucle de surveillance
  dashboard.py   tableau de bord web
tests/           python -m unittest discover -s tests -t .
```

## Chantiers

- [x] Enseignes : JouéClub, La Grande Récré, Fnac, Cultura (+ Carrefour, Leclerc, Micromania)
- [x] Alertes : Discord, Telegram, console
- [x] Stock en ligne + nouveautés + tableau de bord
- [x] Stock par magasin : JouéClub, La Grande Récré
- [ ] Fnac et Cultura : valider depuis une connexion personnelle, puis stock par magasin
- [ ] Hébergement 24h/24 (PC allumé, Raspberry Pi ou petit serveur)
