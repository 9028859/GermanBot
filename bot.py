import os
import json
from datetime import datetime, date
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
TOKEN         = os.getenv("BOT_TOKEN")
ADMIN_ID      = os.getenv("ADMIN_ID")
ADMIN_PASS    = os.getenv("ADMIN_PASSWORD", "anand2024")

# Files
DB_FILE        = "database.json"
STUDENTS_FILE  = "students.json"
EXERCISES_FILE = "exercises.json"
SETTINGS_FILE  = "settings.json"

# ─────────────────────────────────────────────
# FILE HELPERS
# ─────────────────────────────────────────────
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def load_students():    return load_json(STUDENTS_FILE, {})
def save_students(d):   save_json(STUDENTS_FILE, d)
def load_database():    return load_json(DB_FILE, {})
def load_exercises():   return load_json(EXERCISES_FILE, [])
def save_exercises(d):  save_json(EXERCISES_FILE, d)
def load_settings():    return load_json(SETTINGS_FILE, {
    "admin_password": ADMIN_PASS,
    "daily_exercise_time": "09:00",
    "reminders_enabled": True
})
def save_settings(d):   save_json(SETTINGS_FILE, d)

# ─────────────────────────────────────────────
# ADMIN SESSION STORE
# ─────────────────────────────────────────────
admin_sessions = {}

def is_admin_logged_in(user_id: int) -> bool:
    return admin_sessions.get(user_id, {}).get("state") == "logged_in"

def admin_state(user_id: int) -> str:
    return admin_sessions.get(user_id, {}).get("state", "")

def set_admin_state(user_id: int, state: str, data: dict = None):
    if user_id not in admin_sessions:
        admin_sessions[user_id] = {}
    admin_sessions[user_id]["state"] = state
    admin_sessions[user_id]["data"] = data or {}

def clear_admin(user_id: int):
    admin_sessions.pop(user_id, None)

# ─────────────────────────────────────────────
# STUDENT HELPERS
# ─────────────────────────────────────────────
def touch_student(user_id: str):
    students = load_students()
    if user_id not in students:
        return
    s = students[user_id]
    today_str = date.today().isoformat()
    last = s.get("last_active_date", "")
    if last != today_str:
        if last == (date.today().replace(day=date.today().day - 1)).isoformat():
            s["streak"] = s.get("streak", 0) + 1
        else:
            s["streak"] = 1
        s["last_active_date"] = today_str
    s["last_active"] = datetime.now().strftime("%d %b %Y %H:%M")
    students[user_id] = s
    save_students(students)

def add_points(user_id: str, pts: int):
    students = load_students()
    if user_id in students:
        students[user_id]["points"] = students[user_id].get("points", 0) + pts
        save_students(students)

# ─────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────
def level_keyboard():
    return ReplyKeyboardMarkup([["A1", "A2"], ["B1", "B2"]], resize_keyboard=True)

def admin_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Students",   callback_data="adm_students")],
        [InlineKeyboardButton("📊 Statistics", callback_data="adm_stats")],
        [InlineKeyboardButton("📤 Broadcast",  callback_data="adm_broadcast")],
        [InlineKeyboardButton("⚙️ Settings",   callback_data="adm_settings")],
        [InlineKeyboardButton("🚪 Logout",     callback_data="adm_logout")],
    ])

def settings_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Change Password",      callback_data="set_password")],
        [InlineKeyboardButton("🕐 Daily Exercise Time",  callback_data="set_time")],
        [InlineKeyboardButton("🔔 Toggle Reminders",     callback_data="set_reminders")],
        [InlineKeyboardButton("➕ Add Vocabulary",       callback_data="set_addvocab")],
        [InlineKeyboardButton("📝 Add Exercise",         callback_data="set_addexercise")],
        [InlineKeyboardButton("🔙 Back",                 callback_data="adm_back")],
    ])

def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="adm_back")]])

# ─────────────────────────────────────────────
# /administrator COMMAND
# ─────────────────────────────────────────────
async def cmd_administrator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if str(user_id) != str(ADMIN_ID):
        await update.message.reply_text("⛔ You are not authorised.")
        return
    set_admin_state(user_id, "waiting_password")
    await update.message.reply_text(
        "🔐 *Admin Panel*\n\nPlease enter the admin password:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )

# ─────────────────────────────────────────────
# SEND ADMIN MENU
# ─────────────────────────────────────────────
async def send_admin_menu(update_or_query, context):
    text = "✅ *Login successful.*\n\nChoose an option:"
    kb   = admin_menu_keyboard()
    if hasattr(update_or_query, "message") and update_or_query.message:
        await update_or_query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update_or_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

# ─────────────────────────────────────────────
# CALLBACK QUERY HANDLER
# ─────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    data    = query.data
    await query.answer()

    if not is_admin_logged_in(user_id):
        await query.edit_message_text("⛔ Session expired. Use /administrator to login again.")
        return

    if data == "adm_back":
        set_admin_state(user_id, "logged_in")
        await query.edit_message_text(
            "✅ *Admin Panel*\n\nChoose an option:",
            parse_mode="Markdown",
            reply_markup=admin_menu_keyboard()
        )
        return

    if data == "adm_logout":
        clear_admin(user_id)
        await query.edit_message_text("👋 Logged out successfully.")
        return

    if data == "adm_students":
        students = load_students()
        if not students:
            await query.edit_message_text("No students yet.", reply_markup=back_keyboard())
            return
        buttons = []
        lines   = [f"👥 *Total Students: {len(students)}*\n"]
        for i, (uid, s) in enumerate(students.items(), 1):
            name  = s.get("name", "Unknown")
            level = s.get("level", "?")
            lines.append(f"{i}. {name} ({level})")
            buttons.append([InlineKeyboardButton(
                f"{name} ({level})", callback_data=f"student_{uid}"
            )])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm_back")])
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("student_"):
        uid      = data[len("student_"):]
        students = load_students()
        s        = students.get(uid, {})
        name     = s.get("name", "Unknown")
        level    = s.get("level", "?")
        streak   = s.get("streak", 0)
        points   = s.get("points", 0)
        joined   = s.get("joined", "—")
        last     = s.get("last_active", "—")
        text = (
            f"👤 *Name:* {name}\n"
            f"🆔 *Telegram ID:* `{uid}`\n"
            f"📖 *Level:* {level}\n"
            f"🔥 *Streak:* {streak} days\n"
            f"⭐ *Points:* {points}\n"
            f"📅 *Joined:* {joined}\n"
            f"🕐 *Last Active:* {last}"
        )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Students", callback_data="adm_students")]
            ])
        )
        return

    if data == "adm_stats":
        students = load_students()
        counts   = {"A1": 0, "A2": 0, "B1": 0, "B2": 0}
        today    = date.today().isoformat()
        active_today = 0
        for s in students.values():
            lv = s.get("level", "")
            if lv in counts:
                counts[lv] += 1
            if s.get("last_active_date", "") == today:
                active_today += 1
        total_completed = sum(s.get("exercises_completed", 0) for s in students.values())
        text = (
            f"📊 *Statistics*\n\n"
            f"👥 *Total Students:* {len(students)}\n\n"
            f"A1 : {counts['A1']}\n"
            f"A2 : {counts['A2']}\n"
            f"B1 : {counts['B1']}\n"
            f"B2 : {counts['B2']}\n\n"
            f"✅ *Today's Active Users:* {active_today}\n"
            f"📝 *Exercises Completed:* {total_completed}"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
        return

    if data == "adm_broadcast":
        set_admin_state(user_id, "broadcast_message")
        await query.edit_message_text(
            "📤 *Broadcast*\n\nType the message you want to send to ALL students.\n\nSend /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data == "adm_settings":
        settings = load_settings()
        reminder = "✅ ON" if settings.get("reminders_enabled") else "❌ OFF"
        time_val = settings.get("daily_exercise_time", "09:00")
        text = (
            f"⚙️ *Settings*\n\n"
            f"🕐 Daily Exercise Time: *{time_val}*\n"
            f"🔔 Reminders: *{reminder}*"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=settings_keyboard())
        return

    if data == "set_password":
        set_admin_state(user_id, "set_password")
        await query.edit_message_text("🔑 Enter your *new admin password*:", parse_mode="Markdown")
        return

    if data == "set_time":
        set_admin_state(user_id, "set_time")
        await query.edit_message_text("🕐 Enter the new daily exercise time (e.g. *08:30*):", parse_mode="Markdown")
        return

    if data == "set_reminders":
        settings = load_settings()
        settings["reminders_enabled"] = not settings.get("reminders_enabled", True)
        save_settings(settings)
        status = "✅ ON" if settings["reminders_enabled"] else "❌ OFF"
        await query.edit_message_text(
            f"🔔 Reminders toggled: *{status}*",
            parse_mode="Markdown",
            reply_markup=back_keyboard()
        )
        return

    if data == "set_addvocab":
        set_admin_state(user_id, "add_vocab")
        await query.edit_message_text(
            "📖 *Add Vocabulary*\n\n"
            "Send the word and meaning in this format:\n"
            "`word = meaning`\n\n"
            "Example: `Haus = House`\n\n"
            "Send /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data == "set_addexercise":
        set_admin_state(user_id, "add_exercise_level")
        await query.edit_message_text(
            "📝 *Add Exercise*\n\n"
            "First, choose the level this exercise is for:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("A1", callback_data="exlevel_A1"),
                 InlineKeyboardButton("A2", callback_data="exlevel_A2")],
                [InlineKeyboardButton("B1", callback_data="exlevel_B1"),
                 InlineKeyboardButton("B2", callback_data="exlevel_B2")],
            ])
        )
        return

    if data.startswith("exlevel_"):
        level = data[len("exlevel_"):]
        set_admin_state(user_id, "add_exercise_text", {"level": level})
        await query.edit_message_text(
            f"📝 *Adding exercise for level {level}*\n\n"
            "Send the exercise in this format:\n"
            "`Question | Answer`\n\n"
            "Example: `Was ist die Hauptstadt von Deutschland? | Berlin`\n\n"
            "Send /cancel to abort.",
            parse_mode="Markdown"
        )
        return

# ─────────────────────────────────────────────
# /cancel COMMAND
# ─────────────────────────────────────────────
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin_logged_in(user_id) or admin_state(user_id):
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(
            "❌ Cancelled.\n\n✅ *Admin Panel* — Choose an option:",
            parse_mode="Markdown",
            reply_markup=admin_menu_keyboard()
        )
    else:
        await update.message.reply_text("Nothing to cancel.")

# ─────────────────────────────────────────────
# MAIN MESSAGE HANDLER
# ─────────────────────────────────────────────
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()
    user_id      = update.effective_user.id
    uid_str      = str(user_id)

    # ── ADMIN FLOW ──
    state = admin_state(user_id)

    if state == "waiting_password":
        try:
            await context.bot.delete_message(
                chat_id=update.message.chat_id,
                message_id=update.message.message_id
            )
        except Exception:
            pass
        settings = load_settings()
        correct  = settings.get("admin_password", ADMIN_PASS)
        if user_message == correct:
            set_admin_state(user_id, "logged_in")
            await send_admin_menu(update, context)
        else:
            await update.message.reply_text("❌ Wrong password. Try again or use /administrator.")
            clear_admin(user_id)
        return

    if state == "broadcast_message":
        students = load_students()
        sent = 0
        for uid in students:
            try:
                await context.bot.send_message(
                    chat_id=int(uid),
                    text=f"📢 *Message from your German tutor:*\n\n{user_message}",
                    parse_mode="Markdown"
                )
                sent += 1
            except Exception:
                pass
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(
            f"✅ Broadcast sent to {sent} student(s).",
            reply_markup=admin_menu_keyboard()
        )
        return

    if state == "set_password":
        settings = load_settings()
        settings["admin_password"] = user_message
        save_settings(settings)
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(
            "✅ Password updated successfully!",
            reply_markup=admin_menu_keyboard()
        )
        return

    if state == "set_time":
        settings = load_settings()
        settings["daily_exercise_time"] = user_message
        save_settings(settings)
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(
            f"✅ Daily exercise time set to *{user_message}*.",
            parse_mode="Markdown",
            reply_markup=admin_menu_keyboard()
        )
        return

    if state == "add_vocab":
        if "=" in user_message:
            parts   = user_message.split("=", 1)
            word    = parts[0].strip().lower()
            meaning = parts[1].strip()
            database = load_database()
            database[word] = meaning
            save_json(DB_FILE, database)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(
                f"✅ Vocabulary added!\n\n*{word}* = {meaning}",
                parse_mode="Markdown",
                reply_markup=admin_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                "⚠️ Wrong format. Use: `word = meaning`", parse_mode="Markdown"
            )
        return

    if state == "add_exercise_text":
        stored_data = admin_sessions[user_id].get("data", {})
        level = stored_data.get("level", "A1")
        if "|" in user_message:
            parts    = user_message.split("|", 1)
            question = parts[0].strip()
            answer   = parts[1].strip()
            exercises = load_exercises()
            exercises.append({"level": level, "question": question, "answer": answer})
            save_exercises(exercises)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(
                f"✅ Exercise added for *{level}*!\n\n"
                f"❓ {question}\n✅ {answer}",
                parse_mode="Markdown",
                reply_markup=admin_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                "⚠️ Wrong format. Use: `Question | Answer`", parse_mode="Markdown"
            )
        return

    # ── STUDENT FLOW ──
    students = load_students()

    if uid_str not in students:
        students[uid_str] = {
            "level": "",
            "name": "",
            "status": "waiting_for_level",
            "points": 0,
            "streak": 0,
            "exercises_completed": 0,
            "joined": datetime.now().strftime("%d %B %Y"),
            "last_active": datetime.now().strftime("%d %b %Y %H:%M"),
            "last_active_date": date.today().isoformat()
        }
        save_students(students)
        await update.message.reply_text(
            "Hallo! 👋\n\nWie geht es dir?\n\nBitte wähle dein Deutschniveau:",
            reply_markup=level_keyboard()
        )
        return

    student = students[uid_str]

    if student["status"] == "waiting_for_level":
        if user_message in ["A1", "A2", "B1", "B2"]:
            student["level"]  = user_message
            student["status"] = "waiting_for_name"
            save_students(students)
            await update.message.reply_text("Super! 😊\n\nWie heißt du?", reply_markup=ReplyKeyboardRemove())
        else:
            await update.message.reply_text("Bitte wähle dein Deutschniveau:", reply_markup=level_keyboard())
        return

    if student["status"] == "waiting_for_name":
        student["name"]   = user_message
        student["status"] = "active"
        save_students(students)
        await update.message.reply_text(
            f"Freut mich, {user_message}! 🎉\n\nJetzt können wir Deutsch zusammen lernen."
        )
        return

    # Active student
    touch_student(uid_str)
    name     = student.get("name", "")
    database = load_database()

    if user_message.lower() in database:
        add_points(uid_str, 2)
        await update.message.reply_text(f"{name}, {database[user_message.lower()]} ⭐")
    else:
        await update.message.reply_text(f"{name}, ich lerne das noch. 😊")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("administrator", cmd_administrator))
    app.add_handler(CommandHandler("cancel",        cmd_cancel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
