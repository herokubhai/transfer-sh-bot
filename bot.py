import os
import telebot
import requests
import logging

# টেলিগ্রাম বট টোকেন এখানে দিন
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not BOT_TOKEN:
    print("ত্রুটি: BOT_TOKEN এনভায়রনমেন্ট ভেরিয়েবল সেট করা নেই।")
    exit()

bot = telebot.TeleBot(BOT_TOKEN)
logger = telebot.logger
telebot.logger.setLevel(logging.INFO) # লগিং লেভেল সেট করা

# Gofile.io সার্ভার পাওয়ার জন্য API এন্ডপয়েন্ট
GOFILE_API_SERVER_URL = 'https://api.gofile.io/getServers'
# ফাইল আপলোড করার জন্য Gofile.io API এন্ডপয়েন্ট (সার্ভার পাওয়ার পর ফরম্যাট করা হবে)
GOFILE_UPLOAD_URL_FORMAT = 'https://{server}.gofile.io/uploadFile'

# /start এবং /help কমান্ডের জন্য হ্যান্ডলার
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "স্বাগতম! 👋\n\nআমাকে যেকোনো ফাইল পাঠান, আমি সেটি Gofile.io তে আপলোড করে আপনাকে ডাউনলোড লিংক দেবো।")

# ডকুমেন্ট (যেকোনো ফাইল) হ্যান্ডলার
@bot.message_handler(content_types=['document', 'video', 'audio', 'photo', 'voice', 'sticker'])
def handle_docs(message):
    try:
        file_info = None
        file_name = "uploaded_file" # ডিফল্ট ফাইলের নাম

        if message.document:
            file_info = bot.get_file(message.document.file_id)
            file_name = message.document.file_name
        elif message.video:
            file_info = bot.get_file(message.video.file_id)
            file_name = f"video_{message.video.file_id}.{message.video.mime_type.split('/')[1] if message.video.mime_type else 'mp4'}"
        elif message.audio:
            file_info = bot.get_file(message.audio.file_id)
            file_name = f"audio_{message.audio.file_id}.{message.audio.mime_type.split('/')[1] if message.audio.mime_type else 'mp3'}"
        elif message.photo:
            # ছবিগুলো বিভিন্ন সাইজে আসে, সবচেয়ে বড়টা নিচ্ছি
            file_info = bot.get_file(message.photo[-1].file_id)
            file_name = f"photo_{message.photo[-1].file_id}.jpg"
        elif message.voice:
            file_info = bot.get_file(message.voice.file_id)
            file_name = f"voice_{message.voice.file_id}.ogg"
        elif message.sticker:
            if message.sticker.is_animated or message.sticker.is_video:
                bot.reply_to(message, "দুঃখিত, অ্যানিমেটেড বা ভিডিও স্টিকার আপলোড করা যাবে না। সাধারণ স্টিকার (webp) পাঠান।")
                return
            file_info = bot.get_file(message.sticker.file_id)
            file_name = f"sticker_{message.sticker.file_id}.webp"

        if not file_info:
            bot.reply_to(message, "দুঃখিত, ফাইলটি প্রসেস করা যায়নি।")
            return

        # ব্যবহারকারীকে জানানো হচ্ছে যে ফাইল ডাউনলোড ও আপলোড শুরু হয়েছে
        processing_message = bot.reply_to(message, "ফাইল প্রসেস করা হচ্ছে... ⏳")

        downloaded_file = bot.download_file(file_info.file_path)

        # Gofile.io সার্ভার পাওয়া
        try:
            server_response = requests.get(GOFILE_API_SERVER_URL)
            server_response.raise_for_status() # HTTPエラーのチェック
            server_data = server_response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Gofile সার্ভার পেতে সমস্যা: {e}")
            bot.edit_message_text(chat_id=processing_message.chat.id, message_id=processing_message.message_id, text="দুঃখিত, Gofile.io সার্ভার পেতে সমস্যা হচ্ছে। অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।")
            return
        except ValueError: # JSON ডিকোড সমস্যা
            logger.error(f"Gofile সার্ভার রেসপন্স JSON পার্স করতে সমস্যা: {server_response.text}")
            bot.edit_message_text(chat_id=processing_message.chat.id, message_id=processing_message.message_id, text="দুঃখিত, Gofile.io থেকে অপ্রত্যাশিত উত্তর এসেছে।")
            return


        if server_data.get('status') == 'ok':
            server_name = server_data['data']['server']
            upload_url = GOFILE_UPLOAD_URL_FORMAT.format(server=server_name)

            # ফাইল আপলোড করা
            files = {'file': (file_name, downloaded_file)}
            try:
                upload_response = requests.post(upload_url, files=files)
                upload_response.raise_for_status() # HTTPエラーのチェック
                upload_data = upload_response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"Gofile আপলোডে সমস্যা: {e}")
                bot.edit_message_text(chat_id=processing_message.chat.id, message_id=processing_message.message_id, text="দুঃখিত, Gofile.io তে ফাইল আপলোড করতে সমস্যা হচ্ছে।")
                return
            except ValueError: # JSON ডিকোড সমস্যা
                 logger.error(f"Gofile আপলোড রেসপন্স JSON পার্স করতে সমস্যা: {upload_response.text}")
                 bot.edit_message_text(chat_id=processing_message.chat.id, message_id=processing_message.message_id, text="দুঃখিত, Gofile.io থেকে আপলোড করার পর অপ্রত্যাশিত উত্তর এসেছে।")
                 return


            if upload_data.get('status') == 'ok':
                download_page = upload_data['data']['downloadPage']
                file_link = upload_data['data']['directLink'] if 'directLink' in upload_data['data'] else download_page # সরাসরি লিংক না থাকলে ডাউনলোড পেইজ লিংক
                reply_text = f"✅ ফাইল সফলভাবে আপলোড হয়েছে!\n\n🔗 ডাউনলোড লিংক: {download_page}"
                if 'directLink' in upload_data['data']: # কিছু ফাইলের ক্ষেত্রে ডিরেক্ট লিংক নাও থাকতে পারে
                     reply_text += f"\n\n🔗 সরাসরি ডাউনলোড লিংক: {file_link} (এটি কিছু সময় পর কাজ নাও করতে পারে)"

                bot.edit_message_text(chat_id=processing_message.chat.id, message_id=processing_message.message_id, text=reply_text)
                logger.info(f"ফাইল আপলোড সফল: {download_page}")
            else:
                error_message = upload_data.get('status')
                logger.error(f"Gofile আপলোড ব্যর্থ: {error_message}")
                bot.edit_message_text(chat_id=processing_message.chat.id, message_id=processing_message.message_id, text=f"দুঃখিত, Gofile.io তে ফাইল আপলোড করা যায়নি। কারণ: {error_message}")
        else:
            error_message = server_data.get('status')
            logger.error(f"Gofile সার্ভার পেতে ব্যর্থ: {error_message}")
            bot.edit_message_text(chat_id=processing_message.chat.id, message_id=processing_message.message_id, text=f"দুঃখিত, Gofile.io সার্ভার পাওয়া যায়নি। কারণ: {error_message}")

    except Exception as e:
        logger.error(f"একটি অপ্রত্যাশিত ত্রুটি ঘটেছে: {e}")
        try:
            # যদি processing_message তৈরি হয়ে থাকে, তাহলে সেটি এডিট করার চেষ্টা করুন
            if 'processing_message' in locals() and processing_message:
                 bot.edit_message_text(chat_id=processing_message.chat.id, message_id=processing_message.message_id, text="দুঃখিত, একটি অপ্রত্যাশিত সমস্যা হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন।")
            else: # অন্যথায় নতুন মেসেজ পাঠান
                 bot.reply_to(message, "দুঃখিত, একটি অপ্রত্যাশিত সমস্যা হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন।")
        except Exception as ex: # যদি মেসেজ এডিট বা রিপ্লাই করতেও সমস্যা হয়
            logger.error(f"ত্রুটির মেসেজ পাঠাতেও সমস্যা: {ex}")


if __name__ == '__main__':
    print("বট চালু হচ্ছে...")
    try:
        bot.infinity_polling(logger_level=logging.INFO)
    except Exception as e:
        logger.error(f"বট চালু হতে সমস্যা: {e}")
        print(f"বট চালু হতে সমস্যা: {e}")
