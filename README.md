# Raudar Food — Personal Calorie & Nutrition Bot

A single-user Telegram bot + Mini App deployed on **Vercel** (serverless). Logs meals from photos, text, or voice; tracks water intake; shows a rich dashboard Mini App; sends a nightly AI summary. Built for one lifter with Crohn's-friendly preferences — profile is hardcoded in `lib/config.py`.

## What it does

**Meal logging — three input modes, same downstream flow**
- 📸 Photo → GPT-4o Vision extracts dish, ingredients, macros, allergen & Crohn's flags
- 📝 Text ("курка 200г, рис 150г, броколі 100г") → GPT-4o text analysis
- 🎙 Voice message → Whisper (UA-biased) transcribes → fed into the text flow

All three paths converge on a moderation screen (✅ Accept / 🔄 Recalc / ✏️ Manual) and then a saved meal with an inline action row: **⭐ Favorite · ✏️ Edit · 🗑 Delete**.

**Favorites & quick re-log**
- ⭐ Star any meal → appears in `/fav`
- `/recent` lists the last 10 unique meals
- 🔁 Tap to clone into today (meal type auto-picked by Kyiv local hour)
- ↩️ Undo the clone for as long as the meal exists

**Water tracking**
- `💧 +250мл` reply-keyboard button for instant quick-add
- `/water` opens the full card: +200 / +250 / +300 / +500 / +750 inline buttons, ↩️ undo last, 🎯 goal picker (1.5 / 2.0 / 2.5 / 3.0 L)
- Default target 2500 ml; stored per-user in `water_prefs`, overridable from the UI
- Rendered as a progress bar on the Mini App dashboard (День + Вчора tabs)

**Dashboard Mini App (`/api/dashboard`)**
- Tabs: День · Вчора · 7 днів · 30 днів
- Cards: macro bars · 💧 Вода · 💡 Підсумок дня (rule-based headline + per-macro advice) · 🍽️ Страви (searchable list with meal-type and Crohn's filter chips)
- iOS safe-area aware (`env(safe-area-inset-top)` + Telegram `--tg-content-safe-area-inset-top`)
- Two auth paths:
  - **Inline keyboard web_app button** → signed `initData` HMAC verification
  - **Chat menu button (phone icon)** → falls back to a `?t=<DASHBOARD_TOKEN>` query-string bypass, because Telegram's menu-button launch reuses cached/stale `initData` that can fail verification
- `Cache-Control: no-store` on every response — Telegram webview caches mini-apps aggressively otherwise

**AI daily summary (nightly cron)**
- 22:00 UTC — GPT-4o reviews the day and writes a ≤150-word Ukrainian review (✅ good / ⚠️ improve / 💡 tomorrow / 🍽️ meal idea)
- Saved in `daily_recommendations` + delivered as a Telegram message

**AI chat (`/ask`)** — multi-turn nutrition Q&A with 1-hour memory, fed today's intake as context.

**Meal suggestions (`/suggest_meal`)** — GPT-4o picks a dish that fits the remaining macros.

---

## Reply keyboard

```
[💬 Запитати AI]   [⭐ Улюблені]
[💧 +250мл]        [📊 Сьогодні]
[🍽️ Ідея страви]   [⚙️ Профіль]
```

## Slash commands

`/start` · `/help` · `/today` · `/yesterday` · `/meals` · `/history` · `/history_detail YYYY-MM-DD` · `/fav` · `/recent` · `/water` · `/suggest_meal` · `/ask` · `/profile`

---

## Prerequisites

1. **Telegram bot** from [@BotFather](https://t.me/BotFather).
2. **OpenAI API key** — GPT-4o (vision + text) + Whisper access. Single key covers all three.
3. **Vercel account** — free tier is enough. Neon Postgres is installed from the Marketplace inside Vercel; no separate signup.
4. **GitHub** — source + auto-deploy.
5. **Python 3.11+** locally (for `scripts/set_webhook.py`).

## Setup

### 1. Clone & install
```bash
git clone <your-fork-url> Hulk_eats
cd Hulk_eats
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Deploy + provision DB
- Push to GitHub, import into Vercel (framework preset: **Other**).
- After the first deploy, go to **Storage → Create Database → Neon** inside the Vercel project. `DATABASE_URL` auto-injects into all environments.

### 3. Set environment variables (Vercel → Settings → Environment Variables)

| Var | Where from |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather |
| `OPENAI_API_KEY` | platform.openai.com |
| `WEBHOOK_SECRET` | `python -c 'import secrets; print(secrets.token_urlsafe(32))'` |
| `CRON_SECRET` | same generator |
| `DASHBOARD_TOKEN` | `openssl rand -hex 24` — used for menu-button auth bypass |
| `VERCEL_URL` | the deployed domain (no `https://`), e.g. `food-clone-xi.vercel.app` |
| `DATABASE_URL` | auto-injected by Neon Marketplace — don't set manually |

Redeploy after adding vars.

Copy the same values into your local `.env` (for running `set_webhook.py`).

### 4. Lock the bot down to your Telegram user
Edit `lib/config.py`:
```python
ALLOWED_USER_IDS: set[int] = {169742339}   # ← your Telegram ID
```
All other IDs get a polite rejection.

### 5. Customize the profile
`lib/config.py` has `USER_PROFILE` — weight, goal, allergens, macro split, daily calorie target. Edit to match yourself.

### 6. Register the webhook, menus, and chat menu button
```bash
python scripts/set_webhook.py
```
This call:
- Sets the webhook URL + secret token
- Registers the `/` slash-command menu in both UA and EN
- Installs the `📱 Dashboard` chat menu button (phone icon) pointing at `/api/dashboard?t=<DASHBOARD_TOKEN>`

Re-run it any time you rename commands or rotate `DASHBOARD_TOKEN`.

### 7. Try it
- `/start` in Telegram → welcome + reply keyboard
- Send a meal photo, text, or voice message
- Tap **📱 Dashboard** (phone icon next to the input) → Mini App opens
- `💧 +250мл` → log water
- `/fav`, `/recent` → quick re-log

Nightly summary fires automatically at **22:00 UTC** via Vercel Cron.

---

## Architecture

```
Telegram ─► POST /api/webhook ─┬─► lib/database.py    ── psycopg ──► Neon Postgres
                               ├─► lib/openai_vision.py  (GPT-4o Vision / text)
                               ├─► lib/openai_voice.py   (Whisper-1)
                               ├─► lib/openai_nutrition.py (summaries + recipes)
                               └─► lib/openai_chat.py   (/ask multi-turn)

Mini App ─► GET/POST /api/dashboard ─► lib/database.py  (HTML response)

Vercel Cron → GET /api/cron_daily_summary   (22:00 UTC)
Vercel Cron → GET /api/cron_midnight_reset  (00:00 UTC)
```

- **Stateless** — Vercel functions don't persist between invocations. Pending meals between "send photo" and "tap meal type" live in `pending_analyses` (10-min expiry, cleaned on every request).
- **Webhook auth** — `X-Telegram-Bot-Api-Secret-Token` header must match `WEBHOOK_SECRET`; otherwise 403.
- **Cron auth** — `Authorization: Bearer $CRON_SECRET` required.
- **Mini-app auth** — signed `initData` HMAC (inline-keyboard launch) OR `?t=<DASHBOARD_TOKEN>` query bypass (chat-menu-button launch).
- **Kyiv local time** — calendar day (`meals.date`, water-day aggregation) is computed in `Europe/Kyiv`. Timestamps in UTC. This prevents meals logged between midnight Kyiv and midnight UTC falling on the wrong day.
- **Always returns HTTP 200** to Telegram even on errors, so a buggy code path doesn't cause Telegram to retry forever. Errors surface in Vercel logs.

---

## Database

Auto-migrated on every request via `CREATE TABLE IF NOT EXISTS`. No manual migrations.

| Table | Purpose |
|---|---|
| `users` | Telegram user ↔ username mapping |
| `meals` | Every logged meal (description, ingredients, macros, allergen/Crohn's flags, `is_favorite`) |
| `daily_logs` | Per-day totals (denormalized for quick dashboard render) |
| `daily_recommendations` | Nightly AI summary text |
| `pending_analyses` | In-flight meal analyses between photo/text/voice and user confirmation |
| `pending_photos` | Raw pending file_ids before meal-type pick |
| `chat_sessions` | 1-hour rolling `/ask` conversation memory |
| `water_logs` | Every water sip (`amount_ml` + timestamp) |
| `water_prefs` | Per-user water target (default 2500 ml) |

---

## Files

```
Hulk_eats/
├── vercel.json
├── requirements.txt
├── api/
│   ├── webhook.py                # POST — Telegram updates (photo / text / voice / callbacks)
│   ├── dashboard.py              # GET/POST — Mini App HTML (initData HMAC + token bypass)
│   ├── cron_daily_summary.py     # 22:00 UTC — AI summary → Telegram + DB
│   └── cron_midnight_reset.py    # 00:00 UTC — cleanup stale pending rows
├── lib/
│   ├── config.py                 # USER_PROFILE, ALLOWED_USER_IDS, env, prompts
│   ├── database.py               # Schema + all CRUD (meals, water, favorites, chat, pending)
│   ├── telegram_helpers.py       # sendMessage, editMessage*, sendChatAction, keyboards
│   ├── openai_vision.py          # GPT-4o photo + text analysis
│   ├── openai_voice.py           # Whisper-1 transcription (UA-biased)
│   ├── openai_nutrition.py       # Nightly summary + /suggest_meal
│   ├── openai_chat.py            # /ask multi-turn
│   └── formatters.py             # Ukrainian HTML copy, progress bars, BTN_* labels
└── scripts/
    └── set_webhook.py            # Webhook + setMyCommands + chat menu button
```

---

## Local development

Pure serverless — no local runtime, no FSM. Options:

```bash
vercel dev --listen 3000            # emulates the serverless runtime
ngrok http 3000                      # expose via HTTPS
# Point VERCEL_URL at the ngrok domain and re-run set_webhook.py temporarily.
```

For most tweaks, pushing to a preview branch and testing against the Vercel preview URL is simpler. The Mini App supports `cmd+R` reload inside Telegram's `⋯` menu.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Webhook registered, no replies | Check `VERCEL_URL` has no `https://`, redeploy, re-run `set_webhook.py`. Check Vercel → Logs. |
| `403` from webhook | `WEBHOOK_SECRET` in Vercel doesn't match the one `set_webhook.py` used. |
| `psycopg` errors / DB connection | Ensure the Neon integration is installed and `DATABASE_URL` is present in Vercel env. |
| Photo/voice analysis times out | Hobby plan is 60s. Whisper + GPT-4o usually finishes in 10–25s; very long voice messages are capped to 2 MB (≈60–90s). |
| Cron didn't fire | Crons require a Production deployment. Promote your deploy, or GET the cron URL manually with `Authorization: Bearer $CRON_SECRET`. |
| Dashboard opens from menu button with no data | Confirm `DASHBOARD_TOKEN` env is set and `set_webhook.py` has been re-run after adding it — the menu button URL must include `?t=…`. |
| Dashboard still shows old content | Telegram caches mini-app HTML. Tap `⋯` top-right inside the mini-app → **Reload page**, or close and reopen. |
| Header overlaps phone status bar in mini-app | Already handled via `viewport-fit=cover` + `env(safe-area-inset-top)`. If you fork and break it, check `api/dashboard.py` `_BOOTSTRAP_HTML` + main dashboard `<style>`. |
| `/fav`, `/recent`, `/water` missing from `/` autocomplete | Re-run `python scripts/set_webhook.py` with real env vars (Vercel masks secrets on `env pull`). |

---

## Deployment checklist

- [ ] GitHub repo pushed
- [ ] Vercel project imported + first deploy succeeded
- [ ] Neon database provisioned (auto-injects `DATABASE_URL`)
- [ ] Env vars set: `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `WEBHOOK_SECRET`, `CRON_SECRET`, `DASHBOARD_TOKEN`, `VERCEL_URL`
- [ ] `ALLOWED_USER_IDS` edited to your Telegram user ID
- [ ] `USER_PROFILE` edited to match you
- [ ] Deployment promoted to production (crons need Production)
- [ ] `python scripts/set_webhook.py` succeeded
- [ ] `/start` replies with welcome + new 2×3 reply keyboard
- [ ] Photo / text / voice meal → moderation → saved
- [ ] `/water` → tap `+500` → bar updates
- [ ] `/fav` empty; star a meal; `/fav` now lists it; tap 🔁 clones to today; ↩️ undo works
- [ ] Tap **📱 Dashboard** phone icon → Mini App opens with 💧 Вода + 💡 Підсумок дня cards
- [ ] (Optional) Manually GET `/api/cron_daily_summary` with the bearer header to verify the summary flow

---

## Scope & non-goals

This is a **personal single-user bot**. It intentionally does NOT:

- Manage multiple users or profiles (one hardcoded `USER_PROFILE` in `lib/config.py`; one ID in `ALLOWED_USER_IDS`)
- Accept payments or handle subscriptions
- Persist photos (only Telegram `file_id` is kept)
- Support timezone selection (everything is UTC except calendar-day calculations which use `Europe/Kyiv`)
- Offer a multi-step onboarding — edit `USER_PROFILE` directly in code and redeploy
- Provide reminders / push notifications (out of scope for V1)
