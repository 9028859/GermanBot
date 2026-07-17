#!/usr/bin/env python3
"""
Deutsch Lernen Bot — MongoDB Edition
Complete rewrite using MongoDB Atlas for persistent storage
"""

import os
import json
import asyncio
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import pytz
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# ─────────────────────────────────────────────
# ENVIRONMENT & TIMEZONE
# ─────────────────────────────────────────────
BOT_TOKEN      = os.getenv("BOT_TOKEN")
ADMIN_ID       = os.getenv("ADMIN_ID")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "anand2024")
GROUP_ID       = int(os.getenv("GROUP_ID", "-1004485792523"))
MONGODB_URL    = os.getenv("MONGODB_URL")  # e.g., mongodb+srv://user:pass@cluster.xxx

IST = pytz.timezone("Asia/Kolkata")

if not BOT_TOKEN or not MONGODB_URL:
    raise ValueError("❌ BOT_TOKEN and MONGODB_URL must be set in environment variables")

# ─────────────────────────────────────────────
# MONGODB CONNECTION
# ─────────────────────────────────────────────
try:
    mongo_client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=5000)
    # Test connection
    mongo_client.admin.command('ismaster')
    print("✅ MongoDB connected successfully")
except ServerSelectionTimeoutError as e:
    print(f"❌ MongoDB connection failed: {e}")
    raise

db = mongo_client["deutsch_lernen"]
col_students   = db["students"]
col_database   = db["database"]      # Vocabulary
col_trials     = db["trials"]
col_daily      = db["daily"]
col_exercises  = db["exercises"]
col_settings   = db["settings"]

# Create indexes for performance
col_students.create_index("user_id", unique=True)
col_trials.create_index("user_id", unique=True)
col_daily.create_index("date", unique=True)
col_exercises.create_index("level")

# ─────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────

def esc(text: str) -> str:
    """Escape all MarkdownV2 special characters by prefixing with backslash."""
    if not text:
        return ""
    chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    result = str(text)
    for char in chars:
        result = result.replace(char, '\\' + char)
    return result

# ─────────────────────────────────────────────
# DATABASE FUNCTIONS — STUDENTS
# ─────────────────────────────────────────────

def load_students() -> Dict:
    """Load all students from MongoDB."""
    students = {}
    for doc in col_students.find():
        user_id = doc.get("user_id")
        if user_id:
            students[str(user_id)] = doc
    return students

def load_student(user_id) -> Dict:
    """Load single student by user_id."""
    return col_students.find_one({"user_id": str(user_id)}) or {}

def save_student(user_id, student_data: Dict):
    """Save/update student."""
    student_data["user_id"] = str(user_id)
    col_students.update_one(
        {"user_id": str(user_id)},
        {"$set": student_data},
        upsert=True
    )

def is_enrolled(user_id) -> bool:
    """Check if user is enrolled and has paid."""
    student = load_student(user_id)
    return student.get("status") == "active"

def is_admin(user_id) -> bool:
    """Check if user is admin."""
    student = load_student(user_id)
    return student.get("is_admin", False)

# ─────────────────────────────────────────────
# DATABASE FUNCTIONS — TRIALS
# ─────────────────────────────────────────────

def load_trials() -> Dict:
    """Load all trial users."""
    trials = {}
    for doc in col_trials.find():
        user_id = doc.get("user_id")
        if user_id:
            trials[str(user_id)] = doc
    return trials

def get_trial(user_id):
    """Get trial data for user."""
    return col_trials.find_one({"user_id": str(user_id)}) or {}

def save_trial(user_id, trial_data: Dict):
    """Save trial data."""
    trial_data["user_id"] = str(user_id)
    col_trials.update_one(
        {"user_id": str(user_id)},
        {"$set": trial_data},
        upsert=True
    )

def delete_trial(user_id):
    """Delete trial user (when they enroll)."""
    col_trials.delete_one({"user_id": str(user_id)})

# ─────────────────────────────────────────────
# DATABASE FUNCTIONS — VOCABULARY
# ─────────────────────────────────────────────

def load_database() -> Dict:
    """Load all vocabulary words."""
    words = {}
    for doc in col_database.find():
        word = doc.get("word")
        if word:
            words[word] = doc.get("meaning", "")
    return words

def add_word(word: str, meaning: str, level: str = "A1"):
    """Add a single word."""
    col_database.update_one(
        {"word": word},
        {"$set": {"word": word, "meaning": meaning, "level": level}},
        upsert=True
    )

def bulk_add_words(words_list: List[Dict]):
    """Add multiple words at once."""
    if words_list:
        col_database.insert_many(words_list, ordered=False)

# ─────────────────────────────────────────────
# DATABASE FUNCTIONS — DAILY BROADCAST
# ─────────────────────────────────────────────

def load_daily() -> Dict:
    """Load today's daily data (words, attendance, test results)."""
    today = date.today().isoformat()
    doc = col_daily.find_one({"date": today})
    if not doc:
        return {
            "date": today,
            "words": {},
            "attendance": [],
            "test_results": {},
            "word_index": 0,
            "last_broadcast_time": None
        }
    return doc

def save_daily(daily_data: Dict):
    """Save daily data."""
    today = date.today().isoformat()
    daily_data["date"] = today
    col_daily.update_one(
        {"date": today},
        {"$set": daily_data},
        upsert=True
    )

# ─────────────────────────────────────────────
# DATABASE FUNCTIONS — EXERCISES
# ─────────────────────────────────────────────

def load_exercises() -> List[Dict]:
    """Load all exercises."""
    return list(col_exercises.find())

def add_exercise(level: str, question: str, answer: str, options: List[str] = None):
    """Add a single exercise."""
    col_exercises.insert_one({
        "level": level,
        "question": question,
        "answer": answer,
        "options": options or [],
        "created_at": datetime.now(IST).isoformat()
    })

# ─────────────────────────────────────────────
# KEYBOARD & STATE MANAGEMENT
# ─────────────────────────────────────────────

MAIN_KB    = ReplyKeyboardMarkup([["📖 Vocabulary Practice","❓ Q&A"],["📝 Today's Test","📊 My Progress"],["🏆 Leaderboard","👁️ View Vocab"]], resize_keyboard=True)
TRIAL_KB   = ReplyKeyboardMarkup([["📖 Vocabulary Practice","❓ Q&A"]], resize_keyboard=True)
LEVEL_KB   = ReplyKeyboardMarkup([["A1","A2"],["B1","B2"]], resize_keyboard=True)
CANCEL_KB  = ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)
BACK_KB    = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="adm_back")]])

def get_s_mode(uid: str) -> str:
    """Get user's current mode."""
    settings = col_settings.find_one({"user_id": uid}) or {}
    return settings.get("mode", "menu")

def set_s_mode(uid: str, mode: str):
    """Set user's mode."""
    col_settings.update_one(
        {"user_id": uid},
        {"$set": {"user_id": uid, "mode": mode}},
        upsert=True
    )

# ─────────────────────────────────────────────
# HANDLERS — /START
# ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user_id = update.effective_user.id
    uid     = str(user_id)
    name    = update.effective_user.first_name or "Student"
    
    # Check if enrolled
    if is_enrolled(user_id):
        msg = f"🎉 Welcome back, {name}\\!\n\nYou're enrolled in Deutsch Lernen\\."
        await update.message.reply_text(msg, parse_mode="MarkdownV2", reply_markup=MAIN_KB)
        return
    
    # Check if admin
    if is_admin(user_id):
        msg = f"👨‍💼 Admin panel active\\."
        await update.message.reply_text(msg, parse_mode="MarkdownV2", reply_markup=MAIN_KB)
        return
    
    # Trial user — give 3 free sessions
    trial = get_trial(user_id)
    if not trial:
        trial = {
            "user_id": uid,
            "name": "",
            "sessions_used": 0,
            "asking_name": True,
            "created_at": datetime.now(IST).isoformat()
        }
        save_trial(user_id, trial)
        set_s_mode(uid, "trial_asking_name")
        await update.message.reply_text(
            "👋 Welcome to Deutsch Lernen\\!\n\nWhat's your name\\?",
            parse_mode="MarkdownV2",
            reply_markup=CANCEL_KB
        )
    else:
        sessions_left = 3 - trial.get("sessions_used", 0)
        if sessions_left <= 0:
            await update.message.reply_text(
                "❌ Your 3 free trial sessions are over\\.\n\nTo continue, please enroll\\.",
                parse_mode="MarkdownV2"
            )
        else:
            msg = f"✅ You have {sessions_left} session\\(s\\) left\\.\n\nWhat would you like to do\\?"
            await update.message.reply_text(msg, parse_mode="MarkdownV2", reply_markup=TRIAL_KB)
            set_s_mode(uid, "menu")

# ─────────────────────────────────────────────
# HANDLERS — MESSAGE REPLIES
# ─────────────────────────────────────────────

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message handler with MongoDB."""
    try:
        await reply_handler(update, context)
    except Exception as e:
        print(f"❌ reply() exception: {e}")
        await context.bot.send_message(
            chat_id=int(ADMIN_ID),
            text=f"🔴 *CRITICAL: reply\\(\\) crashed*\n\nUser: {update.effective_user.id}\nError: `{str(e)[:200]}`",
            parse_mode="MarkdownV2"
        )
        raise

async def reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process user messages."""
    msg       = update.message.text.strip()
    user_id   = update.effective_user.id
    uid       = str(user_id)
    chat_type = update.effective_chat.type

    # Ignore group messages
    if chat_type in ("group", "supergroup"):
        return

    # Enrolled users
    if is_enrolled(user_id):
        student = load_student(user_id)
        level   = student.get("level", "A1")

        # View Vocab
        if "View Vocab" in msg:
            daily = load_daily()
            today = date.today().isoformat()
            
            if daily.get("date") != today or not daily.get("words"):
                await update.message.reply_text(
                    "📖 *Today's Vocabulary*\n\n❌ Vocab not sent yet\\. Check back at 6:00 AM IST\\!",
                    parse_mode="MarkdownV2",
                    reply_markup=MAIN_KB
                )
                return
            
            words = daily.get("words", {})
            lines = ["📖 *Today's 10 Vocabulary Words*\n"]
            for i, (word, meaning) in enumerate(words.items(), 1):
                lines.append(f"{i}\\. *{esc(word)}* — {esc(meaning)}")
            
            lines.append(f"\n_Sent on:_ {daily.get('last_broadcast_time', 'N/A')}")
            
            await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2", reply_markup=MAIN_KB)
            return

        # Vocab Practice
        if "Vocabulary Practice" in msg:
            await update.message.reply_text(
                f"📖 Vocabulary Practice for {level}",
                reply_markup=MAIN_KB
            )
            return

        # Q&A
        if "Q&A" in msg:
            exercises = load_exercises()
            level_exercises = [e for e in exercises if e.get("level") == level]
            if not level_exercises:
                await update.message.reply_text(
                    "❌ No questions available yet for your level\\!",
                    parse_mode="MarkdownV2",
                    reply_markup=MAIN_KB
                )
                return
            q = level_exercises[0]
            await update.message.reply_text(
                f"❓ {esc(q.get('question', 'Q'))}\n\n_Level: {level}_",
                parse_mode="MarkdownV2",
                reply_markup=MAIN_KB
            )
            return

        # Progress
        if "My Progress" in msg:
            progress = f"📊 *Your Progress*\n\nLevel: {level}\nPoints: {student.get('points', 0)}\nStreak: {student.get('streak', 0)}"
            await update.message.reply_text(progress, parse_mode="Markdown", reply_markup=MAIN_KB)
            return

        # Leaderboard
        if "Leaderboard" in msg:
            students = load_students()
            ranked = sorted(
                [(s.get("name","?"),s.get("weekly_points",0))
                 for s in students.values() if s.get("status")=="active"],
                key=lambda x: x[1], reverse=True
            )
            lines = ["🏆 *Weekly Leaderboard*\n"]
            medals = ["🥇","🥈","🥉"]
            for i,(name,wpts) in enumerate(ranked[:10],0):
                medal = medals[i] if i < 3 else f"{i+1}\\."
                lines.append(f"{medal} *{esc(name)}* — {wpts} pts")
            if not ranked:
                lines.append("No students yet\\!")
            lines.append("\n_Resets Friday 6:00 PM_ 🗓")
            await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2", reply_markup=MAIN_KB)
            return

        # Fallback
        await update.message.reply_text(
            "❓ I didn't understand that\\.\n\nPlease use the menu buttons below 👇",
            parse_mode="MarkdownV2",
            reply_markup=MAIN_KB
        )
        return

    # Trial users
    trial = get_trial(user_id)
    if trial:
        sessions_left = 3 - trial.get("sessions_used", 0)
        if sessions_left <= 0:
            await update.message.reply_text("❌ Trial expired\\. Please enroll\\.", parse_mode="MarkdownV2")
            return

        if "Vocabulary Practice" in msg or "Q&A" in msg:
            trial["sessions_used"] = trial.get("sessions_used", 0) + 1
            save_trial(user_id, trial)
            await update.message.reply_text(
                f"✅ Session used\\. {sessions_left - 1} left\\.",
                parse_mode="MarkdownV2",
                reply_markup=TRIAL_KB
            )
            return

        # Fallback
        await update.message.reply_text(
            "❓ I didn't understand that\\.\n\nPlease use the buttons below 👇",
            parse_mode="MarkdownV2",
            reply_markup=TRIAL_KB
        )
        return

# ─────────────────────────────────────────────
# SCHEDULED JOBS
# ─────────────────────────────────────────────

async def job_daily_vocab(context: ContextTypes.DEFAULT_TYPE):
    """Broadcast 10 words at 6:00 AM IST."""
    db_vocab = load_database()
    if not db_vocab:
        return

    daily = load_daily()
    today = date.today().isoformat()

    # Only once per day
    if daily.get("date") == today and daily.get("words"):
        print(f"✅ Vocab for {today} already sent. Skipping.")
        return

    all_words = list(db_vocab.keys())
    total = len(all_words)
    idx = daily.get("word_index", 0) % total
    chosen = [all_words[(idx + i) % total] for i in range(min(10, total))]
    new_index = (idx + 10) % total

    daily = {
        "date": today,
        "words": {w: db_vocab[w] for w in chosen},
        "attendance": [],
        "test_results": {},
        "word_index": new_index,
        "last_broadcast_time": datetime.now(IST).isoformat()
    }
    save_daily(daily)

    lines = ["🌅 *Guten Morgen\\! Good Morning\\!*\n\n📖 *Today\\'s 10 Vocabulary Words:*\n"]
    for i, w in enumerate(chosen, 1):
        lines.append(f"{i}\\. *{esc(w)}* — {esc(db_vocab[w])}")
    lines.append("\n🧪 *Test at 7:00 PM sharp\\!* ⏱\n📚 Keep studying\\!")

    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text="\n".join(lines),
            parse_mode="MarkdownV2"
        )
        print(f"✅ Vocab sent for {today}")
    except Exception as e:
        print(f"❌ Vocab send error: {e}")

# ─────────────────────────────────────────────
# ERROR HANDLER
# ─────────────────────────────────────────────

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log and report errors."""
    print(f"\n{'='*60}")
    print(f"⚠️ ERROR at {datetime.now(IST).strftime('%d %b %Y %H:%M:%S')}")
    print(f"{'='*60}")
    print(context.error)
    print(f"{'='*60}\n")

    try:
        error_msg = f"❌ *BOT ERROR*\n\nError: `{str(context.error)[:200]}`"
        if update:
            error_msg += f"\n\nUser: `{update.effective_user.id}`"
        
        await context.bot.send_message(
            chat_id=int(ADMIN_ID),
            text=error_msg,
            parse_mode="MarkdownV2"
        )
    except Exception as e:
        print(f"Failed to notify admin: {e}")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    """Start the bot."""
    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    app.add_error_handler(error_handler)

    # Scheduled jobs
    app.job_queue.run_daily(
        job_daily_vocab,
        time=datetime.now(IST).replace(hour=6, minute=0, second=0, microsecond=0).time(),
        name="daily_vocab"
    )

    # Startup diagnostics
    students = load_students()
    trials = load_trials()
    vocab = load_database()
    daily = load_daily()

    print("\n" + "="*60)
    print("🤖 Deutsch Lernen Bot started!")
    print("="*60)
    print(f"\n📊 BOT STATE AT STARTUP:")
    print(f"   • Database: ✅ MongoDB connected")
    print(f"   • Vocabulary words: {len(vocab)}")
    print(f"   • Enrolled Students: {len([s for s in students.values() if s.get('status')=='active'])}")
    print(f"   • Trial Users: {len(trials)}")
    print(f"   • Today's Vocab Sent: {'✅ Yes' if daily.get('date') == date.today().isoformat() else '❌ Not yet'}")
    print(f"   • Current Word Index: {daily.get('word_index', 0)}\n")
    print("="*60 + "\n")

    app.run_polling()

if __name__ == "__main__":
    main()
