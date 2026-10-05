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
    last_error TEXT
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
CREATE TABLE IF NOT EXISTS searches (
    url        TEXT PRIMARY KEY,
    first_run  TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

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

    def search_seen(self, url: str) -> bool:
        """Marque une page de recherche comme déjà parcourue ; retourne True si c'était déjà le cas."""
        cur = self.db.execute("INSERT OR IGNORE INTO searches (url, first_run) VALUES (?, ?)", (url, now()))
        self.db.commit()
        return cur.rowcount == 0

    def products(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM products ORDER BY CASE status WHEN 'en_stock' THEN 0 WHEN 'precommande' THEN 1 "
            "ELSE 2 END, last_change DESC"
        ).fetchall()

    def events(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM events ORDER BY ts DESC, id DESC LIMIT ?", (limit,)).fetchall()
