import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_path = "/tmp/" + update.message.document.file_name
    await file.download_to_drive(file_path)

    # Gofile.io API তে আপলোড
    with open(file_path, 'rb') as f:
        response = requests.post("https://upload.gofile.io/uploadfile", files={"file": f})
        result = response.json()

    if result["status"] == "ok":
        download_link = result["data"]["downloadPage"]
        await update.message.reply_text(f"তোমার ফাইলটি আপলোড হয়েছে:\n{download_link}")
    else:
        await update.message.reply_text("দুঃখিত, ফাইল আপলোডে সমস্যা হয়েছে।")

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    print("Bot is running...")
    app.run_polling()
