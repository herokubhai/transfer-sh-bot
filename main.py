import logging
import os
import asyncio
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from telegram.constants import ParseMode
from telethon import TelegramClient, errors as telethon_errors
from telethon.sessions import StringSession
from dotenv import load_dotenv # dotenv লাইব্রেরি ইম্পোর্ট করা হয়েছে

# --- Logging Setup (আগেই থাকবে) ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Load Environment Variables ---
# config.env ফাইল থেকে ভেরিয়েবল লোড করার চেষ্টা করা হবে (লোকাল ডেভেলপমেন্টের জন্য)
# override=True দিলে .env ফাইলের ভেরিয়েবল সিস্টেমের ভেরিয়েবলকে ওভাররাইড করবে (যদি একই নামে থাকে)
CONFIG_ENV_PATH = 'config.env'
if load_dotenv(dotenv_path=CONFIG_ENV_PATH, override=True):
    logger.info(f"Loaded environment variables from '{CONFIG_ENV_PATH}' for local development.")
else:
    logger.info(f"'{CONFIG_ENV_PATH}' not found. Relying on system environment variables (expected for production/Seenode).")


# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID_STR = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
OWNER_ID_STR = os.environ.get("OWNER_ID") # Optional: Your Telegram User ID for admin notifications

# Validate mandatory environment variables
if not BOT_TOKEN: raise ValueError("BOT_TOKEN environment variable not set!")
if not API_ID_STR: raise ValueError("API_ID environment variable not set!")
if not API_HASH: raise ValueError("API_HASH environment variable not set!")
if not SESSION_STRING: raise ValueError("SESSION_STRING environment variable not set! Generate it using generate_session.py.")

try:
    API_ID = int(API_ID_STR)
except ValueError:
    raise ValueError("API_ID must be an integer.")

OWNER_ID = None
if OWNER_ID_STR:
    try:
        OWNER_ID = int(OWNER_ID_STR)
    except ValueError:
        logging.warning("OWNER_ID is set but not a valid integer. It will be ignored.")


# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s',
    level=logging.INFO
)
# Suppress noisy logs from underlying libraries if needed
# logging.getLogger('httpx').setLevel(logging.WARNING)
# logging.getLogger('telethon').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# --- Gofile.io Helper ---
def get_gofile_server():
    try:
        response = requests.get("https://api.gofile.io/getServer", timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "ok":
            server = data.get("data", {}).get("server")
            if server:
                logger.info(f"Using Gofile server: {server}")
                return server
        logger.error(f"Failed to get optimal Gofile server: {data}")
    except Exception as e:
        logger.error(f"Exception in get_gofile_server: {e}")
    logger.warning("Falling back to default Gofile server 'store1'")
    return "store1"

# --- Telethon Client Setup ---
# This client will use your user account for heavy lifting (large file downloads)
user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH, base_logger=logger)


# --- Core File Processing (using Telethon) ---
async def process_file_via_user_api(ptb_bot_ref, original_user_chat_id, file_message_id_in_user_chat, bot_status_message_id):
    """
    Downloads a file using Telethon (user account) and uploads to Gofile.
    Updates the PTB bot's status message.
    """
    original_file_name = "unknown_file" # Default
    temp_file_path = None

    try:
        logger.info(f"[UserAPI] Processing file: user_chat_id={original_user_chat_id}, msg_id={file_message_id_in_user_chat}")
        await ptb_bot_ref.edit_message_text(
            chat_id=original_user_chat_id,
            message_id=bot_status_message_id,
            text=" বড় ফাইল সনাক্ত করা হয়েছে। আপনার ব্যক্তিগত অ্যাকাউন্টের মাধ্যমে টেলিগ্রাম থেকে ডাউনলোড করা হচ্ছে... 📥"
        )

        # Fetch the specific message using Telethon
        # The message ID is from the chat with the bot (which is original_user_chat_id)
        message_to_download = await user_client.get_messages(original_user_chat_id, ids=file_message_id_in_user_chat)

        if not message_to_download or not message_to_download.media:
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text="❌ ফাইলটি খুঁজে পাওয়া যায়নি বা এটিতে কোনো মিডিয়া নেই।")
            return

        # Determine original file name
        if message_to_download.document:
            original_file_name = next((attr.file_name for attr in message_to_download.document.attributes if hasattr(attr, 'file_name')), f"document_{message_to_download.id}")
        elif message_to_download.video:
            original_file_name = next((attr.file_name for attr in message_to_download.video.attributes if hasattr(attr, 'file_name')), f"video_{message_to_download.id}.mp4")
        elif message_to_download.audio:
             original_file_name = next((attr.file_name for attr in message_to_download.audio.attributes if hasattr(attr, 'file_name')), f"audio_{message_to_download.id}.mp3")
        elif message_to_download.photo:
            original_file_name = f"photo_{message_to_download.id}.jpg"
        else: # Should not happen if PTB filters are correct
            original_file_name = f"file_{message_to_download.id}"


        logger.info(f"[UserAPI] Downloading '{original_file_name}' from Telegram via user account...")
        # Download to a temporary file path
        # Docker containers have ephemeral storage, so this is fine
        temp_file_path = f"./temp_download_{original_file_name.replace(' ', '_')}" # Sanitize filename slightly for path
        
        # Progress callback for Telethon download (optional but good for user experience if bot could update)
        # For now, just download
        downloaded_file_path = await user_client.download_media(message_to_download.media, file=temp_file_path)

        if not downloaded_file_path or not os.path.exists(downloaded_file_path):
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=f"❌ টেলিগ্রাম থেকে '{original_file_name}' ডাউনলোড করতে ব্যর্থ হয়েছে।")
            return
        
        logger.info(f"[UserAPI] Downloaded '{original_file_name}' to {downloaded_file_path}. Uploading to Gofile.io...")
        await ptb_bot_ref.edit_message_text(
            chat_id=original_user_chat_id,
            message_id=bot_status_message_id,
            text=f"'{original_file_name}' Gofile.io তে আপলোড করা হচ্ছে... 📤"
        )

        gofile_server = get_gofile_server()
        upload_url = f"https://{gofile_server}.gofile.io/uploadFile"
        
        gofile_api_response = None
        with open(downloaded_file_path, 'rb') as f:
            files_payload = {'file': (original_file_name, f)} # Use the determined original_file_name for Gofile
            try:
                # Increased timeout for potentially very large files
                response = requests.post(upload_url, files=files_payload, timeout=1800) # 30 mins timeout
                response.raise_for_status()
                gofile_api_response = response.json()
            except requests.exceptions.Timeout:
                logger.error(f"[UserAPI] Gofile.io upload timed out for {original_file_name}")
                await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text="❌ Gofile.io আপলোড টাইম আউট হয়েছে।")
                return
            except requests.exceptions.RequestException as e:
                logger.error(f"[UserAPI] Gofile.io upload error for {original_file_name}: {e}")
                await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=f"❌ Gofile.io আপলোড ত্রুটি: {e}")
                return
            except ValueError: # JSONDecodeError
                 logger.error(f"[UserAPI] Gofile.io JSON decode error for {original_file_name}. Response: {response.text if 'response' in locals() else 'Unknown response'}")
                 await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text="❌ Gofile.io থেকে উত্তর প্রক্রিয়াকরণে ত্রুটি।")
                 return


        if gofile_api_response and gofile_api_response.get("status") == "ok":
            data_payload = gofile_api_response.get("data", {})
            download_link = data_payload.get("downloadPage")
            gofile_file_name = data_payload.get("fileName", original_file_name)
            admin_code = data_payload.get("adminCode")

            if not download_link:
                logger.error(f"[UserAPI] Gofile success but no downloadPage. Data: {data_payload}")
                await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=" Gofile আপলোড সফল হয়েছে, কিন্তু ডাউনলোড লিঙ্ক পাওয়া যায়নি।")
                return

            final_text = (
                f"✅ ফাইল সফলভাবে আপলোড হয়েছে!\n\n"
                f"🏷️ **নাম:** {gofile_file_name}\n"
                f"🔗 **ডাউনলোড লিঙ্ক:** {download_link}"
            )
            if admin_code:
                final_text += f"\n🔑 **অ্যাডমিন কোড:** `{admin_code}` (ফাইল পরিচালনার জন্য)"
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=final_text, disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN_V2)
            logger.info(f"[UserAPI] Successfully processed and sent link for {original_file_name} to user {original_user_chat_id}")
        else:
            error_msg_gofile = gofile_api_response.get('status', 'Unknown Gofile error') if gofile_api_response else "No Gofile response"
            logger.error(f"[UserAPI] Gofile API error: {error_msg_gofile} - Full response: {gofile_api_response}")
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=f"❌ Gofile.io তে আপলোড ব্যর্থ হয়েছে: {error_msg_gofile}")

    except telethon_errors.rpcerrorlist.FileReferenceExpiredError:
        logger.warning(f"[UserAPI] File reference expired for message {file_message_id_in_user_chat} in chat {original_user_chat_id}. Asking user to resend.")
        await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text="❌ ফাইলটি আর টেলিগ্রামে পাওয়া যাচ্ছে না। অনুগ্রহ করে আবার পাঠান।")
    except Exception as e:
        logger.error(f"[UserAPI] Unexpected error in process_file_via_user_api for {original_file_name}: {e}", exc_info=True)
        await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id, text=f"❌ একটি অপ্রত্যাশিত ত্রুটি ঘটেছে: {str(e)[:200]}")
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
        "বড় ফাইল প্রসেস করতে একটু বেশি সময় লাগতে পারে।"
    )
    logger.info(f"User {user.id} ({user.username}) started the bot.")

async def file_handler_ptb(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user
    original_user_chat_id = message.chat_id
    file_message_id_for_telethon = message.message_id # The ID of the message user sent to bot

    # Determine file size approximately (PTB file objects have 'file_size')
    file_size = 0
    if message.document: file_size = message.document.file_size
    elif message.video: file_size = message.video.file_size
    elif message.audio: file_size = message.audio.file_size
    elif message.photo: file_size = message.photo[-1].file_size
    
    logger.info(f"PTB Bot received a file. User: {user.id}, Chat: {original_user_chat_id}, Msg ID: {file_message_id_for_telethon}, Approx Size: {file_size / (1024*1024) if file_size else 0 :.2f} MB")

    bot_status_msg = await message.reply_text("ফাইল পেয়েছি, প্রসেসিং শুরু করছি...")

    # Create a task for Telethon processing to run it in the background
    # This allows PTB to remain responsive if Telethon part takes time.
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
    logger.error(msg="[PTB] Exception while handling an update:", exc_info=context.error)
    if OWNER_ID and isinstance(context.error, Exception): # Avoid sending for non-Exception errors
        try:
            error_details = f"PTB Error: {context.error}\nUpdate: {update}"
            await context.bot.send_message(chat_id=OWNER_ID, text=f" হাইব্রিড বটে একটি ত্রুটি ঘটেছে:\n<pre>{error_details[:4000]}</pre>", parse_mode=ParseMode.HTML)
        except Exception as e_report:
            logger.error(f"Failed to report PTB error to OWNER_ID: {e_report}")


# --- Main Application Setup and Run ---
async def main_hybrid_async():
    # 1. Start and authorize Telethon client (User API part)
    logger.info("Attempting to start Telethon client (User API)...")
    try:
        # user_client.start() will use the session string.
        # If it's invalid or first time and no phone/code_callback, it will fail.
        await user_client.connect()
        if not await user_client.is_user_authorized():
            logger.critical("Telethon client (user account) IS NOT AUTHORIZED. SESSION_STRING is likely invalid or expired. Please regenerate it using generate_session.py and update the environment variable. The bot cannot function for large files without this.")
            if OWNER_ID:
                try:
                    # Assuming ptb_app is not yet available, need a temp bot instance or direct HTTP API call for critical error
                    # For simplicity, this critical error means the bot won't start properly.
                    pass # Cannot easily send Telegram message here without PTB bot up.
                except: pass
            return # Stop further execution if user client cannot auth
        
        me = await user_client.get_me()
        logger.info(f"Telethon client (User API) logged in successfully as: {me.first_name} (@{me.username})")
        if OWNER_ID: # Send startup notification to owner via User API client itself
            try:
                 await user_client.send_message(OWNER_ID, f"হাইব্রিড GoFile বট চালু হয়েছে!\nUser API অংশটি '{me.first_name}' হিসেবে লগইন করেছে।")
            except Exception as e_own:
                logger.warning(f"Could not send startup message to OWNER_ID via User API: {e_own}")
    except Exception as e_telethon_start:
        logger.critical(f"FATAL: Could not start or authorize the Telethon client (User API): {e_telethon_start}", exc_info=True)
        logger.critical("The bot will not be able to process large files. Please check API_ID, API_HASH, SESSION_STRING and network.")
        return # Critical failure

    # 2. Setup PTB application (Bot API part)
    logger.info("Initializing PTB Application (Bot API)...")
    ptb_application = Application.builder().token(BOT_TOKEN).build()

    # Add PTB handlers
    ptb_application.add_handler(CommandHandler("start", start_command_ptb))
    ptb_application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO),
        file_handler_ptb
    ))
    ptb_application.add_error_handler(error_handler_ptb)

    # 3. Run PTB polling alongside Telethon client
    logger.info("Starting PTB Bot polling...")
    try:
        await ptb_application.initialize() # Initializes Application, Bot, Updater etc.
        await ptb_application.start()      # Starts agraceful shutdown handler
        await ptb_application.updater.start_polling(poll_interval=1, timeout=20) # Starts polling in the background (non-blocking)
        
        logger.info("✅ Hybrid Bot is now running! (PTB Polling and Telethon Client active)")
        
        # Keep the Telethon client running (it handles its own disconnects and event loop)
        # This will keep the script alive. PTB polling runs in asyncio tasks.
        await user_client.run_until_disconnected()

    except Exception as e_main_run:
        logger.critical(f"FATAL: An error occurred while running the main hybrid application: {e_main_run}", exc_info=True)
    finally:
        logger.info("Shutting down PTB Application...")
        if 'ptb_application' in locals() and ptb_application.updater and ptb_application.updater.running:
            await ptb_application.updater.stop()
        if 'ptb_application' in locals() and ptb_application.running: # Check if ptb_application was defined and started
            await ptb_application.stop()
        # await ptb_application.shutdown() # PTB's shutdown includes stop() and more

        logger.info("Disconnecting Telethon client...")
        if user_client.is_connected():
            await user_client.disconnect()
        
        logger.info("Hybrid Bot shutdown complete.")


if __name__ == "__main__":
    if not SESSION_STRING: # Crucial check before starting
        print("❌ CRITICAL ERROR: SESSION_STRING environment variable is not set.")
        print("   Please generate it using 'generate_session.py' and set it in your environment.")
        print("   The bot will not start without it.")
    else:
        # Run the main async function
        try:
            asyncio.run(main_hybrid_async())
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Shutting down...")
        except Exception as e_global:
            logger.critical(f"A critical unhandled exception occurred at the global level: {e_global}", exc_info=True)
