import logging
import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get Bot Token from environment variable
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable not set!")
    exit(1)

def get_gofile_server():
    """Gets the best available Gofile server."""
    try:
        response = requests.get("https://api.gofile.io/getServer", timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "ok":
            return data.get("data", {}).get("server")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting Gofile server: {e}")
    except (KeyError, ValueError) as e: # ValueError for JSON decoding issues
        logger.error(f"Unexpected response format or content from Gofile getServer: {e}")
    return "store1" # Fallback server

# Handler for /start command
async def start(update: Update, context: CallbackContext) -> None:
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text(
        "Hello! Send me any file, and I'll upload it to Gofile.io and give you a download link."
    )

# Handler for file uploads
async def handle_file(update: Update, context: CallbackContext) -> None:
    """Handles file uploads, uploads them to Gofile.io, and sends back the link."""
    message = update.message
    file_to_upload = None
    file_type_for_name = "file" # Default for naming
    original_file_name = None # To store the name from Telegram

    if message.document:
        file_to_upload = message.document
        original_file_name = file_to_upload.file_name
        file_type_for_name = "document"
    elif message.video:
        file_to_upload = message.video
        original_file_name = file_to_upload.file_name
        file_type_for_name = "video"
    elif message.audio:
        file_to_upload = message.audio
        original_file_name = file_to_upload.file_name
        file_type_for_name = "audio"
    elif message.photo:
        file_to_upload = message.photo[-1] # Take the largest photo
        # Photos don't have a 'file_name' attribute directly in the PhotoSize object
        # We will generate one later if Gofile doesn't provide one
        file_type_for_name = "photo"
    else:
        await message.reply_text("Sorry, I can only handle documents, videos, audio files, and photos.")
        return

    bot_message = None # Initialize bot_message
    try:
        bot_message = await message.reply_text("Downloading your file...")
        new_file = await context.bot.get_file(file_to_upload.file_id)

        # Generate a filename if not available (e.g., for photos, or if original_file_name is None)
        if not original_file_name:
            extension = new_file.file_path.split('.')[-1].split('?')[0] if new_file.file_path and '.' in new_file.file_path else 'dat'
            original_file_name = f"{file_type_for_name}_{file_to_upload.file_unique_id}.{extension}"

        await bot_message.edit_text(f"Downloading '{original_file_name}' complete. Now uploading to Gofile.io...")

        file_bytes = await new_file.download_as_bytearray()

        # Prepare for Gofile.io upload
        server = get_gofile_server()
        if not server:
            logger.error("Could not get a Gofile server. Aborting upload.")
            await bot_message.edit_text("Sorry, could not connect to Gofile.io servers. Please try again later.")
            return
            
        upload_url = f"https://{server}.gofile.io/uploadFile"
        files_payload = {'file': (original_file_name, bytes(file_bytes))}

        # Upload to Gofile.io
        gofile_response = requests.post(upload_url, files=files_payload, timeout=60) # Added timeout
        gofile_response.raise_for_status()
        gofile_data = gofile_response.json()

        logger.info(f"Gofile.io API response: {gofile_data}") # Log the full response for debugging

        if gofile_data.get("status") == "ok":
            data_payload = gofile_data.get("data", {})
            download_link = data_payload.get("downloadPage")
            # Use Gofile's filename if available, otherwise use the original name
            returned_file_name = data_payload.get("fileName", original_file_name)
            admin_code = data_payload.get("adminCode")

            if not download_link:
                logger.error(f"Gofile.io success status but no downloadPage. Full data: {data_payload}")
                await bot_message.edit_text(f"Uploaded to Gofile, but could not get a download link. Admin code: {admin_code or 'N/A'}")
                return

            response_text = (
                f"File uploaded successfully!\n\n"
                f"Name: {returned_file_name}\n"
                f"Download Link: {download_link}"
            )
            if admin_code:
                 response_text += f"\nAdmin Code (to manage file): {admin_code}"
            await bot_message.edit_text(response_text)
        else:
            error_message = gofile_data.get('status', 'Unknown Gofile error')
            logger.error(f"Gofile.io API error: {error_message} - Full response: {gofile_data}")
            await bot_message.edit_text(f"Sorry, something went wrong while uploading to Gofile.io. Error: {error_message}")

    except requests.exceptions.Timeout:
        logger.error("Request to Gofile.io timed out.")
        if bot_message:
            await bot_message.edit_text("Sorry, the upload to Gofile.io timed out. Please try again.")
        else:
            await message.reply_text("Sorry, the upload to Gofile.io timed out. Please try again.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during Gofile.io interaction: {e}", exc_info=True)
        if bot_message:
            await bot_message.edit_text(f"A network error occurred: {e}")
        else:
            await message.reply_text(f"A network error occurred: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred in handle_file: {e}", exc_info=True)
        error_display_message = str(e) if len(str(e)) < 100 else "An internal error occurred." # Avoid overly long error messages to user
        if bot_message:
            try:
                await bot_message.edit_text(f"An unexpected error occurred: {error_display_message}")
            except Exception as edit_e:
                logger.error(f"Failed to edit message with error: {edit_e}")
                await message.reply_text(f"An unexpected error occurred: {error_display_message}")
        else:
            await message.reply_text(f"An unexpected error occurred: {error_display_message}")


def main() -> None:
    """Start the bot."""
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO),
        handle_file
    ))
    application.add_error_handler(error_handler)

    logger.info("Bot is starting...")
    application.run_polling()

async def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)


if __name__ == '__main__':
    main()
