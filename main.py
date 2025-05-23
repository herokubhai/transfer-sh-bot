# main.py
import logging
import os
import asyncio
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.constants import ParseMode
from telethon import TelegramClient, errors as telethon_errors
from telethon.sessions import StringSession

# --- Configuration is now imported from config.py ---
# config.py is expected to load these from environment variables and validate them.
try:
    from config import BOT_TOKEN, API_ID, API_HASH, SESSION_STRING, OWNER_ID
except ImportError:
    # This log might not be visible if logging is not yet configured,
    # so a print statement might also be useful for critical startup errors.
    print("CRITICAL: config.py not found. Please ensure it exists in the same directory as main.py.")
    logging.critical("FATAL: config.py not found. Please ensure it exists and is configured correctly.")
    exit(1) # Exit if config cannot be imported
except ValueError as e: # Handles errors from within config.py if env vars are missing/invalid
    print(f"CRITICAL: Configuration error from config.py: {e}")
    logging.critical(f"FATAL: Configuration error from config.py: {e}")
    exit(1) # Exit if config.py raises an error during import

# --- Logging Setup ---
# Configure logging after importing config, in case config itself has logging settings (though not in this example)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(funcName)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Gofile.io Helper ---
def get_gofile_server():
    """Gets the best available Gofile server or falls back to a default."""
    try:
        response = requests.get("https://api.gofile.io/getServer", timeout=10)
        response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
        data = response.json()
        if data.get("status") == "ok":
            server = data.get("data", {}).get("server")
            if server:
                logger.info(f"Using Gofile server: {server}")
                return server
            else:
                logger.error("Gofile getServer response OK, but 'server' field not found in data.")
        else:
            logger.error(f"Gofile getServer responded with status: {data.get('status')}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting Gofile server (RequestException): {e}")
    except ValueError as e: # Includes JSONDecodeError if response is not valid JSON
        logger.error(f"Error decoding Gofile server response (ValueError): {e}")
    except Exception as e: # Catch any other unexpected errors
        logger.error(f"An unexpected error occurred in get_gofile_server: {e}", exc_info=True)
    
    logger.warning("Falling back to default Gofile server 'store1' due to issues.")
    return "store1"

# --- Telethon Client Setup ---
# This client will use your user account for heavy lifting (large file downloads)
user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH, base_logger=logger.getChild('TelethonClient'))


# --- Core File Processing (using Telethon) ---
async def process_file_via_user_api(ptb_bot_ref, original_user_chat_id, file_message_id_in_user_chat, bot_status_message_id):
    """
    Downloads a file using Telethon (user account) and uploads to Gofile.
    Updates the PTB bot's status message.
    """
    original_file_name = "unknown_file" # Default
    temp_file_path = None # Initialize to ensure it's defined for finally block

    try:
        logger.info(f"[UserAPI] Processing file: user_chat_id={original_user_chat_id}, msg_id={file_message_id_in_user_chat}")
        await ptb_bot_ref.edit_message_text(
            chat_id=original_user_chat_id,
            message_id=bot_status_message_id,
            text="⏳ বড় ফাইল সনাক্ত করা হয়েছে। আপনার ব্যক্তিগত অ্যাকাউন্টের মাধ্যমে টেলিগ্রাম থেকে ডাউনলোড করা হচ্ছে..."
        )

        message_to_download = await user_client.get_messages(original_user_chat_id, ids=file_message_id_in_user_chat)

        if not message_to_download or not message_to_download.media:
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text="❌ ফাইলটি খুঁজে পাওয়া যায়নি অথবা এটিতে কোনো মিডিয়া নেই।")
            return

        # Determine original file name more robustly
        if hasattr(message_to_download, 'file') and hasattr(message_to_download.file, 'name') and message_to_download.file.name:
            original_file_name = message_to_download.file.name
        elif message_to_download.document and hasattr(message_to_download.document, 'attributes'):
            original_file_name = next((attr.file_name for attr in message_to_download.document.attributes if hasattr(attr, 'file_name') and attr.file_name), f"document_{message_to_download.id}")
        elif message_to_download.video and hasattr(message_to_download.video, 'attributes'):
            original_file_name = next((attr.file_name for attr in message_to_download.video.attributes if hasattr(attr, 'file_name') and attr.file_name), f"video_{message_to_download.id}.mp4")
        elif message_to_download.audio and hasattr(message_to_download.audio, 'attributes'):
             original_file_name = next((attr.file_name for attr in message_to_download.audio.attributes if hasattr(attr, 'file_name') and attr.file_name), f"audio_{message_to_download.id}.mp3")
        elif message_to_download.photo:
            original_file_name = f"photo_{message_to_download.id}.jpg" # Photos don't usually have explicit names
        else:
            original_file_name = f"file_{message_to_download.id}" # Fallback

        logger.info(f"[UserAPI] Downloading '{original_file_name}' from Telegram via user account...")
        
        # Sanitize filename for path and ensure it's not too long
        safe_original_file_name = "".join(c if c.isalnum() or c in ['.', '_', '-'] else '_' for c in original_file_name)
        if len(safe_original_file_name) > 100: # Limit length to prevent OS errors
            name_part, ext_part = os.path.splitext(safe_original_file_name)
            safe_original_file_name = name_part[:100-len(ext_part)-1] + ext_part if ext_part else name_part[:100]

        temp_file_path = f"./temp_download_{safe_original_file_name}"
        
        downloaded_file_path = await user_client.download_media(message_to_download.media, file=temp_file_path)

        if not downloaded_file_path or not os.path.exists(downloaded_file_path):
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=f"❌ টেলিগ্রাম থেকে '{original_file_name}' ডাউনলোড করতে ব্যর্থ হয়েছে।")
            return
        
        file_size_bytes = os.path.getsize(downloaded_file_path)
        logger.info(f"[UserAPI] Downloaded '{original_file_name}' ({file_size_bytes / (1024*1024):.2f} MB) to {downloaded_file_path}. Uploading to Gofile.io...")
        await ptb_bot_ref.edit_message_text(
            chat_id=original_user_chat_id,
            message_id=bot_status_message_id,
            text=f"⏳ '{original_file_name}' Gofile.io তে আপলোড করা হচ্ছে... ({(file_size_bytes / (1024*1024)):.2f} MB)"
        )

        gofile_server = get_gofile_server()
        upload_url = f"https://{gofile_server}.gofile.io/uploadFile"
        
        gofile_api_response = None
        with open(downloaded_file_path, 'rb') as f:
            files_payload = {'file': (original_file_name, f)}
            try:
                response = requests.post(upload_url, files=files_payload, timeout=1800) # 30 mins
                response.raise_for_status()
                gofile_api_response = response.json()
            except requests.exceptions.Timeout:
                logger.error(f"[UserAPI] Gofile.io upload timed out for {original_file_name}")
                await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text="❌ Gofile.io আপলোড টাইম আউট হয়েছে। ফাইলটি খুব বড় অথবা সার্ভারে সমস্যা হতে পারে।")
                return
            except requests.exceptions.RequestException as e:
                logger.error(f"[UserAPI] Gofile.io upload error for {original_file_name}: {e}")
                await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=f"❌ Gofile.io আপলোড ত্রুটি: {e}")
                return
            except ValueError: # JSONDecodeError
                 logger.error(f"[UserAPI] Gofile.io JSON decode error for {original_file_name}. Response text: {response.text if 'response' in locals() else 'N/A'}")
                 await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text="❌ Gofile.io থেকে উত্তর প্রক্রিয়াকরণে ত্রুটি।")
                 return

        if gofile_api_response and gofile_api_response.get("status") == "ok":
            data_payload = gofile_api_response.get("data", {})
            download_link = data_payload.get("downloadPage")
            gofile_file_name = data_payload.get("fileName", original_file_name)
            admin_code = data_payload.get("adminCode")

            if not download_link:
                logger.error(f"[UserAPI] Gofile success but no downloadPage. Data: {data_payload}")
                await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text="✅ Gofile আপলোড সফল হয়েছে, কিন্তু ডাউনলোড লিঙ্ক পাওয়া যায়নি।")
                return

            final_text = (
                f"✅ ফাইল সফলভাবে আপলোড হয়েছে!\n\n"
                f"🏷️ **নাম:** {gofile_file_name}\n"
                f"🔗 **ডাউনলোড লিঙ্ক:** {download_link}"
            )
            if admin_code:
                final_text += f"\n🔑 **অ্যাডমিন কোড:** `{admin_code}` (ফাইল পরিচালনার জন্য)"
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=final_text, disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN_V2)
            logger.info(f"[UserAPI] Successfully processed and sent link for '{original_file_name}' to user {original_user_chat_id}")
        else:
            error_msg_gofile = gofile_api_response.get('status', 'Unknown Gofile error') if gofile_api_response else "No/Invalid Gofile response"
            logger.error(f"[UserAPI] Gofile API error: {error_msg_gofile} - Full response: {gofile_api_response}")
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=f"❌ Gofile.io তে আপলোড ব্যর্থ হয়েছে: {error_msg_gofile}")

    except telethon_errors.rpcerrorlist.FileReferenceExpiredError:
        logger.warning(f"[UserAPI] File reference expired for message {file_message_id_in_user_chat} in chat {original_user_chat_id}.")
        await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text="❌ ফাইলটি আর টেলিগ্রামে পাওয়া যাচ্ছে না (File Reference Expired)। অনুগ্রহ করে আবার পাঠান।")
    except telethon_errors.FloodWaitError as e:
        logger.warning(f"[UserAPI] Flood wait error: {e}. Waiting for {e.seconds} seconds.")
        await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=f"⏳ টেলিগ্রাম কিছুক্ষণের জন্য অপেক্ষা করতে বলছে (Flood Wait: {e.seconds}s)। একটু পর আবার চেষ্টা করুন।")
        await asyncio.sleep(e.seconds + 5) # Wait a bit longer
    except Exception as e:
        logger.error(f"[UserAPI] Unexpected error in process_file_via_user_api for '{original_file_name}': {e}", exc_info=True)
        await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=f"❌ একটি অপ্রত্যাশিত ত্রুটি ঘটেছে ফাইল প্রসেসিং এর সময়: {str(e)[:200]}")
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info(f"[UserAPI] Cleaned up temporary file: {temp_file_path}")
            except Exception as e_clean:
                logger.error(f"[UserAPI] Error cleaning up temp file {temp_file_path}: {e_clean}")


# --- PTB (Bot Frontend) Handlers ---
async def start_command_ptb(update: Update, context: CallbackContext):
    user = update.effective_user
    await update.message.reply_html(
        f"👋 Hello {user.mention_html()}!\n\n"
        "আমি একটি হাইব্রিড ফাইল আপলোডার। আমাকে যেকোনো সাইজের ফাইল পাঠান, আমি চেষ্টা করবো Gofile.io তে আপলোড করে আপনাকে লিঙ্ক দিতে। "
        "বড় ফাইল প্রসেস করতে একটু বেশি সময় লাগতে পারে। অনুগ্রহ করে ধৈর্য ধরুন।"
    )
    logger.info(f"User {user.id} ('{user.username}') executed /start.")

async def file_handler_ptb(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user
    original_user_chat_id = message.chat_id
    file_message_id_for_telethon = message.message_id

    # Basic check for media type from PTB update object
    is_valid_media = message.document or message.video or message.audio or message.photo
    if not is_valid_media:
        logger.warning(f"User {user.id} sent a message without valid media to file_handler_ptb. Update: {update}")
        # This should ideally not be reached if filters are correct.
        await message.reply_text("❓ অনুগ্রহ করে একটি ফাইল (ডকুমেন্ট, ভিডিও, অডিও, বা ছবি) পাঠান।")
        return
        
    file_size_approx = 0
    media_obj = message.document or message.video or message.audio or (message.photo[-1] if message.photo else None)
    if media_obj and hasattr(media_obj, 'file_size') and media_obj.file_size:
        file_size_approx = media_obj.file_size
        logger.info(f"PTB Bot received a file. User: {user.id}, Chat: {original_user_chat_id}, Msg ID: {file_message_id_for_telethon}, Approx Size: {file_size_approx / (1024*1024) :.2f} MB")
    else:
        logger.info(f"PTB Bot received a file. User: {user.id}, Chat: {original_user_chat_id}, Msg ID: {file_message_id_for_telethon}. Size info not readily available from PTB object.")


    bot_status_msg = await message.reply_text("🔄 ফাইল পেয়েছি, এটি প্রসেস করার জন্য প্রস্তুত করছি...")

    # Create a task for Telethon processing to run it in the background
    asyncio.create_task(
        process_file_via_user_api(
            ptb_bot_ref=context.bot,
            original_user_chat_id=original_user_chat_id,
            file_message_id_in_user_chat=file_message_id_for_telethon,
            bot_status_message_id=bot_status_msg.message_id
        )
    )

async def error_handler_ptb(update: object, context: CallbackContext) -> None:
    """Log Errors caused by PTB Updates."""
    logger.error(msg="[PTB] Exception while handling an PTB update:", exc_info=context.error)
    if OWNER_ID and isinstance(context.error, Exception):
        try:
            error_details = f"PTB Bot Error: {context.error}\n\nUpdate Details:\n{update}"
            # Truncate if too long for a Telegram message
            if len(error_details) > 4000:
                error_details = error_details[:4000] + "\n...(truncated)"
            
            # Use the application's bot instance to send the error message
            if context.application and context.application.bot:
                 await context.application.bot.send_message(
                     chat_id=OWNER_ID,
                     text=f"⚠️ হাইব্রিড বটে একটি ত্রুটি ঘটেছে (PTB অংশ):\n<pre>{error_details}</pre>",
                     parse_mode=ParseMode.HTML
                 )
            else: # Fallback if bot instance not easily available (should be rare)
                logger.warning("[PTB] Could not send error report to OWNER_ID as bot instance was not available in error context.")
        except Exception as e_report:
            logger.error(f"[PTB] Failed to report PTB error to OWNER_ID: {e_report}")


# --- Main Application Setup and Run ---
async def main_hybrid_async():
    # 1. Start and authorize Telethon client (User API part)
    logger.info("Attempting to start Telethon client (User API)...")
    try:
        await user_client.connect()
        if not await user_client.is_user_authorized():
            logger.critical("Telethon client (user account) IS NOT AUTHORIZED. SESSION_STRING is likely invalid or expired. Please regenerate it using generate_session.py and update the environment variable. The bot cannot function for large files without this.")
            # Notify owner if possible (though PTB bot might not be up yet)
            if OWNER_ID: # Try sending via user_client itself if it connected but not authorized
                try: await user_client.send_message(OWNER_ID, "🔴 জরুরি সতর্কবার্তা: Telethon ক্লায়েন্ট (ইউজার অ্যাকাউন্ট) অনুমোদিত নয়! SESSION_STRING সম্ভবত ভুল বা মেয়াদোত্তীর্ণ। বট বড় ফাইল প্রসেস করতে পারবে না।")
                except: pass # Ignore if cannot send
            return 
        
        me = await user_client.get_me()
        logger.info(f"Telethon client (User API) logged in successfully as: {me.first_name} (@{me.username if me.username else 'N/A'})")
        if OWNER_ID:
            try:
                 await user_client.send_message(OWNER_ID, f"🟢 হাইব্রিড GoFile বট চালু হয়েছে!\n👤 User API অংশটি '{me.first_name}' হিসেবে লগইন করেছে।")
            except Exception as e_own:
                logger.warning(f"Could not send startup message to OWNER_ID via User API: {e_own}")
    except Exception as e_telethon_start:
        logger.critical(f"FATAL: Could not start or authorize the Telethon client (User API): {e_telethon_start}", exc_info=True)
        logger.critical("The bot will not be able to process large files. Please check API_ID, API_HASH, SESSION_STRING and network connectivity.")
        return

    # 2. Setup PTB application (Bot API part)
    logger.info("Initializing PTB Application (Bot API)...")
    ptb_application = Application.builder().token(BOT_TOKEN).build()

    ptb_application.add_handler(CommandHandler("start", start_command_ptb))
    ptb_application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO),
        file_handler_ptb
    ))
    ptb_application.add_error_handler(error_handler_ptb)

    # 3. Run PTB polling alongside Telethon client
    logger.info("Starting PTB Bot polling...")
    try:
        await ptb_application.initialize()
        await ptb_application.start()
        await ptb_application.updater.start_polling(poll_interval=1, timeout=20, bootstrap_retries=-1) # bootstrap_retries=-1 for infinite retries on startup
        
        logger.info("✅ Hybrid Bot is now running! (PTB Polling and Telethon Client active)")
        
        # This will keep the script alive and Telethon client processing events.
        # PTB updater.start_polling runs in background asyncio tasks.
        await user_client.run_until_disconnected()

    except Exception as e_main_run:
        logger.critical(f"FATAL: An error occurred while running the main hybrid application: {e_main_run}", exc_info=True)
    finally:
        logger.info("Initiating shutdown sequence for Hybrid Bot...")
        
        logger.info("Stopping PTB Application polling...")
        if 'ptb_application' in locals() and ptb_application.updater and ptb_application.updater.running:
            await ptb_application.updater.stop()
        
        logger.info("Stopping PTB Application...")
        if 'ptb_application' in locals() and hasattr(ptb_application, 'running') and ptb_application.running:
            await ptb_application.stop()
        
        # ptb_application.shutdown() is more comprehensive if available and needed
        # await ptb_application.shutdown()

        logger.info("Disconnecting Telethon client (User API)...")
        if user_client and user_client.is_connected(): # Check if user_client is not None
            await user_client.disconnect()
        
        logger.info("Hybrid Bot shutdown complete.")


if __name__ == "__main__":
    # Critical configuration variables are checked during import from config.py
    # If config.py raised an error due to missing env vars, the script would have exited.
    # This check is more of a safeguard if config.py import somehow succeeded without all vars.
    if not BOT_TOKEN or not API_ID or not API_HASH or not SESSION_STRING:
        print("❌ CRITICAL ERROR: One or more core environment variables (BOT_TOKEN, API_ID, API_HASH, SESSION_STRING) are missing.")
        print("   These should be loaded via config.py from your environment.")
        print("   The bot will not start.")
    else:
        try:
            asyncio.run(main_hybrid_async())
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received by asyncio.run. Shutting down...")
        except Exception as e_global:
            # This catches errors during asyncio.run() itself or unhandled errors from main_hybrid_async
            logger.critical(f"A critical unhandled exception occurred at the global level: {e_global}", exc_info=True)
