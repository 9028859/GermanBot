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
TOKEN          = os.getenv("BOT_TOKEN")
ADMIN_ID       = os.getenv("ADMIN_ID")
ADMIN_PASS     = os.getenv("ADMIN_PASSWORD", "anand2024")

# Files
DB_FILE        = "database.json"
STUDENTS_FILE  = "students.json"
EXERCISES_FILE = "exercises.json"
SETTINGS_FILE  = "settings.json"
WHITELIST_FILE = "whitelist.json"

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
    "reminders_enabled": True,
    "whitelist_enabled": False
})
def save_settings(d):   save_json(SETTINGS_FILE, d)
def load_whitelist():   return load_json(WHITELIST_FILE, {"ids": [], "usernames": []})
def save_whitelist(d):  save_json(WHITELIST_FILE, d)

# ─────────────────────────────────────────────
# WHITELIST CHECK
# ─────────────────────────────────────────────
def is_allowed(user_id: int, username: str) -> bool:
    settings = load_settings()
    if not settings.get("whitelist_enabled", False):
        return True  # whitelist off = open to everyone
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
        [InlineKeyboardButton("📚 Students",     callback_data="adm_students")],
        [InlineKeyboardButton("📊 Statistics",   callback_data="adm_stats")],
        [InlineKeyboardButton("📤 Broadcast",    callback_data="adm_broadcast")],
        [InlineKeyboardButton("🔒 Whitelist",    callback_data="adm_whitelist")],
        [InlineKeyboardButton("⚙️ Settings",     callback_data="adm_settings")],
        [InlineKeyboardButton("🚪 Logout",       callback_data="adm_logout")],
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

def whitelist_keyboard():
    settings = load_settings()
    status = "✅ ON" if settings.get("whitelist_enabled") else "❌ OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔒 Whitelist: {status}",     callback_data="wl_toggle")],
        [InlineKeyboardButton("➕ Add by Telegram ID",       callback_data="wl_add_id")],
        [InlineKeyboardButton("➕ Add by Username (@user)",  callback_data="wl_add_username")],
        [InlineKeyboardButton("👁 View Whitelist",           callback_data="wl_view")],
        [InlineKeyboardButton("❌ Remove Entry",             callback_data="wl_remove")],
        [InlineKeyboardButton("🔙 Back",                     callback_data="adm_back")],
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

    # ── BACK TO MENU ──
    if data == "adm_back":
        set_admin_state(user_id, "logged_in")
        await query.edit_message_text(
            "✅ *Admin Panel*\n\nChoose an option:",
            parse_mode="Markdown",
            reply_markup=admin_menu_keyboard()
        )
        return

    # ── LOGOUT ──
    if data == "adm_logout":
        clear_admin(user_id)
        await query.edit_message_text("👋 Logged out successfully.")
        return

    # ── STUDENTS LIST ──
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

    # ── SINGLE STUDENT ──
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
        username = s.get("username", "—")
        text = (
            f"👤 *Name:* {name}\n"
            f"🆔 *Telegram ID:* `{uid}`\n"
            f"👤 *Username:* @{username}\n"
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
                [InlineKeyboardButton("➕ Add to Whitelist", callback_data=f"wl_addstudent_{uid}")],
                [InlineKeyboardButton("🔙 Back to Students", callback_data="adm_students")]
            ])
        )
        return

    # ── ADD STUDENT TO WHITELIST FROM PROFILE ──
    if data.startswith("wl_addstudent_"):
        uid = data[len("wl_addstudent_"):]
        whitelist = load_whitelist()
        if uid not in [str(i) for i in whitelist["ids"]]:
            whitelist["ids"].append(uid)
            save_whitelist(whitelist)
            await query.edit_message_text(
                f"✅ Student ID `{uid}` added to whitelist!",
                parse_mode="Markdown",
                reply_markup=back_keyboard()
            )
        else:
            await query.edit_message_text(
                f"ℹ️ Student ID `{uid}` is already in the whitelist.",
                parse_mode="Markdown",
                reply_markup=back_keyboard()
            )
        return

    # ── STATISTICS ──
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

    # ── BROADCAST ──
    if data == "adm_broadcast":
        set_admin_state(user_id, "broadcast_message")
        await query.edit_message_text(
            "📤 *Broadcast*\n\nType the message to send to ALL students.\n\nSend /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    # ── WHITELIST PANEL ──
    if data == "adm_whitelist":
        whitelist = load_whitelist()
        settings  = load_settings()
        status    = "✅ ON" if settings.get("whitelist_enabled") else "❌ OFF"
        total_ids = len(whitelist.get("ids", []))
        total_un  = len(whitelist.get("usernames", []))
        text = (
            f"🔒 *Whitelist Panel*\n\n"
            f"Status: *{status}*\n"
            f"Allowed IDs: *{total_ids}*\n"
            f"Allowed Usernames: *{total_un}*\n\n"
            f"When ON, only whitelisted users can use the bot."
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=whitelist_keyboard())
        return

    if data == "wl_toggle":
        settings = load_settings()
        settings["whitelist_enabled"] = not settings.get("whitelist_enabled", False)
        save_settings(settings)
        status = "✅ ON" if settings["whitelist_enabled"] else "❌ OFF"
        await query.edit_message_text(
            f"🔒 Whitelist is now *{status}*",
            parse_mode="Markdown",
            reply_markup=whitelist_keyboard()
        )
        return

    if data == "wl_add_id":
        set_admin_state(user_id, "wl_add_id")
        await query.edit_message_text(
            "➕ *Add by Telegram ID*\n\n"
            "Send the student's Telegram ID (numbers only).\n\n"
            "💡 Students can find their ID by messaging @userinfobot\n\n"
            "Send /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data == "wl_add_username":
        set_admin_state(user_id, "wl_add_username")
        await query.edit_message_text(
            "➕ *Add by Username*\n\n"
            "Send the student's Telegram username.\n"
            "Example: `@johnsmith` or just `johnsmith`\n\n"
            "Send /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data == "wl_view":
        whitelist = load_whitelist()
        ids       = whitelist.get("ids", [])
        usernames = whitelist.get("usernames", [])
        lines = ["🔒 *Whitelist*\n"]
        if ids:
            lines.append("*By Telegram ID:*")
            for i, tid in enumerate(ids, 1):
                lines.append(f"{i}. `{tid}`")
        if usernames:
            lines.append("\n*By Username:*")
            for i, un in enumerate(usernames, 1):
                lines.append(f"{i}. @{un}")
        if not ids and not usernames:
            lines.append("_No entries yet._")
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="adm_whitelist")]
            ])
        )
        return

    if data == "wl_remove":
        set_admin_state(user_id, "wl_remove")
        await query.edit_message_text(
            "❌ *Remove from Whitelist*\n\n"
            "Send the Telegram ID or username to remove.\n\n"
            "Send /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    # ── SETTINGS MENU ──
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
            "Format: `word = meaning`\n"
            "Example: `Haus = House`\n\n"
            "Send /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data == "set_addexercise":
        set_admin_state(user_id, "add_exercise_level")
        await query.edit_message_text(
            "📝 *Add Exercise*\n\nChoose the level:",
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
            f"📝 *Exercise for level {level}*\n\n"
            "Format: `Question | Answer`\n"
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
    username     = update.effective_user.username or ""

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
        await update.message.reply_text("✅ Password updated!", reply_markup=admin_menu_keyboard())
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
            await update.message.reply_text("⚠️ Wrong format. Use: `word = meaning`", parse_mode="Markdown")
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
                parse_mode="Markdown",
                reply_markup=admin_menu_keyboard()
            )
        else:
            await update.message.reply_text("⚠️ Wrong format. Use: `Question | Answer`", parse_mode="Markdown")
        return

    if state == "wl_add_id":
        entry = user_message.strip()
        if entry.isdigit():
            whitelist = load_whitelist()
            if entry not in [str(i) for i in whitelist["ids"]]:
                whitelist["ids"].append(entry)
                save_whitelist(whitelist)
                set_admin_state(user_id, "logged_in")
                await update.message.reply_text(
                    f"✅ Telegram ID `{entry}` added to whitelist!",
                    parse_mode="Markdown",
                    reply_markup=admin_menu_keyboard()
                )
            else:
                await update.message.reply_text("ℹ️ This ID is already in the whitelist.")
        else:
            await update.message.reply_text("⚠️ Please send numbers only (Telegram ID).")
        return

    if state == "wl_add_username":
        entry = user_message.strip().lstrip("@").lower()
        whitelist = load_whitelist()
        if entry not in [u.lower() for u in whitelist["usernames"]]:
            whitelist["usernames"].append(entry)
            save_whitelist(whitelist)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(
                f"✅ Username @{entry} added to whitelist!",
                parse_mode="Markdown",
                reply_markup=admin_menu_keyboard()
            )
        else:
            await update.message.reply_text("ℹ️ This username is already in the whitelist.")
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
            await update.message.reply_text(
                f"✅ `{entry}` removed from whitelist.",
                parse_mode="Markdown",
                reply_markup=admin_menu_keyboard()
            )
        else:
            await update.message.reply_text("⚠️ Entry not found in whitelist.")
        return

    # ── WHITELIST CHECK FOR STUDENTS ──
    if str(user_id) != str(ADMIN_ID) and not is_allowed(user_id, username):
        await update.message.reply_text(
            "⛔ Sorry, this bot is currently private.\n\n"
            "Please contact your German tutor to get access."
        )
        return

    # ── STUDENT FLOW ──
    students = load_students()

    if uid_str not in students:
        students[uid_str] = {
            "level": "",
            "name": "",
            "username": username,
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
