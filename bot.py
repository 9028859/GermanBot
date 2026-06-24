import os
import json
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

with open("database.json", "r", encoding="utf-8") as file:
    database = json.load(file)

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_message = update.message.text.lower()

    if user_message in database:
        await update.message.reply_text(database[user_message])
    else:
        await update.message.reply_text(
            "Sorry, I don't know that yet."
        )

app = Application.builder().token(TOKEN).build()

app.add_handler(
    MessageHandler(filters.TEXT, reply)
)

print("Bot started...")

app.run_polling()
