import logging
import os # এনভায়রনমেন্ট ভ্যারিয়েবল পড়ার জন্য
import requests
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# --- বট কনফিগারেশন ---
# এই মানগুলো হোস্টিং প্ল্যাটফর্মের Environment Variables থেকে আসবে।
BOT_TOKEN = os.environ.get("BOT_TOKEN")
LOG_CHANNEL_ID = os.environ.get("LOG_CHANNEL_ID") # এটি সাংখ্যিক আইডি হতে হবে

# লগিং কনফিগারেশন
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# লগ চ্যানেলে মেসেজ পাঠানোর ফাংশন
def send_log_message(bot_instance: Bot, message_text: str):
    if LOG_CHANNEL_ID:
        try:
            numeric_log_channel_id = int(LOG_CHANNEL_ID)
            bot_instance.send_message(chat_id=numeric_log_channel_id, text=message_text)
            logger.info(f"Log sent to channel {LOG_CHANNEL_ID}")
        except ValueError:
            logger.error(f"LOG_CHANNEL_ID '{LOG_CHANNEL_ID}' is not a valid integer.")
        except Exception as e:
            logger.error(f"Failed to send log to channel {LOG_CHANNEL_ID}: {e}")
    else:
        logger.info("LOG_CHANNEL_ID not set. Skipping log message to channel. Logged to console: " + message_text)

# /start কমান্ড হ্যান্ডলার
def start(update: Update, context: CallbackContext):
    user_name = update.effective_user.first_name
    welcome_message = (
        f"হাই {user_name}! 👋\n\n"
        "আমি ফাইল আপলোড বট। আমাকে যেকোনো ফাইল (ডকুমেন্ট, ছবি, ভিডিও, অডিও) পাঠান,\n"
        "আমি সেটি transfer.sh-এ আপলোড করে আপনাকে ডাউনলোড লিঙ্ক দেবো।"
    )
    update.message.reply_text(welcome_message)
    send_log_message(context.bot, f"User {user_name} (ID: {update.effective_user.id}) started the bot.")

# ফাইল হ্যান্ডলার (ডকুমেন্ট, ছবি, ভিডিও, অডিও)
def handle_file(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user
    file_name_original = "unknown_file"
    file_obj = None

    if message.document:
        file_obj = message.document
        file_name_original = file_obj.file_name
    elif message.photo:
        file_obj = message.photo[-1]
        file_name_original = f"photo_{file_obj.file_unique_id}.jpg"
    elif message.video:
        file_obj = message.video
        file_name_original = file_obj.file_name if file_obj.file_name else f"video_{file_obj.file_unique_id}.mp4"
    elif message.audio:
        file_obj = message.audio
        file_name_original = file_obj.file_name if file_obj.file_name else f"audio_{file_obj.file_unique_id}.mp3"
    else:
        message.reply_text("দুঃখিত, আমি শুধু সাধারণ ডকুমেন্ট, ছবি, ভিডিও বা অডিও ফাইল আপলোড করতে পারি।")
        return

    if not file_obj:
        message.reply_text("ফাইল পেতে সমস্যা হয়েছে।")
        return

    try:
        bot_file = context.bot.get_file(file_obj.file_id)
        file_content_bytes = bot_file.download_as_bytearray()
        message.reply_text(f"'{file_name_original}' ফাইলটি পেয়েছি। transfer.sh-এ আপলোড করা হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
        log_msg_start = f"User {user.first_name} (ID: {user.id}) sent file: '{file_name_original}'. Starting upload."
        send_log_message(context.bot, log_msg_start)

        safe_file_name = "".join(c if c.isalnum() or c in ('.', '_') else '_' for c in file_name_original)
        if not safe_file_name:
            safe_file_name = f"file_{file_obj.file_unique_id}"
        upload_url = f"https://transfer.sh/{safe_file_name}"
        
        response = requests.put(upload_url, data=bytes(file_content_bytes))
        response.raise_for_status()
        download_link = response.text.strip()
        
        success_message = (
            f"✅ '{file_name_original}' ফাইলটি সফলভাবে আপলোড হয়েছে!\n\n"
            f"🔗 ডাউনলোড লিঙ্ক: {download_link}\n\n"
            "(এই লিঙ্কটি সাধারণত ১৪ দিন পর্যন্ত فعال থাকবে)"
        )
        message.reply_text(success_message)
        log_msg_success = f"Successfully uploaded '{file_name_original}' for user {user.first_name} (ID: {user.id}). Link: {download_link}"
        send_log_message(context.bot, log_msg_success)

    except Exception as e:
        logger.error(f"Error processing file for {user.first_name} (ID: {user.id}), File: '{file_name_original}': {e}", exc_info=True)
        message.reply_text(f"'{file_name_original}' ফাইলটি আপলোড করার সময় একটি সমস্যা হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন অথবা অন্য ফাইল পাঠান।\nত্রুটি: {type(e).__name__}")
        send_log_message(context.bot, f"Failed to upload '{file_name_original}' for user {user.first_name} (ID: {user.id}). Error: {type(e).__name__} - {e}")

def main():
    if not BOT_TOKEN:
        logger.critical("🔴 BOT_TOKEN is not set! The bot cannot start. Please set it as an environment variable.")
        return
    if not LOG_CHANNEL_ID:
        logger.warning("🟡 LOG_CHANNEL_ID is not set! Log messages will not be sent to any Telegram channel, only to console.")

    try:
        startup_bot_instance = Bot(token=BOT_TOKEN)
    except Exception as e:
        logger.critical(f"🔴 Failed to create Bot instance with BOT_TOKEN. Error: {e}. The bot cannot start.")
        return

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.document | Filters.photo | Filters.video | Filters.audio, handle_file))

    send_log_message(startup_bot_instance, "🚀 বট সফলভাবে চালু হয়েছে এবং কানেক্টেড।")
    logger.info("Bot has started polling...")
    updater.start_polling()
    updater.idle()
    send_log_message(startup_bot_instance, "🛑 বট বন্ধ হয়ে যাচ্ছে।")
    logger.info("Bot has stopped.")

if __name__ == '__main__':
    main()