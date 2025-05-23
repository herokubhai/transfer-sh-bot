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

# --- Global PTB Application instance (for Telethon to use bot methods) ---
ptb_app_instance: Application = None

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
user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH, base_logger=logger.getChild('TelethonClient'))


# --- Core File Processing (using Telethon, now takes Telethon message object) ---
async def process_forwarded_file_via_user_api(ptb_bot_ref, original_user_chat_id, telethon_file_message_obj, bot_status_message_id_in_user_chat):
    original_file_name = "unknown_file"
    temp_file_path = None 

    try:
        # Determine original file name from Telethon message object
        if hasattr(telethon_file_message_obj, 'file') and hasattr(telethon_file_message_obj.file, 'name') and telethon_file_message_obj.file.name:
            original_file_name = telethon_file_message_obj.file.name
        elif telethon_file_message_obj.document and hasattr(telethon_file_message_obj.document, 'attributes'): # Check attributes exist
            original_file_name = next((attr.file_name for attr in telethon_file_message_obj.document.attributes if hasattr(attr, 'file_name') and attr.file_name), f"document_{telethon_file_message_obj.id}")
        elif telethon_file_message_obj.video and hasattr(telethon_file_message_obj.video, 'attributes'):
             original_file_name = next((attr.file_name for attr in telethon_file_message_obj.video.attributes if hasattr(attr, 'file_name') and attr.file_name), f"video_{telethon_file_message_obj.id}.mp4")
        elif telethon_file_message_obj.audio and hasattr(telethon_file_message_obj.audio, 'attributes'):
             original_file_name = next((attr.file_name for attr in telethon_file_message_obj.audio.attributes if hasattr(attr, 'file_name') and attr.file_name), f"audio_{telethon_file_message_obj.id}.mp3")
        elif telethon_file_message_obj.photo:
             original_file_name = f"photo_{telethon_file_message_obj.id}_{original_user_chat_id}.jpg"
        else:
            original_file_name = f"file_{telethon_file_message_obj.id}"


        logger.info(f"[UserAPI] Processing forwarded file '{original_file_name}' for original user {original_user_chat_id}")
        await ptb_bot_ref.edit_message_text(
            chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat,
            text=f"⏳ আপনার ফাইল ('{original_file_name}') টেলিগ্রাম থেকে ডাউনলোড করা হচ্ছে..."
        )
        
        safe_filename_for_path = "".join(c if c.isalnum() or c in ['.', '_', '-'] else '_' for c in original_file_name)
        if len(safe_filename_for_path) > 100: # Limit length
            name_part, ext_part = os.path.splitext(safe_filename_for_path)
            safe_filename_for_path = name_part[:100-len(ext_part)-1] + ext_part if ext_part else name_part[:100]
        temp_file_path = f"./temp_download_{safe_filename_for_path}"

        downloaded_file_path = await user_client.download_media(telethon_file_message_obj.media, file=temp_file_path)

        if not downloaded_file_path or not os.path.exists(downloaded_file_path):
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text=f"❌ টেলিগ্রাম থেকে '{original_file_name}' ডাউনলোড করতে ব্যর্থ হয়েছে।")
            return
        
        file_size_mb = os.path.getsize(downloaded_file_path) / (1024 * 1024)
        logger.info(f"[UserAPI] Downloaded '{original_file_name}' ({file_size_mb:.2f} MB). Uploading to Gofile.io...")
        await ptb_bot_ref.edit_message_text(
            chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat,
            text=f"⏳ '{original_file_name}' ({file_size_mb:.2f} MB) Gofile.io তে আপলোড করা হচ্ছে..."
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
                await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text="❌ Gofile.io আপলোড টাইম আউট হয়েছে। ফাইলটি খুব বড় অথবা সার্ভারে সমস্যা হতে পারে।")
                return
            except requests.exceptions.RequestException as e:
                logger.error(f"[UserAPI] Gofile.io upload error for {original_file_name}: {e}")
                await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text=f"❌ Gofile.io আপলোড ত্রুটি: {e}")
                return
            except ValueError: 
                 logger.error(f"[UserAPI] Gofile.io JSON decode error for {original_file_name}. Response text: {response.text if 'response' in locals() else 'N/A'}")
                 await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text="❌ Gofile.io থেকে উত্তর প্রক্রিয়াকরণে ত্রুটি।")
                 return

        if gofile_api_response and gofile_api_response.get("status") == "ok":
            data_payload = gofile_api_response.get("data", {})
            download_link = data_payload.get("downloadPage")
            gofile_file_name = data_payload.get("fileName", original_file_name)
            admin_code = data_payload.get("adminCode")

            if not download_link:
                logger.error(f"[UserAPI] Gofile success but no downloadPage. Data: {data_payload}")
                await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text="✅ Gofile আপলোড সফল হয়েছে, কিন্তু ডাউনলোড লিঙ্ক পাওয়া যায়নি।")
                return

            final_text = (
                f"✅ ফাইল সফলভাবে আপলোড হয়েছে!\n\n"
                f"🏷️ **নাম:** {gofile_file_name}\n"
                f"🔗 **ডাউনলোড লিঙ্ক:** {download_link}"
            )
            if admin_code:
                final_text += f"\n🔑 **অ্যাডমিন কোড:** `{admin_code}` (ফাইল পরিচালনার জন্য)"
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text=final_text, disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN_V2)
            logger.info(f"[UserAPI] Successfully processed and sent link for '{original_file_name}' to user {original_user_chat_id}")
        else:
            error_msg_gofile = gofile_api_response.get('status', 'Unknown Gofile error') if gofile_api_response else "No/Invalid Gofile response"
            logger.error(f"[UserAPI] Gofile API error: {error_msg_gofile} - Full response: {gofile_api_response}")
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text=f"❌ Gofile.io তে আপলোড ব্যর্থ হয়েছে: {error_msg_gofile}")

    except telethon_errors.rpcerrorlist.FileReferenceExpiredError:
        logger.warning(f"[UserAPI] File reference expired for message in chat {original_user_chat_id}.")
        await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text="❌ ফাইলটি আর টেলিগ্রামে পাওয়া যাচ্ছে না (File Reference Expired)। অনুগ্রহ করে আবার পাঠান।")
    except telethon_errors.FloodWaitError as e:
        logger.warning(f"[UserAPI] Flood wait error: {e}. Waiting for {e.seconds} seconds.")
        await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text=f"⏳ টেলিগ্রাম কিছুক্ষণের জন্য অপেক্ষা করতে বলছে (Flood Wait: {e.seconds}s)। একটু পর আবার চেষ্টা করুন।")
        # await asyncio.sleep(e.seconds + 5) # Caution: sleeping here blocks this handler. Task might be better.
    except Exception as e:
        logger.error(f"[UserAPI] Unexpected error in process_forwarded_file_via_user_api for '{original_file_name}': {e}", exc_info=True)
        await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text=f"❌ একটি অপ্রত্যাশিত ত্রুটি ঘটেছে ফাইল প্রসেসিং এর সময়: {str(e)[:200]}")
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
    
    if not OWNER_ID: # OWNER_ID must be set for the forwarding logic to work
        logger.error("PTB: OWNER_ID is not configured in environment variables. Cannot forward file for processing by User API.")
        await message.reply_text("❌ দুঃখিত, বট সঠিকভাবে কনফিগার করা হয়নি (বট অ্যাডমিনের আইডি সেট করা নেই)। ফাইল প্রসেস করা সম্ভব হচ্ছে না।")
        return

    bot_status_msg = await message.reply_text("🔄 ফাইল পেয়েছি, এটি প্রসেসিং এর জন্য প্রস্তুত করা হচ্ছে...")
    logger.info(f"PTB: Received file from user {user.id}. Forwarding to OWNER_ID ({OWNER_ID}) for processing.")

    try:
        # Forward the message with the file to the OWNER_ID (Telethon client's account)
        forwarded_msg_to_owner = await context.bot.forward_message(
            chat_id=OWNER_ID, # This must be the User ID of the account Telethon is logged into
            from_chat_id=original_user_chat_id,
            message_id=message.message_id
        )
        
        # Send metadata as a separate message *replying to the forwarded file* in the OWNER_ID's chat
        metadata_text = (
            f"FORWARDED_FOR_PROCESSING\n"
            f"ORIGINAL_USER_CHAT_ID:{original_user_chat_id}\n"
            f"BOT_STATUS_MESSAGE_ID:{bot_status_msg.message_id}"
        )
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=metadata_text,
            reply_to_message_id=forwarded_msg_to_owner.message_id # Crucial: reply to the forwarded message
        )
        
        await bot_status_msg.edit_text("✅ ফাইলটি আপনার ব্যক্তিগত অ্যাকাউন্টে (ব্যাকএন্ডে) প্রসেসিং এর জন্য সফলভাবে পাঠানো হয়েছে। সম্পন্ন হলে এখানে লিঙ্ক দেওয়া হবে।")
    except Exception as e:
        logger.error(f"PTB: Error forwarding message to OWNER_ID for processing: {e}", exc_info=True)
        await bot_status_msg.edit_text(f"❌ ফাইলটি প্রসেসিং এর জন্য পাঠাতে একটি সমস্যা হয়েছে: {str(e)[:200]}")


# --- Telethon (User Backend) Event Handler ---
@user_client.on(events.NewMessage(incoming=True, chats=OWNER_ID)) # Listen to messages in OWNER_ID's chat
async def user_api_event_handler(event):
    message = event.message # This is the metadata message from the bot
    logger.debug(f"[UserAPI] Received message in OWNER_ID chat: '{message.text[:100] if message.text else 'No text'}'")

    # Check if this message is the metadata message and if it's a reply
    if message.text and message.text.startswith("FORWARDED_FOR_PROCESSING") and message.is_reply:
        try:
            lines = message.text.splitlines()
            if len(lines) < 3:
                logger.warning(f"[UserAPI] Metadata message received but format is incorrect: {message.text}")
                return

            original_user_chat_id_str = lines[1].split(":", 1)[1]
            bot_status_message_id_str = lines[2].split(":", 1)[1]
            
            original_user_chat_id = int(original_user_chat_id_str)
            bot_status_message_id = int(bot_status_message_id_str)
            
            replied_to_msg_id = message.reply_to_message_id # ID of the forwarded file message
            file_message_obj = await user_client.get_messages(OWNER_ID, ids=replied_to_msg_id)

            if file_message_obj and file_message_obj.media:
                logger.info(f"[UserAPI] Identified file to process (ID: {file_message_obj.id} in OWNER_ID chat) via reply mechanism for original user {original_user_chat_id}.")
                
                # Access the global ptb_app_instance (defined at module level, assigned in main_hybrid_async)
                if not ptb_app_instance:
                    logger.error("[UserAPI] PTB application instance (ptb_app_instance) is not available for Telethon handler to send reply.")
                    return # Cannot proceed without PTB bot instance

                # Create a new task so this handler can return quickly
                asyncio.create_task(process_forwarded_file_via_user_api(
                    ptb_bot_ref=ptb_app_instance.bot, # Pass the PTB bot object
                    original_user_chat_id=original_user_chat_id,
                    telethon_file_message_obj=file_message_obj, # The actual message with media
                    bot_status_message_id_in_user_chat=bot_status_message_id
                ))
            else:
                 logger.warning(f"[UserAPI] Metadata message was a reply, but replied-to message (ID: {replied_to_msg_id}) has no media or not found in OWNER_ID chat.")

        except ValueError as ve:
            logger.error(f"[UserAPI] ValueError processing metadata: {ve}. Text: '{message.text}'", exc_info=True)
        except Exception as e:
            logger.error(f"[UserAPI] General error processing metadata message in Telethon handler: {e}", exc_info=True)
    
    # Handle direct file uploads to OWNER_ID by the owner themselves (for their own use)
    # Ensure this doesn't conflict with the metadata message logic
    elif not (message.text and message.text.startswith("FORWARDED_FOR_PROCESSING")) and \
         event.is_private and event.media and event.chat_id == OWNER_ID and message.sender_id == OWNER_ID:
            logger.info(f"[UserAPI] Direct file received in chat with self (OWNER_ID: {OWNER_ID}). Processing for self.")
            try:
                status_msg_for_self = await user_client.send_message(OWNER_ID, "🔄 আপনার নিজের পাঠানো ফাইল প্রসেস করা হচ্ছে...", reply_to=message.id)
                
                if not ptb_app_instance:
                    logger.error("[UserAPI] PTB application instance (ptb_app_instance) is not available for self-processing via UserAPI.")
                    await status_msg_for_self.edit("❌ বট কনফিগারেশন ত্রুটি (PTB instance missing)।")
                    return

                asyncio.create_task(process_forwarded_file_via_user_api(
                    ptb_bot_ref=ptb_app_instance.bot, 
                    original_user_chat_id=OWNER_ID, 
                    telethon_file_message_obj=message, 
                    bot_status_message_id_in_user_chat=status_msg_for_self.id
                ))
            except Exception as e:
                logger.error(f"[UserAPI] Error handling direct file from owner: {e}", exc_info=True)


async def error_handler_ptb(update: object, context: CallbackContext) -> None:
    """Log Errors caused by PTB Updates and optionally notify OWNER_ID."""
    logger.error(msg="[PTB] Exception while handling an PTB update:", exc_info=context.error)
    if OWNER_ID and isinstance(context.error, Exception):
        try:
            error_details = f"PTB Bot Error: {context.error}\n\nUpdate Details (truncated):\n{str(update)[:1000]}"
            if len(error_details) > 4000: error_details = error_details[:4000] + "\n...(truncated)"
            
            bot_instance_for_error = context.application.bot if context.application else (ptb_app_instance.bot if ptb_app_instance else None)
            if bot_instance_for_error:
                 await bot_instance_for_error.send_message(
                     chat_id=OWNER_ID,
                     text=f"⚠️ হাইব্রিড বটে একটি ত্রুটি ঘটেছে (PTB অংশ):\n<pre>{error_details}</pre>",
                     parse_mode=ParseMode.HTML
                 )
            else:
                logger.warning("[PTB] Could not send error report to OWNER_ID as bot instance was not available.")
        except Exception as e_report:
            logger.error(f"[PTB] Failed to report PTB error to OWNER_ID: {e_report}")


# --- Main Application Setup and Run ---
async def main_hybrid_async():
    global ptb_app_instance # Declare that we will assign to the global ptb_app_instance

    # 1. Start and authorize Telethon client (User API part)
    logger.info("Attempting to start Telethon client (User API)...")
    try:
        await user_client.connect()
        if not await user_client.is_user_authorized():
            logger.critical("Telethon client (user account) IS NOT AUTHORIZED. SESSION_STRING is likely invalid or expired. Please regenerate it using generate_session.py and update the environment variable. The bot cannot function for large files without this.")
            if OWNER_ID:
                try: 
                    # Try sending message via user_client itself IF it's connected but not authorized
                    if user_client.is_connected():
                        await user_client.send_message(OWNER_ID, "🔴 জরুরি সতর্কবার্তা: Telethon ক্লায়েন্ট (ইউজার অ্যাকাউন্ট) অনুমোদিত নয়! SESSION_STRING সম্ভবত ভুল বা মেয়াদোত্তীর্ণ। বট বড় ফাইল প্রসেস করতে পারবে না।")
                except Exception as e_auth_notify:
                     logger.error(f"Failed to send auth error notification to OWNER_ID via UserAPI: {e_auth_notify}")
            return 
        
        me = await user_client.get_me()
        logger.info(f"Telethon client (User API) logged in successfully as: {me.first_name} (@{me.username if me.username else 'N/A'})")
        if OWNER_ID:
            try:
                 await user_client.send_message(OWNER_ID, f"🟢 হাইব্রিড GoFile বট চালু হয়েছে!\n👤 User API অংশটি '{me.first_name}' (@{me.username if me.username else 'N/A'}) হিসেবে লগইন করেছে।")
            except Exception as e_own_startup_msg:
                logger.warning(f"Could not send startup message to OWNER_ID via User API: {e_own_startup_msg}")
    except Exception as e_telethon_start:
        logger.critical(f"FATAL: Could not start or authorize the Telethon client (User API): {e_telethon_start}", exc_info=True)
        logger.critical("The bot will not be able to process large files. Please check API_ID, API_HASH, SESSION_STRING and network connectivity.")
        return

    # 2. Setup PTB application (Bot API part)
    logger.info("Initializing PTB Application (Bot API)...")
    # Assign to the global instance here
    ptb_app_instance = Application.builder().token(BOT_TOKEN).build()

    ptb_app_instance.add_handler(CommandHandler("start", start_command_ptb))
    ptb_app_instance.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO),
        file_handler_ptb
    ))
    ptb_app_instance.add_error_handler(error_handler_ptb)

    # 3. Run PTB polling alongside Telethon client
    logger.info("Starting PTB Bot polling...")
    try:
        await ptb_app_instance.initialize()
        await ptb_app_instance.start()
        await ptb_app_instance.updater.start_polling(poll_interval=1, timeout=20, bootstrap_retries=-1)
        
        logger.info("✅ Hybrid Bot is now running! (PTB Polling and Telethon Client active)")
        
        await user_client.run_until_disconnected() # This keeps the main script alive for Telethon

    except Exception as e_main_run:
        logger.critical(f"FATAL: An error occurred while running the main hybrid application: {e_main_run}", exc_info=True)
    finally:
        logger.info("Initiating shutdown sequence for Hybrid Bot...")
        
        if ptb_app_instance and ptb_app_instance.updater and ptb_app_instance.updater.running:
            logger.info("Stopping PTB Application polling...")
            await ptb_app_instance.updater.stop()
        
        if ptb_app_instance and hasattr(ptb_app_instance, 'running') and ptb_app_instance.running:
            logger.info("Stopping PTB Application...")
            await ptb_app_instance.stop()
        
        if user_client and user_client.is_connected():
            logger.info("Disconnecting Telethon client (User API)...")
            await user_client.disconnect()
        
        logger.info("Hybrid Bot shutdown complete.")


if __name__ == "__main__":
    if not all([BOT_TOKEN, API_ID, API_HASH, SESSION_STRING]): # OWNER_ID is optional but recommended for this hybrid setup
        print("❌ CRITICAL ERROR: Core environment variables missing (BOT_TOKEN, API_ID, API_HASH, SESSION_STRING).")
        print("   These should be loaded via config.py from your environment.")
        print("   The bot will not start.")
        exit(1)
    
    if not OWNER_ID:
        logger.warning("Warning: OWNER_ID is not set. The bot's file forwarding mechanism for large files relies on OWNER_ID. Please set it for full functionality.")
        # Depending on strictness, you might choose to exit(1) here too if OWNER_ID is critical for your flow.
        # For now, it will log a warning and try to run, but file forwarding will fail.

    try:
        asyncio.run(main_hybrid_async())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received by asyncio.run. Shutting down gracefully...")
    except Exception as e_global:
        logger.critical(f"A critical unhandled exception occurred at the global level, shutting down: {e_global}", exc_info=True)
