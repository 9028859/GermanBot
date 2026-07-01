import os
import json
import random
import pytz
from datetime import datetime, date, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    JobQueue,
)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
TOKEN          = os.getenv("BOT_TOKEN")
ADMIN_ID       = os.getenv("ADMIN_ID")
ADMIN_PASS     = os.getenv("ADMIN_PASSWORD", "anand2024")
GROUP_ID       = int(os.getenv("GROUP_ID", "-5524345306"))
IST            = pytz.timezone("Asia/Kolkata")

# Files
DB_FILE        = "database.json"
STUDENTS_FILE  = "students.json"
EXERCISES_FILE = "exercises.json"
SETTINGS_FILE  = "settings.json"
WHITELIST_FILE = "whitelist.json"
DAILY_FILE     = "daily.json"

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
def load_whitelist():   return load_json(WHITELIST_FILE, {"ids": [], "usernames": []})
def save_whitelist(d):  save_json(WHITELIST_FILE, d)
def load_daily():       return load_json(DAILY_FILE, {"date": "", "words": {}, "attendance": []})
def save_daily(d):      save_json(DAILY_FILE, d)
def load_settings():
    return load_json(SETTINGS_FILE, {
        "admin_password": ADMIN_PASS,
        "daily_exercise_time": "06:00",
        "reminders_enabled": True,
        "whitelist_enabled": False
    })
def save_settings(d):   save_json(SETTINGS_FILE, d)

# ─────────────────────────────────────────────
# WHITELIST CHECK
# ─────────────────────────────────────────────
def is_allowed(user_id: int, username: str) -> bool:
    settings = load_settings()
    if not settings.get("whitelist_enabled", False):
        return True
    whitelist = load_whitelist()
    allowed_ids = [str(i) for i in whitelist.get("ids", [])]
    allowed_usernames = [u.lower().lstrip("@") for u in whitelist.get("usernames", [])]
    if str(user_id) in allowed_ids:
        return True
    if username and username.lower().lstrip("@") in allowed_usernames:
        return True
    return False

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
# STUDENT SESSION STORE
# ─────────────────────────────────────────────
student_sessions = {}  # uid -> {"mode": ..., "data": ...}

def student_mode(uid: str) -> str:
    return student_sessions.get(uid, {}).get("mode", "menu")

def set_student_mode(uid: str, mode: str, data: dict = None):
    student_sessions[uid] = {"mode": mode, "data": data or {}}

def student_data(uid: str) -> dict:
    return student_sessions.get(uid, {}).get("data", {})

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
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if last == yesterday:
            s["streak"] = s.get("streak", 0) + 1
        else:
            s["streak"] = 1
        s["last_active_date"] = today_str
    s["last_active"] = datetime.now(IST).strftime("%d %b %Y %H:%M")
    students[user_id] = s
    save_students(students)

def add_points(user_id: str, pts: int):
    students = load_students()
    if user_id in students:
        students[user_id]["points"] = students[user_id].get("points", 0) + pts
        save_students(students)

# ─────────────────────────────────────────────
# TEST TIME CHECK
# ─────────────────────────────────────────────
def is_test_time() -> bool:
    now = datetime.now(IST)
    test_start = now.replace(hour=18, minute=0, second=0, microsecond=0)
    test_end   = now.replace(hour=18, minute=5, second=0, microsecond=0)
    return test_start <= now <= test_end

def is_before_test() -> bool:
    now = datetime.now(IST)
    return now.hour < 18

def is_after_test() -> bool:
    now = datetime.now(IST)
    return now >= now.replace(hour=18, minute=5, second=0, microsecond=0)

# ─────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["📖 Vocabulary Practice", "❓ Q&A"],
        ["📝 Today's Test",        "📊 My Progress"],
        ["🏆 Leaderboard",         "❌ Cancel"],
    ], resize_keyboard=True)

def level_keyboard():
    return ReplyKeyboardMarkup([["A1", "A2"], ["B1", "B2"]], resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)

def admin_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Students",   callback_data="adm_students")],
        [InlineKeyboardButton("📊 Statistics", callback_data="adm_stats")],
        [InlineKeyboardButton("📤 Broadcast",  callback_data="adm_broadcast")],
        [InlineKeyboardButton("🔒 Whitelist",  callback_data="adm_whitelist")],
        [InlineKeyboardButton("⚙️ Settings",   callback_data="adm_settings")],
        [InlineKeyboardButton("🚪 Logout",     callback_data="adm_logout")],
    ])

def settings_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Change Password",     callback_data="set_password")],
        [InlineKeyboardButton("🕐 Daily Exercise Time", callback_data="set_time")],
        [InlineKeyboardButton("🔔 Toggle Reminders",    callback_data="set_reminders")],
        [InlineKeyboardButton("➕ Add Vocabulary",      callback_data="set_addvocab")],
        [InlineKeyboardButton("📝 Add Exercise",        callback_data="set_addexercise")],
        [InlineKeyboardButton("📄 Upload PDF Vocab",    callback_data="set_uploadpdf")],
        [InlineKeyboardButton("🔙 Back",                callback_data="adm_back")],
    ])

def whitelist_keyboard():
    settings = load_settings()
    status = "✅ ON" if settings.get("whitelist_enabled") else "❌ OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔒 Whitelist: {status}",    callback_data="wl_toggle")],
        [InlineKeyboardButton("➕ Add by Telegram ID",      callback_data="wl_add_id")],
        [InlineKeyboardButton("➕ Add by Username (@user)", callback_data="wl_add_username")],
        [InlineKeyboardButton("👁 View Whitelist",          callback_data="wl_view")],
        [InlineKeyboardButton("❌ Remove Entry",            callback_data="wl_remove")],
        [InlineKeyboardButton("🔙 Back",                    callback_data="adm_back")],
    ])

def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="adm_back")]])

# ─────────────────────────────────────────────
# SCHEDULED JOBS
# ─────────────────────────────────────────────
async def send_daily_vocab(context: ContextTypes.DEFAULT_TYPE):
    """6:00 AM IST — send 10 random words to all students."""
    database = load_database()
    students = load_students()
    if not database or not students:
        return

    all_words = list(database.keys())
    chosen    = random.sample(all_words, min(10, len(all_words)))

    # Save today's words and reset attendance
    daily = {
        "date": date.today().isoformat(),
        "words": {w: database[w] for w in chosen},
        "attendance": []
    }
    save_daily(daily)

    lines = ["🌅 *Guten Morgen! Good Morning!*\n\n📖 *Today's 10 Vocabulary Words:*\n"]
    for i, word in enumerate(chosen, 1):
        lines.append(f"{i}. *{word}* — {database[word]}")
    lines.append("\n🧪 *Test at 6:00 PM sharp! Only 5 minutes!* ⏱\nKeep studying! 💪")
    text = "\n".join(lines)

    for uid, s in students.items():
        if s.get("status") == "active":
            try:
                await context.bot.send_message(
                    chat_id=int(uid),
                    text=text,
                    parse_mode="Markdown"
                )
            except Exception:
                pass

async def send_test_closed(context: ContextTypes.DEFAULT_TYPE):
    """6:05 PM IST — check attendance and send imposition to group."""
    daily    = load_daily()
    students = load_students()
    attended = daily.get("attendance", [])
    words    = daily.get("words", {})

    absent = []
    for uid, s in students.items():
        if s.get("status") == "active" and uid not in attended:
            absent.append(s)

    if not absent:
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text="✅ *Wunderbar! All students attended today's test!* 🎉",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    # Build imposition message
    mentions = ""
    for s in absent:
        name     = s.get("name", "Student")
        username = s.get("username", "")
        if username:
            mentions += f"@{username} "
        else:
            mentions += f"*{name}* "

    word_list = "\n".join([f"• *{w}* — {m}" for w, m in words.items()])
    imposition = (
        f"📋 *Test Attendance Report*\n\n"
        f"❌ The following students missed today's test:\n"
        f"{mentions}\n\n"
        f"🖊 *Du hast den Test verpasst!* (You missed the test!)\n\n"
        f"📝 *Imposition:* Write all today's words *10 times each* and submit in this group before *10:00 PM* today!\n\n"
        f"📖 *Today's Words:*\n{word_list}\n\n"
        f"Weiter lernen! Keep learning! 💪"
    )

    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=imposition,
            parse_mode="Markdown"
        )
    except Exception:
        pass

# ─────────────────────────────────────────────
# /start COMMAND
# ─────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    uid_str  = str(user_id)
    username = update.effective_user.username or ""
    students = load_students()

    if uid_str in students and students[uid_str].get("status") == "active":
        name = students[uid_str].get("name", "")
        await update.message.reply_text(
            f"Willkommen zurück, *{name}*! 👋\n\nWas möchtest du tun?",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        return

    if uid_str not in students:
        students[uid_str] = {
            "level": "", "name": "", "username": username,
            "status": "waiting_for_level",
            "points": 0, "streak": 0, "exercises_completed": 0,
            "joined": datetime.now(IST).strftime("%d %B %Y"),
            "last_active": datetime.now(IST).strftime("%d %b %Y %H:%M"),
            "last_active_date": date.today().isoformat()
        }
        save_students(students)
        await update.message.reply_text(
            "Hallo! 👋 Welcome to *Deutsch Lernen*!\n\n"
            "Please choose your German level:",
            parse_mode="Markdown",
            reply_markup=level_keyboard()
        )

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
    uid_str = str(user_id)
    data    = query.data
    await query.answer()

    # ── STUDENT MCQ ANSWER (Q&A) ──
    if data.startswith("qna_"):
        chosen = data[len("qna_"):]
        sdata  = student_data(uid_str)
        q      = sdata.get("question", {})
        correct = q.get("answer", "")
        is_correct = chosen.strip().lower() == correct.strip().lower()

        if is_correct:
            add_points(uid_str, 5)
            students = load_students()
            if uid_str in students:
                students[uid_str]["exercises_completed"] = students[uid_str].get("exercises_completed", 0) + 1
                save_students(students)
            fb = "✅ *Richtig!* +5 points 🌟"
        else:
            fb = f"❌ *Falsch!*\n\nCorrect answer: *{correct}*"

        set_student_mode(uid_str, "menu")
        await query.edit_message_text(f"{fb}\n\nTap ❓ Q&A again for another question!", parse_mode="Markdown")
        return

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
            buttons.append([InlineKeyboardButton(f"{name} ({level})", callback_data=f"student_{uid}")])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm_back")])
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("student_"):
        uid      = data[len("student_"):]
        students = load_students()
        s        = students.get(uid, {})
        text = (
            f"👤 *Name:* {s.get('name','?')}\n"
            f"🆔 *Telegram ID:* `{uid}`\n"
            f"👤 *Username:* @{s.get('username','—')}\n"
            f"📖 *Level:* {s.get('level','?')}\n"
            f"🔥 *Streak:* {s.get('streak',0)} days\n"
            f"⭐ *Points:* {s.get('points',0)}\n"
            f"📝 *Exercises Done:* {s.get('exercises_completed',0)}\n"
            f"📅 *Joined:* {s.get('joined','—')}\n"
            f"🕐 *Last Active:* {s.get('last_active','—')}"
        )
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add to Whitelist", callback_data=f"wl_addstudent_{uid}")],
                [InlineKeyboardButton("🔙 Back", callback_data="adm_students")]
            ])
        )
        return

    if data.startswith("wl_addstudent_"):
        uid = data[len("wl_addstudent_"):]
        whitelist = load_whitelist()
        if uid not in [str(i) for i in whitelist["ids"]]:
            whitelist["ids"].append(uid)
            save_whitelist(whitelist)
            await query.edit_message_text(f"✅ ID `{uid}` added to whitelist!", parse_mode="Markdown", reply_markup=back_keyboard())
        else:
            await query.edit_message_text("ℹ️ Already in whitelist.", reply_markup=back_keyboard())
        return

    if data == "adm_stats":
        students = load_students()
        counts   = {"A1": 0, "A2": 0, "B1": 0, "B2": 0}
        today    = date.today().isoformat()
        active_today = 0
        for s in students.values():
            lv = s.get("level", "")
            if lv in counts: counts[lv] += 1
            if s.get("last_active_date", "") == today: active_today += 1
        daily = load_daily()
        attended_today = len(daily.get("attendance", []))
        total_completed = sum(s.get("exercises_completed", 0) for s in students.values())
        text = (
            f"📊 *Statistics*\n\n"
            f"👥 *Total Students:* {len(students)}\n\n"
            f"A1 : {counts['A1']}\nA2 : {counts['A2']}\n"
            f"B1 : {counts['B1']}\nB2 : {counts['B2']}\n\n"
            f"✅ *Today's Active:* {active_today}\n"
            f"📝 *Today's Test Attended:* {attended_today}\n"
            f"🏅 *Total Exercises Done:* {total_completed}"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
        return

    if data == "adm_broadcast":
        set_admin_state(user_id, "broadcast_message")
        await query.edit_message_text(
            "📤 *Broadcast*\n\nType your message for ALL students.\n\nSend /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data == "adm_whitelist":
        whitelist = load_whitelist()
        settings  = load_settings()
        status    = "✅ ON" if settings.get("whitelist_enabled") else "❌ OFF"
        text = (
            f"🔒 *Whitelist Panel*\n\n"
            f"Status: *{status}*\n"
            f"Allowed IDs: *{len(whitelist.get('ids',[]))}*\n"
            f"Allowed Usernames: *{len(whitelist.get('usernames',[]))}*"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=whitelist_keyboard())
        return

    if data == "wl_toggle":
        settings = load_settings()
        settings["whitelist_enabled"] = not settings.get("whitelist_enabled", False)
        save_settings(settings)
        status = "✅ ON" if settings["whitelist_enabled"] else "❌ OFF"
        await query.edit_message_text(f"🔒 Whitelist is now *{status}*", parse_mode="Markdown", reply_markup=whitelist_keyboard())
        return

    if data == "wl_add_id":
        set_admin_state(user_id, "wl_add_id")
        await query.edit_message_text("➕ Send the student's Telegram ID (numbers only).\n\nSend /cancel to abort.", parse_mode="Markdown")
        return

    if data == "wl_add_username":
        set_admin_state(user_id, "wl_add_username")
        await query.edit_message_text("➕ Send the student's @username.\n\nSend /cancel to abort.", parse_mode="Markdown")
        return

    if data == "wl_view":
        whitelist = load_whitelist()
        ids       = whitelist.get("ids", [])
        usernames = whitelist.get("usernames", [])
        lines = ["🔒 *Whitelist*\n"]
        if ids:
            lines.append("*By ID:*")
            for i, tid in enumerate(ids, 1): lines.append(f"{i}. `{tid}`")
        if usernames:
            lines.append("\n*By Username:*")
            for i, un in enumerate(usernames, 1): lines.append(f"{i}. @{un}")
        if not ids and not usernames:
            lines.append("_No entries yet._")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_whitelist")]]))
        return

    if data == "wl_remove":
        set_admin_state(user_id, "wl_remove")
        await query.edit_message_text("❌ Send the ID or username to remove.\n\nSend /cancel to abort.", parse_mode="Markdown")
        return

    if data == "adm_settings":
        settings = load_settings()
        reminder = "✅ ON" if settings.get("reminders_enabled") else "❌ OFF"
        await query.edit_message_text(
            f"⚙️ *Settings*\n\n🔔 Reminders: *{reminder}*",
            parse_mode="Markdown", reply_markup=settings_keyboard()
        )
        return

    if data == "set_password":
        set_admin_state(user_id, "set_password")
        await query.edit_message_text("🔑 Enter your *new admin password*:", parse_mode="Markdown")
        return

    if data == "set_time":
        set_admin_state(user_id, "set_time")
        await query.edit_message_text("🕐 Enter the new daily vocab time (e.g. *06:00*):", parse_mode="Markdown")
        return

    if data == "set_reminders":
        settings = load_settings()
        settings["reminders_enabled"] = not settings.get("reminders_enabled", True)
        save_settings(settings)
        status = "✅ ON" if settings["reminders_enabled"] else "❌ OFF"
        await query.edit_message_text(f"🔔 Reminders: *{status}*", parse_mode="Markdown", reply_markup=back_keyboard())
        return

    if data == "set_addvocab":
        set_admin_state(user_id, "add_vocab")
        await query.edit_message_text(
            "📖 *Add Vocabulary*\n\nFormat: `word = meaning`\nExample: `Haus = House`\n\nSend /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data == "set_addexercise":
        set_admin_state(user_id, "add_exercise_level")
        await query.edit_message_text(
            "📝 *Add Exercise* — Choose level:",
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
            f"📝 *Exercise for {level}*\n\nFormat: `Question | Answer`\nExample: `Was ist die Hauptstadt? | Berlin`\n\nSend /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data == "set_uploadpdf":
        set_admin_state(user_id, "upload_pdf")
        await query.edit_message_text(
            "📄 *Upload PDF*\n\nSend me a PDF file. I will extract German words and add them to the vocabulary database.\n\nSend /cancel to abort.",
            parse_mode="Markdown"
        )
        return

# ─────────────────────────────────────────────
# PDF HANDLER
# ─────────────────────────────────────────────
async def pdf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if admin_state(user_id) != "upload_pdf":
        return

    try:
        import pdfplumber
        file = await update.message.document.get_file()
        path = f"/tmp/upload_{user_id}.pdf"
        await file.download_to_drive(path)

        extracted = {}
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    if "=" in line:
                        parts = line.split("=", 1)
                        word    = parts[0].strip().lower()
                        meaning = parts[1].strip()
                        if word and meaning:
                            extracted[word] = meaning
                    elif "-" in line:
                        parts = line.split("-", 1)
                        word    = parts[0].strip().lower()
                        meaning = parts[1].strip()
                        if word and meaning and len(word) < 40:
                            extracted[word] = meaning

        if extracted:
            database = load_database()
            database.update(extracted)
            save_json(DB_FILE, database)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(
                f"✅ *PDF processed!*\n\n{len(extracted)} words added to the database.",
                parse_mode="Markdown",
                reply_markup=admin_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                "⚠️ No vocabulary found in PDF.\n\nMake sure words are in format:\n`word = meaning` or `word - meaning`",
                parse_mode="Markdown"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Error reading PDF: {str(e)}")

# ─────────────────────────────────────────────
# /cancel COMMAND
# ─────────────────────────────────────────────
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    uid_str = str(user_id)

    if is_admin_logged_in(user_id) or admin_state(user_id):
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(
            "❌ Cancelled.\n\n✅ *Admin Panel* — Choose an option:",
            parse_mode="Markdown",
            reply_markup=admin_menu_keyboard()
        )
    else:
        set_student_mode(uid_str, "menu")
        await update.message.reply_text(
            "↩️ Back to main menu.",
            reply_markup=main_menu_keyboard()
        )

async def is_bot_mentioned(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True if the message @mentions the bot or is a reply to one of the bot's messages."""
    msg = update.message
    try:
        bot_me = await context.bot.get_me()
        bot_username = (bot_me.username or "").lower()
    except Exception:
        bot_username = ""
    # Check entities for a mention of this bot
    if msg.entities and msg.text:
        for ent in msg.entities:
            if ent.type == "mention":
                mention_text = msg.text[ent.offset:ent.offset + ent.length].lower().lstrip("@")
                if mention_text == bot_username:
                    return True
    # Check if replying to one of the bot's own messages
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.is_bot:
            return True
    return False

# ─────────────────────────────────────────────
# MAIN MESSAGE HANDLER
# ─────────────────────────────────────────────
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()
    user_id      = update.effective_user.id
    uid_str      = str(user_id)
    username     = update.effective_user.username or ""

    # ── ADMIN FLOW ──
    state = admin_state(user_id)

    if state == "waiting_password":
        try:
            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
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
                await context.bot.send_message(chat_id=int(uid), text=f"📢 *Message from your German tutor:*\n\n{user_message}", parse_mode="Markdown")
                sent += 1
            except Exception:
                pass
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(f"✅ Broadcast sent to {sent} student(s).", reply_markup=admin_menu_keyboard())
        return

    if state == "set_password":
        settings = load_settings()
        settings["admin_password"] = user_message
        save_settings(settings)
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text("✅ Password updated!", reply_markup=admin_menu_keyboard())
        return

    if state == "set_time":
        settings = load_settings()
        settings["daily_exercise_time"] = user_message
        save_settings(settings)
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(f"✅ Daily vocab time set to *{user_message}*.", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
        return

    if state == "add_vocab":
        if "=" in user_message:
            parts = user_message.split("=", 1)
            word    = parts[0].strip().lower()
            meaning = parts[1].strip()
            database = load_database()
            database[word] = meaning
            save_json(DB_FILE, database)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(f"✅ Added!\n\n*{word}* = {meaning}", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
        else:
            await update.message.reply_text("⚠️ Format: `word = meaning`", parse_mode="Markdown")
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
                f"✅ Exercise added for *{level}*!\n\n❓ {question}\n✅ {answer}",
                parse_mode="Markdown", reply_markup=admin_menu_keyboard()
            )
        else:
            await update.message.reply_text("⚠️ Format: `Question | Answer`", parse_mode="Markdown")
        return

    if state == "wl_add_id":
        entry = user_message.strip()
        if entry.isdigit():
            whitelist = load_whitelist()
            if entry not in [str(i) for i in whitelist["ids"]]:
                whitelist["ids"].append(entry)
                save_whitelist(whitelist)
                set_admin_state(user_id, "logged_in")
                await update.message.reply_text(f"✅ ID `{entry}` added!", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
            else:
                await update.message.reply_text("ℹ️ Already in whitelist.")
        else:
            await update.message.reply_text("⚠️ Numbers only.")
        return

    if state == "wl_add_username":
        entry = user_message.strip().lstrip("@").lower()
        whitelist = load_whitelist()
        if entry not in [u.lower() for u in whitelist["usernames"]]:
            whitelist["usernames"].append(entry)
            save_whitelist(whitelist)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(f"✅ @{entry} added!", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
        else:
            await update.message.reply_text("ℹ️ Already in whitelist.")
        return

    if state == "wl_remove":
        entry = user_message.strip().lstrip("@").lower()
        whitelist = load_whitelist()
        removed = False
        if entry.isdigit() and entry in [str(i) for i in whitelist["ids"]]:
            whitelist["ids"] = [i for i in whitelist["ids"] if str(i) != entry]
            removed = True
        elif entry in [u.lower() for u in whitelist["usernames"]]:
            whitelist["usernames"] = [u for u in whitelist["usernames"] if u.lower() != entry]
            removed = True
        if removed:
            save_whitelist(whitelist)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(f"✅ `{entry}` removed.", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
        else:
            await update.message.reply_text("⚠️ Not found in whitelist.")
        return

    # ── WHITELIST CHECK ──
    if str(user_id) != str(ADMIN_ID) and not is_allowed(user_id, username):
        await update.message.reply_text("⛔ Sorry, this bot is currently private.\n\nPlease contact your German tutor to get access.")
        return

    # ── STUDENT REGISTRATION ──
    students = load_students()

    if uid_str not in students:
        students[uid_str] = {
            "level": "", "name": "", "username": username,
            "status": "waiting_for_level",
            "points": 0, "streak": 0, "exercises_completed": 0,
            "joined": datetime.now(IST).strftime("%d %B %Y"),
            "last_active": datetime.now(IST).strftime("%d %b %Y %H:%M"),
            "last_active_date": date.today().isoformat()
        }
        save_students(students)
        await update.message.reply_text(
            "Hallo! 👋 Welcome to *Deutsch Lernen*!\n\nPlease choose your German level:",
            parse_mode="Markdown", reply_markup=level_keyboard()
        )
        return

    student = students[uid_str]

    if student["status"] == "waiting_for_level":
        if user_message in ["A1", "A2", "B1", "B2"]:
            student["level"]  = user_message
            student["status"] = "waiting_for_name"
            save_students(students)
            await update.message.reply_text("Super! 😊\n\nWie heißt du? What is your name?", reply_markup=ReplyKeyboardRemove())
        else:
            await update.message.reply_text("Please choose your level:", reply_markup=level_keyboard())
        return

    if student["status"] == "waiting_for_name":
        student["name"]     = user_message
        student["username"] = username
        student["status"]   = "active"
        save_students(students)
        await update.message.reply_text(
            f"Willkommen, *{user_message}*! 🎉\n\n"
            f"You are registered as *{student['level']}* level.\n\n"
            f"Here is your menu — tap any button to start! 👇",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        return

    # ── ACTIVE STUDENT ──
    touch_student(uid_str)
    mode = student_mode(uid_str)

    # ── CANCEL BUTTON ──
    if "Cancel" in user_message or user_message == "❌ Cancel":
        set_student_mode(uid_str, "menu")
        await update.message.reply_text("↩️ Back to main menu.", reply_markup=main_menu_keyboard())
        return

    # ── VOCABULARY PRACTICE ──
    if "Vocabulary Practice" in user_message or user_message == "📖 Vocabulary Practice":
        database = load_database()
        if not database:
            await update.message.reply_text("No vocabulary yet. Check back soon!", reply_markup=main_menu_keyboard())
            return
        word, meaning = random.choice(list(database.items()))
        set_student_mode(uid_str, "vocab_quiz", {"word": word, "meaning": meaning})
        await update.message.reply_text(
            f"📖 *Vocabulary Practice*\n\n"
            f"What is the meaning of:\n\n"
            f"🇩🇪 *{word.capitalize()}*\n\n"
            f"Type your answer in English!\n\n_(Tap ❌ Cancel to stop)_",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return

    if mode == "vocab_quiz":
        data     = student_data(uid_str)
        word     = data.get("word", "")
        meaning  = data.get("meaning", "").lower()
        answer   = user_message.lower().strip()
        database = load_database()

        if answer in meaning or meaning in answer:
            add_points(uid_str, 5)
            students = load_students()
            students[uid_str]["exercises_completed"] = students[uid_str].get("exercises_completed", 0) + 1
            save_students(students)
            # Next word
            new_word, new_meaning = random.choice(list(database.items()))
            set_student_mode(uid_str, "vocab_quiz", {"word": new_word, "meaning": new_meaning})
            await update.message.reply_text(
                f"✅ *Richtig! Correct!* +5 points 🌟\n\n"
                f"Next word:\n\n🇩🇪 *{new_word.capitalize()}*\n\n"
                f"Type your answer!",
                parse_mode="Markdown",
                reply_markup=cancel_keyboard()
            )
        else:
            new_word, new_meaning = random.choice(list(database.items()))
            set_student_mode(uid_str, "vocab_quiz", {"word": new_word, "meaning": new_meaning})
            await update.message.reply_text(
                f"❌ *Falsch! Wrong!*\n\nThe correct answer was: *{data.get('meaning')}*\n\n"
                f"Next word:\n\n🇩🇪 *{new_word.capitalize()}*\n\nType your answer!",
                parse_mode="Markdown",
                reply_markup=cancel_keyboard()
            )
        return

    # ── Q&A (grammar exercises by level) ──
    if "Q&A" in user_message or user_message == "❓ Q&A":
        level = student.get("level", "A1")
        exercises = [e for e in load_exercises() if e.get("level") == level]
        if not exercises:
            await update.message.reply_text("No questions available for your level yet.", reply_markup=main_menu_keyboard())
            return
        q = random.choice(exercises)
        set_student_mode(uid_str, "qna", {"question": q})
        if q.get("type") == "mcq":
            opts = q.get("options", [])
            buttons = [[InlineKeyboardButton(opt, callback_data=f"qna_{opt}")] for opt in opts]
            await update.message.reply_text(
                f"❓ *Q&A ({level})*\n\n{q['question']}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await update.message.reply_text(
                f"❓ *Q&A ({level})*\n\n{q['question']}\n\n_Type your answer!_",
                parse_mode="Markdown",
                reply_markup=cancel_keyboard()
            )
        return

    if mode == "qna":
        data = student_data(uid_str)
        q = data.get("question", {})
        if q.get("type") == "short":
            correct = q.get("answer", "").lower()
            answer  = user_message.lower().strip()
            is_correct = answer in correct or correct in answer
            if is_correct:
                add_points(uid_str, 5)
                students = load_students()
                students[uid_str]["exercises_completed"] = students[uid_str].get("exercises_completed", 0) + 1
                save_students(students)
                fb = f"✅ *Richtig!* +5 points 🌟"
            else:
                fb = f"❌ *Falsch!*\n\nCorrect answer: *{q.get('answer')}*"
            await update.message.reply_text(
                f"{fb}\n\nTap ❓ Q&A again for another question!",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
            set_student_mode(uid_str, "menu")
        return

    # ── TODAY'S TEST ──
    if "Today's Test" in user_message or user_message == "📝 Today's Test":
        daily = load_daily()
        today = date.today().isoformat()

        if daily.get("date") != today or not daily.get("words"):
            await update.message.reply_text(
                "📭 No vocab was sent today yet.\n\nWait for 6:00 AM vocab! 🌅",
                reply_markup=main_menu_keyboard()
            )
            return

        if uid_str in daily.get("attendance", []):
            await update.message.reply_text(
                "✅ You already completed today's test! Well done! 🎉\n\nCome back tomorrow! 🌟",
                reply_markup=main_menu_keyboard()
            )
            return

        if is_before_test():
            now = datetime.now(IST)
            hrs = 17 - now.hour
            await update.message.reply_text(
                f"⏰ There's still time for the test.\n\n*Keep studying child!* 📚\n\nTest opens at *6:00 PM* sharp!",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
            return

        if is_after_test():
            await update.message.reply_text(
                "⌛ The test window has closed.\n\n*Continue learning and wait for the next test.* 💪\n\nNew vocab tomorrow at *6:00 AM*! 🌅",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
            return

        if is_test_time():
            words = daily.get("words", {})
            word_list = list(words.keys())
            random.shuffle(word_list)
            first_word = word_list[0]
            set_student_mode(uid_str, "test", {
                "words": word_list,
                "index": 0,
                "score": 0,
                "total": len(word_list),
                "daily_words": words
            })
            await update.message.reply_text(
                f"📝 *Today's Test Begins!*\n\n"
                f"You have *5 minutes*. Answer all {len(word_list)} words!\n\n"
                f"Question 1/{len(word_list)}:\n\n"
                f"🇩🇪 *{first_word.capitalize()}*\n\nType the meaning in English!",
                parse_mode="Markdown",
                reply_markup=cancel_keyboard()
            )
        return

    if mode == "test":
        data       = student_data(uid_str)
        words_list = data.get("words", [])
        index      = data.get("index", 0)
        score      = data.get("score", 0)
        total      = data.get("total", 0)
        daily_words = data.get("daily_words", {})

        if not is_test_time():
            set_student_mode(uid_str, "menu")
            await update.message.reply_text(
                "⌛ *Time's up!* The test window closed.\n\n"
                f"You answered *{index}/{total}* questions with *{score}* correct.\n\n"
                "Continue learning and wait for the next test. 💪",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
            return

        current_word = words_list[index]
        correct_meaning = daily_words.get(current_word, "").lower()
        answer = user_message.lower().strip()
        is_correct = answer in correct_meaning or correct_meaning in answer

        if is_correct:
            score += 1

        index += 1
        data["index"] = index
        data["score"] = score
        set_student_mode(uid_str, "test", data)

        if index >= total:
            # Test complete
            add_points(uid_str, score * 10)
            students = load_students()
            students[uid_str]["exercises_completed"] = students[uid_str].get("exercises_completed", 0) + 1
            save_students(students)
            daily = load_daily()
            if uid_str not in daily.get("attendance", []):
                daily["attendance"].append(uid_str)
                save_daily(daily)
            set_student_mode(uid_str, "menu")
            result_text = "🌟 Ausgezeichnet! Excellent!" if score == total else "👍 Gut gemacht! Good job!" if score >= total // 2 else "📚 Weiter üben! Keep practicing!"
            await update.message.reply_text(
                f"🎉 *Test Complete!*\n\n"
                f"Score: *{score}/{total}*\n"
                f"Points earned: *+{score * 10}* ⭐\n\n"
                f"{result_text}",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            next_word = words_list[index]
            fb = "✅ *Richtig!*" if is_correct else f"❌ *Falsch!* Correct: *{daily_words.get(current_word)}*"
            await update.message.reply_text(
                f"{fb}\n\nQuestion {index+1}/{total}:\n\n🇩🇪 *{next_word.capitalize()}*\n\nType the meaning!",
                parse_mode="Markdown",
                reply_markup=cancel_keyboard()
            )
        return

    # ── MY PROGRESS ──
    if "My Progress" in user_message or user_message == "📊 My Progress":
        students = load_students()
        s = students.get(uid_str, {})
        daily = load_daily()
        attended = "✅ Yes" if uid_str in daily.get("attendance", []) else "❌ No"
        await update.message.reply_text(
            f"📊 *My Progress*\n\n"
            f"👤 *Name:* {s.get('name','?')}\n"
            f"📖 *Level:* {s.get('level','?')}\n"
            f"⭐ *Points:* {s.get('points',0)}\n"
            f"🔥 *Streak:* {s.get('streak',0)} days\n"
            f"📝 *Exercises Done:* {s.get('exercises_completed',0)}\n"
            f"📅 *Joined:* {s.get('joined','—')}\n"
            f"🧪 *Today's Test:* {attended}",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        return

    # ── LEADERBOARD ──
    if "Leaderboard" in user_message or user_message == "🏆 Leaderboard":
        students = load_students()
        ranked = sorted(
            [(s.get("name","?"), s.get("points",0)) for s in students.values() if s.get("status")=="active"],
            key=lambda x: x[1], reverse=True
        )
        lines = ["🏆 *Leaderboard*\n"]
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, pts) in enumerate(ranked[:10], 0):
            medal = medals[i] if i < 3 else f"{i+1}."
            lines.append(f"{medal} {name} — *{pts} pts*")
        if not ranked:
            lines.append("No students yet!")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return

    # Outside any active mode:
    # - In private chat with the bot -> reply normally
    # - In a group chat -> stay silent unless mentioned or replied to
    chat_type = update.effective_chat.type
    if chat_type == "private":
        name = student.get("name", "")
        await update.message.reply_text(
            f"Hallo {name}! 👋 Use the menu buttons below to practice, take the test, or check your progress.",
            reply_markup=main_menu_keyboard()
        )
    elif await is_bot_mentioned(update, context):
        name = student.get("name", "")
        await update.message.reply_text(
            f"Hallo {name}! 👋 Use the menu buttons below to practice, take the test, or check your progress.",
            reply_markup=main_menu_keyboard()
        )
    return

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()

    # Scheduled jobs (IST = UTC+5:30)
    jq = app.job_queue
    # 6:00 AM IST = 00:30 UTC
    jq.run_daily(send_daily_vocab, time=__import__("datetime").time(0, 30, 0, tzinfo=pytz.utc))
    # 6:05 PM IST = 12:35 UTC
    jq.run_daily(send_test_closed, time=__import__("datetime").time(12, 35, 0, tzinfo=pytz.utc))

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("administrator", cmd_administrator))
    app.add_handler(CommandHandler("cancel",        cmd_cancel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.Document.PDF, pdf_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
