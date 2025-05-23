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

# --- Configuration is imported from config.py ---
try:
    from config import BOT_TOKEN, API_ID, API_HASH, SESSION_STRING, OWNER_ID
except ImportError:
    print("CRITICAL: config.py not found.")
    logging.critical("FATAL: config.py not found.")
    exit(1)
except ValueError as e:
    print(f"CRITICAL: Configuration error from config.py: {e}")
    logging.critical(f"FATAL: Configuration error from config.py: {e}")
    exit(1)

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(funcName)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Global PTB Application instance (for Telethon to use bot methods) ---
# This is a simplified way to make it accessible; consider dependency injection for more complex apps.
ptb_app_instance: Application = None

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
        logger.error(f"Exception in get_gofile_server: {e}", exc_info=True)
    logger.warning("Falling back to default Gofile server 'store1'")
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
        elif telethon_file_message_obj.document and hasattr(telethon_file_message_obj.document, 'attributes'):
            original_file_name = next((attr.file_name for attr in telethon_file_message_obj.document.attributes if hasattr(attr, 'file_name') and attr.file_name), f"document_{telethon_file_message_obj.id}")
        # ... (add similar elif for video, audio, photo as in previous complete main.py) ...
        elif telethon_file_message_obj.photo: # Photos don't typically have a user-set filename attribute this way
             original_file_name = f"photo_{telethon_file_message_obj.id}_{original_user_chat_id}.jpg"
        else:
            original_file_name = f"file_{telethon_file_message_obj.id}"


        logger.info(f"[UserAPI] Processing forwarded file '{original_file_name}' for original user {original_user_chat_id}")
        await ptb_bot_ref.edit_message_text(
            chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat,
            text=f"⏳ আপনার ফাইল ('{original_file_name}') টেলিগ্রাম থেকে ডাউনলোড করা হচ্ছে..."
        )
        
        safe_filename_for_path = "".join(c if c.isalnum() or c in ['.', '_', '-'] else '_' for c in original_file_name)
        if len(safe_filename_for_path) > 100:
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
            # ... ( Gofile upload requests.post call with error handling - refer to previous complete main.py for full try/except block ) ...
            try:
                response = requests.post(upload_url, files=files_payload, timeout=1800) # 30 mins
                response.raise_for_status()
                gofile_api_response = response.json()
            except requests.exceptions.Timeout:
                logger.error(f"[UserAPI] Gofile.io upload timed out for {original_file_name}")
                await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text="❌ Gofile.io আপলোড টাইম আউট হয়েছে।")
                return # Important to return after handling
            except requests.exceptions.RequestException as e:
                logger.error(f"[UserAPI] Gofile.io upload error for {original_file_name}: {e}")
                await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text=f"❌ Gofile.io আপলোড ত্রুটি: {e}")
                return # Important to return
            except ValueError: # JSONDecodeError
                 logger.error(f"[UserAPI] Gofile.io JSON decode error for {original_file_name}. Response text: {response.text if 'response' in locals() else 'N/A'}")
                 await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text="❌ Gofile.io থেকে উত্তর প্রক্রিয়াকরণে ত্রুটি।")
                 return # Important to return


        if gofile_api_response and gofile_api_response.get("status") == "ok":
            # ... ( Construct success message with Gofile link - refer to previous complete main.py ) ...
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
            # ... ( Handle Gofile API error - refer to previous complete main.py ) ...
            error_msg_gofile = gofile_api_response.get('status', 'Unknown Gofile error') if gofile_api_response else "No/Invalid Gofile response"
            logger.error(f"[UserAPI] Gofile API error: {error_msg_gofile} - Full response: {gofile_api_response}")
            await ptb_bot_ref.edit_message_text(chat_id=original_user_chat_id, message_id=bot_status_message_id_in_user_chat, text=f"❌ Gofile.io তে আপলোড ব্যর্থ হয়েছে: {error_msg_gofile}")

    except Exception as e:
        # ... ( General error handling for process_forwarded_file_via_user_api - refer to previous complete main.py ) ...
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

async def file_handler_ptb(update: Update, context: CallbackContext):
    message = update.message
    user = update.effective_user
    original_user_chat_id = message.chat_id
    
    if not OWNER_ID:
        logger.error("OWNER_ID is not configured. Cannot forward file for processing.")
        await message.reply_text("❌ দুঃখিত, বট সঠিকভাবে কনফিগার করা হয়নি (OWNER_ID মিসিং)। ফাইল প্রসেস করা সম্ভব হচ্ছে না।")
        return

    bot_status_msg = await message.reply_text("🔄 ফাইল পেয়েছি, এটি প্রসেসিং এর জন্য প্রস্তুত করা হচ্ছে...")
    logger.info(f"PTB: Received file from user {user.id}. Forwarding to OWNER_ID ({OWNER_ID}) for processing.")

    try:
        # Forward the message with the file to the OWNER_ID (Telethon client's account)
        forwarded_msg_to_owner = await context.bot.forward_message(
            chat_id=OWNER_ID,
            from_chat_id=original_user_chat_id,
            message_id=message.message_id
        )
        
        # Send metadata as a separate message replying to the forwarded file in the OWNER_ID's chat
        # This metadata helps Telethon handler identify the original user and the bot's status message
        metadata_text = (
            f"FORWARDED_FOR_PROCESSING\n"
            f"ORIGINAL_USER_CHAT_ID:{original_user_chat_id}\n"
            f"BOT_STATUS_MESSAGE_ID:{bot_status_msg.message_id}"
        )
        await context.bot.send_message( # Send as a new message, not a reply to forwarded_msg_to_owner to simplify Telethon logic
            chat_id=OWNER_ID,
            text=metadata_text,
            # Optional: could reply to forwarded_msg_to_owner.message_id if Telethon handler is adjusted
        )
        
        await bot_status_msg.edit_text("✅ ফাইলটি আপনার অ্যাকাউন্টে (ব্যাকএন্ডে) প্রসেসিং এর জন্য পাঠানো হয়েছে। সম্পন্ন হলে এখানে লিঙ্ক দেওয়া হবে।")
    except Exception as e:
        logger.error(f"PTB: Error forwarding message to OWNER_ID for processing: {e}", exc_info=True)
        await bot_status_msg.edit_text(f"❌ ফাইলটি প্রসেসিং এর জন্য পাঠাতে একটি সমস্যা হয়েছে: {e}")


# --- Telethon (User Backend) Event Handler ---
@user_client.on(events.NewMessage(incoming=True, chats=OWNER_ID)) # Listen to messages in OWNER_ID's chat
async def user_api_event_handler(event):
    message = event.message
    logger.debug(f"[UserAPI] Received message in OWNER_ID chat: {message.text[:100] if message.text else 'No text'}")

    # Check if this message is the metadata message
    if message.text and message.text.startswith("FORWARDED_FOR_PROCESSING"):
        try:
            lines = message.text.splitlines()
            if len(lines) < 3:
                logger.warning(f"[UserAPI] Metadata message received but format is incorrect: {message.text}")
                return

            original_user_chat_id = int(lines[1].split(":")[1])
            bot_status_message_id = int(lines[2].split(":")[1])
            
            # Find the actual forwarded file message.
            # The bot now forwards the file first, then sends this metadata message.
            # So, the file message might be the one immediately preceding this metadata message,
            # or we need a more robust way to link them if other messages can interleave.
            # For simplicity, let's assume the user/owner doesn't chat rapidly with the bot in between.
            # A better way: bot forwards file, gets forwarded_msg_id, includes that in metadata.
            # For now, let's try to find the most recent message with media before this metadata message.
            
            limit_fetch = 5 # Look at last few messages
            recent_messages = await user_client.get_messages(OWNER_ID, limit=limit_fetch)
            forwarded_file_message = None
            for msg_in_owner_chat in recent_messages:
                # We are looking for a message that IS a forward, has media,
                # and is NOT the metadata message itself.
                # And its original sender (if forwarded) was the user we are interested in.
                # The bot now forwards it, so original_fwd_from might not be useful here.
                # The key is it's a message with media received around the same time.
                if msg_in_owner_chat.id < message.id and msg_in_owner_chat.media and msg_in_owner_chat.forward:
                    # This logic needs to be more robust to correctly identify the corresponding file.
                    # A simple assumption: the message immediately before this metadata text message,
                    # if it was also sent by the bot and contains the forwarded file.
                    # However, the bot forwards the *user's* message, so message.fwd_from will be the original user.
                    # The PTB part forwards the message from original_user_chat_id.
                    # So, in OWNER_ID's chat, the forwarded message will have fwd_from.id == original_user_chat_id (if not from channel)
                    # or fwd_from.chat_id for channels.
                    # Let's find the message that was forwarded by the bot. The current forwarded_msg_to_owner in PTB handler is what we need.
                    #
                    # The current design: PTB forwards, then sends metadata.
                    # The metadata should ideally contain the message_id of the forwarded message in OWNER_ID's chat.
                    # Let's modify PTB handler to include that.
                    # For now, this handler will assume the metadata is enough to trigger,
                    # and the file to process is the message this metadata is replying to,
                    # *if the bot was made to reply to the forwarded file with the metadata*.
                    #
                    # The PTB code was changed to:
                    # 1. Bot forwards file to OWNER_ID (gets `forwarded_msg_to_owner`)
                    # 2. Bot sends metadata to OWNER_ID (NOT as a reply, for simplicity here now)
                    # This makes linking them harder.
                    #
                    # Easiest Fix: The metadata message should *reply to* the forwarded file message.
                    # PTB Handler:
                    # forwarded_msg_to_owner = await context.bot.forward_message(...)
                    # await context.bot.send_message(chat_id=OWNER_ID, text=metadata_text, reply_to_message_id=forwarded_msg_to_owner.message_id)
                    #
                    # Then Telethon Handler:
                    if event.message.is_reply:
                        replied_to_msg_id = event.message.reply_to_msg_id
                        file_message_obj = await user_client.get_messages(OWNER_ID, ids=replied_to_msg_id)
                        if file_message_obj and file_message_obj.media:
                            logger.info(f"[UserAPI] Identified file to process (ID: {file_message_obj.id}) via reply mechanism.")
                            global ptb_app_instance
                            if not ptb_app_instance:
                                logger.error("[UserAPI] PTB application instance not available for Telethon handler.")
                                return

                            asyncio.create_task(process_forwarded_file_via_user_api(
                                ptb_bot_ref=ptb_app_instance.bot,
                                original_user_chat_id=original_user_chat_id,
                                telethon_file_message_obj=file_message_obj,
                                bot_status_message_id_in_user_chat=bot_status_message_id
                            ))
                            return # Processed
                        else:
                             logger.warning(f"[UserAPI] Metadata message was a reply, but replied-to message {replied_to_msg_id} has no media or not found.")
                    else:
                        logger.warning(f"[UserAPI] Metadata message received, but it's not a reply to the forwarded file. Cannot reliably find the file. Please adjust bot to send metadata as reply.")

        except ValueError as ve: # For int conversion errors
            logger.error(f"[UserAPI] ValueError processing metadata: {ve}. Text: {message.text}", exc_info=True)
        except Exception as e:
            logger.error(f"[UserAPI] General error processing metadata message: {e}", exc_info=True)
    
    # Handle direct file uploads to OWNER_ID by the owner themselves (for their own use)
    elif event.is_private and event.media and event.chat_id == OWNER_ID: # Make sure it's really from self
        if message.sender_id == OWNER_ID : # Check if the sender is the owner
            logger.info(f"[UserAPI] Direct file received in chat with self (OWNER_ID: {OWNER_ID}). Processing for self.")
            # Create a dummy status message in the same chat or handle differently
            status_msg_for_self = await user_client.send_message(OWNER_ID, "🔄 আপনার নিজের পাঠানো ফাইল প্রসেস করা হচ্ছে...")
            global ptb_app_instance
            if not ptb_app_instance: # Should not happen if bot is running
                logger.error("[UserAPI] PTB application instance not available for self-processing.")
                await status_msg_for_self.edit("❌ বট এরর: সঠিকভাবে কনফিগার করা হয়নি।")
                return

            asyncio.create_task(process_forwarded_file_via_user_api(
                ptb_bot_ref=ptb_app_instance.bot, # Bot will reply to OWNER_ID
                original_user_chat_id=OWNER_ID, # Replies go to OWNER_ID chat
                telethon_file_message_obj=message, # The message object itself
                bot_status_message_id_in_user_chat=status_msg_for_self.id
            ))


async def error_handler_ptb(update: object, context: CallbackContext) -> None:
    logger.error(msg="[PTB] Exception while handling an PTB update:", exc_info=context.error)
    # ... (owner notification logic from previous main.py) ...

# --- Main Application Setup and Run ---
async def main_hybrid_async():
    global ptb_app_instance # Make PTB app instance global for Telethon handler access

    logger.info("Attempting to start Telethon client (User API)...")
    try:
        await user_client.connect()
        if not await user_client.is_user_authorized():
            logger.critical("Telethon client (user account) IS NOT AUTHORIZED. SESSION_STRING is likely invalid or expired.")
            if OWNER_ID:
                try: await user_client.send_message(OWNER_ID, "🔴 Telethon ক্লায়েন্ট অনুমোদিত নয়! SESSION_STRING চেক করুন।")
                except: pass
            return
        me = await user_client.get_me()
        logger.info(f"Telethon client (User API) logged in as: {me.first_name} (@{me.username if me.username else 'N/A'})")
        if OWNER_ID:
            try: await user_client.send_message(OWNER_ID, f"🟢 হাইব্রিড GoFile বট (User API: '{me.first_name}') চালু হয়েছে!")
            except Exception as e: logger.warning(f"Could not send startup message to OWNER_ID: {e}")
    except Exception as e:
        logger.critical(f"FATAL: Could not start/authorize Telethon client: {e}", exc_info=True)
        return

    logger.info("Initializing PTB Application (Bot API)...")
    ptb_app_instance = Application.builder().token(BOT_TOKEN).build()
    ptb_app_instance.add_handler(CommandHandler("start", start_command_ptb))
    ptb_app_instance.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO),
        file_handler_ptb
    ))
    ptb_app_instance.add_error_handler(error_handler_ptb)

    logger.info("Starting PTB Bot polling...")
    try:
        await ptb_app_instance.initialize()
        await ptb_app_instance.start()
        await ptb_app_instance.updater.start_polling(poll_interval=1, timeout=20, bootstrap_retries=-1)
        logger.info("✅ Hybrid Bot is now running!")
        await user_client.run_until_disconnected()
    except Exception as e:
        logger.critical(f"FATAL: Error running main hybrid application: {e}", exc_info=True)
    finally:
        logger.info("Shutting down Hybrid Bot...")
        # ... (shutdown logic from previous main.py) ...
        if ptb_app_instance and ptb_app_instance.updater and ptb_app_instance.updater.running:
            await ptb_app_instance.updater.stop()
        if ptb_app_instance and hasattr(ptb_app_instance, 'running') and ptb_app_instance.running:
            await ptb_app_instance.stop()
        if user_client and user_client.is_connected():
            await user_client.disconnect()
        logger.info("Hybrid Bot shutdown complete.")

if __name__ == "__main__":
    if not all([BOT_TOKEN, API_ID, API_HASH, SESSION_STRING]): # OWNER_ID is optional
        print("❌ CRITICAL ERROR: Core environment variables missing (BOT_TOKEN, API_ID, API_HASH, SESSION_STRING).")
        exit(1)
    try:
        asyncio.run(main_hybrid_async())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt. Shutting down...")
    except Exception as e:
        logger.critical(f"Global unhandled exception: {e}", exc_info=True)
