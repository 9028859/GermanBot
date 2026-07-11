import os
import json
import random
import pytz
import datetime as dt
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


def esc(text: str) -> str:
    """Escape special Markdown V2 characters in dynamic content."""
    if not text:
        return ""
    return str(text).replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_").replace("`", "\\`").replace("[", "\\[")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
TOKEN          = os.getenv("BOT_TOKEN")
ADMIN_ID       = os.getenv("ADMIN_ID")
ADMIN_PASS     = os.getenv("ADMIN_PASSWORD", "anand2024")
GROUP_ID       = int(os.getenv("GROUP_ID", "-1004485792523"))
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
def load_daily():       return load_json(DAILY_FILE, {"date": "", "words": {}, "attendance": [], "test_results": {}})
def save_daily(d):      save_json(DAILY_FILE, d)
def load_settings():
    return load_json(SETTINGS_FILE, {
        "admin_password": ADMIN_PASS,
        "daily_exercise_time": "06:00",
        "reminders_enabled": True,
    })
def save_settings(d):   save_json(SETTINGS_FILE, d)

# ─────────────────────────────────────────────
# WHITELIST — ALWAYS ON
# ─────────────────────────────────────────────
def is_allowed(user_id: int, username: str) -> bool:
    whitelist = load_whitelist()
    # Convert all IDs to string for safe comparison
    allowed_ids = [str(i).strip() for i in whitelist.get("ids", [])]
    allowed_usernames = [u.lower().strip().lstrip("@") for u in whitelist.get("usernames", [])]
    uid_str = str(user_id).strip()
    # Check by ID
    if uid_str in allowed_ids:
        # Check if frozen
        frozen_until = whitelist.get("frozen", {}).get(uid_str)
        if frozen_until:
            if datetime.now(IST) < datetime.fromisoformat(frozen_until):
                return False
        return True
    # Check by username
    if username and username.lower().strip().lstrip("@") in allowed_usernames:
        return True
    return False

def is_frozen(user_id: int) -> str:
    """Returns freeze expiry string if frozen, else empty string."""
    whitelist = load_whitelist()
    frozen_until = whitelist.get("frozen", {}).get(str(user_id), "")
    if frozen_until:
        if datetime.now(IST) < datetime.fromisoformat(frozen_until):
            return frozen_until
    return ""

# ─────────────────────────────────────────────
# ADMIN SESSION — NEVER EXPIRES UNTIL LOGOUT
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
student_sessions = {}
active_tests     = {}  # uid -> {"questions": [...], "index": int, "score": int, "job": job}
trial_sessions   = {}  # uid -> {"name": str, "actions": int} for non-whitelisted users

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
        s["streak"] = s.get("streak", 0) + 1 if last == yesterday else 1
        s["last_active_date"] = today_str
    s["last_active"] = datetime.now(IST).strftime("%d %b %Y %H:%M")
    students[user_id] = s
    save_students(students)

def add_points(user_id: str, pts: int):
    students = load_students()
    if user_id in students:
        students[user_id]["points"]        = students[user_id].get("points", 0) + pts
        students[user_id]["weekly_points"] = students[user_id].get("weekly_points", 0) + pts
        save_students(students)

# ─────────────────────────────────────────────
# TEST TIME CHECK
# ─────────────────────────────────────────────
def is_test_time() -> bool:
    now = datetime.now(IST)
    start = now.replace(hour=18, minute=0, second=0, microsecond=0)
    end   = now.replace(hour=18, minute=5, second=0, microsecond=0)
    return start <= now <= end

def is_before_test() -> bool:
    return datetime.now(IST).hour < 18

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
        ["🏆 Leaderboard"],
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Student by ID",       callback_data="wl_add_id")],
        [InlineKeyboardButton("➕ Add by Username (@user)", callback_data="wl_add_username")],
        [InlineKeyboardButton("👁 View Whitelist",          callback_data="wl_view")],
        [InlineKeyboardButton("❄️ Freeze Student",          callback_data="wl_freeze")],
        [InlineKeyboardButton("❌ Remove Student",          callback_data="wl_remove")],
        [InlineKeyboardButton("🔙 Back",                    callback_data="adm_back")],
    ])

def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="adm_back")]])

# ─────────────────────────────────────────────
# SCHEDULED JOBS
# ─────────────────────────────────────────────
async def send_daily_vocab(context: ContextTypes.DEFAULT_TYPE):
    """6:00 AM IST — send 10 random words to the group only."""
    database = load_database()
    if not database:
        return
    all_words = list(database.keys())
    chosen    = random.sample(all_words, min(10, len(all_words)))
    daily = {
        "date": date.today().isoformat(),
        "words": {w: database[w] for w in chosen},
        "attendance": [],
        "test_results": {}
    }
    save_daily(daily)
    lines = ["🌅 *Guten Morgen! Good Morning!*\n\n📖 *Today's 10 Vocabulary Words:*\n"]
    for i, word in enumerate(chosen, 1):
        lines.append(f"{i}. *{word}* — {database[word]}")
    lines.append("\n🧪 *Test at 6:00 PM sharp! Only 5 minutes!* ⏱\nKeep studying! 💪")
    try:
        await context.bot.send_message(chat_id=GROUP_ID, text="\n".join(lines), parse_mode="Markdown")
    except Exception:
        pass

async def send_test_to_students(context: ContextTypes.DEFAULT_TYPE):
    """6:00 PM IST — send MCQ test privately to each whitelisted student."""
    daily = load_daily()
    if daily.get("date") != date.today().isoformat() or not daily.get("words"):
        return

    whitelist = load_whitelist()
    allowed_ids = [str(i) for i in whitelist.get("ids", [])]
    students  = load_students()
    words     = daily.get("words", {})
    word_items = list(words.items())

    # Build 10 MCQ questions from today's words
    questions = []
    for word, meaning in word_items:
        # Get 3 wrong options from database
        db = load_database()
        wrong_pool = [v for k, v in db.items() if k != word]
        wrong = random.sample(wrong_pool, min(3, len(wrong_pool)))
        options = wrong + [meaning]
        random.shuffle(options)
        questions.append({
            "word": word,
            "correct": meaning,
            "options": options
        })

    # Send test to each allowed student
    for uid in allowed_ids:
        s = students.get(uid, {})
        if s.get("status") != "active":
            continue
        frozen = is_frozen(int(uid))
        if frozen:
            continue
        try:
            name = s.get("name", "Student")
            await context.bot.send_message(
                chat_id=int(uid),
                text=f"📝 *Hallo {esc(name)}! Your test starts NOW!*\n\n"
                     f"10 questions • 30 seconds each • Total 5 minutes\n\n"
                     f"*Question 1/10:*\n\n"
                     f"🇩🇪 What is the meaning of: *{esc(questions[0]['word'].capitalize())}*?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(opt, callback_data=f"test_{uid}_0_{opt}")]
                    for opt in questions[0]["options"]
                ])
            )
            active_tests[uid] = {
                "questions": questions,
                "index": 0,
                "score": 0,
                "answered": False
            }
        except Exception:
            pass

    # Announce test open in group
    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text="🧪 *Test time! Prüfungszeit!*\n\nCheck your private chat with the bot — your test has started!\n\n⏱ *5 minutes only!*",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    # Schedule auto-close after 5 minutes
    context.job_queue.run_once(close_test, when=310, name="close_test")

async def close_test(context: ContextTypes.DEFAULT_TYPE):
    """Called 5 minutes after test starts — always post attendance to group."""
    students = load_students()
    daily    = load_daily()
    whitelist = load_whitelist()
    allowed_ids = [str(i) for i in whitelist.get("ids", [])]

    # Close any still-active tests and record scores
    for uid, test in list(active_tests.items()):
        score = test.get("score", 0)
        total = len(test.get("questions", []))
        add_points(uid, score * 10)
        students = load_students()
        if uid in students:
            students[uid]["exercises_completed"] = students[uid].get("exercises_completed", 0) + 1
            save_students(students)
        daily.setdefault("test_results", {})[uid] = score
        # Note: attendance already marked when student completed test in callback_handler
        try:
            msg = f"⏱ *Zeit ist um! Time\'s up!*\n\nYour score: *{score}/{total}*\nPoints: *+{score * 10}* ⭐"
            await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode="Markdown")
        except Exception:
            pass

    save_daily(daily)
    active_tests.clear()

    # Reload updated data
    students  = load_students()
    attended  = daily.get("attendance", [])
    results   = daily.get("test_results", {})

    # Build results message — always post even if nobody attended
    lines = ["📊 *Test Attendance Report*\n"]
    
    # Who attended
    if attended:
        lines.append("✅ *Attended:*")
        sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)
        medals = ["🥇","🥈","🥉"]
        for i, (uid, score) in enumerate(sorted_results):
            s     = students.get(str(uid), {})
            name  = s.get("name", "Student")
            total = 10
            medal = medals[i] if i < 3 else "▪️"
            lines.append(f"{medal} *{name}* — {score}/{total} (+{score*10} pts)")
    else:
        lines.append("❌ *No students attended today\'s test!*")

    # Who missed
    absent = []
    for uid in allowed_ids:
        s = students.get(str(uid), {})
        if s.get("status") == "active" and str(uid) not in [str(a) for a in attended]:
            absent.append(s)

    if absent:
        lines.append("\n❌ *Missed the test:*")
        for s in absent:
            username = s.get("username", "")
            name     = s.get("name", "Student")
            lines.append(f"@{username}" if username else f"*{name}*")
        word_list = "\n".join([f"• *{w}* — {m}" for w, m in daily.get("words", {}).items()])
        lines.append(
            f"\n🖊 *Du hast den Test verpasst!*\n"
            f"Write all today\'s words *10 times* and submit before *10:00 PM!*\n\n"
            f"📖 *Today\'s Words:*\n{word_list}"
        )

    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text="\n".join(lines),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Error posting results to group: {e}")


async def send_weekly_winner(context: ContextTypes.DEFAULT_TYPE):
    """Friday 6:00 PM IST — announce top scorer and reset weekly points."""
    students = load_students()
    ranked = sorted(
        [(uid, s.get("name", "?"), s.get("weekly_points", 0))
         for uid, s in students.items() if s.get("status") == "active"],
        key=lambda x: x[2], reverse=True
    )
    if not ranked:
        return

    winner_uid, winner_name, winner_pts = ranked[0]
    username = students.get(winner_uid, {}).get("username", "")
    mention  = f"@{username}" if username else f"*{winner_name}*"

    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=(
                f"🏆 *Weekly Champion! Wochenchampion!*\n\n"
                f"🥇 Congratulations {mention}!\n\n"
                f"You are this week's top scorer with *{winner_pts} points!* 🌟\n\n"
                f"*Herzlichen Glückwunsch!* Keep it up! 💪\n\n"
                f"_Points have been reset for the new week. Good luck everyone!_ 🍀"
            ),
            parse_mode="Markdown"
        )
    except Exception:
        pass

    # Reset weekly points
    for uid in students:
        students[uid]["weekly_points"] = 0
    save_students(students)

# ─────────────────────────────────────────────
# MENTION DETECTION
# ─────────────────────────────────────────────
async def is_bot_mentioned(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    msg = update.message
    try:
        bot_me       = await context.bot.get_me()
        bot_username = (bot_me.username or "").lower()
    except Exception:
        bot_username = ""
    if msg.entities and msg.text:
        for ent in msg.entities:
            if ent.type == "mention":
                mention_text = msg.text[ent.offset:ent.offset + ent.length].lower().lstrip("@")
                if mention_text == bot_username:
                    return True
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.is_bot:
            return True
    return False

PRIVATE_ONLY_KEYWORDS = ["q&a", "vocab", "practice", "leaderboard", "progress", "test", "lernen", "übung", "vokabel"]

# ─────────────────────────────────────────────
# /start COMMAND
# ─────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # In group — only reply to /start with private chat notice
    if update.effective_chat.type in ("group", "supergroup"):
        await update.message.reply_text(
            "🔒 Bitte schreibe mir privat!\n"
            "_(Please open a private chat with me to get started.)_ 📩",
            parse_mode="Markdown"
        )
        return
    user_id  = update.effective_user.id
    uid_str  = str(user_id)
    username = update.effective_user.username or ""
    students = load_students()

    if uid_str in students and students[uid_str].get("status") == "active":
        name = students[uid_str].get("name", "")
        await update.message.reply_text(
            f"Willkommen zurück, *{esc(name)}*! 👋\n\nWas möchtest du tun?",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        return

    if uid_str not in students:
        if str(user_id) != str(ADMIN_ID) and not is_allowed(user_id, username):
            await update.message.reply_text(
                "⛔ Bot usage restricted.\n\nPlease contact *+91 7012098913* to get access.",
                parse_mode="Markdown"
            )
            return
        students[uid_str] = {
            "level": "", "name": "", "username": username,
            "status": "waiting_for_level",
            "points": 0, "weekly_points": 0, "streak": 0, "exercises_completed": 0,
            "joined": datetime.now(IST).strftime("%d %B %Y"),
            "last_active": datetime.now(IST).strftime("%d %b %Y %H:%M"),
            "last_active_date": date.today().isoformat()
        }
        save_students(students)
        await update.message.reply_text(
            "Hallo! 👋 Welcome to *Deutsch Lernen*!\n\nPlease choose your German level:",
            parse_mode="Markdown",
            reply_markup=level_keyboard()
        )

# ─────────────────────────────────────────────
# /administrator COMMAND
# ─────────────────────────────────────────────
async def cmd_administrator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        return
    user_id = update.effective_user.id
    if str(user_id) != str(ADMIN_ID):
        await update.message.reply_text("⛔ You are not authorised.\n\nPlease contact *+91 7012098913*.", parse_mode="Markdown")
        return
    set_admin_state(user_id, "waiting_password")
    await update.message.reply_text(
        "🔐 *Admin Panel*\n\nPlease enter the admin password:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )

async def send_admin_menu(update_or_query, context):
    text = "✅ *Admin Panel*\n\nChoose an option:"
    kb   = admin_menu_keyboard()
    if hasattr(update_or_query, "message") and update_or_query.message:
        await update_or_query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update_or_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

# ─────────────────────────────────────────────
# CALLBACK QUERY HANDLER
# ─────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    user_id   = query.from_user.id
    uid_str   = str(user_id)
    data      = query.data
    chat_type = update.effective_chat.type
    await query.answer()

    # ── GROUP CHAT — complete silence for all button taps ──
    if chat_type in ("group", "supergroup"):
        return

    # ── STUDENT TEST MCQ ANSWER ──
    if data.startswith("test_"):
        parts   = data.split("_", 3)
        t_uid   = parts[1]
        t_index = int(parts[2])
        chosen  = parts[3]

        if t_uid not in active_tests:
            await query.edit_message_text("⏱ Test has already closed.", parse_mode="Markdown")
            return

        test = active_tests[t_uid]
        if test.get("answered"):
            return
        test["answered"] = True

        questions = test["questions"]
        q         = questions[t_index]
        is_correct = chosen.strip().lower() == q["correct"].strip().lower()
        if is_correct:
            test["score"] += 1
            fb = "✅ *Richtig!*"
        else:
            fb = f"❌ *Falsch!*\nCorrect: *{esc(q['correct'])}*"

        next_index = t_index + 1
        test["index"] = next_index

        if next_index >= len(questions):
            # Test done early
            score = test["score"]
            total = len(questions)
            add_points(t_uid, score * 10)
            students = load_students()
            students[t_uid]["exercises_completed"] = students[t_uid].get("exercises_completed", 0) + 1
            save_students(students)
            daily = load_daily()
            if t_uid not in daily.get("attendance", []):
                daily["attendance"].append(t_uid)
            daily.setdefault("test_results", {})[t_uid] = score
            save_daily(daily)
            active_tests.pop(t_uid, None)
            await query.edit_message_text(
                f"{fb}\n\n🎉 *Test Complete!*\nScore: *{score}/{total}* (+{score*10} pts)",
                parse_mode="Markdown"
            )
        else:
            # Next question
            nq = questions[next_index]
            test["answered"] = False
            active_tests[t_uid] = test
            await query.edit_message_text(
                f"{fb}\n\n*Question {next_index+1}/10:*\n\n"
                f"🇩🇪 What is the meaning of: *{esc(nq['word'].capitalize())}*?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(opt, callback_data=f"test_{t_uid}_{next_index}_{opt}")]
                    for opt in nq["options"]
                ])
            )
        return

    # ── STUDENT Q&A MCQ ANSWER ──
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

    # ── ADMIN SESSION CHECK — NEVER EXPIRES ──
    if not is_admin_logged_in(user_id):
        set_admin_state(user_id, "waiting_password")
        try:
            await query.edit_message_text(
                "🔐 *Session ended.*\n\nPlease send your admin password to log in again:",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if data == "adm_back":
        set_admin_state(user_id, "logged_in")
        await query.edit_message_text("✅ *Admin Panel*\n\nChoose an option:", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
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
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("student_"):
        uid      = data[len("student_"):]
        students = load_students()
        s        = students.get(uid, {})
        frozen   = is_frozen(int(uid))
        status   = f"❄️ Frozen till {frozen}" if frozen else "✅ Active"
        text = (
            f"👤 *Name:* {esc(s.get('name','?'))}\n"
            f"🆔 *ID:* `{uid}`\n"
            f"📖 *Level:* {s.get('level','?')}\n"
            f"⭐ *Points:* {s.get('points',0)}\n"
            f"🔥 *Streak:* {s.get('streak',0)} days\n"
            f"📝 *Exercises:* {s.get('exercises_completed',0)}\n"
            f"📅 *Joined:* {s.get('joined','—')}\n"
            f"🕐 *Last Active:* {s.get('last_active','—')}\n"
            f"🔒 *Status:* {status}"
        )
        await query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❄️ Freeze",  callback_data=f"wl_freeze_id_{uid}"),
                 InlineKeyboardButton("❌ Remove",  callback_data=f"wl_remove_id_{uid}")],
                [InlineKeyboardButton("🔙 Back",    callback_data="adm_students")]
            ])
        )
        return

    if data.startswith("wl_freeze_id_"):
        uid = data[len("wl_freeze_id_"):]
        set_admin_state(user_id, "freeze_student", {"uid": uid})
        await query.edit_message_text(
            f"❄️ *Freeze Student*\n\nHow long to freeze `{uid}`?\n\n"
            "Send number of days (e.g. `3`) or a date (e.g. `2026-07-10 18:00`)\n\nSend /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data.startswith("wl_remove_id_"):
        uid = data[len("wl_remove_id_"):]
        whitelist = load_whitelist()
        whitelist["ids"] = [i for i in whitelist["ids"] if str(i) != uid]
        whitelist.get("frozen", {}).pop(uid, None)
        save_whitelist(whitelist)
        await query.edit_message_text(f"✅ Student `{uid}` removed from whitelist.", parse_mode="Markdown", reply_markup=back_keyboard())
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
        attended = len(daily.get("attendance", []))
        total_ex = sum(s.get("exercises_completed", 0) for s in students.values())
        text = (
            f"📊 *Statistics*\n\n"
            f"👥 Total: {len(students)}\n"
            f"A1:{counts['A1']} A2:{counts['A2']} B1:{counts['B1']} B2:{counts['B2']}\n\n"
            f"✅ Active Today: {active_today}\n"
            f"📝 Test Attended Today: {attended}\n"
            f"🏅 Total Exercises: {total_ex}"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=back_keyboard())
        return

    if data == "adm_broadcast":
        set_admin_state(user_id, "broadcast_message")
        await query.edit_message_text("📤 *Broadcast*\n\nType your message.\n\nSend /cancel to abort.", parse_mode="Markdown")
        return

    if data == "adm_whitelist":
        whitelist = load_whitelist()
        frozen    = whitelist.get("frozen", {})
        active_now = datetime.now(IST)
        active_frozen = {k: v for k, v in frozen.items() if datetime.fromisoformat(v) > active_now}
        text = (
            f"🔒 *Whitelist Panel*\n\n"
            f"✅ Allowed IDs: *{len(whitelist.get('ids', []))}*\n"
            f"❄️ Currently Frozen: *{len(active_frozen)}*"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=whitelist_keyboard())
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
        frozen    = whitelist.get("frozen", {})
        students  = load_students()
        lines     = ["🔒 *Whitelist*\n"]
        if ids:
            lines.append("*Students by ID:*")
            for i, tid in enumerate(ids, 1):
                s    = students.get(str(tid), {})
                name = s.get("name", "Unknown")
                f_until = frozen.get(str(tid), "")
                tag  = f" ❄️ till {f_until[:10]}" if f_until else ""
                lines.append(f"{i}. *{name}* — `{tid}`{tag}")
        if usernames:
            lines.append("\n*By Username:*")
            for i, un in enumerate(usernames, 1):
                lines.append(f"{i}. @{un}")
        if not ids and not usernames:
            lines.append("_No students added yet._")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_whitelist")]]))
        return

    if data == "wl_freeze":
        set_admin_state(user_id, "freeze_student_by_id")
        await query.edit_message_text(
            "❄️ *Freeze Student*\n\nSend the Telegram ID of the student to freeze.\n\nSend /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data == "wl_remove":
        set_admin_state(user_id, "wl_remove")
        await query.edit_message_text("❌ Send the Telegram ID or username to remove.\n\nSend /cancel to abort.", parse_mode="Markdown")
        return

    if data == "adm_settings":
        settings = load_settings()
        reminder = "✅ ON" if settings.get("reminders_enabled") else "❌ OFF"
        await query.edit_message_text(f"⚙️ *Settings*\n\n🔔 Reminders: *{reminder}*", parse_mode="Markdown", reply_markup=settings_keyboard())
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
        await query.edit_message_text("📖 *Add Vocabulary*\n\nFormat: `word = meaning`\nExample: `Haus = House`\n\nSend /cancel to abort.", parse_mode="Markdown")
        return

    if data == "set_addexercise":
        set_admin_state(user_id, "add_exercise_level")
        await query.edit_message_text("📝 *Add Exercise* — Choose level:", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("A1", callback_data="exlevel_A1"), InlineKeyboardButton("A2", callback_data="exlevel_A2")],
                [InlineKeyboardButton("B1", callback_data="exlevel_B1"), InlineKeyboardButton("B2", callback_data="exlevel_B2")],
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
        await query.edit_message_text("📄 *Upload PDF*\n\nSend a PDF file. Words should be in `word = meaning` format.\n\nSend /cancel to abort.", parse_mode="Markdown")
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
                    for sep in ["=", "-", "–"]:
                        if sep in line:
                            parts = line.split(sep, 1)
                            word    = parts[0].strip().lower()
                            meaning = parts[1].strip()
                            if word and meaning and len(word) < 40:
                                extracted[word] = meaning
                            break
        if extracted:
            database = load_database()
            database.update(extracted)
            save_json(DB_FILE, database)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(f"✅ *PDF processed!*\n\n{len(extracted)} words added.", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
        else:
            await update.message.reply_text("⚠️ No vocabulary found. Format must be `word = meaning`.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ─────────────────────────────────────────────
# /cancel COMMAND
# ─────────────────────────────────────────────
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group", "supergroup"):
        return
    user_id = update.effective_user.id
    uid_str = str(user_id)
    if is_admin_logged_in(user_id) or admin_state(user_id):
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text("❌ Cancelled.\n\n✅ *Admin Panel*", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
    else:
        set_student_mode(uid_str, "menu")
        await update.message.reply_text("↩️ Back to main menu.", reply_markup=main_menu_keyboard())

# ─────────────────────────────────────────────
# MAIN MESSAGE HANDLER
# ─────────────────────────────────────────────
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip()
    user_id      = update.effective_user.id
    uid_str      = str(user_id)
    username     = update.effective_user.username or ""
    chat_type    = update.effective_chat.type

    # ── GROUP CHAT — COMPLETE SILENCE ──
    # Bot never replies to any message in the group
    # Only scheduled jobs send to group (vocab, results, winner)
    if chat_type in ("group", "supergroup"):
        return

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
        whitelist = load_whitelist()
        students  = load_students()
        sent = 0
        for uid in whitelist.get("ids", []):
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
        await update.message.reply_text(f"✅ Time set to *{user_message}*.", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
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
            await update.message.reply_text(f"✅ Added!\n\n*{esc(word)}* = {esc(meaning)}", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
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
            exercises.append({"level": level, "question": question, "answer": answer, "type": "short"})
            save_exercises(exercises)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(f"✅ Exercise added for *{level}*!", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
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
                await update.message.reply_text(f"✅ ID `{entry}` added to whitelist!", parse_mode="Markdown", reply_markup=admin_menu_keyboard())
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
            whitelist.get("frozen", {}).pop(entry, None)
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

    if state in ("freeze_student", "freeze_student_by_id"):
        stored = admin_sessions[user_id].get("data", {})
        if state == "freeze_student_by_id":
            if not user_message.strip().isdigit():
                await update.message.reply_text("⚠️ Please send a valid Telegram ID (numbers only).")
                return
            stored["uid"] = user_message.strip()
            set_admin_state(user_id, "freeze_student", stored)
            await update.message.reply_text(
                f"❄️ How long to freeze `{stored['uid']}`?\n\nSend number of days (e.g. `3`) or datetime (e.g. `2026-07-10 18:00`)\n\nSend /cancel to abort.",
                parse_mode="Markdown"
            )
            return
        uid_to_freeze = stored.get("uid", "")
        try:
            entry = user_message.strip()
            if entry.isdigit():
                until = datetime.now(IST) + timedelta(days=int(entry))
            else:
                until = IST.localize(datetime.strptime(entry, "%Y-%m-%d %H:%M"))
            whitelist = load_whitelist()
            if "frozen" not in whitelist:
                whitelist["frozen"] = {}
            whitelist["frozen"][uid_to_freeze] = until.isoformat()
            save_whitelist(whitelist)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(
                f"❄️ Student `{uid_to_freeze}` frozen until *{until.strftime('%d %b %Y %H:%M')}*",
                parse_mode="Markdown",
                reply_markup=admin_menu_keyboard()
            )
        except Exception:
            await update.message.reply_text("⚠️ Invalid format. Send days (e.g. `3`) or `2026-07-10 18:00`")
        return

    # ── STUDENT REGISTRATION ──
    students = load_students()

    # ── WHITELIST & TRIAL CHECK ──
    if str(user_id) != str(ADMIN_ID):
        already_registered = uid_str in students and students[uid_str].get("status") == "active"
        if not already_registered and not is_allowed(user_id, username):
            # Not whitelisted — handle trial
            trial = trial_sessions.get(uid_str)

            # Step 1: Ask name if first time
            if not trial:
                trial_sessions[uid_str] = {"name": "", "actions": 0, "asking_name": True}
                await update.message.reply_text(
                    "Hallo! 👋 Ich bin der Deutsche Lern-Bot der *Deutsch Lernen Company!*\n\n"
                    "Wie heißt du? *What is your name?*",
                    parse_mode="Markdown",
                    reply_markup=ReplyKeyboardRemove()
                )
                return

            # Step 2: Save name if asking
            if trial.get("asking_name"):
                trial["name"] = user_message
                trial["asking_name"] = False
                trial_sessions[uid_str] = trial
                await update.message.reply_text(
                    f"Willkommen, *{esc(user_message)}*! 🎉\n\n"
                    f"You have *3 free tries!*\n\n"
                    f"📖 Vocabulary Practice and ❓ Q&A are available for you to try!",
                    parse_mode="Markdown",
                    reply_markup=ReplyKeyboardMarkup([
                        ["📖 Vocabulary Practice", "❓ Q&A"],
                    ], resize_keyboard=True)
                )
                return

            # Step 3: Block restricted buttons for trial users
            if any(kw in user_message for kw in ["Today's Test", "Leaderboard", "My Progress", "📝", "🏆", "📊"]):
                await update.message.reply_text(
                    f"⛔ This feature is only available for enrolled students.\n\n"
                    f"Please contact *+91 7012098913* to join!",
                    parse_mode="Markdown"
                )
                return

            # Step 4: Check if trial exhausted
            if trial.get("actions", 0) >= 3:
                await update.message.reply_text(
                    f"Hallo *{esc(trial.get('name', ''))}*! 👋\n\n"
                    f"You have used all *3 free tries!* 🎓\n\n"
                    f"To continue learning German with us, please contact your tutor:\n"
                    f"📞 *+91 7012098913*\n\n"
                    f"Mention your name and we will activate your account! 😊",
                    parse_mode="Markdown",
                    reply_markup=ReplyKeyboardRemove()
                )
                return

            # Step 5: Allow action and increment counter
            trial["actions"] = trial.get("actions", 0) + 1
            trial_sessions[uid_str] = trial
            remaining = 3 - trial["actions"]
            if remaining == 0:
                pass  # Will show exhausted message next time
            # Continue to handle the actual message below
        frozen = is_frozen(user_id)
        if frozen:
            await update.message.reply_text(
                f"❄️ Your access is temporarily suspended.\n\nPlease contact *+91 7012098913*.",
                parse_mode="Markdown"
            )
            return

    if uid_str not in students:
        students[uid_str] = {
            "level": "", "name": "", "username": username,
            "status": "waiting_for_level",
            "points": 0, "weekly_points": 0, "streak": 0, "exercises_completed": 0,
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
            f"Willkommen, *{esc(user_message)}*! 🎉\n\nLevel: *{esc(student['level'])}*\n\nHere is your menu 👇",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
        return

    # ── ACTIVE STUDENT ──
    touch_student(uid_str)
    mode = student_mode(uid_str)

    if "Cancel" in user_message or user_message == "❌ Cancel":
        set_student_mode(uid_str, "menu")
        await update.message.reply_text("↩️ Back to main menu.", reply_markup=main_menu_keyboard())
        return

    # ── VOCABULARY PRACTICE ──
    if "Vocabulary Practice" in user_message or user_message == "📖 Vocabulary Practice":
        database = load_database()
        if not database:
            await update.message.reply_text("No vocabulary yet!", reply_markup=main_menu_keyboard())
            return
        word, meaning = random.choice(list(database.items()))
        set_student_mode(uid_str, "vocab_quiz", {"word": word, "meaning": meaning})
        await update.message.reply_text(
            f"📖 *Vocabulary Practice*\n\nWhat is the meaning of:\n\n🇩🇪 *{esc(word.capitalize())}*\n\nType your answer!\n\n_(Tap ❌ Cancel to stop)_",
            parse_mode="Markdown", reply_markup=cancel_keyboard()
        )
        return

    if mode == "vocab_quiz":
        data     = student_data(uid_str)
        meaning  = data.get("meaning", "").lower()
        answer   = user_message.lower().strip()
        database = load_database()
        if answer in meaning or meaning in answer:
            add_points(uid_str, 5)
            students = load_students()
            students[uid_str]["exercises_completed"] = students[uid_str].get("exercises_completed", 0) + 1
            save_students(students)
            new_word, new_meaning = random.choice(list(database.items()))
            set_student_mode(uid_str, "vocab_quiz", {"word": new_word, "meaning": new_meaning})
            await update.message.reply_text(
                f"✅ *Richtig!* +5 points 🌟\n\nNext:\n\n🇩🇪 *{esc(new_word.capitalize())}*\n\nType the meaning!",
                parse_mode="Markdown", reply_markup=cancel_keyboard()
            )
        else:
            new_word, new_meaning = random.choice(list(database.items()))
            set_student_mode(uid_str, "vocab_quiz", {"word": new_word, "meaning": new_meaning})
            await update.message.reply_text(
                f"❌ *Falsch!*\nCorrect: *{esc(data.get('meaning',''))}*\n\nNext:\n\n🇩🇪 *{esc(new_word.capitalize())}*\n\nType the meaning!",
                parse_mode="Markdown", reply_markup=cancel_keyboard()
            )
        return

    # ── Q&A ──
    if "Q&A" in user_message or user_message == "❓ Q&A":
        level     = student.get("level", "A1")
        exercises = [e for e in load_exercises() if e.get("level") == level]
        if not exercises:
            await update.message.reply_text("No questions available yet!", reply_markup=main_menu_keyboard())
            return
        q = random.choice(exercises)
        set_student_mode(uid_str, "qna", {"question": q})
        if q.get("type") == "mcq":
            opts = q.get("options", [])
            await update.message.reply_text(
                f"❓ *Q&A ({level})*\n\n{q['question']}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"qna_{opt}")] for opt in opts])
            )
        else:
            await update.message.reply_text(
                f"❓ *Q&A ({level})*\n\n{q['question']}\n\n_Type your answer!_",
                parse_mode="Markdown", reply_markup=cancel_keyboard()
            )
        return

    if mode == "qna":
        data    = student_data(uid_str)
        q       = data.get("question", {})
        if q.get("type") == "short":
            correct    = q.get("answer", "").lower()
            answer     = user_message.lower().strip()
            is_correct = answer in correct or correct in answer
            if is_correct:
                add_points(uid_str, 5)
                students = load_students()
                students[uid_str]["exercises_completed"] = students[uid_str].get("exercises_completed", 0) + 1
                save_students(students)
                fb = "✅ *Richtig!* +5 points 🌟"
            else:
                fb = f"❌ *Falsch!*\n\nCorrect: *{esc(q.get('answer',''))}*"
            set_student_mode(uid_str, "menu")
            await update.message.reply_text(f"{fb}\n\nTap ❓ Q&A again!", parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return

    # ── TODAY'S TEST ──
    if "Today's Test" in user_message or user_message == "📝 Today's Test":
        daily = load_daily()
        today = date.today().isoformat()
        if daily.get("date") != today or not daily.get("words"):
            await update.message.reply_text("📭 No test today yet.\n\nWait for 6:00 AM vocab! 🌅", reply_markup=main_menu_keyboard())
            return
        if uid_str in daily.get("attendance", []):
            await update.message.reply_text("✅ You already completed today's test! 🎉\n\nCome back tomorrow!", reply_markup=main_menu_keyboard())
            return
        if is_before_test():
            await update.message.reply_text("⏰ *There's still time for the test.\nKeep studying child!* 📚\n\nTest opens at *6:00 PM* sharp!", parse_mode="Markdown", reply_markup=main_menu_keyboard())
            return
        if is_after_test():
            await update.message.reply_text("⌛ *Continue learning and wait for the next test.* 💪\n\nNew vocab tomorrow at *6:00 AM*! 🌅", parse_mode="Markdown", reply_markup=main_menu_keyboard())
            return
        if uid_str in active_tests:
            await update.message.reply_text("📝 Your test is already running! Check the question above. ⬆️", reply_markup=cancel_keyboard())
        else:
            await update.message.reply_text("📝 Your test will be sent to you shortly!\n\nPlease wait... ⏱", reply_markup=main_menu_keyboard())
        return

    # ── MY PROGRESS ──
    if "My Progress" in user_message or user_message == "📊 My Progress":
        students = load_students()
        s = students.get(uid_str, {})
        daily = load_daily()
        attended = "✅ Yes" if uid_str in daily.get("attendance", []) else "❌ No"
        await update.message.reply_text(
            f"📊 *My Progress*\n\n"
            f"👤 *Name:* {esc(s.get('name','?'))}\n"
            f"📖 *Level:* {s.get('level','?')}\n"
            f"⭐ *Total Points:* {s.get('points',0)}\n"
            f"🏅 *Weekly Points:* {s.get('weekly_points',0)}\n"
            f"🔥 *Streak:* {s.get('streak',0)} days\n"
            f"📝 *Exercises Done:* {s.get('exercises_completed',0)}\n"
            f"📅 *Joined:* {s.get('joined','—')}\n"
            f"🧪 *Today's Test:* {attended}",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()
        )
        return

    # ── LEADERBOARD ──
    if "Leaderboard" in user_message or user_message == "🏆 Leaderboard":
        students = load_students()
        ranked = sorted(
            [(s.get("name","?"), s.get("weekly_points",0), s.get("points",0))
             for s in students.values() if s.get("status")=="active"],
            key=lambda x: x[1], reverse=True
        )
        lines = ["🏆 *Weekly Leaderboard*\n"]
        medals = ["🥇","🥈","🥉"]
        for i, (name, wpts, tpts) in enumerate(ranked[:10], 0):
            medal = medals[i] if i < 3 else f"{i+1}."
            lines.append(f"{medal} *{name}* — {wpts} pts this week")
        if not ranked:
            lines.append("No students yet!")
        lines.append(f"\n_Resets every Friday at 6:00 PM_ 🗓")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return

    # Outside any active mode — stay silent in private too
    return

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()

    jq  = app.job_queue
    ist = pytz.timezone("Asia/Kolkata")

    # 6:00 AM IST — daily vocab to group
    jq.run_daily(send_daily_vocab,    time=dt.time(6,  0, 0, tzinfo=ist))
    # 6:00 PM IST — send MCQ test privately to all students
    jq.run_daily(send_test_to_students, time=dt.time(18, 0, 0, tzinfo=ist))
    # Friday 6:00 PM IST — weekly winner announcement
    jq.run_daily(send_weekly_winner,  time=dt.time(18, 0, 0, tzinfo=ist), days=(5,))  # 5 = Friday

    # Handlers — group blocking is done inside each function
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("administrator", cmd_administrator))
    app.add_handler(CommandHandler("cancel",        cmd_cancel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.Document.PDF, pdf_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

    print("Bot started...")
    print(f"Job queue: {app.job_queue}")
    print(f"Jobs scheduled: {len(app.job_queue.jobs())}")
    app.run_polling()

if __name__ == "__main__":
    main()
