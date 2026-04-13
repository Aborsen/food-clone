"""Message formatting helpers for Telegram replies."""
from datetime import datetime

from lib.config import DAILY_CAL_TARGET, MACRO_GRAM_TARGETS


def _bar(used: float, target: float, width: int = 10) -> str:
    if target <= 0:
        return "─" * width
    pct = max(0.0, min(1.0, used / target))
    filled = round(pct * width)
    return "█" * filled + "░" * (width - filled)


def _pct(used: float, target: float) -> int:
    if target <= 0:
        return 0
    return round(100 * used / target)


def format_today_progress(log: dict) -> str:
    date_display = datetime.utcnow().strftime("%B %d")
    cal = log.get("calories", 0)
    p = log.get("protein", 0)
    c = log.get("carbs", 0)
    f = log.get("fat", 0)
    fib = log.get("fiber", 0)
    sug = log.get("sugar", 0)
    meals = log.get("meal_count", 0)
    remaining = max(0, DAILY_CAL_TARGET - cal)

    return (
        f"📊 <b>Today's Progress ({date_display})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 Calories: {round(cal)} / {DAILY_CAL_TARGET} ({_pct(cal, DAILY_CAL_TARGET)}%)\n"
        f"   {_bar(cal, DAILY_CAL_TARGET)}\n"
        f"🥩 Protein:  {round(p)}g / {MACRO_GRAM_TARGETS['protein']}g ({_pct(p, MACRO_GRAM_TARGETS['protein'])}%)\n"
        f"   {_bar(p, MACRO_GRAM_TARGETS['protein'])}\n"
        f"🍚 Carbs:    {round(c)}g / {MACRO_GRAM_TARGETS['carbs']}g ({_pct(c, MACRO_GRAM_TARGETS['carbs'])}%)\n"
        f"   {_bar(c, MACRO_GRAM_TARGETS['carbs'])}\n"
        f"🧈 Fat:      {round(f)}g / {MACRO_GRAM_TARGETS['fat']}g ({_pct(f, MACRO_GRAM_TARGETS['fat'])}%)\n"
        f"   {_bar(f, MACRO_GRAM_TARGETS['fat'])}\n"
        f"📈 Fiber:    {round(fib)}g\n"
        f"🍬 Sugar:    {round(sug)}g\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Meals logged: {meals}\n"
        f"Remaining: ~{round(remaining)} calories"
    )


_CONFIDENCE_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}
_SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def format_meal_logged(meal_type: str, analysis: dict, today_log: dict) -> str:
    nutrition = analysis.get("nutrition", {}) or {}
    dish = analysis.get("dish_name") or "Meal"
    date_display = datetime.utcnow().strftime("%B %d")

    allergen_flags = analysis.get("allergen_flags") or []
    crohn_flags = analysis.get("crohn_flags") or []

    lines = [
        f"✅ <b>Logged: {dish}</b>",
        f"🕐 {meal_type.capitalize()} — {date_display}",
        "",
        (
            f"🔥 {round(nutrition.get('calories', 0))} cal | "
            f"🥩 {round(nutrition.get('protein_g', 0))}g P | "
            f"🍚 {round(nutrition.get('carbs_g', 0))}g C | "
            f"🧈 {round(nutrition.get('fat_g', 0))}g F"
        ),
    ]

    if allergen_flags:
        lines.append("")
        lines.append("⚠️ <b>ALLERGEN WARNING:</b>")
        for a in allergen_flags:
            icon = _CONFIDENCE_ICON.get((a.get("confidence") or "").lower(), "⚠️")
            lines.append(
                f"  {icon} {a.get('allergen', '?').capitalize()} detected "
                f"({a.get('confidence', '?')} confidence) — in {a.get('ingredient', 'this dish')}"
            )

    if crohn_flags:
        lines.append("")
        lines.append("⚠️ <b>CROHN'S NOTE:</b>")
        for c in crohn_flags:
            icon = _SEVERITY_ICON.get((c.get("severity") or "").lower(), "🟡")
            lines.append(
                f"  {icon} {c.get('concern', 'concern')} "
                f"({c.get('ingredient', '?')})"
            )

    assessment = analysis.get("overall_assessment")
    if assessment:
        lines.append("")
        lines.append(f"💬 {assessment}")

    lines.append("")
    lines.append(
        f"📊 Daily total so far: {round(today_log.get('calories', 0))} / {DAILY_CAL_TARGET} cal"
    )

    return "\n".join(lines)


def format_history(rows: list[dict]) -> str:
    if not rows:
        return "📅 No history yet. Log your first meal by sending a photo!"

    lines = ["📅 <b>Your Last 7 Days</b>"]
    for r in rows:
        cal = r.get("calories", 0)
        p = r.get("protein", 0)
        c = r.get("carbs", 0)
        f = r.get("fat", 0)
        total_macro_cal = p * 4 + c * 4 + f * 9
        if total_macro_cal > 0:
            p_pct = round(100 * p * 4 / total_macro_cal)
            c_pct = round(100 * c * 4 / total_macro_cal)
            f_pct = round(100 * f * 9 / total_macro_cal)
        else:
            p_pct = c_pct = f_pct = 0

        if cal == 0:
            marker = ""
        elif cal > DAILY_CAL_TARGET * 1.05:
            marker = "⚠️ over"
        elif cal < DAILY_CAL_TARGET * 0.80:
            marker = "⚠️ low"
        else:
            marker = "✅"

        # Reformat date to short display (e.g. "Apr 12")
        try:
            date_short = datetime.strptime(r["date"], "%Y-%m-%d").strftime("%b %d")
        except Exception:
            date_short = r.get("date", "")

        lines.append(
            f"{date_short}: {round(cal)} cal — P:{p_pct}% C:{c_pct}% F:{f_pct}% {marker}"
        )
    return "\n".join(lines)


def format_day_detail(date: str, meals: list[dict]) -> str:
    if not meals:
        return f"📅 No meals logged on {date}."

    lines = [f"📅 <b>Meals on {date}</b>", ""]
    total_cal = 0
    for m in meals:
        total_cal += m.get("calories", 0)
        lines.append(
            f"🕐 <b>{m.get('meal_type', '').capitalize()}</b> — {m.get('description', '')}"
        )
        lines.append(
            f"   🔥 {round(m.get('calories', 0))} cal | "
            f"🥩 {round(m.get('protein_g', 0))}g P | "
            f"🍚 {round(m.get('carbs_g', 0))}g C | "
            f"🧈 {round(m.get('fat_g', 0))}g F"
        )
        if m.get("allergen_warnings"):
            names = ", ".join(a.get("allergen", "?") for a in m["allergen_warnings"])
            lines.append(f"   ⚠️ Allergens: {names}")
        lines.append("")

    lines.append(f"<b>Total: {round(total_cal)} cal</b>")
    return "\n".join(lines)


WELCOME_MESSAGE = (
    "Hi! I'm your Crohn's-friendly food tracker 🥗.\n\n"
    "Send me a photo of your meal and I'll analyze it — tracking calories, macros, "
    "and flagging anything that might not agree with your Crohn's or allergies. "
    "I'll also send you a daily summary each night!\n\n"
    "Commands:\n"
    "/today — today's progress\n"
    "/history — last 7 days\n"
    "/history_detail YYYY-MM-DD — meals on a day\n"
    "/suggest_meal — AI recipe suggestion for your remaining macros\n"
    "/help — show this list"
)

HELP_MESSAGE = (
    "🤖 <b>Commands</b>\n"
    "/start — welcome & setup\n"
    "/today — today's calorie & macro progress\n"
    "/history — last 7 days summary\n"
    "/history_detail YYYY-MM-DD — meals on a specific day\n"
    "/suggest_meal — AI recipe suggestion that fills today's gap\n"
    "/help — show this list\n\n"
    "📸 Send a photo anytime to log a meal — I'll ask which meal type and then analyze it."
)
