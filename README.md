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
| Fnac | ❌ bloque même depuis un PC (DataDome) | ❌ | ❌ |
| Cultura | ✅ depuis votre PC | ✅ depuis votre PC | ⏳ en cours |

⚠️ = bloqué depuis un serveur. Depuis votre PC, avec `browser_visible = true` (une vraie fenêtre
de navigateur s'ouvre), ça passe en général. À vérifier chez vous avec
`python -m pokewatch test --visible "<url>"`.

## Cultura : sur votre PC (Windows)

Son anti-robot bloque tous les serveurs (GitHub compris) : Cultura est relevée depuis votre PC,
avec une vraie fenêtre de navigateur. La Fnac bloque même les navigateurs pilotés depuis un PC
personnel : pour elle, utilisez l'alerte de disponibilité intégrée au site / à l'application Fnac. Téléchargez le dépôt (bouton vert *Code* →
*Download ZIP*), décompressez-le, puis double-cliquez dans l'ordre :

1. `1-installer.bat` — installe ce qu'il faut (une seule fois) ;
2. `2-explorer-cultura.bat` — sur une fiche produit, cliquez sur la disponibilité en magasin,
   tapez votre code postal puis fermez la fenêtre : le fichier `exploration-cultura.json` produit
   permet de brancher le stock magasin (cookies non enregistrés) ;
3. `3-surveiller-fnac-cultura.bat` — surveillance continue (laissez la fenêtre ouverte).

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
