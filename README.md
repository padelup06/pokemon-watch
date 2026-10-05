# pokemon-watch

Veille des **restocks et nouveautés Pokémon TCG** chez les enseignes françaises :
Cultura, JouéClub, La Grande Récré, Auchan (+ Carrefour, E.Leclerc, Fnac, Micromania).

Le logiciel :

1. **repère les nouveaux produits** sur les pages de recherche des enseignes (nouvelle extension, nouveau coffret…) ;
2. **relève la disponibilité** de chaque fiche produit à intervalle régulier (en stock / précommande / rupture + prix) ;
3. **vous alerte** (console, Discord, Telegram) dès qu'un produit **devient achetable** ;
4. affiche tout dans un **tableau de bord web** avec l'historique des mouvements.

## Installation

```bash
python3 --version                # 3.11 minimum
cp config.example.toml config.toml
# optionnel mais recommandé (sites protégés par un anti-bot, ex. Auchan) :
pip install playwright && playwright install chromium
```

## Utilisation

```bash
python -m pokewatch test "https://www.cultura.com/p-....html"   # vérifier qu'une fiche est bien lue
python -m pokewatch notify-test     # vérifier les alertes Discord/Telegram
python -m pokewatch check           # un passage complet
python -m pokewatch watch           # surveillance continue (toutes les 10 min par défaut)
python -m pokewatch dashboard       # http://127.0.0.1:8000
```

Lancez `watch` dans un terminal et `dashboard` dans un autre. Au premier passage,
les produits trouvés sont enregistrés **sans alerte « nouveau produit »** pour ne pas vous
inonder ; ensuite seuls les vrais nouveaux produits et les retours en stock vous sont signalés.

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

## Limites à connaître

- **Stock en ligne, pas stock par magasin.** Ce qui est surveillé, c'est la disponibilité affichée sur le site
  (livraison / retrait). Le stock d'un magasin précis passe par des API internes propres à chaque enseigne
  (non documentées, qui changent souvent) — c'est la prochaine étape logique, enseigne par enseigne.
- **Anti-bot.** Auchan, Carrefour, Fnac et Leclerc bloquent souvent les requêtes simples ; le mode navigateur
  (Playwright) passe mieux mais pas à tous les coups. Gardez un intervalle raisonnable (≥ 5 min).
- **Les sites changent.** Les URLs de recherche dans `config.example.toml` et les motifs de liens produits sont
  à vérifier avec `python -m pokewatch test "<url>"`.
- Respectez les conditions d'utilisation des sites : usage personnel, fréquence modérée.

## Structure

```
pokewatch/
  parse.py       détection de la disponibilité dans le HTML
  retailers.py   profils des enseignes (domaines, motifs d'URL, mots-clés)
  fetch.py       récupération HTTP / navigateur headless
  store.py       historique SQLite
  notify.py      alertes console / Discord / Telegram
  watcher.py     boucle de surveillance
  dashboard.py   tableau de bord web
tests/           python -m unittest
```

## Chantiers

- [x] Enseignes : Cultura, JouéClub, La Grande Récré, Auchan (+ Carrefour, Leclerc, Fnac, Micromania)
- [x] Alertes : Discord, Telegram, console
- [x] Première implémentation (stock en ligne + nouveautés + tableau de bord)
- [ ] Valider les sélecteurs sur les sites réels, enseigne par enseigne
- [ ] Stock par magasin (API internes des enseignes, à partir d'un code postal)
- [ ] Hébergement 24h/24 (Raspberry Pi, VPS ou GitHub Actions)
