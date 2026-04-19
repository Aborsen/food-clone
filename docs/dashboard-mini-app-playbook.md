# Telegram Mini App Dashboard — Portable Playbook

Everything we built into [api/dashboard.py](../api/dashboard.py), in the order a new project should apply it. Use this as a checklist when spinning up the same dashboard on another bot.

---

## 1. Architecture

- **Single-file Python handler** at `api/dashboard.py`, served from `/api/dashboard` by Vercel's `@vercel/python` builder.
- **No client-side framework, no JSON API.** The handler returns a full HTML document from an f-string. Quick actions re-render the whole page.
- **Two launch paths** from Telegram, both handled by the same endpoint:
  1. Inline-keyboard `web_app` button (bot sends a button) — signed `initData` via HMAC.
  2. Chat menu button (the 📱 / phone-icon next to the input) — falls back to a query-string bypass because the cached initData on menu-button launches is often stale.
- **Stateless.** Every request opens a fresh DB connection.

File layout:

```
api/dashboard.py        # handler + HTML template
lib/database.py         # CRUD helpers the dashboard reads
lib/config.py           # USER_PROFILE, env vars, DASHBOARD_TOKEN
scripts/set_webhook.py  # registers the chat menu button URL
```

---

## 2. Environment variables

| Var | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Webhook + mini-app HMAC secret seed + `getMe` for bot username |
| `WEBHOOK_SECRET` | Validates Telegram webhook header |
| `VERCEL_URL` | Base domain (no `https://`) for building the mini-app URL |
| `DASHBOARD_TOKEN` | 24-byte hex secret for the chat-menu-button auth bypass |
| `DATABASE_URL` | Auto-injected by the Neon Marketplace integration |
| `VERCEL_GIT_COMMIT_SHA` | Auto-injected by Vercel — used to cache-bust the menu-button URL per deploy |

Generate the dashboard token once: `openssl rand -hex 24`, then `vercel env add DASHBOARD_TOKEN production`.

---

## 3. Auth — signed initData + token bypass

### 3a. `_verify_init_data(init_data) -> dict | None`

Standard Telegram Web App auth. Key points:

1. Parse the query-string-style payload with `urllib.parse.parse_qsl`.
2. Build `data_check_string` from sorted `key=value` lines, `\n`-joined.
3. `secret_key = HMAC_SHA256(key=b"WebAppData", msg=bot_token)`.
4. `calculated_hash = HMAC_SHA256(key=secret_key, msg=data_check_string).hexdigest()`.
5. Constant-time compare with received `hash`.
6. Parse `user` JSON.

**Gotcha we hit:** the default 24-hour `auth_date` freshness window is too strict for the chat menu button, which hands Telegram a cached initData from the first mini-app launch. Set `INIT_DATA_MAX_AGE = 30 * 24 * 60 * 60` (30 days) for a personal bot. Replay risk is negligible when only one user ID is allowlisted.

### 3b. Token bypass (`?t=<DASHBOARD_TOKEN>`)

Why needed: even with the 30-day window, the menu button sometimes presents initData without a valid `hash` at all (different Telegram clients behave differently). Without a fallback, the user sees 401.

Shape of the bypass:

```python
def do_GET(self):
    parsed = urllib.parse.urlparse(self.path)
    q = urllib.parse.parse_qs(parsed.query)
    token = (q.get("t") or [""])[0]
    if DASHBOARD_TOKEN and token and hmac.compare_digest(token, DASHBOARD_TOKEN):
        user_id = next(iter(ALLOWED_USER_IDS))  # single-user bot
        user = {"id": user_id, "first_name": "Raudar"}
        self._send_html(200, _render_dashboard(user))
        return
    # default: serve bootstrap page that POSTs initData back
    self._send_html(200, _BOOTSTRAP_HTML)
```

The token is also accepted in POST (for quick-action requests) — same check against `self.path` query string.

**For multi-user bots:** don't use this bypass. Either require initData-only, or issue per-user magic-link tokens stored in the DB.

### 3c. Chat menu button URL

Built in `lib/telegram_helpers.py::_dashboard_url()`:

```python
def _dashboard_url() -> str:
    host = (VERCEL_URL or "").replace("https://", "").rstrip("/")
    base = f"https://{host}/api/dashboard"
    params = []
    if DASHBOARD_TOKEN:
        params.append(f"t={DASHBOARD_TOKEN}")
    sha = os.environ.get("VERCEL_GIT_COMMIT_SHA", "")[:8]
    if sha:
        params.append(f"v={sha}")
    return f"{base}?{'&'.join(params)}" if params else base
```

Registered on `/start` via `setChatMenuButton` with `type: "web_app"`.

---

## 4. The cache problem (the one that ate an afternoon)

**Symptom:** deploy new dashboard → open from inline keyboard → new version. Open from chat menu button → old version from two days ago. Same phone, different launch mode.

### What does NOT fully fix it

- `Cache-Control: no-store, no-cache, must-revalidate, private, max-age=0`
- `Pragma: no-cache` + `Expires: 0`
- `CDN-Cache-Control`, `Vercel-CDN-Cache-Control`, `Surrogate-Control`
- `<meta http-equiv="Cache-Control" content="no-store">`

These all help (and you should include them — they prevent the Vercel edge and some browsers from caching), but Telegram's **iOS in-app WebView ignores Cache-Control** for mini-app URLs it already has cached by URL identity. The cache key is the URL.

### What actually fixes it

**Make the URL change every deploy.** Vercel injects `VERCEL_GIT_COMMIT_SHA` into the function runtime. Append the first 8 chars as a `v=` query param to the chat menu button URL. Per deploy, the URL is different → Telegram treats it as a new resource → fresh fetch.

The user must `/start` once per deploy to register the new URL (our `handle_command("/start")` calls `set_chat_menu_button` with the current URL). Everything after that works automatically.

If you need to avoid requiring `/start`, an alternative is to call `setChatMenuButton` on every webhook message — Telegram's API is idempotent enough for this to be cheap.

### Copy the security headers anyway

```python
_SECURITY_HEADERS = [
    ("Strict-Transport-Security", "max-age=63072000; includeSubDomains"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store, no-cache, must-revalidate, private, max-age=0"),
    ("CDN-Cache-Control", "no-store"),
    ("Vercel-CDN-Cache-Control", "no-store"),
    ("Surrogate-Control", "no-store"),
    ("Pragma", "no-cache"),
    ("Expires", "0"),
    ("Content-Security-Policy",
     "default-src 'none'; style-src 'self' 'unsafe-inline'; "
     "script-src 'self' 'unsafe-inline' https://telegram.org; "
     "img-src 'self' data:; connect-src 'self'; "
     "frame-ancestors https://web.telegram.org https://t.me"),
]
```

And inside the `<head>`:

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
```

---

## 5. iOS safe-area handling (the status-bar-overlap bug)

Without handling safe-area insets, the header sits under the iPhone's clock/notch. Two changes in the HTML:

1. Viewport must opt in to safe-area insets:
   ```html
   <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
   ```

2. Body padding must include both the phone's safe area **and** Telegram's own content inset (the native header Telegram paints above the mini-app on some layouts):
   ```css
   body {
     padding: max(16px, calc(
       var(--tg-safe-area-inset-top, env(safe-area-inset-top, 0px))
       + var(--tg-content-safe-area-inset-top, 0px)
     )) 16px 16px;
   }
   ```

Apply the same to the bootstrap HTML if you have one.

---

## 6. Page structure (the user-oriented layout)

Top to bottom:

1. **Goal-aware header** — `<h1>Привіт, {name}!</h1>` plus an amber `<p class="goal">🎯 {USER_PROFILE["goal"]}</p>` and a muted `<p class="sub">За 7 днів: N/M днів у цілі</p>`. The adherence line is computed from the week history rows (`days where 0.85 ≤ cal/target ≤ 1.05`).

2. **Tabs** — День / Вчора / 7 днів / 30 днів. Plain `<button class="tab">` + one-liner JS to toggle `.active` on `.tab` and the matching `.view`.

3. **Hero card** — the single most important number at 2.8em, on a dark gradient. Calculates `ратіо r = calories / target` and picks a chip:
   - `cal == 0` → ⚪ "ще нічого"
   - `0.85 ≤ r ≤ 1.05` → 🟢 "на місці"
   - `r < 0.85` and ≥4 hours left → 🔵 "простір є"
   - `r < 0.85` and <4 hours left → 🟡 "дожени"
   - `1.05 < r ≤ 1.15` → 🟡 "майже впритик"
   - `r > 1.15` → 🔴 "перебір" (big number goes red, shows negative)

   Plus a time-aware subtext `До кінця дня ~X год` computed from `datetime.now(LOCAL_TZ).hour` and a compact "Білки X/Y г · Вода Z л" pill line.

4. **Quick actions** (3-column grid): `💧 +250 мл`, `↩️ Скасувати воду`, `💬 До бота`. Each button carries `data-action="..."` and is wired to a shared JS dispatcher.

5. **Deep details** (`<details class="card">`) with a rotating chevron — full macro bars inline (see section 7), meal count. Collapsed by default.

6. **Water card** — dedicated row + horizontal bar.

7. **Summary card** — rule-based "Підсумок дня" with a headline and per-macro bullets. No AI call.

8. **Meals list** — searchable with filter chips (meal type + "only with health notes"). Pure client-side filter.

---

## 7. Macro progress row — label + bar + value on one line

The fix we applied last: label, bar, and value in a flex row so everything reads on one line, mobile-width friendly.

Helper:

```python
def _macro_row(label: str, value: float, target: float, unit: str) -> str:
    pct = max(0.0, min(100.0, (value / target) * 100)) if target else 0.0
    return (
        f'<div class="macro">'
        f'<span class="macro-name">{_esc(label)}</span>'
        f'<div class="macro-fill-wrap"><div class="macro-fill" style="width:{pct:.1f}%"></div></div>'
        f'<b class="macro-value">{round(value)} / {round(target)} {_esc(unit)}</b>'
        f'</div>'
    )
```

CSS:

```css
.macro { display: flex; align-items: center; gap: 10px; margin: 10px 0; }
.macro-name { flex: 0 0 auto; width: 78px; color: #bdbdd0; font-size: 0.88em; }
.macro-fill-wrap { flex: 1 1 auto; height: 8px; background: #0f0f1a;
                   border-radius: 4px; overflow: hidden; min-width: 40px; }
.macro-fill { height: 100%; background: #e94560; border-radius: 4px; }
.macro-value { flex: 0 0 auto; color: #e0e0e0; font-size: 0.84em;
               font-weight: 500; white-space: nowrap; }
```

---

## 8. Quick actions — POST dispatch that re-renders the whole page

### Server

```python
def do_POST(self):
    raw = self.rfile.read(length).decode("utf-8")
    form = urllib.parse.parse_qs(raw)
    init_data = (form.get("initData") or [""])[0]
    action = (form.get("action") or [""])[0]

    user = _verify_init_data(init_data)
    if user is None:
        # token-bypass fallback so quick actions work when launched via menu button
        token = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("t", [""])[0]
        if DASHBOARD_TOKEN and token and hmac.compare_digest(token, DASHBOARD_TOKEN):
            user = {"id": next(iter(ALLOWED_USER_IDS)), "first_name": "…"}
        else:
            self._send_html(401, _unauthorized_html()); return

    if action:
        conn = get_conn()
        try: _dispatch_action(conn, user["id"], action)
        finally: conn.close()

    self._send_html(200, _render_dashboard(user))


def _dispatch_action(conn, user_id: int, action: str) -> None:
    if action == "water_add:250": add_water(conn, user_id, 250)
    elif action == "water_undo":  remove_last_water_today(conn, user_id)
```

### Client

The dashboard HTML injects the token and bot URL as JS constants, then binds button handlers:

```html
<script>
  var TG = (window.Telegram && window.Telegram.WebApp) || null;
  if (TG) { TG.ready(); TG.expand(); }
  var DASHBOARD_TOKEN = {_js_token};
  var BOT_URL = {_js_bot_url};

  function doAction(action, btn) {
    var url = '/api/dashboard' + (DASHBOARD_TOKEN ? '?t=' + encodeURIComponent(DASHBOARD_TOKEN) : '');
    var initData = (TG && TG.initData) || '';
    var body = 'action=' + encodeURIComponent(action) +
               '&initData=' + encodeURIComponent(initData);
    if (btn) { btn.disabled = true; btn.style.opacity = 0.5; }
    fetch(url, { method: 'POST',
                 headers: {'Content-Type':'application/x-www-form-urlencoded'},
                 body: body })
      .then(r => r.text())
      .then(html => { document.open(); document.write(html); document.close(); });
  }

  document.querySelectorAll('[data-action]').forEach(el =>
    el.addEventListener('click', () => doAction(el.dataset.action, el)));
</script>
```

`document.open/write/close` is the simplest possible "reload" that keeps you in the same WebView context without an actual navigation.

---

## 9. "Back to bot" button — works from any launch context

**The bug we fixed last:** `Telegram.WebApp.close()` just dismisses the mini-app overlay. If the user launched the mini-app via a direct link from the chat list, `close()` returns them to the chat list, not to the bot chat.

**Fix:** use `Telegram.WebApp.openTelegramLink('https://t.me/<bot_username>')` instead. It always lands in the bot chat, regardless of where the mini-app was launched from.

Finding the bot username without a new env var — call `getMe` once per cold start and cache in memory:

```python
_BOT_USERNAME_CACHE: str | None = None

def _get_bot_username() -> str:
    global _BOT_USERNAME_CACHE
    if _BOT_USERNAME_CACHE is not None:
        return _BOT_USERNAME_CACHE
    try:
        import httpx
        r = httpx.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe", timeout=5)
        data = r.json()
        _BOT_USERNAME_CACHE = (data.get("result") or {}).get("username", "") if data.get("ok") else ""
    except Exception:
        _BOT_USERNAME_CACHE = ""
    return _BOT_USERNAME_CACHE or ""
```

Inject alongside the token:

```python
_js_bot_url = json.dumps(f"https://t.me/{_get_bot_username()}" if _get_bot_username() else "")
```

JS with a fallback cascade:

```js
function closeApp() {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (BOT_URL && tg && typeof tg.openTelegramLink === 'function') {
    try { tg.openTelegramLink(BOT_URL); return; } catch(e) {}
  }
  if (tg && typeof tg.close === 'function') { try { tg.close(); return; } catch(e) {} }
  try { window.close(); } catch(e) {}
  try { history.back(); } catch(e) {}
}
```

---

## 10. Bootstrap page (for the inline-keyboard path)

When the inline-keyboard launch hits `/api/dashboard` as a GET (with token missing), we serve a minimal HTML page whose only job is:

1. Load the Telegram Web App SDK.
2. Read `initData` from either `window.Telegram.WebApp.initData` or the URL fragment.
3. POST it back to `/api/dashboard` and replace the page with the response (`document.open/write/close`).

This keeps the initData out of the URL bar / browser history. The bootstrap page also retries up to 20× 100ms to account for slow SDK init on older Telegram clients, and shows a diagnostic panel (`has SDK? has initData? platform? version?`) on failure.

---

## 11. End-to-end verification checklist

1. Deploy with `vercel --prod`.
2. Send `/start` to the bot → menu button URL updates to include the new SHA.
3. Tap the chat menu button (phone icon) → fresh dashboard loads (no stale HTML).
4. Tap the inline **📱 Відкрити Dashboard** button bot sent earlier → same dashboard.
5. Tap **💧 +250 мл** → water bar and hero both reflect the change; page doesn't navigate away.
6. Tap **💬 До бота** from: (a) inside the bot chat, (b) from the chat list after opening the mini-app via a direct link — both should land in the bot chat.
7. iPhone with notch — confirm the `👋 Привіт` header clears the status bar.
8. Open in desktop Telegram — works identically (safe-area vars resolve to 0).

---

## 12. Gotchas / lessons

- **Cache is a URL problem, not a header problem** on Telegram's iOS webview. Version the URL.
- **initData from the chat menu button is structurally different** from the inline-keyboard variant and can't be fully verified. Plan for a bypass if you need a menu-button UX.
- `document.write` is ugly but the simplest way to hot-swap the whole page without a full navigation. It also re-initializes the Telegram SDK cleanly each time, which matters for `close()` to keep working.
- `Telegram.WebApp.close()` and `openTelegramLink()` have different effects — know which you want.
- Keep the DB connection opened and closed within a single request. `psycopg` over Neon behaves better if each serverless invocation gets its own connection.

---

## 13. One-screen summary

| Problem | Fix |
|---|---|
| Menu-button launch 401 because initData is weird/stale | `?t=<DASHBOARD_TOKEN>` query bypass in `do_GET` |
| Menu-button launch shows stale HTML from a previous deploy | Append `?v=<VERCEL_GIT_COMMIT_SHA>` to menu-button URL + `/start` once per deploy |
| Header overlaps iPhone status bar | `viewport-fit=cover` + `max(16px, env(safe-area-inset-top) + var(--tg-content-safe-area-inset-top))` padding |
| No quick actions without leaving the mini-app | POST `?t=<token>&action=...`; re-render via `document.open/write/close` |
| "Close" returns to chat list, not bot chat | `tg.openTelegramLink('https://t.me/<botname>')`; username via cached `getMe` |
| Macro bars wrap onto two lines | Flex row: `name | fill-wrap | value`, CSS-based bar (not ASCII) |
| Dashboard is a status report, not a tool | Hero card + status chip + time-aware subtext + goal + 7-day adherence |

Ship in that order and the other bot will have the same dashboard with all the bugs already fixed.
