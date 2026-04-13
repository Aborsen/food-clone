"""Vercel serverless handler for Telegram webhook updates."""
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler

# Ensure project root is on sys.path so `lib.*` imports resolve on Vercel
_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.config import WEBHOOK_SECRET
from lib.database import (
    get_conn,
    init_db,
    upsert_user,
    save_pending_photo,
    pop_pending_photo,
    cleanup_stale_pending,
    save_meal,
    upsert_daily_log_from_meal,
    get_today_log,
    get_history,
    get_meals_for_day,
)
from lib.telegram_helpers import (
    send_message,
    answer_callback_query,
    get_file_bytes,
    meal_type_keyboard,
)
from lib.openai_vision import analyze_photo
from lib.openai_nutrition import suggest_meal
from lib.formatters import (
    WELCOME_MESSAGE,
    HELP_MESSAGE,
    format_today_progress,
    format_history,
    format_day_detail,
    format_meal_logged,
)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Verify webhook secret
        secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
            self.send_response(403)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            update = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._respond_ok()
            return

        try:
            process_update(update)
        except Exception:
            # Log but always return 200 so Telegram doesn't retry-loop us
            print("webhook error:", traceback.format_exc(), flush=True)

        self._respond_ok()

    def do_GET(self):
        # Health check
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "service": "webhook"}).encode())

    def _respond_ok(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())


def process_update(update: dict) -> None:
    conn = get_conn()
    try:
        init_db(conn)
        cleanup_stale_pending(conn, minutes=10)

        if "callback_query" in update:
            handle_callback(conn, update["callback_query"])
            return

        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        user = message.get("from", {})
        user_id = user.get("id")
        username = user.get("username") or user.get("first_name")
        if user_id:
            upsert_user(conn, user_id, username)

        if message.get("photo"):
            handle_photo(conn, message)
            return

        text = (message.get("text") or "").strip()
        if text.startswith("/"):
            handle_command(conn, message, text)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------- Handlers ----------

def handle_photo(conn, message: dict) -> None:
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    photos = message["photo"]
    # Telegram sends multiple sizes; pick the largest (last)
    file_id = photos[-1]["file_id"]
    save_pending_photo(conn, user_id, file_id)
    send_message(
        chat_id,
        "📸 Got it! What meal is this?",
        reply_markup=meal_type_keyboard(),
    )


def handle_callback(conn, cb: dict) -> None:
    cb_id = cb["id"]
    data = cb.get("data", "")
    user_id = cb["from"]["id"]
    message = cb.get("message", {})
    chat_id = message.get("chat", {}).get("id", user_id)

    if not data.startswith("meal_type:"):
        answer_callback_query(cb_id, "Unknown action")
        return

    meal_type = data.split(":", 1)[1]
    answer_callback_query(cb_id, f"Analyzing your {meal_type}…")

    file_id = pop_pending_photo(conn, user_id)
    if not file_id:
        send_message(
            chat_id,
            "⏰ I don't have a pending photo for you anymore (expired after 10 min). "
            "Please send a fresh photo.",
        )
        return

    send_message(chat_id, "🔍 Analyzing your meal, one moment…")

    try:
        image_bytes = get_file_bytes(file_id)
    except Exception as e:
        print("getFile error:", e, flush=True)
        send_message(chat_id, "Sorry, I couldn't download the photo. Please try again.")
        return

    try:
        analysis, raw = analyze_photo(image_bytes)
    except Exception as e:
        print("vision error:", e, flush=True)
        send_message(
            chat_id,
            "Sorry, I couldn't analyze this photo. Please try again with a clearer image.",
        )
        return

    # Persist
    save_meal(conn, user_id, meal_type, analysis, file_id, raw)
    upsert_daily_log_from_meal(conn, user_id, analysis)
    today_log = get_today_log(conn, user_id)

    send_message(chat_id, format_meal_logged(meal_type, analysis, today_log))


def handle_command(conn, message: dict, text: str) -> None:
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]

    # Split "/cmd@botname arg1 arg2" → cmd + args
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]

    if cmd == "/start":
        send_message(chat_id, WELCOME_MESSAGE)
        return

    if cmd == "/help":
        send_message(chat_id, HELP_MESSAGE)
        return

    if cmd == "/today":
        log = get_today_log(conn, user_id)
        send_message(chat_id, format_today_progress(log))
        return

    if cmd == "/history":
        rows = get_history(conn, user_id, days=7)
        send_message(chat_id, format_history(rows))
        return

    if cmd == "/history_detail":
        if not args:
            send_message(chat_id, "Usage: /history_detail YYYY-MM-DD")
            return
        date = args[0]
        meals = get_meals_for_day(conn, user_id, date)
        send_message(chat_id, format_day_detail(date, meals))
        return

    if cmd == "/suggest_meal":
        log = get_today_log(conn, user_id)
        meals = get_meals_for_day(conn, user_id, log["date"])
        send_message(chat_id, "🧠 Thinking of a meal that fits your day…")
        try:
            recipe = suggest_meal(log, meals)
        except Exception as e:
            print("suggest error:", e, flush=True)
            send_message(chat_id, "Sorry, I couldn't generate a suggestion right now. Try again shortly.")
            return
        send_message(chat_id, recipe)
        return

    send_message(chat_id, "Unknown command. Try /help.")
