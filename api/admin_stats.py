"""Admin stats dashboard — view in browser with bearer token auth."""
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.config import CRON_SECRET
from lib.database import get_conn, init_db


def _authorized(headers) -> bool:
    if not CRON_SECRET:
        return True
    auth = headers.get("Authorization", "")
    return auth == f"Bearer {CRON_SECRET}"


def _esc(s) -> str:
    """Minimal HTML escaping."""
    if not s:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _token_from_query(path: str) -> str:
    import urllib.parse
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(path or "").query)
    return (qs.get("token") or [""])[0]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Accept either Authorization header OR ?token= query param
        authed = _authorized(self.headers)
        if not authed:
            token = _token_from_query(self.path)
            if CRON_SECRET and token == CRON_SECRET:
                authed = True
        if not authed:
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Unauthorized. Add ?token=YOUR_CRON_SECRET or Authorization: Bearer header.")
            return

        try:
            html = build_html()
        except Exception:
            print("admin_stats error:", traceback.format_exc(), flush=True)
            html = f"<pre>Error: {traceback.format_exc()}</pre>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))


def build_html() -> str:
    conn = get_conn()
    try:
        init_db(conn)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM users")
        n_users = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM meals")
        n_meals = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM daily_logs")
        n_days = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM daily_recommendations")
        n_recs = cur.fetchone()[0]

        # Per-user stats
        cur.execute("""
            SELECT u.user_id, COALESCE(u.username, ''), u.created_at,
                   COUNT(m.id) AS meals, MAX(m.created_at) AS last_meal
            FROM users u LEFT JOIN meals m ON m.user_id = u.user_id
            GROUP BY u.user_id, u.username, u.created_at
            ORDER BY meals DESC, u.created_at DESC
        """)
        user_rows = cur.fetchall()

        # Last 20 meals
        cur.execute("""
            SELECT user_id, date, meal_type, description, calories, protein_g,
                   carbs_g, fat_g, created_at
            FROM meals ORDER BY id DESC LIMIT 20
        """)
        meal_rows = cur.fetchall()

        cur.close()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Build user table rows
    user_tbody = ""
    for r in user_rows:
        uid, uname, joined, meals, last = r
        user_tbody += (
            f"<tr><td>{uid}</td><td>{_esc(uname)}</td>"
            f"<td>{_esc((joined or '')[:19])}</td>"
            f"<td>{meals}</td><td>{_esc((last or '—')[:19])}</td></tr>\n"
        )

    # Build meals table rows
    meals_tbody = ""
    for r in meal_rows:
        uid, date, mt, desc, cal, p, c, f, ts = r
        meals_tbody += (
            f"<tr><td>{_esc((ts or '')[:19])}</td><td>{uid}</td>"
            f"<td>{_esc(date)}</td><td>{_esc(mt)}</td>"
            f"<td>{_esc((desc or '')[:60])}</td>"
            f"<td>{round(cal or 0)}</td><td>{round(p or 0)}</td>"
            f"<td>{round(c or 0)}</td><td>{round(f or 0)}</td></tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Food Tracker — Admin</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #1a1a2e; color: #e0e0e0; margin: 0; padding: 20px; }}
  h1 {{ color: #e94560; }}
  h2 {{ color: #0f3460; background: #16213e; padding: 10px 16px; border-radius: 8px; color: #e0e0e0; }}
  .cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 20px 0; }}
  .card {{ background: #16213e; border-radius: 12px; padding: 20px; min-width: 140px; text-align: center; }}
  .card .num {{ font-size: 2em; font-weight: bold; color: #e94560; }}
  .card .label {{ color: #a0a0a0; margin-top: 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0 30px; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #2a2a4a; }}
  th {{ background: #0f3460; color: #fff; }}
  tr:hover {{ background: #1f1f3a; }}
  @media (max-width: 600px) {{ .cards {{ flex-direction: column; }} table {{ font-size: 0.85em; }} }}
</style>
</head>
<body>
<h1>🥗 Food Tracker — Admin Dashboard</h1>

<div class="cards">
  <div class="card"><div class="num">{n_users}</div><div class="label">Користувачів</div></div>
  <div class="card"><div class="num">{n_meals}</div><div class="label">Страв записано</div></div>
  <div class="card"><div class="num">{n_days}</div><div class="label">Днів з даними</div></div>
  <div class="card"><div class="num">{n_recs}</div><div class="label">Нічних підсумків</div></div>
</div>

<h2>👥 Користувачі</h2>
<table>
<thead><tr><th>user_id</th><th>username</th><th>Приєднався</th><th>Страв</th><th>Остання страва</th></tr></thead>
<tbody>{user_tbody}</tbody>
</table>

<h2>🍽️ Останні 20 страв</h2>
<table>
<thead><tr><th>Час</th><th>user_id</th><th>Дата</th><th>Тип</th><th>Опис</th><th>ккал</th><th>Б</th><th>В</th><th>Ж</th></tr></thead>
<tbody>{meals_tbody}</tbody>
</table>
</body>
</html>"""
