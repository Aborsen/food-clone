"""Turso (libSQL) database layer: connection, schema migration, and CRUD helpers."""
import json
from datetime import datetime, timezone
from typing import Any, Optional

import libsql_experimental as libsql

from lib.config import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN


def get_conn():
    """Return a fresh libsql connection. Call per invocation (serverless)."""
    return libsql.connect(
        database=TURSO_DATABASE_URL,
        auth_token=TURSO_AUTH_TOKEN,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def init_db(conn=None) -> None:
    """Create tables if they don't exist. Idempotent — safe to call every request."""
    close_after = False
    if conn is None:
        conn = get_conn()
        close_after = True

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            created_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            total_calories REAL DEFAULT 0,
            total_protein_g REAL DEFAULT 0,
            total_carbs_g REAL DEFAULT 0,
            total_fat_g REAL DEFAULT 0,
            total_fiber_g REAL DEFAULT 0,
            total_sugar_g REAL DEFAULT 0,
            summary_sent INTEGER DEFAULT 0,
            created_at TEXT,
            UNIQUE(user_id, date)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            meal_type TEXT,
            description TEXT,
            ingredients TEXT,
            allergen_warnings TEXT,
            crohn_warnings TEXT,
            calories REAL,
            protein_g REAL,
            carbs_g REAL,
            fat_g REAL,
            fiber_g REAL,
            sugar_g REAL,
            photo_file_id TEXT,
            ai_raw_response TEXT,
            created_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            recommendation TEXT,
            created_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            photo_file_id TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    if close_after:
        try:
            conn.close()
        except Exception:
            pass


# ---------- Users ----------

def upsert_user(conn, user_id: int, username: Optional[str]) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, created_at) VALUES (?, ?, ?)",
        (user_id, username or "", _now_iso()),
    )
    conn.commit()


# ---------- Pending photos ----------

def save_pending_photo(conn, user_id: int, photo_file_id: str) -> None:
    # Clear any previous pending for this user, then insert fresh
    conn.execute("DELETE FROM pending_photos WHERE user_id = ?", (user_id,))
    conn.execute(
        "INSERT INTO pending_photos (user_id, photo_file_id, created_at) VALUES (?, ?, ?)",
        (user_id, photo_file_id, _now_iso()),
    )
    conn.commit()


def pop_pending_photo(conn, user_id: int) -> Optional[str]:
    """Return the most recent pending photo_file_id and delete all pending for user."""
    row = conn.execute(
        "SELECT photo_file_id FROM pending_photos WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    file_id = row[0]
    conn.execute("DELETE FROM pending_photos WHERE user_id = ?", (user_id,))
    conn.commit()
    return file_id


def cleanup_stale_pending(conn, minutes: int = 10) -> None:
    """Delete pending_photos older than N minutes."""
    cutoff_iso = datetime.now(timezone.utc).isoformat()
    # Compare as ISO strings — sort lexicographically for UTC ISO timestamps
    # Compute cutoff manually
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    conn.execute("DELETE FROM pending_photos WHERE created_at < ?", (cutoff,))
    conn.commit()


# ---------- Meals ----------

def save_meal(
    conn,
    user_id: int,
    meal_type: str,
    analysis: dict,
    photo_file_id: str,
    raw_response: str,
) -> None:
    nutrition = analysis.get("nutrition", {}) or {}
    conn.execute(
        """INSERT INTO meals (
            user_id, date, meal_type, description, ingredients,
            allergen_warnings, crohn_warnings,
            calories, protein_g, carbs_g, fat_g, fiber_g, sugar_g,
            photo_file_id, ai_raw_response, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            _today_str(),
            meal_type,
            analysis.get("description") or analysis.get("dish_name", ""),
            json.dumps(analysis.get("ingredients", [])),
            json.dumps(analysis.get("allergen_flags", [])),
            json.dumps(analysis.get("crohn_flags", [])),
            float(nutrition.get("calories", 0) or 0),
            float(nutrition.get("protein_g", 0) or 0),
            float(nutrition.get("carbs_g", 0) or 0),
            float(nutrition.get("fat_g", 0) or 0),
            float(nutrition.get("fiber_g", 0) or 0),
            float(nutrition.get("sugar_g", 0) or 0),
            photo_file_id,
            raw_response,
            _now_iso(),
        ),
    )
    conn.commit()


def get_meals_for_day(conn, user_id: int, date: str) -> list[dict]:
    rows = conn.execute(
        """SELECT meal_type, description, ingredients, allergen_warnings, crohn_warnings,
                  calories, protein_g, carbs_g, fat_g, fiber_g, sugar_g, created_at
           FROM meals WHERE user_id = ? AND date = ? ORDER BY id ASC""",
        (user_id, date),
    ).fetchall()
    return [
        {
            "meal_type": r[0],
            "description": r[1],
            "ingredients": json.loads(r[2] or "[]"),
            "allergen_warnings": json.loads(r[3] or "[]"),
            "crohn_warnings": json.loads(r[4] or "[]"),
            "calories": r[5] or 0,
            "protein_g": r[6] or 0,
            "carbs_g": r[7] or 0,
            "fat_g": r[8] or 0,
            "fiber_g": r[9] or 0,
            "sugar_g": r[10] or 0,
            "created_at": r[11],
        }
        for r in rows
    ]


# ---------- Daily logs ----------

def upsert_daily_log_from_meal(conn, user_id: int, analysis: dict) -> None:
    """Insert today's row if needed, then increment totals from this meal."""
    today = _today_str()
    nutrition = analysis.get("nutrition", {}) or {}
    cal = float(nutrition.get("calories", 0) or 0)
    p = float(nutrition.get("protein_g", 0) or 0)
    c = float(nutrition.get("carbs_g", 0) or 0)
    f = float(nutrition.get("fat_g", 0) or 0)
    fib = float(nutrition.get("fiber_g", 0) or 0)
    sug = float(nutrition.get("sugar_g", 0) or 0)

    conn.execute(
        """INSERT INTO daily_logs (user_id, date, total_calories, total_protein_g,
                                   total_carbs_g, total_fat_g, total_fiber_g, total_sugar_g,
                                   summary_sent, created_at)
           VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0, ?)
           ON CONFLICT(user_id, date) DO NOTHING""",
        (user_id, today, _now_iso()),
    )
    conn.execute(
        """UPDATE daily_logs
           SET total_calories = total_calories + ?,
               total_protein_g = total_protein_g + ?,
               total_carbs_g = total_carbs_g + ?,
               total_fat_g = total_fat_g + ?,
               total_fiber_g = total_fiber_g + ?,
               total_sugar_g = total_sugar_g + ?
           WHERE user_id = ? AND date = ?""",
        (cal, p, c, f, fib, sug, user_id, today),
    )
    conn.commit()


def get_today_log(conn, user_id: int) -> dict:
    today = _today_str()
    row = conn.execute(
        """SELECT total_calories, total_protein_g, total_carbs_g, total_fat_g,
                  total_fiber_g, total_sugar_g
           FROM daily_logs WHERE user_id = ? AND date = ?""",
        (user_id, today),
    ).fetchone()
    meal_count_row = conn.execute(
        "SELECT COUNT(*) FROM meals WHERE user_id = ? AND date = ?",
        (user_id, today),
    ).fetchone()
    meal_count = meal_count_row[0] if meal_count_row else 0
    if not row:
        return {
            "date": today, "calories": 0, "protein": 0, "carbs": 0,
            "fat": 0, "fiber": 0, "sugar": 0, "meal_count": meal_count,
        }
    return {
        "date": today,
        "calories": row[0] or 0,
        "protein": row[1] or 0,
        "carbs": row[2] or 0,
        "fat": row[3] or 0,
        "fiber": row[4] or 0,
        "sugar": row[5] or 0,
        "meal_count": meal_count,
    }


def get_history(conn, user_id: int, days: int = 7) -> list[dict]:
    rows = conn.execute(
        """SELECT date, total_calories, total_protein_g, total_carbs_g, total_fat_g
           FROM daily_logs WHERE user_id = ?
           ORDER BY date DESC LIMIT ?""",
        (user_id, days),
    ).fetchall()
    return [
        {
            "date": r[0],
            "calories": r[1] or 0,
            "protein": r[2] or 0,
            "carbs": r[3] or 0,
            "fat": r[4] or 0,
        }
        for r in rows
    ]


# ---------- Summaries / recommendations ----------

def get_users_needing_summary(conn) -> list[tuple[int, str]]:
    """Users with meals today and no summary yet. Returns [(user_id, date)]."""
    today = _today_str()
    rows = conn.execute(
        """SELECT DISTINCT dl.user_id, dl.date
           FROM daily_logs dl
           WHERE dl.date = ? AND dl.summary_sent = 0
             AND EXISTS (SELECT 1 FROM meals m WHERE m.user_id = dl.user_id AND m.date = dl.date)""",
        (today,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def save_recommendation(conn, user_id: int, date: str, text: str) -> None:
    conn.execute(
        "INSERT INTO daily_recommendations (user_id, date, recommendation, created_at) VALUES (?, ?, ?, ?)",
        (user_id, date, text, _now_iso()),
    )
    conn.commit()


def mark_summary_sent(conn, user_id: int, date: str) -> None:
    conn.execute(
        "UPDATE daily_logs SET summary_sent = 1 WHERE user_id = ? AND date = ?",
        (user_id, date),
    )
    conn.commit()


def mark_all_previous_summaries_sent(conn) -> None:
    """Failsafe midnight call: mark any unsent prior-day summaries as sent."""
    today = _today_str()
    conn.execute(
        "UPDATE daily_logs SET summary_sent = 1 WHERE date < ? AND summary_sent = 0",
        (today,),
    )
    conn.commit()
