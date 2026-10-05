"""Tableau de bord web minimal (aucune dépendance) : http://localhost:8000"""

from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .notify import STATUS_LABEL
from .retailers import RETAILERS
from .store import Store

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--muted:#6b7280;--line:#e5e7eb;
--ok:#0f7a3d;--okbg:#e3f6ea;--pre:#8a5a00;--prebg:#fff3d6;--ko:#9b1c1c;--kobg:#fde8e8}
@media (prefers-color-scheme:dark){:root{--bg:#11141a;--card:#1a1e26;--fg:#e8eaf0;--muted:#9aa3b2;
--line:#2a303b;--ok:#6ee7a0;--okbg:#123222;--pre:#facc6b;--prebg:#3a2c0b;--ko:#fca5a5;--kobg:#3b1515}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}
h2{font-size:17px;margin:28px 0 10px}.sub{color:var(--muted);margin:0 0 18px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.chip{padding:5px 12px;border:1px solid var(--line);border-radius:999px;background:var(--card);
color:var(--fg);text-decoration:none;font-size:14px}.chip.on{border-color:var(--fg)}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{width:100%;border-collapse:collapse}th,td{padding:9px 12px;text-align:left;
border-bottom:1px solid var(--line);vertical-align:top}th{font-size:13px;color:var(--muted);font-weight:600}
tr:last-child td{border-bottom:0}a{color:inherit}.muted{color:var(--muted);font-size:13px}
.b{display:inline-block;padding:2px 8px;border-radius:6px;font-size:13px;white-space:nowrap}
.en_stock{color:var(--ok);background:var(--okbg)}.precommande{color:var(--pre);background:var(--prebg)}
.rupture{color:var(--ko);background:var(--kobg)}.inconnu{color:var(--muted);background:var(--bg)}
"""


def _when(ts: str | None) -> str:
    return escape(ts.replace("T", " ")[:16]) + " UTC" if ts else "—"


def _badge(status: str | None) -> str:
    s = status or "inconnu"
    return f'<span class="b {escape(s)}">{escape(STATUS_LABEL.get(s, s))}</span>'


def render(store: Store, retailer: str | None = None) -> str:
    rows = [p for p in store.products() if not retailer or p["retailer"] == retailer]
    in_stock = sum(1 for p in rows if p["status"] in ("en_stock", "precommande"))
    chips = ['<a class="chip%s" href="/">Toutes</a>' % (" on" if not retailer else "")]
    for key in sorted({p["retailer"] for p in store.products()}):
        name = RETAILERS[key].name if key in RETAILERS else key
        chips.append(f'<a class="chip{" on" if key == retailer else ""}" href="/?r={escape(key)}">{escape(name)}</a>')

    prod_html = []
    for p in rows:
        name = p["label"] if p["label"] and p["label"] != "découverte" else p["name"]
        rname = RETAILERS[p["retailer"]].name if p["retailer"] in RETAILERS else p["retailer"]
        err = f'<div class="muted">⚠ {escape(p["last_error"])}</div>' if p["last_error"] else ""
        price = f'{p["price"]:.2f} €' if p["price"] is not None else "—"
        def _names(rows):
            names = ", ".join(
                escape(st["store_name"]) + (f' <span class="muted">{st["distance_km"]:g} km</span>' if st["distance_km"] is not None else "")
                for st in rows[:3]
            )
            return names + (f' <span class="muted">+{len(rows) - 3}</span>' if len(rows) > 3 else "")

        stores, incoming = store.stores_in_stock(p["url"]), store.stores_incoming(p["url"])
        parts = []
        if stores:
            parts.append(f'<div><span class="b en_stock">{len(stores)} en stock</span> {_names(stores)}</div>')
        if incoming:
            parts.append(f'<div><span class="b precommande">🚚 {len(incoming)} arrivage</span> {_names(incoming)}</div>')
        if parts:
            shops = "".join(parts)
        elif p["store_check"]:
            shops = '<span class="muted">aucun</span>'
        else:
            shops = '<span class="muted">—</span>'
        if p["restock"]:
            err += f'<div><span class="b precommande">📦 réassort prévu : {escape(p["restock"])}</span></div>'
        prod_html.append(
            f"<tr><td>{_badge(p['status'])}</td><td>{escape(rname)}</td>"
            f'<td><a href="{escape(p["url"])}" target="_blank" rel="noopener">{escape(name or p["url"])}</a>{err}</td>'
            f'<td style="white-space:nowrap">{price}</td><td>{shops}</td>'
            f"<td class=muted>{_when(p['last_change'])}</td><td class=muted>{_when(p['last_check'])}</td></tr>"
        )

    ev_html = []
    for e in store.events(50):
        if retailer and e["retailer"] != retailer:
            continue
        rname = RETAILERS[e["retailer"]].name if e["retailer"] in RETAILERS else e["retailer"]
        ev_html.append(
            f"<tr><td class=muted>{_when(e['ts'])}</td><td>{escape(rname)}</td>"
            f'<td><a href="{escape(e["url"])}" target="_blank" rel="noopener">{escape(e["name"] or e["url"])}</a></td>'
            f"<td>{_badge(e['old']) if e['old'] else '<span class=muted>nouveau</span>'} → {_badge(e['new'])}</td></tr>"
        )

    empty = '<tr><td colspan="7" class="muted">Aucun produit suivi pour l\'instant. Lancez <code>python -m pokewatch check</code>.</td></tr>'
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60">
<title>Pokémon Watch</title><style>{CSS}</style></head><body><main>
<h1>Pokémon Watch</h1><p class="sub">{len(rows)} produits suivis · <b>{in_stock}</b> achetables · actualisation auto toutes les 60 s</p>
<div class="chips">{''.join(chips)}</div>
<div class="wrap"><table><thead><tr><th>En ligne</th><th>Enseigne</th><th>Produit</th><th>Prix</th><th>En magasin</th><th>Dernier changement</th><th>Dernier relevé</th></tr></thead>
<tbody>{''.join(prod_html) or empty}</tbody></table></div>
<h2>Derniers mouvements</h2>
<div class="wrap"><table><thead><tr><th>Quand</th><th>Enseigne</th><th>Produit</th><th>Changement</th></tr></thead>
<tbody>{''.join(ev_html) or '<tr><td colspan="4" class="muted">Aucun mouvement enregistré.</td></tr>'}</tbody></table></div>
</main></body></html>"""


def serve(db_path: str, host: str = "127.0.0.1", port: int = 8000) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            from urllib.parse import parse_qs, urlparse

            q = parse_qs(urlparse(self.path).query)
            body = render(Store(db_path), (q.get("r") or [None])[0]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    print(f"Tableau de bord : http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
