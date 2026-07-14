import os
import json
import random
import pytz
import re
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

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
TOKEN      = os.getenv("BOT_TOKEN")
ADMIN_ID   = os.getenv("ADMIN_ID")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "anand2024")
GROUP_ID   = int(os.getenv("GROUP_ID", "-1004485792523"))
IST        = pytz.timezone("Asia/Kolkata")

# Files
DB_FILE        = "database.json"
STUDENTS_FILE  = "students.json"
EXERCISES_FILE = "exercises.json"
SETTINGS_FILE  = "settings.json"
WHITELIST_FILE = "whitelist.json"
DAILY_FILE     = "daily.json"
TRIAL_FILE     = "trials.json"

# ─────────────────────────────────────────────
# HELPERS
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

def load_students():  return load_json(STUDENTS_FILE, {})
def save_students(d): save_json(STUDENTS_FILE, d)
def load_database():  return load_json(DB_FILE, {})
def save_database(d): save_json(DB_FILE, d)
def load_exercises(): return load_json(EXERCISES_FILE, [])
def save_exercises(d):save_json(EXERCISES_FILE, d)
def load_whitelist(): return load_json(WHITELIST_FILE, {"ids": [], "usernames": [], "frozen": {}})
def save_whitelist(d):save_json(WHITELIST_FILE, d)
def load_daily():     return load_json(DAILY_FILE, {"date": "", "words": {}, "attendance": [], "test_results": {}, "word_index": 0})
def save_daily(d):    save_json(DAILY_FILE, d)
def load_settings():  return load_json(SETTINGS_FILE, {"admin_password": ADMIN_PASS, "reminders_enabled": True})
def save_settings(d): save_json(SETTINGS_FILE, d)
def load_trials():    return load_json(TRIAL_FILE, {})
def save_trials(d):   save_json(TRIAL_FILE, d)

def esc(text: str) -> str:
    if not text:
        return ""
    return str(text).replace("*","").replace("_","").replace("`","").replace("[","")

def get_question(level: str) -> dict:
    """Get a random question for a level — fast single call."""
    exercises = load_exercises()
    pool = [e for e in exercises if e.get("level") == level]
    if not pool:
        return {}
    return random.choice(pool)

def extract_name(text: str) -> str:
    """Extract just the first name from various formats."""
    text = text.strip()
    patterns = [
        r"(?:my name is|i am|i'm|ich bin|mein name ist)\s+([a-zA-ZÄäÖöÜüß]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).capitalize()
    # If no pattern matches, take the first word
    words = text.split()
    if words:
        return words[0].capitalize()
    return text.capitalize()

# ─────────────────────────────────────────────
# WHITELIST & ACCESS
# ─────────────────────────────────────────────
def is_whitelisted(user_id: int, username: str = "") -> bool:
    wl = load_whitelist()
    ids = [str(i).strip() for i in wl.get("ids", [])]
    uns = [u.lower().strip().lstrip("@") for u in wl.get("usernames", [])]
    if str(user_id) in ids:
        frozen = wl.get("frozen", {}).get(str(user_id), "")
        if frozen:
            try:
                if datetime.now(IST) < datetime.fromisoformat(frozen):
                    return False
            except Exception:
                pass
        return True
    if username and username.lower().lstrip("@") in uns:
        return True
    return False

def is_frozen(user_id: int) -> str:
    wl = load_whitelist()
    until = wl.get("frozen", {}).get(str(user_id), "")
    if until:
        try:
            if datetime.now(IST) < datetime.fromisoformat(until):
                return until
        except Exception:
            pass
    return ""

def is_admin(user_id) -> bool:
    return str(user_id) == str(ADMIN_ID)

# ─────────────────────────────────────────────
# SESSION STORES (in-memory)
# ─────────────────────────────────────────────
admin_sessions  = {}  # user_id -> {state, data}
student_sessions= {}  # uid_str -> {mode, data}
active_tests    = {}  # uid_str -> {questions, index, score, answered}

def admin_state(uid): return admin_sessions.get(uid, {}).get("state", "")
def set_admin_state(uid, state, data=None):
    admin_sessions[uid] = {"state": state, "data": data or {}}
def clear_admin(uid): admin_sessions.pop(uid, None)
def is_admin_logged_in(uid): return admin_sessions.get(uid, {}).get("state") == "logged_in"

def s_mode(uid): return student_sessions.get(uid, {}).get("mode", "menu")
def set_s_mode(uid, mode, data=None): student_sessions[uid] = {"mode": mode, "data": data or {}}
def s_data(uid): return student_sessions.get(uid, {}).get("data", {})

# ─────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────
MAIN_KB    = ReplyKeyboardMarkup([["📖 Vocabulary Practice","❓ Q&A"],["📝 Today's Test","📊 My Progress"],["🏆 Leaderboard"]], resize_keyboard=True)
TRIAL_KB   = ReplyKeyboardMarkup([["📖 Vocabulary Practice","❓ Q&A"]], resize_keyboard=True)
LEVEL_KB   = ReplyKeyboardMarkup([["A1","A2"],["B1","B2"]], resize_keyboard=True)
CANCEL_KB  = ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
BACK_KB    = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="adm_back")]])

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Students",  callback_data="adm_students")],
        [InlineKeyboardButton("📊 Statistics",callback_data="adm_stats")],
        [InlineKeyboardButton("📤 Broadcast", callback_data="adm_broadcast")],
        [InlineKeyboardButton("🔒 Whitelist", callback_data="adm_whitelist")],
        [InlineKeyboardButton("⚙️ Settings",  callback_data="adm_settings")],
        [InlineKeyboardButton("🚪 Logout",    callback_data="adm_logout")],
    ])

def settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Change Password",    callback_data="set_password")],
        [InlineKeyboardButton("🔔 Toggle Reminders",   callback_data="set_reminders")],
        [InlineKeyboardButton("➕ Add Vocabulary",     callback_data="set_addvocab")],
        [InlineKeyboardButton("📝 Add Exercise",       callback_data="set_addexercise")],
        [InlineKeyboardButton("📄 Upload PDF Vocab",   callback_data="set_uploadpdf")],
        [InlineKeyboardButton("🔙 Back",               callback_data="adm_back")],
    ])

def whitelist_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add by Telegram ID",      callback_data="wl_add_id")],
        [InlineKeyboardButton("➕ Add by Username",         callback_data="wl_add_username")],
        [InlineKeyboardButton("👁 View Students",           callback_data="wl_view")],
        [InlineKeyboardButton("❄️ Freeze Student",          callback_data="wl_freeze")],
        [InlineKeyboardButton("❌ Remove Student",          callback_data="wl_remove")],
        [InlineKeyboardButton("🔙 Back",                    callback_data="adm_back")],
    ])

# ─────────────────────────────────────────────
# STUDENT HELPERS
# ─────────────────────────────────────────────
def touch_student(uid: str):
    students = load_students()
    if uid not in students: return
    s = students[uid]
    today = date.today().isoformat()
    last  = s.get("last_active_date","")
    if last != today:
        yesterday = (date.today()-timedelta(days=1)).isoformat()
        s["streak"] = s.get("streak",0)+1 if last==yesterday else 1
        s["last_active_date"] = today
    s["last_active"] = datetime.now(IST).strftime("%d %b %Y %H:%M")
    students[uid] = s
    save_students(students)

def add_points(uid: str, pts: int):
    students = load_students()
    if uid in students:
        students[uid]["points"]        = students[uid].get("points",0) + pts
        students[uid]["weekly_points"] = students[uid].get("weekly_points",0) + pts
        save_students(students)

def check_low_score(uid: str):
    """Notify admin if student scores below 6/10 for 3 consecutive tests."""
    students = load_students()
    s = students.get(uid, {})
    recent = s.get("recent_scores", [])
    if len(recent) >= 3 and all(score < 6 for score in recent[-3:]):
        return True
    return False

# ─────────────────────────────────────────────
# TEST TIME
# ─────────────────────────────────────────────
def test_is_open():
    now = datetime.now(IST)
    start = now.replace(hour=19, minute=0, second=0, microsecond=0)
    end   = now.replace(hour=19, minute=5, second=0, microsecond=0)
    return start <= now <= end

def test_not_started():
    return datetime.now(IST).hour < 19

def test_already_closed():
    now = datetime.now(IST)
    return now >= now.replace(hour=19, minute=5, second=0, microsecond=0)

# ─────────────────────────────────────────────
# SCHEDULED JOBS
# ─────────────────────────────────────────────
async def job_daily_vocab(context: ContextTypes.DEFAULT_TYPE):
    """6:00 AM IST — post 10 vocab words to group."""
    db = load_database()
    if not db:
        return
    daily = load_daily()
    all_words = list(db.keys())
    total     = len(all_words)
    idx       = daily.get("word_index", 0) % total
    chosen    = []
    for i in range(min(10, total)):
        chosen.append(all_words[(idx + i) % total])
    new_index = (idx + 10) % total
    daily = {
        "date"       : date.today().isoformat(),
        "words"      : {w: db[w] for w in chosen},
        "attendance" : [],
        "test_results": {},
        "word_index" : new_index
    }
    save_daily(daily)
    lines = ["🌅 *Guten Morgen\\! Good Morning\\!*\n\n📖 *Today\\'s 10 Vocabulary Words:*\n"]
    for i, w in enumerate(chosen, 1):
        lines.append(f"{i}\\. *{esc(w)}* — {esc(db[w])}")
    lines.append("\n🧪 *Test at 7:00 PM sharp\\! Only 5 minutes\\!* ⏱\n📚 Keep studying\\!")
    try:
        await context.bot.send_message(chat_id=GROUP_ID, text="\n".join(lines), parse_mode="MarkdownV2")
    except Exception as e:
        print(f"Vocab send error: {e}")

async def job_test_announcement(context: ContextTypes.DEFAULT_TYPE):
    """7:00 PM IST — announce test in group and send MCQ to all students."""
    daily = load_daily()
    if daily.get("date") != date.today().isoformat() or not daily.get("words"):
        return
    # Group announcement
    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=(
                "🇩🇪 *Es ist Zeit für den heutigen Test\\!*\n\n"
                "📩 Schau in deine privaten Nachrichten\\.\n\n"
                "⏰ Du hast nur *5 Minuten*\\."
            ),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        print(f"Test announcement error: {e}")
    # Send MCQ privately to each whitelisted student
    wl       = load_whitelist()
    students = load_students()
    words    = daily.get("words", {})
    db       = load_database()
    word_items = list(words.items())
    # Build questions
    questions = []
    for word, meaning in word_items:
        wrong_pool = [v for k, v in db.items() if k != word]
        if len(wrong_pool) < 3:
            continue
        wrong   = random.sample(wrong_pool, 3)
        options = wrong + [meaning]
        random.shuffle(options)
        questions.append({"word": word, "correct": meaning, "options": options})
    if not questions:
        return
    random.shuffle(questions)
    questions = questions[:10]

    for uid in [str(i) for i in wl.get("ids", [])]:
        s = students.get(uid, {})
        if s.get("status") != "active":
            continue
        if is_frozen(int(uid)):
            continue
        try:
            name = esc(s.get("name", "Student"))
            q    = questions[0]
            await context.bot.send_message(
                chat_id=int(uid),
                text=(
                    f"📝 *Hallo {name}\\! Dein Test beginnt jetzt\\!*\n\n"
                    f"10 Fragen • 30 Sekunden pro Frage\n\n"
                    f"*Frage 1/10:*\n\n"
                    f"🇩🇪 Was bedeutet: *{esc(q['word'].capitalize())}*?"
                ),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(opt, callback_data=f"test_{uid}_0_{opt}")]
                    for opt in q["options"]
                ])
            )
            active_tests[uid] = {"questions": questions, "index": 0, "score": 0, "answered": False}
        except Exception as e:
            print(f"Test send error for {uid}: {e}")
    # Schedule auto-close
    context.job_queue.run_once(job_close_test, when=305, name="close_test")

async def job_close_test(context: ContextTypes.DEFAULT_TYPE):
    """7:05 PM IST — close all tests and post attendance."""
    students = load_students()
    daily    = load_daily()
    wl       = load_whitelist()
    allowed  = [str(i) for i in wl.get("ids", [])]

    # Finalize any still-open tests
    for uid, test in list(active_tests.items()):
        score = test.get("score", 0)
        total = len(test.get("questions", []))
        add_points(uid, score * 10)
        students = load_students()
        if uid in students:
            # Update recent scores for low score monitoring
            recent = students[uid].get("recent_scores", [])
            recent.append(score)
            students[uid]["recent_scores"] = recent[-5:]
            students[uid]["exercises_completed"] = students[uid].get("exercises_completed", 0) + 1
            save_students(students)
        if uid not in daily.get("attendance", []):
            daily["attendance"].append(uid)
        daily.setdefault("test_results", {})[uid] = score
        # Check low score
        if check_low_score(uid):
            try:
                name = students.get(uid, {}).get("name", "A student")
                await context.bot.send_message(
                    chat_id=int(ADMIN_ID),
                    text=f"⚠️ *Low Score Alert*\n\n{esc(name)} has scored below 6/10 for 3 consecutive tests.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        try:
            s     = students.get(uid, {})
            name  = esc(s.get("name", "Student"))
            # Calculate rank
            all_results = daily.get("test_results", {})
            rank = sum(1 for v in all_results.values() if v > score) + 1
            msg = (
                f"⏱ *Zeit ist um\\!*\n\n"
                f"✅ Richtig: *{score}/{total}*\n"
                f"🏅 Punkte: *\\+{score * 10}*\n"
                f"📊 Rang: *\\#{rank}*\n\n"
            )
            if score == total:
                msg += "🌟 *Ausgezeichnet\\! Perfect score\\!*"
            elif score >= 7:
                msg += "👍 *Sehr gut\\! Well done\\!*"
            elif score >= 5:
                msg += "📚 *Gut gemacht\\! Keep practicing\\!*"
            else:
                msg += "💪 *Weiter üben\\! Keep going\\!*"
            await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode="MarkdownV2")
        except Exception:
            pass

    save_daily(daily)
    active_tests.clear()
    students = load_students()

    # Post attendance to group
    attended = daily.get("attendance", [])
    absent   = [uid for uid in allowed if uid not in attended and students.get(uid, {}).get("status") == "active"]
    present  = [uid for uid in allowed if uid in attended and students.get(uid, {}).get("status") == "active"]

    lines = ["📋 *Heutige Anwesenheit \\| Today\\'s Attendance*\n"]
    if present:
        lines.append(f"✅ *Anwesend \\| Present: {len(present)}*")
    if absent:
        lines.append(f"❌ *Abwesend \\| Absent: {len(absent)}*")
    try:
        await context.bot.send_message(chat_id=GROUP_ID, text="\n".join(lines), parse_mode="MarkdownV2")
    except Exception:
        pass

    # Imposition for absent students
    if absent:
        daily_words = daily.get("words", {})
        word_list   = "\n".join([f"• {esc(w)} — {esc(m)}" for w, m in daily_words.items()])
        for uid in absent:
            s        = students.get(uid, {})
            username = s.get("username", "")
            name     = esc(s.get("name", "Student"))
            mention  = f"@{username}" if username else f"*{name}*"
            try:
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=(
                        f"{mention}\n\n"
                        f"Du hast den heutigen Vokabeltest verpasst\\!\n"
                        f"*You missed today\\'s vocabulary test\\.*\n\n"
                        f"📝 Bitte schreibe die 10 heutigen Wörter je *10 Mal* ab\\.\n"
                        f"*Please write today\\'s 10 words 10 times each\\.*\n\n"
                        f"📖 *Today\\'s Words:*\n{word_list}\n\n"
                        f"📤 Sende deine Arbeit vor *22:00 Uhr* in die Gruppe\\.\n"
                        f"*Submit your work before 10:00 PM\\.*"
                    ),
                    parse_mode="MarkdownV2"
                )
            except Exception:
                pass

async def job_weekly_winner(context: ContextTypes.DEFAULT_TYPE):
    """Friday 6:00 PM IST — announce weekly winner and reset weekly points."""
    students = load_students()
    ranked = sorted(
        [(uid, s.get("name","?"), s.get("weekly_points",0), s.get("attendance_count",0))
         for uid, s in students.items() if s.get("status") == "active"],
        key=lambda x: (x[2], x[3]), reverse=True
    )
    if not ranked:
        return
    winner_uid, winner_name, winner_pts, _ = ranked[0]
    username = students.get(winner_uid, {}).get("username", "")
    mention  = f"@{username}" if username else f"*{esc(winner_name)}*"
    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=(
                f"🏆 *Wochenchampion\\! Weekly Champion\\!*\n\n"
                f"🥇 Herzlichen Glückwunsch {mention}\\!\n\n"
                f"Du bist der Wochenchampion mit *{winner_pts} Punkten\\!* 🌟\n\n"
                f"_Alle Wochenpunkte werden jetzt zurückgesetzt\\._\n"
                f"_Weekly points have been reset\\. Good luck everyone\\!_ 🍀"
            ),
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        print(f"Weekly winner error: {e}")
    # Reset weekly points
    for uid in students:
        students[uid]["weekly_points"] = 0
    save_students(students)

# ─────────────────────────────────────────────
# /start COMMAND
# ─────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group","supergroup"):
        return
    user_id  = update.effective_user.id
    uid      = str(user_id)
    username = update.effective_user.username or ""
    students = load_students()

    if is_admin(user_id):
        await update.message.reply_text("Welcome back Admin! Use /administrator to access the panel.")
        return

    # Whitelisted — check if already registered
    if is_whitelisted(user_id, username):
        # Clear any trial session
        trials = load_trials()
        if uid in trials:
            trials.pop(uid)
            save_trials(trials)
        if uid in students and students[uid].get("status") == "active":
            name = esc(students[uid].get("name",""))
            await update.message.reply_text(
                f"Willkommen zurück, *{name}*! 👋\n\nWas möchtest du tun?",
                parse_mode="Markdown",
                reply_markup=MAIN_KB
            )
        else:
            # New whitelisted student — start profile setup
            set_s_mode(uid, "setup_name")
            await update.message.reply_text(
                "Hallo! 👋 Willkommen bei *Deutsch Lernen*!\n\nWie heißt du? *What is your name?*",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove()
            )
        return

    # Trial user
    trials = load_trials()
    trial  = trials.get(uid, {})
    if not trial:
        set_s_mode(uid, "trial_name")
        await update.message.reply_text(
            "Hallo! 👋 Ich bin der Deutsche Lern-Bot der *Deutsch Lernen Company!*\n\n"
            "Wie heißt du? *What is your name?*",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
    elif trial.get("sessions_used", 0) >= 3:
        name = esc(trial.get("name",""))
        await update.message.reply_text(
            f"Hallo *{name}*! 👋\n\n"
            "Your free trial has ended. 🎓\n\n"
            "To continue learning German, please contact:\n"
            "📞 *+91 7012098913*\n\n"
            "Mention your name and we will activate your account!",
            parse_mode="Markdown"
        )
    else:
        name = esc(trial.get("name",""))
        used = trial.get("sessions_used", 0)
        remaining = 3 - used
        await update.message.reply_text(
            f"Willkommen zurück, *{name}*! 👋\n\n"
            f"You have *{remaining} free trial session(s)* remaining.\n\n"
            "👇 Choose what you'd like to try:",
            parse_mode="Markdown",
            reply_markup=TRIAL_KB
        )

# ─────────────────────────────────────────────
# /administrator COMMAND
# ─────────────────────────────────────────────
async def cmd_administrator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group","supergroup"):
        return
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ You are not authorised.\n\nPlease contact *+91 7012098913*.",
            parse_mode="Markdown"
        )
        return
    set_admin_state(user_id, "waiting_password")
    await update.message.reply_text(
        "🔐 *Admin Panel*\n\nPlease enter your password:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ("group","supergroup"):
        return
    user_id = update.effective_user.id
    uid     = str(user_id)
    if is_admin_logged_in(user_id) or admin_state(user_id):
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text("❌ Cancelled.", reply_markup=admin_kb())
    else:
        set_s_mode(uid, "menu")
        students = load_students()
        if uid in students and students[uid].get("status") == "active":
            await update.message.reply_text("↩️ Back to main menu.", reply_markup=MAIN_KB)
        else:
            trials = load_trials()
            if uid in trials:
                await update.message.reply_text("↩️ Back.", reply_markup=TRIAL_KB)

async def send_admin_menu(target, context, text="✅ *Admin Panel*\n\nChoose an option:"):
    kb = admin_kb()
    if hasattr(target, "message") and target.message:
        await target.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await target.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

# ─────────────────────────────────────────────
# CALLBACK HANDLER
# ─────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    user_id   = query.from_user.id
    uid       = str(user_id)
    data      = query.data
    chat_type = update.effective_chat.type
    await query.answer()

    # Ignore all group callbacks
    if chat_type in ("group","supergroup"):
        return

    # ── TEST ANSWER ──
    if data.startswith("test_"):
        parts   = data.split("_", 3)
        t_uid   = parts[1]
        t_index = int(parts[2])
        chosen  = parts[3]
        if t_uid not in active_tests:
            await query.edit_message_text("⏱ Test has already closed.")
            return
        test = active_tests[t_uid]
        if test.get("answered"):
            return
        test["answered"] = True
        q          = test["questions"][t_index]
        is_correct = chosen.strip().lower() == q["correct"].strip().lower()
        if is_correct:
            test["score"] += 1
            fb = "✅ *Richtig\\!*"
        else:
            fb = f"❌ *Falsch\\!*\nRichtig: *{esc(q['correct'])}*"
        next_index = t_index + 1
        test["index"] = next_index
        if next_index >= len(test["questions"]):
            score = test["score"]
            total = len(test["questions"])
            add_points(t_uid, score * 10)
            students = load_students()
            if t_uid in students:
                recent = students[t_uid].get("recent_scores", [])
                recent.append(score)
                students[t_uid]["recent_scores"] = recent[-5:]
                students[t_uid]["exercises_completed"] = students[t_uid].get("exercises_completed",0)+1
                save_students(students)
            daily = load_daily()
            if t_uid not in daily.get("attendance",[]):
                daily["attendance"].append(t_uid)
            daily.setdefault("test_results",{})[t_uid] = score
            save_daily(daily)
            active_tests.pop(t_uid, None)
            if check_low_score(t_uid):
                try:
                    name = students.get(t_uid,{}).get("name","A student")
                    await context.bot.send_message(
                        chat_id=int(ADMIN_ID),
                        text=f"⚠️ *Low Score Alert*\n\n{esc(name)} has scored below 6/10 for 3 consecutive tests.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            await query.edit_message_text(
                f"{fb}\n\n🎉 *Test abgeschlossen\\!*\nScore: *{score}/{total}* \\(\\+{score*10} Punkte\\)",
                parse_mode="MarkdownV2"
            )
        else:
            nq = test["questions"][next_index]
            test["answered"] = False
            active_tests[t_uid] = test
            await query.edit_message_text(
                f"{fb}\n\n*Frage {next_index+1}/10:*\n\n🇩🇪 Was bedeutet: *{esc(nq['word'].capitalize())}*?",
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(opt, callback_data=f"test_{t_uid}_{next_index}_{opt}")]
                    for opt in nq["options"]
                ])
            )
        return

    # ── Q&A MCQ ANSWER ──
    if data.startswith("qna_"):
        chosen  = data[len("qna_"):]
        sd      = s_data(uid)
        q       = sd.get("question", {})
        correct = q.get("answer","")
        is_correct = chosen.strip().lower() == correct.strip().lower()
        if is_correct:
            add_points(uid, 5)
            students = load_students()
            if uid in students:
                students[uid]["exercises_completed"] = students[uid].get("exercises_completed",0)+1
                save_students(students)
            fb = "✅ *Richtig!* +5 points 🌟"
        else:
            fb = f"❌ *Falsch!*\n\nCorrect: *{esc(correct)}*"
        # Auto send next question
        students  = load_students()
        s         = students.get(uid, {})
        level     = s.get("level","A1")
        exercises = [e for e in load_exercises() if e.get("level") == level]
        if exercises:
            next_q = random.choice(exercises)
            set_s_mode(uid, "qna", {"question": next_q})
            if next_q.get("type") == "mcq":
                opts = next_q.get("options",[])
                await query.edit_message_text(
                    f"{fb}\n\n❓ *Nächste Frage ({level})*\n\n{next_q['question']}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"qna_{opt}")] for opt in opts])
                )
            else:
                await query.edit_message_text(
                    f"{fb}\n\n❓ *Nächste Frage ({level})*\n\n{next_q['question']}\n\n_Type your answer!_",
                    parse_mode="Markdown"
                )
        else:
            set_s_mode(uid, "menu")
            await query.edit_message_text(f"{fb}\n\nTap ❓ Q&A for another question!", parse_mode="Markdown")
        return

    # ── ADMIN GATE ──
    if not is_admin_logged_in(user_id):
        set_admin_state(user_id, "waiting_password")
        try:
            await query.edit_message_text("🔐 Session ended. Please send your password to login again.")
        except Exception:
            pass
        return

    # ── ADMIN CALLBACKS ──
    if data == "adm_back":
        set_admin_state(user_id, "logged_in")
        await query.edit_message_text("✅ *Admin Panel*\n\nChoose an option:", parse_mode="Markdown", reply_markup=admin_kb())
        return

    if data == "adm_logout":
        clear_admin(user_id)
        await query.edit_message_text("👋 Logged out successfully.")
        return

    if data == "adm_students":
        students = load_students()
        if not students:
            await query.edit_message_text("No students yet.", reply_markup=BACK_KB)
            return
        buttons = []
        lines   = [f"👥 *Total Students: {len(students)}*\n"]
        for i,(uid2,s) in enumerate(students.items(),1):
            name  = s.get("name","Unknown")
            level = s.get("level","?")
            lines.append(f"{i}\\. {esc(name)} \\({level}\\)")
            buttons.append([InlineKeyboardButton(f"{name} ({level})", callback_data=f"student_{uid2}")])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="adm_back")])
        await query.edit_message_text("\n".join(lines), parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("student_"):
        sid      = data[len("student_"):]
        students = load_students()
        s        = students.get(sid, {})
        frozen   = is_frozen(int(sid))
        status   = f"❄️ Frozen till {frozen[:10]}" if frozen else "✅ Active"
        text = (
            f"👤 *Name:* {esc(s.get('name','?'))}\n"
            f"🆔 *ID:* `{sid}`\n"
            f"📖 *Level:* {s.get('level','?')}\n"
            f"⭐ *Total Points:* {s.get('points',0)}\n"
            f"🏅 *Weekly Points:* {s.get('weekly_points',0)}\n"
            f"🔥 *Streak:* {s.get('streak',0)} days\n"
            f"📝 *Tests Done:* {s.get('exercises_completed',0)}\n"
            f"📅 *Joined:* {s.get('joined','—')}\n"
            f"🕐 *Last Active:* {s.get('last_active','—')}\n"
            f"🔒 *Status:* {status}"
        )
        await query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❄️ Freeze", callback_data=f"freeze_{sid}"),
                 InlineKeyboardButton("❌ Remove",  callback_data=f"remove_{sid}")],
                [InlineKeyboardButton("🔙 Back",    callback_data="adm_students")]
            ])
        )
        return

    if data.startswith("freeze_"):
        sid = data[len("freeze_"):]
        set_admin_state(user_id, "freeze_input", {"uid": sid})
        await query.edit_message_text(
            f"❄️ How long to freeze `{sid}`?\n\nSend number of days (e.g. `3`)\nor date/time (e.g. `2026-08-01 18:00`)\n\nSend /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data.startswith("remove_"):
        sid = data[len("remove_"):]
        wl  = load_whitelist()
        wl["ids"] = [i for i in wl["ids"] if str(i) != sid]
        wl.get("frozen",{}).pop(sid, None)
        save_whitelist(wl)
        await query.edit_message_text(f"✅ Student `{sid}` removed.", parse_mode="Markdown", reply_markup=BACK_KB)
        return

    if data == "adm_stats":
        students = load_students()
        counts   = {"A1":0,"A2":0,"B1":0,"B2":0}
        today    = date.today().isoformat()
        active_t = 0
        for s in students.values():
            if s.get("level") in counts: counts[s["level"]] += 1
            if s.get("last_active_date","") == today: active_t += 1
        daily   = load_daily()
        attended= len(daily.get("attendance",[]))
        total_ex= sum(s.get("exercises_completed",0) for s in students.values())
        db      = load_database()
        text = (
            f"📊 *Statistics*\n\n"
            f"👥 Total Students: *{len(students)}*\n"
            f"A1:{counts['A1']} A2:{counts['A2']} B1:{counts['B1']} B2:{counts['B2']}\n\n"
            f"✅ Active Today: *{active_t}*\n"
            f"📝 Test Attended Today: *{attended}*\n"
            f"🏅 Total Exercises Done: *{total_ex}*\n"
            f"📚 Vocabulary Database: *{len(db)} words*"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=BACK_KB)
        return

    if data == "adm_broadcast":
        set_admin_state(user_id, "broadcast")
        await query.edit_message_text("📤 *Broadcast*\n\nType your message.\n\nSend /cancel to abort.", parse_mode="Markdown")
        return

    if data == "adm_whitelist":
        wl      = load_whitelist()
        frozen  = wl.get("frozen",{})
        now_ist = datetime.now(IST)
        active_frozen = {k:v for k,v in frozen.items() if datetime.fromisoformat(v) > now_ist}
        text = (
            f"🔒 *Whitelist Panel*\n\n"
            f"✅ Allowed Students: *{len(wl.get('ids',[]))}*\n"
            f"❄️ Currently Frozen: *{len(active_frozen)}*"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=whitelist_kb())
        return

    if data == "wl_add_id":
        set_admin_state(user_id, "wl_add_id")
        await query.edit_message_text("➕ Send the student's Telegram ID (numbers only).\n\nSend /cancel to abort.")
        return

    if data == "wl_add_username":
        set_admin_state(user_id, "wl_add_username")
        await query.edit_message_text("➕ Send the student's @username.\n\nSend /cancel to abort.")
        return

    if data == "wl_view":
        wl       = load_whitelist()
        students = load_students()
        frozen   = wl.get("frozen",{})
        lines    = ["🔒 *Whitelisted Students*\n"]
        for i,tid in enumerate(wl.get("ids",[]),1):
            s    = students.get(str(tid),{})
            name = s.get("name","Unknown")
            f_u  = frozen.get(str(tid),"")
            tag  = f" ❄️ till {f_u[:10]}" if f_u else ""
            lines.append(f"{i}\\. *{esc(name)}* — `{tid}`{tag}")
        if not wl.get("ids"):
            lines.append("_No students added yet\\._")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_whitelist")]])
        )
        return

    if data == "wl_freeze":
        set_admin_state(user_id, "wl_freeze_id")
        await query.edit_message_text("❄️ Send the Telegram ID of the student to freeze.\n\nSend /cancel to abort.")
        return

    if data == "wl_remove":
        set_admin_state(user_id, "wl_remove")
        await query.edit_message_text("❌ Send the Telegram ID or @username to remove.\n\nSend /cancel to abort.")
        return

    if data == "adm_settings":
        settings = load_settings()
        reminder = "✅ ON" if settings.get("reminders_enabled") else "❌ OFF"
        await query.edit_message_text(f"⚙️ *Settings*\n\n🔔 Reminders: *{reminder}*", parse_mode="Markdown", reply_markup=settings_kb())
        return

    if data == "set_password":
        set_admin_state(user_id, "set_password")
        await query.edit_message_text("🔑 Enter your *new admin password*:", parse_mode="Markdown")
        return

    if data == "set_reminders":
        settings = load_settings()
        settings["reminders_enabled"] = not settings.get("reminders_enabled",True)
        save_settings(settings)
        status = "✅ ON" if settings["reminders_enabled"] else "❌ OFF"
        await query.edit_message_text(f"🔔 Reminders: *{status}*", parse_mode="Markdown", reply_markup=BACK_KB)
        return

    if data == "set_addvocab":
        set_admin_state(user_id, "add_vocab")
        await query.edit_message_text(
            "📖 *Add Vocabulary*\n\nSupported formats:\n"
            "`word = meaning`\n`word - meaning`\n`word meaning`\n\n"
            "You can paste multiple words at once.\n\nSend /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data == "set_addexercise":
        set_admin_state(user_id, "add_exercise_level")
        await query.edit_message_text("📝 Choose level:", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("A1",callback_data="exlevel_A1"),InlineKeyboardButton("A2",callback_data="exlevel_A2")],
                [InlineKeyboardButton("B1",callback_data="exlevel_B1"),InlineKeyboardButton("B2",callback_data="exlevel_B2")],
            ])
        )
        return

    if data.startswith("exlevel_"):
        level = data[len("exlevel_"):]
        set_admin_state(user_id, "add_exercise_text", {"level": level})
        await query.edit_message_text(
            f"📝 *Exercise for {level}*\n\nFormat: `Question | Answer`\n\nSend /cancel to abort.",
            parse_mode="Markdown"
        )
        return

    if data == "set_uploadpdf":
        set_admin_state(user_id, "upload_pdf")
        await query.edit_message_text(
            "📄 *Upload PDF*\n\nSend a PDF. Words should be in:\n`word = meaning` or `word - meaning` format.\n\nSend /cancel to abort.",
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
        db       = load_database()
        added    = 0
        skipped  = 0
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    word, meaning = None, None
                    for sep in [" = "," - "," – "]:
                        if sep in line:
                            parts   = line.split(sep, 1)
                            word    = parts[0].strip().lower()
                            meaning = parts[1].strip()
                            break
                    if word and meaning and len(word) < 60:
                        if word in db:
                            skipped += 1
                        else:
                            db[word]  = meaning
                            added += 1
        save_database(db)
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(
            f"✅ *PDF processed!*\n\nAdded: *{added}*\nSkipped: *{skipped} duplicates*",
            parse_mode="Markdown", reply_markup=admin_kb()
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ─────────────────────────────────────────────
# MAIN REPLY HANDLER
# ─────────────────────────────────────────────
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg      = update.message.text.strip()
    user_id  = update.effective_user.id
    uid      = str(user_id)
    username = update.effective_user.username or ""
    chat_type= update.effective_chat.type

    # Group = complete silence
    if chat_type in ("group","supergroup"):
        return

    # ── ADMIN FLOW ──
    state = admin_state(user_id)

    if state == "waiting_password":
        try:
            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
        except Exception:
            pass
        settings = load_settings()
        if msg == settings.get("admin_password", ADMIN_PASS):
            set_admin_state(user_id, "logged_in")
            await send_admin_menu(update, context, "✅ *Login successful!*\n\nChoose an option:")
        else:
            await update.message.reply_text("❌ Wrong password.")
            clear_admin(user_id)
        return

    if state == "broadcast":
        wl   = load_whitelist()
        sent = 0
        for wid in wl.get("ids",[]):
            try:
                await context.bot.send_message(chat_id=int(wid), text=f"📢 *Message from your German tutor:*\n\n{msg}", parse_mode="Markdown")
                sent += 1
            except Exception:
                pass
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(f"✅ Sent to {sent} student(s).", reply_markup=admin_kb())
        return

    if state == "set_password":
        settings = load_settings()
        settings["admin_password"] = msg
        save_settings(settings)
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text("✅ Password updated!", reply_markup=admin_kb())
        return

    if state == "add_vocab":
        db     = load_database()
        added  = 0
        skipped= 0
        lines  = msg.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            word, meaning = None, None
            for sep in [" = "," - "," – "]:
                if sep in line:
                    parts   = line.split(sep,1)
                    word    = parts[0].strip().lower()
                    meaning = parts[1].strip()
                    break
            if not word and " " in line:
                parts   = line.split(" ",1)
                word    = parts[0].strip().lower()
                meaning = parts[1].strip()
            if word and meaning:
                if word in db:
                    skipped += 1
                else:
                    db[word] = meaning
                    added += 1
        save_database(db)
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(
            f"✅ *Vocabulary updated!*\n\nAdded: *{added}*\nSkipped: *{skipped} duplicates*",
            parse_mode="Markdown", reply_markup=admin_kb()
        )
        return

    if state == "add_exercise_text":
        stored = admin_sessions[user_id].get("data",{})
        level  = stored.get("level","A1")
        if "|" in msg:
            parts    = msg.split("|",1)
            question = parts[0].strip()
            answer   = parts[1].strip()
            exercises = load_exercises()
            exercises.append({"level":level,"question":question,"answer":answer,"type":"short"})
            save_exercises(exercises)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(f"✅ Exercise added for *{level}*!", parse_mode="Markdown", reply_markup=admin_kb())
        else:
            await update.message.reply_text("⚠️ Format: `Question | Answer`", parse_mode="Markdown")
        return

    if state == "wl_add_id":
        entry = msg.strip()
        if entry.isdigit():
            wl = load_whitelist()
            if entry not in [str(i) for i in wl["ids"]]:
                wl["ids"].append(entry)
                save_whitelist(wl)
                set_admin_state(user_id, "logged_in")
                await update.message.reply_text(f"✅ ID `{entry}` added!", parse_mode="Markdown", reply_markup=admin_kb())
            else:
                await update.message.reply_text("ℹ️ Already in whitelist.")
        else:
            await update.message.reply_text("⚠️ Numbers only.")
        return

    if state == "wl_add_username":
        entry = msg.strip().lstrip("@").lower()
        wl    = load_whitelist()
        if entry not in [u.lower() for u in wl.get("usernames",[])]:
            wl["usernames"].append(entry)
            save_whitelist(wl)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(f"✅ @{entry} added!", parse_mode="Markdown", reply_markup=admin_kb())
        else:
            await update.message.reply_text("ℹ️ Already in whitelist.")
        return

    if state == "wl_remove":
        entry = msg.strip().lstrip("@").lower()
        wl    = load_whitelist()
        removed = False
        if entry.isdigit() and entry in [str(i) for i in wl["ids"]]:
            wl["ids"] = [i for i in wl["ids"] if str(i) != entry]
            wl.get("frozen",{}).pop(entry,None)
            removed = True
        elif entry in [u.lower() for u in wl.get("usernames",[])]:
            wl["usernames"] = [u for u in wl["usernames"] if u.lower() != entry]
            removed = True
        if removed:
            save_whitelist(wl)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(f"✅ `{entry}` removed.", parse_mode="Markdown", reply_markup=admin_kb())
        else:
            await update.message.reply_text("⚠️ Not found.")
        return

    if state in ("wl_freeze_id","freeze_input"):
        stored = admin_sessions[user_id].get("data",{})
        if state == "wl_freeze_id":
            if not msg.strip().isdigit():
                await update.message.reply_text("⚠️ Numbers only.")
                return
            stored["uid"] = msg.strip()
            set_admin_state(user_id, "freeze_input", stored)
            await update.message.reply_text(
                f"❄️ How long to freeze `{stored['uid']}`?\n\nSend days (e.g. `3`) or datetime (e.g. `2026-08-01 18:00`)\n\nSend /cancel to abort.",
                parse_mode="Markdown"
            )
            return
        uid_to_freeze = stored.get("uid","")
        try:
            entry = msg.strip()
            if entry.isdigit():
                until = datetime.now(IST) + timedelta(days=int(entry))
            else:
                until = IST.localize(datetime.strptime(entry,"%Y-%m-%d %H:%M"))
            wl = load_whitelist()
            if "frozen" not in wl: wl["frozen"] = {}
            wl["frozen"][uid_to_freeze] = until.isoformat()
            save_whitelist(wl)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(
                f"❄️ Student `{uid_to_freeze}` frozen until *{until.strftime('%d %b %Y %H:%M')}*",
                parse_mode="Markdown", reply_markup=admin_kb()
            )
        except Exception:
            await update.message.reply_text("⚠️ Format: days (e.g. `3`) or `2026-08-01 18:00`", parse_mode="Markdown")
        return

    # ── WHITELISTED STUDENT FLOW ──
    if is_whitelisted(user_id, username) and not is_admin(user_id):
        # Clear trial if any
        trials = load_trials()
        if uid in trials:
            trials.pop(uid)
            save_trials(trials)

        frozen = is_frozen(user_id)
        if frozen:
            await update.message.reply_text(
                f"❄️ Your access is temporarily suspended.\n\nPlease contact *+91 7012098913*.",
                parse_mode="Markdown"
            )
            return

        students = load_students()
        mode     = s_mode(uid)

        # ── PROFILE SETUP ──
        if mode == "setup_name":
            name = extract_name(msg)
            set_s_mode(uid, "setup_level", {"name": name})
            await update.message.reply_text(
                f"Schön, *{esc(name)}*! 😊\n\nWähle dein Deutschniveau:\n*Choose your German level:*",
                parse_mode="Markdown",
                reply_markup=LEVEL_KB
            )
            return

        if mode == "setup_level":
            if msg not in ["A1","A2","B1","B2"]:
                await update.message.reply_text("Please choose your level:", reply_markup=LEVEL_KB)
                return
            stored_data = s_data(uid)
            name        = stored_data.get("name","Student")
            students[uid] = {
                "name"            : name,
                "username"        : username,
                "level"           : msg,
                "status"          : "active",
                "points"          : 0,
                "weekly_points"   : 0,
                "streak"          : 0,
                "exercises_completed": 0,
                "recent_scores"   : [],
                "attendance_count": 0,
                "joined"          : datetime.now(IST).strftime("%d %B %Y"),
                "last_active"     : datetime.now(IST).strftime("%d %b %Y %H:%M"),
                "last_active_date": date.today().isoformat()
            }
            save_students(students)
            set_s_mode(uid, "menu")
            await update.message.reply_text(
                f"Willkommen, *{esc(name)}*! 🎉\n\nLevel: *{msg}*\n\nHier ist dein Menü! Here is your menu! 👇",
                parse_mode="Markdown",
                reply_markup=MAIN_KB
            )
            return

        # Reload student
        student = students.get(uid, {})
        if not student or student.get("status") != "active":
            set_s_mode(uid, "setup_name")
            await update.message.reply_text("Wie heißt du? What is your name?", reply_markup=ReplyKeyboardRemove())
            return

        touch_student(uid)

        # ── CANCEL ──
        if "Cancel" in msg or msg == "❌ Cancel":
            set_s_mode(uid, "menu")
            await update.message.reply_text("↩️ Zurück zum Menü.", reply_markup=MAIN_KB)
            return

        # ── VOCAB PRACTICE ──
        if "Vocabulary Practice" in msg:
            db = load_database()
            if not db:
                await update.message.reply_text("No vocabulary yet!", reply_markup=MAIN_KB)
                return
            word, meaning = random.choice(list(db.items()))
            set_s_mode(uid, "vocab_quiz", {"word": word, "meaning": meaning})
            await update.message.reply_text(
                f"📖 *Vocabulary Practice*\n\nWas bedeutet auf Englisch:\n\n🇩🇪 *{esc(word.capitalize())}*\n\n_Type your answer!_ _(Tap ❌ Cancel to stop)_",
                parse_mode="Markdown",
                reply_markup=CANCEL_KB
            )
            return

        if mode == "vocab_quiz":
            sd      = s_data(uid)
            meaning = sd.get("meaning","").lower()
            answer  = msg.lower().strip()
            db      = load_database()
            correct = answer in meaning or meaning in answer
            if correct:
                add_points(uid, 5)
                students = load_students()
                students[uid]["exercises_completed"] = students[uid].get("exercises_completed",0)+1
                save_students(students)
                fb = "✅ *Richtig!* +5 points 🌟\n\n"
            else:
                fb = f"❌ *Falsch!*\nRichtig: *{esc(sd.get('meaning',''))}*\n\n"
            new_word, new_meaning = random.choice(list(db.items()))
            set_s_mode(uid, "vocab_quiz", {"word": new_word, "meaning": new_meaning})
            await update.message.reply_text(
                f"{fb}Nächstes Wort:\n\n🇩🇪 *{esc(new_word.capitalize())}*\n\n_Type the meaning!_",
                parse_mode="Markdown",
                reply_markup=CANCEL_KB
            )
            return

        # ── Q&A ──
        if "Q&A" in msg:
            level = student.get("level","A1")
            q     = get_question(level)
            if not q:
                await update.message.reply_text("No questions available yet for your level!", reply_markup=MAIN_KB)
                return
            set_s_mode(uid, "qna", {"question": q})
            if q.get("type") == "mcq":
                opts = q.get("options",[])
                await update.message.reply_text(
                    f"❓ *Q&A ({level})*\n\n{q['question']}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"qna_{opt}")] for opt in opts])
                )
            else:
                await update.message.reply_text(
                    f"❓ *Q&A ({level})*\n\n{q['question']}\n\n_Type your answer!_",
                    parse_mode="Markdown",
                    reply_markup=CANCEL_KB
                )
            return

        if mode == "qna":
            sd      = s_data(uid)
            q       = sd.get("question",{})
            if q.get("type") == "short":
                correct    = q.get("answer","").lower()
                answer     = msg.lower().strip()
                is_correct = answer in correct or correct in answer
                if is_correct:
                    add_points(uid, 5)
                    students = load_students()
                    students[uid]["exercises_completed"] = students[uid].get("exercises_completed",0)+1
                    save_students(students)
                    fb = "✅ *Richtig!* +5 points 🌟"
                else:
                    fb = f"❌ *Falsch!*\n\nCorrect: *{esc(q.get('answer',''))}*"
                # Auto next question
                level  = student.get("level","A1")
                next_q = get_question(level)
                if next_q:
                    next_q = next_q
                    set_s_mode(uid, "qna", {"question": next_q})
                    if next_q.get("type") == "mcq":
                        opts = next_q.get("options",[])
                        await update.message.reply_text(
                            f"{fb}\n\n❓ *Nächste Frage ({level})*\n\n{next_q['question']}",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"qna_{opt}")] for opt in opts])
                        )
                    else:
                        await update.message.reply_text(
                            f"{fb}\n\n❓ *Nächste Frage ({level})*\n\n{next_q['question']}\n\n_Type your answer!_",
                            parse_mode="Markdown",
                            reply_markup=CANCEL_KB
                        )
                else:
                    set_s_mode(uid, "menu")
                    await update.message.reply_text(fb, parse_mode="Markdown", reply_markup=MAIN_KB)
            return

        # ── TODAY'S TEST ──
        if "Today's Test" in msg or "Test" in msg:
            daily = load_daily()
            today = date.today().isoformat()
            if daily.get("date") != today or not daily.get("words"):
                await update.message.reply_text("📭 No test today yet.\n\nWait for 6:00 AM vocab! 🌅", reply_markup=MAIN_KB)
                return
            if uid in daily.get("attendance",[]):
                await update.message.reply_text("✅ You already completed today's test! 🎉\nCome back tomorrow!", reply_markup=MAIN_KB)
                return
            if test_not_started():
                await update.message.reply_text(
                    "⏰ *There's still time for the test.*\n\n*Keep studying child!* 📚\n\nTest opens at *7:00 PM* sharp!",
                    parse_mode="Markdown", reply_markup=MAIN_KB
                )
                return
            if test_already_closed():
                await update.message.reply_text(
                    "⌛ *Continue learning and wait for the next test.* 💪\n\nNew vocab tomorrow at *6:00 AM*! 🌅",
                    parse_mode="Markdown", reply_markup=MAIN_KB
                )
                return
            if uid in active_tests:
                await update.message.reply_text("📝 Your test is already running! Check above. ⬆️", reply_markup=CANCEL_KB)
            else:
                await update.message.reply_text("📝 Your test will arrive shortly! Please wait... ⏱", reply_markup=MAIN_KB)
            return

        # ── MY PROGRESS ──
        if "Progress" in msg:
            s     = students.get(uid,{})
            daily = load_daily()
            att   = "✅ Yes" if uid in daily.get("attendance",[]) else "❌ No"
            await update.message.reply_text(
                f"📊 *My Progress*\n\n"
                f"👤 *Name:* {esc(s.get('name','?'))}\n"
                f"📖 *Level:* {s.get('level','?')}\n"
                f"⭐ *Total Points:* {s.get('points',0)}\n"
                f"🏅 *Weekly Points:* {s.get('weekly_points',0)}\n"
                f"🔥 *Streak:* {s.get('streak',0)} days\n"
                f"📝 *Tests Done:* {s.get('exercises_completed',0)}\n"
                f"📅 *Joined:* {s.get('joined','—')}\n"
                f"🧪 *Today's Test:* {att}",
                parse_mode="Markdown", reply_markup=MAIN_KB
            )
            return

        # ── LEADERBOARD ──
        if "Leaderboard" in msg:
            students = load_students()
            ranked = sorted(
                [(s.get("name","?"),s.get("weekly_points",0),s.get("points",0))
                 for s in students.values() if s.get("status")=="active"],
                key=lambda x: x[1], reverse=True
            )
            lines  = ["🏆 *Weekly Leaderboard*\n"]
            medals = ["🥇","🥈","🥉"]
            for i,(name,wpts,tpts) in enumerate(ranked[:10],0):
                medal = medals[i] if i < 3 else f"{i+1}\\."
                lines.append(f"{medal} *{esc(name)}* — {wpts} pts this week")
            if not ranked:
                lines.append("No students yet!")
            lines.append("\n_Resets every Friday at 6:00 PM_ 🗓")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=MAIN_KB)
            return

        # Silent for anything else
        return

    # ── TRIAL USER FLOW ──
    if not is_admin(user_id):
        trials = load_trials()
        trial  = trials.get(uid, {})
        mode   = s_mode(uid)

        # Step 1: First time — ask name
        if not trial:
            trials[uid] = {"name": "", "sessions_used": 0, "asking_name": True}
            save_trials(trials)
            set_s_mode(uid, "trial_asking_name")
            await update.message.reply_text(
                "Hallo! 👋 Ich bin der Deutsche Lern-Bot der *Deutsch Lernen Company!*\n\n"
                "Wie heißt du? *What is your name?*",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove()
            )
            return

        # Step 2: Save name
        if trial.get("asking_name") or mode == "trial_asking_name":
            name = extract_name(msg)
            trials[uid] = {"name": name, "sessions_used": 0, "asking_name": False}
            save_trials(trials)
            set_s_mode(uid, "menu")
            await update.message.reply_text(
                f"Willkommen, *{esc(name)}*! 🎉\n\n"
                f"You have *3 free trial sessions!*\n\n"
                f"👇 Try Vocabulary Practice or Q&A!",
                parse_mode="Markdown",
                reply_markup=TRIAL_KB
            )
            return

        # Reload trial
        trial         = trials.get(uid, {})
        name          = esc(trial.get("name", ""))
        sessions_used = trial.get("sessions_used", 0)

        # Block restricted features
        if any(kw in msg for kw in ["Today's Test", "Leaderboard", "Progress", "📝", "🏆", "📊"]):
            await update.message.reply_text(
                "⛔ Only for enrolled students.\n\nContact *+91 7012098913* to join!",
                parse_mode="Markdown"
            )
            return

        # Cancel — end session
        if "Cancel" in msg or msg == "❌ Cancel":
            set_s_mode(uid, "menu")
            await update.message.reply_text("↩️ Back.", reply_markup=TRIAL_KB)
            return

        # Check if starting NEW session (not mid-session)
        is_starting_vocab = "Vocabulary Practice" in msg
        is_starting_qna   = "Q&A" in msg
        is_new_session    = is_starting_vocab or is_starting_qna

        if is_new_session:
            # Check trial limit
            if sessions_used >= 3:
                await update.message.reply_text(
                    f"Hallo *{name}*! 👋\n\n"
                    f"Your free trial has ended. 🎓\n\n"
                    f"To continue learning German, contact:\n"
                    f"📞 *+91 7012098913*\n\n"
                    f"Mention your name to activate your account!",
                    parse_mode="Markdown",
                    reply_markup=ReplyKeyboardRemove()
                )
                return
            # Consume one trial session
            trials[uid]["sessions_used"] = sessions_used + 1
            save_trials(trials)
            remaining = 3 - trials[uid]["sessions_used"]
            if remaining > 0:
                await update.message.reply_text(
                    f"_Session {trials[uid]['sessions_used']}/3 — {remaining} free session(s) remaining._",
                    parse_mode="Markdown"
                )

        # VOCAB PRACTICE
        if is_starting_vocab or mode == "vocab_quiz":
            if is_starting_vocab:
                db = load_database()
                if not db:
                    await update.message.reply_text("No vocabulary yet!", reply_markup=TRIAL_KB)
                    return
                word, meaning = random.choice(list(db.items()))
                set_s_mode(uid, "vocab_quiz", {"word": word, "meaning": meaning})
                await update.message.reply_text(
                    f"📖 *Vocabulary Practice*\n\n🇩🇪 *{esc(word.capitalize())}*\n\n_Type the meaning!_ _(Tap ❌ Cancel to stop)_",
                    parse_mode="Markdown",
                    reply_markup=CANCEL_KB
                )
            else:
                sd      = s_data(uid)
                meaning = sd.get("meaning", "").lower()
                answer  = msg.lower().strip()
                db      = load_database()
                correct = answer in meaning or meaning in answer
                fb      = "✅ *Richtig!* 🌟\n\n" if correct else f"❌ *Falsch!*\nRichtig: *{esc(sd.get('meaning', ''))}*\n\n"
                new_word, new_meaning = random.choice(list(db.items()))
                set_s_mode(uid, "vocab_quiz", {"word": new_word, "meaning": new_meaning})
                await update.message.reply_text(
                    f"{fb}🇩🇪 *{esc(new_word.capitalize())}*\n\n_Type the meaning!_",
                    parse_mode="Markdown",
                    reply_markup=CANCEL_KB
                )
            return

        # Q&A
        if is_starting_qna or mode == "qna":
            if is_starting_qna:
                q = get_question("A1")
                if not q:
                    await update.message.reply_text("No questions available yet!", reply_markup=TRIAL_KB)
                    return
                set_s_mode(uid, "qna", {"question": q})
                if q.get("type") == "mcq":
                    await update.message.reply_text(
                        f"❓ *Q&A*\n\n{q['question']}",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"qna_{opt}")] for opt in q.get("options", [])])
                    )
                else:
                    await update.message.reply_text(
                        f"❓ *Q&A*\n\n{q['question']}\n\n_Type your answer!_",
                        parse_mode="Markdown",
                        reply_markup=CANCEL_KB
                    )
            else:
                sd = s_data(uid)
                q  = sd.get("question", {})
                if q.get("type") == "short":
                    correct    = q.get("answer", "").lower()
                    is_correct = msg.lower().strip() in correct or correct in msg.lower().strip()
                    fb = "✅ *Richtig!* 🌟" if is_correct else f"❌ *Falsch!*\n\nCorrect: *{esc(q.get('answer', ''))}*"
                    next_q = get_question("A1")
                    if next_q:
                        set_s_mode(uid, "qna", {"question": next_q})
                        if next_q.get("type") == "mcq":
                            await update.message.reply_text(
                                f"{fb}\n\n❓ *Next Question*\n\n{next_q['question']}",
                                parse_mode="Markdown",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"qna_{opt}")] for opt in next_q.get("options", [])])
                            )
                        else:
                            await update.message.reply_text(
                                f"{fb}\n\n❓ *Next Question*\n\n{next_q['question']}\n\n_Type your answer!_",
                                parse_mode="Markdown",
                                reply_markup=CANCEL_KB
                            )
                    else:
                        set_s_mode(uid, "menu")
                        await update.message.reply_text(fb, parse_mode="Markdown", reply_markup=TRIAL_KB)
            return

        return


# ─────────────────────────────────────────────
# MAIN REPLY HANDLER
# ─────────────────────────────────────────────
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg      = update.message.text.strip()
    user_id  = update.effective_user.id
    uid      = str(user_id)
    username = update.effective_user.username or ""
    chat_type= update.effective_chat.type

    # Group = complete silence
    if chat_type in ("group","supergroup"):
        return

    # ── ADMIN FLOW ──
    state = admin_state(user_id)

    if state == "waiting_password":
        try:
            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=update.message.message_id)
        except Exception:
            pass
        settings = load_settings()
        if msg == settings.get("admin_password", ADMIN_PASS):
            set_admin_state(user_id, "logged_in")
            await send_admin_menu(update, context, "✅ *Login successful!*\n\nChoose an option:")
        else:
            await update.message.reply_text("❌ Wrong password.")
            clear_admin(user_id)
        return

    if state == "broadcast":
        wl   = load_whitelist()
        sent = 0
        for wid in wl.get("ids",[]):
            try:
                await context.bot.send_message(chat_id=int(wid), text=f"📢 *Message from your German tutor:*\n\n{msg}", parse_mode="Markdown")
                sent += 1
            except Exception:
                pass
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(f"✅ Sent to {sent} student(s).", reply_markup=admin_kb())
        return

    if state == "set_password":
        settings = load_settings()
        settings["admin_password"] = msg
        save_settings(settings)
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text("✅ Password updated!", reply_markup=admin_kb())
        return

    if state == "add_vocab":
        db     = load_database()
        added  = 0
        skipped= 0
        lines  = msg.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            word, meaning = None, None
            for sep in [" = "," - "," – "]:
                if sep in line:
                    parts   = line.split(sep,1)
                    word    = parts[0].strip().lower()
                    meaning = parts[1].strip()
                    break
            if not word and " " in line:
                parts   = line.split(" ",1)
                word    = parts[0].strip().lower()
                meaning = parts[1].strip()
            if word and meaning:
                if word in db:
                    skipped += 1
                else:
                    db[word] = meaning
                    added += 1
        save_database(db)
        set_admin_state(user_id, "logged_in")
        await update.message.reply_text(
            f"✅ *Vocabulary updated!*\n\nAdded: *{added}*\nSkipped: *{skipped} duplicates*",
            parse_mode="Markdown", reply_markup=admin_kb()
        )
        return

    if state == "add_exercise_text":
        stored = admin_sessions[user_id].get("data",{})
        level  = stored.get("level","A1")
        if "|" in msg:
            parts    = msg.split("|",1)
            question = parts[0].strip()
            answer   = parts[1].strip()
            exercises = load_exercises()
            exercises.append({"level":level,"question":question,"answer":answer,"type":"short"})
            save_exercises(exercises)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(f"✅ Exercise added for *{level}*!", parse_mode="Markdown", reply_markup=admin_kb())
        else:
            await update.message.reply_text("⚠️ Format: `Question | Answer`", parse_mode="Markdown")
        return

    if state == "wl_add_id":
        entry = msg.strip()
        if entry.isdigit():
            wl = load_whitelist()
            if entry not in [str(i) for i in wl["ids"]]:
                wl["ids"].append(entry)
                save_whitelist(wl)
                set_admin_state(user_id, "logged_in")
                await update.message.reply_text(f"✅ ID `{entry}` added!", parse_mode="Markdown", reply_markup=admin_kb())
            else:
                await update.message.reply_text("ℹ️ Already in whitelist.")
        else:
            await update.message.reply_text("⚠️ Numbers only.")
        return

    if state == "wl_add_username":
        entry = msg.strip().lstrip("@").lower()
        wl    = load_whitelist()
        if entry not in [u.lower() for u in wl.get("usernames",[])]:
            wl["usernames"].append(entry)
            save_whitelist(wl)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(f"✅ @{entry} added!", parse_mode="Markdown", reply_markup=admin_kb())
        else:
            await update.message.reply_text("ℹ️ Already in whitelist.")
        return

    if state == "wl_remove":
        entry = msg.strip().lstrip("@").lower()
        wl    = load_whitelist()
        removed = False
        if entry.isdigit() and entry in [str(i) for i in wl["ids"]]:
            wl["ids"] = [i for i in wl["ids"] if str(i) != entry]
            wl.get("frozen",{}).pop(entry,None)
            removed = True
        elif entry in [u.lower() for u in wl.get("usernames",[])]:
            wl["usernames"] = [u for u in wl["usernames"] if u.lower() != entry]
            removed = True
        if removed:
            save_whitelist(wl)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(f"✅ `{entry}` removed.", parse_mode="Markdown", reply_markup=admin_kb())
        else:
            await update.message.reply_text("⚠️ Not found.")
        return

    if state in ("wl_freeze_id","freeze_input"):
        stored = admin_sessions[user_id].get("data",{})
        if state == "wl_freeze_id":
            if not msg.strip().isdigit():
                await update.message.reply_text("⚠️ Numbers only.")
                return
            stored["uid"] = msg.strip()
            set_admin_state(user_id, "freeze_input", stored)
            await update.message.reply_text(
                f"❄️ How long to freeze `{stored['uid']}`?\n\nSend days (e.g. `3`) or datetime (e.g. `2026-08-01 18:00`)\n\nSend /cancel to abort.",
                parse_mode="Markdown"
            )
            return
        uid_to_freeze = stored.get("uid","")
        try:
            entry = msg.strip()
            if entry.isdigit():
                until = datetime.now(IST) + timedelta(days=int(entry))
            else:
                until = IST.localize(datetime.strptime(entry,"%Y-%m-%d %H:%M"))
            wl = load_whitelist()
            if "frozen" not in wl: wl["frozen"] = {}
            wl["frozen"][uid_to_freeze] = until.isoformat()
            save_whitelist(wl)
            set_admin_state(user_id, "logged_in")
            await update.message.reply_text(
                f"❄️ Student `{uid_to_freeze}` frozen until *{until.strftime('%d %b %Y %H:%M')}*",
                parse_mode="Markdown", reply_markup=admin_kb()
            )
        except Exception:
            await update.message.reply_text("⚠️ Format: days (e.g. `3`) or `2026-08-01 18:00`", parse_mode="Markdown")
        return

    # ── WHITELISTED STUDENT FLOW ──
    if is_whitelisted(user_id, username) and not is_admin(user_id):
        # Clear trial if any
        trials = load_trials()
        if uid in trials:
            trials.pop(uid)
            save_trials(trials)

        frozen = is_frozen(user_id)
        if frozen:
            await update.message.reply_text(
                f"❄️ Your access is temporarily suspended.\n\nPlease contact *+91 7012098913*.",
                parse_mode="Markdown"
            )
            return

        students = load_students()
        mode     = s_mode(uid)

        # ── PROFILE SETUP ──
        if mode == "setup_name":
            name = extract_name(msg)
            set_s_mode(uid, "setup_level", {"name": name})
            await update.message.reply_text(
                f"Schön, *{esc(name)}*! 😊\n\nWähle dein Deutschniveau:\n*Choose your German level:*",
                parse_mode="Markdown",
                reply_markup=LEVEL_KB
            )
            return

        if mode == "setup_level":
            if msg not in ["A1","A2","B1","B2"]:
                await update.message.reply_text("Please choose your level:", reply_markup=LEVEL_KB)
                return
            stored_data = s_data(uid)
            name        = stored_data.get("name","Student")
            students[uid] = {
                "name"            : name,
                "username"        : username,
                "level"           : msg,
                "status"          : "active",
                "points"          : 0,
                "weekly_points"   : 0,
                "streak"          : 0,
                "exercises_completed": 0,
                "recent_scores"   : [],
                "attendance_count": 0,
                "joined"          : datetime.now(IST).strftime("%d %B %Y"),
                "last_active"     : datetime.now(IST).strftime("%d %b %Y %H:%M"),
                "last_active_date": date.today().isoformat()
            }
            save_students(students)
            set_s_mode(uid, "menu")
            await update.message.reply_text(
                f"Willkommen, *{esc(name)}*! 🎉\n\nLevel: *{msg}*\n\nHier ist dein Menü! Here is your menu! 👇",
                parse_mode="Markdown",
                reply_markup=MAIN_KB
            )
            return

        # Reload student
        student = students.get(uid, {})
        if not student or student.get("status") != "active":
            set_s_mode(uid, "setup_name")
            await update.message.reply_text("Wie heißt du? What is your name?", reply_markup=ReplyKeyboardRemove())
            return

        touch_student(uid)

        # ── CANCEL ──
        if "Cancel" in msg or msg == "❌ Cancel":
            set_s_mode(uid, "menu")
            await update.message.reply_text("↩️ Zurück zum Menü.", reply_markup=MAIN_KB)
            return

        # ── VOCAB PRACTICE ──
        if "Vocabulary Practice" in msg:
            db = load_database()
            if not db:
                await update.message.reply_text("No vocabulary yet!", reply_markup=MAIN_KB)
                return
            word, meaning = random.choice(list(db.items()))
            set_s_mode(uid, "vocab_quiz", {"word": word, "meaning": meaning})
            await update.message.reply_text(
                f"📖 *Vocabulary Practice*\n\nWas bedeutet auf Englisch:\n\n🇩🇪 *{esc(word.capitalize())}*\n\n_Type your answer!_ _(Tap ❌ Cancel to stop)_",
                parse_mode="Markdown",
                reply_markup=CANCEL_KB
            )
            return

        if mode == "vocab_quiz":
            sd      = s_data(uid)
            meaning = sd.get("meaning","").lower()
            answer  = msg.lower().strip()
            db      = load_database()
            correct = answer in meaning or meaning in answer
            if correct:
                add_points(uid, 5)
                students = load_students()
                students[uid]["exercises_completed"] = students[uid].get("exercises_completed",0)+1
                save_students(students)
                fb = "✅ *Richtig!* +5 points 🌟\n\n"
            else:
                fb = f"❌ *Falsch!*\nRichtig: *{esc(sd.get('meaning',''))}*\n\n"
            new_word, new_meaning = random.choice(list(db.items()))
            set_s_mode(uid, "vocab_quiz", {"word": new_word, "meaning": new_meaning})
            await update.message.reply_text(
                f"{fb}Nächstes Wort:\n\n🇩🇪 *{esc(new_word.capitalize())}*\n\n_Type the meaning!_",
                parse_mode="Markdown",
                reply_markup=CANCEL_KB
            )
            return

        # ── Q&A ──
        if "Q&A" in msg:
            level = student.get("level","A1")
            q     = get_question(level)
            if not q:
                await update.message.reply_text("No questions available yet for your level!", reply_markup=MAIN_KB)
                return
            set_s_mode(uid, "qna", {"question": q})
            if q.get("type") == "mcq":
                opts = q.get("options",[])
                await update.message.reply_text(
                    f"❓ *Q&A ({level})*\n\n{q['question']}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"qna_{opt}")] for opt in opts])
                )
            else:
                await update.message.reply_text(
                    f"❓ *Q&A ({level})*\n\n{q['question']}\n\n_Type your answer!_",
                    parse_mode="Markdown",
                    reply_markup=CANCEL_KB
                )
            return

        if mode == "qna":
            sd      = s_data(uid)
            q       = sd.get("question",{})
            if q.get("type") == "short":
                correct    = q.get("answer","").lower()
                answer     = msg.lower().strip()
                is_correct = answer in correct or correct in answer
                if is_correct:
                    add_points(uid, 5)
                    students = load_students()
                    students[uid]["exercises_completed"] = students[uid].get("exercises_completed",0)+1
                    save_students(students)
                    fb = "✅ *Richtig!* +5 points 🌟"
                else:
                    fb = f"❌ *Falsch!*\n\nCorrect: *{esc(q.get('answer',''))}*"
                # Auto next question
                level  = student.get("level","A1")
                next_q = get_question(level)
                if next_q:
                    next_q = next_q
                    set_s_mode(uid, "qna", {"question": next_q})
                    if next_q.get("type") == "mcq":
                        opts = next_q.get("options",[])
                        await update.message.reply_text(
                            f"{fb}\n\n❓ *Nächste Frage ({level})*\n\n{next_q['question']}",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"qna_{opt}")] for opt in opts])
                        )
                    else:
                        await update.message.reply_text(
                            f"{fb}\n\n❓ *Nächste Frage ({level})*\n\n{next_q['question']}\n\n_Type your answer!_",
                            parse_mode="Markdown",
                            reply_markup=CANCEL_KB
                        )
                else:
                    set_s_mode(uid, "menu")
                    await update.message.reply_text(fb, parse_mode="Markdown", reply_markup=MAIN_KB)
            return

        # ── TODAY'S TEST ──
        if "Today's Test" in msg or "Test" in msg:
            daily = load_daily()
            today = date.today().isoformat()
            if daily.get("date") != today or not daily.get("words"):
                await update.message.reply_text("📭 No test today yet.\n\nWait for 6:00 AM vocab! 🌅", reply_markup=MAIN_KB)
                return
            if uid in daily.get("attendance",[]):
                await update.message.reply_text("✅ You already completed today's test! 🎉\nCome back tomorrow!", reply_markup=MAIN_KB)
                return
            if test_not_started():
                await update.message.reply_text(
                    "⏰ *There's still time for the test.*\n\n*Keep studying child!* 📚\n\nTest opens at *7:00 PM* sharp!",
                    parse_mode="Markdown", reply_markup=MAIN_KB
                )
                return
            if test_already_closed():
                await update.message.reply_text(
                    "⌛ *Continue learning and wait for the next test.* 💪\n\nNew vocab tomorrow at *6:00 AM*! 🌅",
                    parse_mode="Markdown", reply_markup=MAIN_KB
                )
                return
            if uid in active_tests:
                await update.message.reply_text("📝 Your test is already running! Check above. ⬆️", reply_markup=CANCEL_KB)
            else:
                await update.message.reply_text("📝 Your test will arrive shortly! Please wait... ⏱", reply_markup=MAIN_KB)
            return

        # ── MY PROGRESS ──
        if "Progress" in msg:
            s     = students.get(uid,{})
            daily = load_daily()
            att   = "✅ Yes" if uid in daily.get("attendance",[]) else "❌ No"
            await update.message.reply_text(
                f"📊 *My Progress*\n\n"
                f"👤 *Name:* {esc(s.get('name','?'))}\n"
                f"📖 *Level:* {s.get('level','?')}\n"
                f"⭐ *Total Points:* {s.get('points',0)}\n"
                f"🏅 *Weekly Points:* {s.get('weekly_points',0)}\n"
                f"🔥 *Streak:* {s.get('streak',0)} days\n"
                f"📝 *Tests Done:* {s.get('exercises_completed',0)}\n"
                f"📅 *Joined:* {s.get('joined','—')}\n"
                f"🧪 *Today's Test:* {att}",
                parse_mode="Markdown", reply_markup=MAIN_KB
            )
            return

        # ── LEADERBOARD ──
        if "Leaderboard" in msg:
            students = load_students()
            ranked = sorted(
                [(s.get("name","?"),s.get("weekly_points",0),s.get("points",0))
                 for s in students.values() if s.get("status")=="active"],
                key=lambda x: x[1], reverse=True
            )
            lines  = ["🏆 *Weekly Leaderboard*\n"]
            medals = ["🥇","🥈","🥉"]
            for i,(name,wpts,tpts) in enumerate(ranked[:10],0):
                medal = medals[i] if i < 3 else f"{i+1}\\."
                lines.append(f"{medal} *{esc(name)}* — {wpts} pts this week")
            if not ranked:
                lines.append("No students yet!")
            lines.append("\n_Resets every Friday at 6:00 PM_ 🗓")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=MAIN_KB)
            return

        # Silent for anything else
        return

    # ── TRIAL USER FLOW ──
    if not is_admin(user_id):
        trials = load_trials()
        trial  = trials.get(uid, {})
        mode   = s_mode(uid)

        # First message ever
        if not trial and mode != "trial_name":
            set_s_mode(uid, "trial_name")
            await update.message.reply_text(
                "Hallo! 👋 Ich bin der Deutsche Lern-Bot der *Deutsch Lernen Company!*\n\nWie heißt du? *What is your name?*",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove()
            )
            return

        if mode == "trial_name":
            name = extract_name(msg)
            trials[uid] = {"name": name, "sessions_used": 0, "in_session": False}
            save_trials(trials)
            set_s_mode(uid, "menu")
            await update.message.reply_text(
                f"Willkommen, *{esc(name)}*! 🎉\n\n"
                f"You have *3 free trial sessions\\!*\n\n"
                f"Try our Vocabulary Practice and Q&A! 👇",
                parse_mode="Markdown",
                reply_markup=TRIAL_KB
            )
            return

        # Reload trial
        trial = trials.get(uid, {})
        name  = esc(trial.get("name",""))

        # Block restricted features
        if any(kw in msg for kw in ["Today's Test","Leaderboard","Progress","📝","🏆","📊"]):
            await update.message.reply_text(
                "⛔ This feature is only for enrolled students.\n\nContact *+91 7012098913* to join!",
                parse_mode="Markdown"
            )
            return

        # Cancel — end current session
        if "Cancel" in msg:
            trial["current_session"] = ""
            trials[uid] = trial
            save_trials(trials)
            set_s_mode(uid, "menu")
            await update.message.reply_text("↩️ Back.", reply_markup=TRIAL_KB)
            return

        sessions_used = trial.get("sessions_used", 0)
        current_session = trial.get("current_session", "")  # "vocab" or "qna" or ""

        if "Vocabulary Practice" in msg or "Q&A" in msg:
            # Starting a brand new session (not continuing one)
            new_session_type = "vocab" if "Vocabulary Practice" in msg else "qna"
            if current_session != new_session_type:
                # This is a new session — check and consume a trial
                if sessions_used >= 3:
                    await update.message.reply_text(
                        f"Hallo *{name}*! 👋\n\n"
                        f"Your free trial has ended. 🎓\n\n"
                        f"To continue learning German, please contact:\n"
                        f"📞 *+91 7012098913*\n\n"
                        f"Mention your name and we will activate your account!",
                        parse_mode="Markdown",
                        reply_markup=ReplyKeyboardRemove()
                    )
                    return
                trial["sessions_used"]    = sessions_used + 1
                trial["current_session"]  = new_session_type
                trials[uid] = trial
                save_trials(trials)
                remaining = 3 - trial["sessions_used"]
                if remaining > 0:
                    await update.message.reply_text(
                        f"_{remaining} free session(s) remaining after this one._",
                        parse_mode="Markdown"
                    )

        # Handle vocab practice for trial user
        if "Vocabulary Practice" in msg or (mode == "vocab_quiz"):
            if "Vocabulary Practice" in msg:
                db = load_database()
                if not db:
                    await update.message.reply_text("No vocabulary yet!", reply_markup=TRIAL_KB)
                    return
                word, meaning = random.choice(list(db.items()))
                set_s_mode(uid, "vocab_quiz", {"word": word, "meaning": meaning})
                await update.message.reply_text(
                    f"📖 *Vocabulary Practice*\n\n🇩🇪 *{esc(word.capitalize())}*\n\n_Type the meaning!_ _(Tap ❌ Cancel to stop)_",
                    parse_mode="Markdown",
                    reply_markup=CANCEL_KB
                )
            else:
                sd      = s_data(uid)
                meaning = sd.get("meaning","").lower()
                answer  = msg.lower().strip()
                db      = load_database()
                correct = answer in meaning or meaning in answer
                fb      = "✅ *Richtig!* 🌟\n\n" if correct else f"❌ *Falsch!*\nRichtig: *{esc(sd.get('meaning',''))}*\n\n"
                new_word, new_meaning = random.choice(list(db.items()))
                set_s_mode(uid, "vocab_quiz", {"word": new_word, "meaning": new_meaning})
                await update.message.reply_text(
                    f"{fb}🇩🇪 *{esc(new_word.capitalize())}*\n\n_Type the meaning!_",
                    parse_mode="Markdown",
                    reply_markup=CANCEL_KB
                )
            return

        # Handle Q&A for trial user
        if "Q&A" in msg or mode == "qna":
            if "Q&A" in msg:
                exercises = [e for e in load_exercises() if e.get("level") == "A1"]
                if not exercises:
                    await update.message.reply_text("No questions available yet!", reply_markup=TRIAL_KB)
                    return
                q = random.choice(exercises)
                set_s_mode(uid, "qna", {"question": q})
                if q.get("type") == "mcq":
                    opts = q.get("options",[])
                    await update.message.reply_text(
                        f"❓ *Q&A*\n\n{q['question']}",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"qna_{opt}")] for opt in opts])
                    )
                else:
                    await update.message.reply_text(
                        f"❓ *Q&A*\n\n{q['question']}\n\n_Type your answer!_",
                        parse_mode="Markdown",
                        reply_markup=CANCEL_KB
                    )
            else:
                sd      = s_data(uid)
                q       = sd.get("question",{})
                if q.get("type") == "short":
                    correct    = q.get("answer","").lower()
                    answer     = msg.lower().strip()
                    is_correct = answer in correct or correct in answer
                    fb = "✅ *Richtig!* 🌟" if is_correct else f"❌ *Falsch!*\n\nCorrect: *{esc(q.get('answer',''))}*"
                    exercises = [e for e in load_exercises() if e.get("level") == "A1"]
                    if exercises:
                        next_q = random.choice(exercises)
                        set_s_mode(uid, "qna", {"question": next_q})
                        if next_q.get("type") == "mcq":
                            opts = next_q.get("options",[])
                            await update.message.reply_text(
                                f"{fb}\n\n❓ *Next Question*\n\n{next_q['question']}",
                                parse_mode="Markdown",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"qna_{opt}")] for opt in opts])
                            )
                        else:
                            await update.message.reply_text(
                                f"{fb}\n\n❓ *Next Question*\n\n{next_q['question']}\n\n_Type your answer!_",
                                parse_mode="Markdown",
                                reply_markup=CANCEL_KB
                            )
                    else:
                        set_s_mode(uid, "menu")
                        await update.message.reply_text(fb, parse_mode="Markdown", reply_markup=TRIAL_KB)
            return

        return

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()
    jq  = app.job_queue
    ist = pytz.timezone("Asia/Kolkata")

    jq.run_daily(job_daily_vocab,       time=dt.time(6,  0, 0, tzinfo=ist))          # 6:00 AM IST
    jq.run_daily(job_test_announcement, time=dt.time(19, 0, 0, tzinfo=ist))          # 7:00 PM IST
    jq.run_daily(job_weekly_winner,     time=dt.time(18, 0, 0, tzinfo=ist), days=(5,)) # Friday 6 PM

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("administrator", cmd_administrator))
    app.add_handler(CommandHandler("cancel",        cmd_cancel))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.Document.PDF, pdf_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

    print("🤖 Deutsch Lernen Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
