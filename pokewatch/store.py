"""Historique des relevés (SQLite)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    url        TEXT PRIMARY KEY,
    retailer   TEXT NOT NULL,
    label      TEXT,
    name       TEXT,
    status     TEXT,
    price      REAL,
    first_seen TEXT NOT NULL,
    last_check TEXT,
    last_change TEXT,
    last_error TEXT,
    store_check TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    url      TEXT NOT NULL,
    retailer TEXT NOT NULL,
    name     TEXT,
    old      TEXT,
    new      TEXT NOT NULL,
    price    REAL
);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts DESC);
CREATE TABLE IF NOT EXISTS store_stock (
    url         TEXT NOT NULL,
    store_id    TEXT NOT NULL,
    store_name  TEXT NOT NULL,
    distance_km REAL,
    in_stock    INTEGER NOT NULL,  -- 1 = en stock, 2 = arrivage (commandable en retrait), 0 = non
    label       TEXT,
    last_check  TEXT NOT NULL,
    last_change TEXT NOT NULL,
    PRIMARY KEY (url, store_id)
);
CREATE TABLE IF NOT EXISTS searches (
    url        TEXT PRIMARY KEY,
    first_run  TEXT NOT NULL
);
"""


STORE_STATES = {0: "rupture", 1: "en_stock", 2: "arrivage"}
_RANK = {0: 0, 2: 1, 1: 2}  # rupture < arrivage < en stock


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str) -> None:
        # timeout : en mode parallèle, plusieurs fils écrivent dans la même base.
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        # Colonnes ajoutées après coup : on complète les bases existantes.
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(products)")}
        for col in ("restock", "found_url"):
            if col not in cols:
                self.db.execute(f"ALTER TABLE products ADD COLUMN {col} TEXT")
        if "last_check" not in {r[1] for r in self.db.execute("PRAGMA table_info(searches)")}:
            self.db.execute("ALTER TABLE searches ADD COLUMN last_check TEXT")
        self.db.commit()

    def get(self, url: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM products WHERE url = ?", (url,)).fetchone()

    def known_urls(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT url FROM products")}

    def add_product(self, url: str, retailer: str, label: str | None = None) -> bool:
        """Retourne True si le produit est nouveau."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO products (url, retailer, label, first_seen) VALUES (?, ?, ?, ?)",
            (url, retailer, label, now()),
        )
        self.db.commit()
        return cur.rowcount == 1

    def record(self, url: str, retailer: str, status: str, name: str | None, price: float | None):
        """Enregistre un relevé. Retourne l'ancien statut si le statut a changé, sinon None.

        Un produit jamais relevé a un ancien statut "" (différent de None),
        pour qu'un produit qui apparaît directement en stock déclenche une alerte.
        """
        row = self.get(url)
        old = row["status"] if row else None
        ts = now()
        changed = old != status
        self.db.execute(
            """INSERT INTO products (url, retailer, name, status, price, first_seen, last_check, last_change)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                 name = COALESCE(excluded.name, products.name),
                 status = excluded.status,
                 price = COALESCE(excluded.price, products.price),
                 last_check = excluded.last_check,
                 last_change = CASE WHEN products.status IS excluded.status
                                    THEN products.last_change ELSE excluded.last_change END,
                 last_error = NULL""",
            (url, retailer, name, status, price, ts, ts, ts),
        )
        if changed:
            self.db.execute(
                "INSERT INTO events (ts, url, retailer, name, old, new, price) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, url, retailer, name, old, status, price),
            )
        self.db.commit()
        return (old or "") if changed else None

    def record_error(self, url: str, retailer: str, error: str) -> None:
        self.db.execute(
            """INSERT INTO products (url, retailer, first_seen, last_check, last_error)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET last_check = excluded.last_check,
                                              last_error = excluded.last_error""",
            (url, retailer, now(), now(), error),
        )
        self.db.commit()

    def record_store_stock(self, url: str, retailer: str, name: str | None, stocks) -> list:
        """Enregistre le stock magasin par magasin.

        Retourne les magasins dont la situation vient de s'améliorer (rupture -> arrivage,
        ou -> en stock). Un magasin absent de la réponse est considéré sans stock
        (La Grande Récré et Cultura ne listent que les magasins qui ont le produit).
        """
        ts = now()
        previous = {
            r["store_id"]: r for r in self.db.execute("SELECT * FROM store_stock WHERE url = ?", (url,))
        }
        first = self.db.execute("SELECT store_check FROM products WHERE url = ?", (url,)).fetchone()
        first_time = first is None or first[0] is None
        seen, newly = set(), []
        for st in stocks:
            seen.add(st.store_id)
            old = previous.get(st.store_id)
            old_code = old["in_stock"] if old is not None else 0
            changed = old is None or old_code != st.code
            if st.code and _RANK[st.code] > _RANK[old_code]:
                newly.append(st)
            self.db.execute(
                """INSERT INTO store_stock (url, store_id, store_name, distance_km, in_stock, label, last_check, last_change)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(url, store_id) DO UPDATE SET store_name = excluded.store_name,
                     distance_km = excluded.distance_km, in_stock = excluded.in_stock, label = excluded.label,
                     last_check = excluded.last_check,
                     last_change = CASE WHEN ? THEN excluded.last_change ELSE store_stock.last_change END""",
                (url, st.store_id, st.name, st.distance_km, st.code, st.label, ts, ts, changed),
            )
            if changed and not first_time and (old is not None or st.code):
                self.db.execute(
                    "INSERT INTO events (ts, url, retailer, name, old, new, price) VALUES (?, ?, ?, ?, ?, ?, NULL)",
                    (ts, url, retailer, f"{name or url} — {st.name}",
                     None if old is None else STORE_STATES[old_code], STORE_STATES[st.code]),
                )
        for store_id, old in previous.items():
            if store_id not in seen and old["in_stock"]:
                self.db.execute(
                    "UPDATE store_stock SET in_stock = 0, label = 'En rupture', last_check = ?, last_change = ? "
                    "WHERE url = ? AND store_id = ?",
                    (ts, ts, url, store_id),
                )
                self.db.execute(
                    "INSERT INTO events (ts, url, retailer, name, old, new, price) VALUES (?, ?, ?, ?, ?, 'rupture', NULL)",
                    (ts, url, retailer, f"{name or url} — {old['store_name']}", STORE_STATES[old["in_stock"]]),
                )
        self.db.execute("UPDATE products SET store_check = ? WHERE url = ?", (ts, url))
        self.db.commit()
        # Premier relevé magasin de ce produit : on constitue l'état sans alerter.
        if first_time:
            return []
        return newly

    def stores_in_stock(self, url: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM store_stock WHERE url = ? AND in_stock = 1 ORDER BY distance_km", (url,)
        ).fetchall()

    def stores_incoming(self, url: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM store_stock WHERE url = ? AND in_stock = 2 ORDER BY distance_km", (url,)
        ).fetchall()

    def set_found(self, url: str, found_url: str | None) -> bool:
        """Pour une recherche par code-barres : mémorise la fiche trouvée ; True si elle vient d'apparaître."""
        row = self.db.execute("SELECT found_url FROM products WHERE url = ?", (url,)).fetchone()
        old = row[0] if row else None
        if old == found_url:
            return False
        self.db.execute("UPDATE products SET found_url = ? WHERE url = ?", (found_url, url))
        self.db.commit()
        return found_url is not None and old is None

    def found_urls(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT found_url FROM products WHERE found_url IS NOT NULL")]

    def set_restock(self, url: str, restock: str | None) -> str | None:
        """Enregistre l'info de réassort ; retourne la nouvelle valeur si elle vient d'apparaître ou de changer."""
        row = self.db.execute("SELECT restock FROM products WHERE url = ?", (url,)).fetchone()
        old = row[0] if row else None
        if old == restock:
            return None
        self.db.execute("UPDATE products SET restock = ? WHERE url = ?", (restock, url))
        self.db.commit()
        return restock

    def search_seen(self, url: str) -> bool:
        """Marque une page de recherche comme déjà parcourue ; retourne True si c'était déjà le cas."""
        cur = self.db.execute("INSERT OR IGNORE INTO searches (url, first_run) VALUES (?, ?)", (url, now()))
        self.db.commit()
        return cur.rowcount == 0

    def search_due(self, url: str, every_minutes: float) -> bool:
        """True si la page n'a pas été parcourue depuis every_minutes (ou jamais) ; note alors l'heure du passage."""
        row = self.db.execute("SELECT last_check FROM searches WHERE url = ?", (url,)).fetchone()
        if row and row[0] and every_minutes:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(row[0])
            if age.total_seconds() < every_minutes * 60:
                return False
        self.db.execute("UPDATE searches SET last_check = ? WHERE url = ?", (now(), url))
        self.db.commit()
        return True

    def products(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM products ORDER BY CASE status WHEN 'en_stock' THEN 0 WHEN 'precommande' THEN 1 "
            "ELSE 2 END, last_change DESC"
        ).fetchall()

    def events(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM events ORDER BY ts DESC, id DESC LIMIT ?", (limit,)).fetchall()
