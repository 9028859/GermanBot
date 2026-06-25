import os
import json
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes
)

TOKEN = os.getenv("BOT_TOKEN")

with open("database.json", "r", encoding="utf-8") as file:
    database = json.load(file)

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_message = update.message.text
    user_id = str(update.message.from_user.id)

    if user_message in ["A1", "A2", "B1", "B2"]:

        with open("students.json", "r") as file:
            students = json.load(file)

        students[user_id] = {
            "level": user_message
        }

        with open("students.json", "w") as file:
            json.dump(students, file, indent=4)

        await update.message.reply_text(
            f"Your level has been saved as {user_message}"
        )

        return

    if user_message.lower() in database:

        await update.message.reply_text(
            database[user_message.lower()]
        )

    else:

        await update.message.reply_text(
            "Sorry, I don't know that yet."
        )
app = Application.builder().token(TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        ["A1"],
        ["A2"],
        ["B1"],
        ["B2"]
    ]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

    await update.message.reply_text(
        "Choose your German level:",
        reply_markup=reply_markup
    )
app.add_handler(
    CommandHandler("start", start)
)
app.add_handler(
    MessageHandler(filters.TEXT, reply)
)

print("Bot started...")

app.run_polling()
