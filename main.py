import logging
import os
import requests
from telegram import Update
# Corrected import for filters
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

# Gofile.io API endpoint for uploading
# GOFILE_API_URL = "https://store1.gofile.io/uploadFile" # This will be dynamic

def get_gofile_server():
    """Gets the best available Gofile server."""
    try:
        response = requests.get("https://api.gofile.io/getServer")
        response.raise_for_status()
        data = response.json()
        if data["status"] == "ok":
            return data["data"]["server"]
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting Gofile server: {e}")
    except KeyError:
        logger.error(f"Unexpected response format from Gofile getServer.") # Removed data from log for brevity
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

    if message.document:
        file_to_upload = message.document
        file_type_for_name = "document"
    elif message.video:
        file_to_upload = message.video
        file_type_for_name = "video"
    elif message.audio:
        file_to_upload = message.audio
        file_type_for_name = "audio"
    elif message.photo:
        # For photos, telegram sends multiple sizes. We'll take the largest one.
        file_to_upload = message.photo[-1]
        file_type_for_name = "photo"
    else:
        await message.reply_text("Sorry, I can only handle documents, videos, audio files, and photos.")
        return

    try:
        bot_message = await message.reply_text("Downloading your file...")
        # Using context.bot.get_file for v20+
        new_file = await context.bot.get_file(file_to_upload.file_id)

        # Download the file from Telegram
        # We need to download it to memory or a temporary file to send with requests
        file_bytes = await new_file.download_as_bytearray()


        file_name = getattr(file_to_upload, 'file_name', None) # Works for document, video, audio
        if not file_name:
            # Generate a filename if not available (e.g., for photos)
            extension = new_file.file_path.split('.')[-1].split('?')[0] if new_file.file_path else 'jpg'
            file_name = f"{file_type_for_name}_{file_to_upload.file_unique_id}.{extension}"


        await bot_message.edit_text(f"Uploading '{file_name}' to Gofile.io...")

        # Prepare for Gofile.io upload
        server = get_gofile_server()
        upload_url = f"https://{server}.gofile.io/uploadFile"

        files = {'file': (file_name, bytes(file_bytes))} # Send bytes directly

        # Upload to Gofile.io
        gofile_response = requests.post(upload_url, files=files)
        gofile_response.raise_for_status() # Raise an exception for HTTP errors
        gofile_data = gofile_response.json()

        if gofile_data.get("status") == "ok":
            download_link = gofile_data["data"]["downloadPage"]
            admin_code = gofile_data["data"].get("adminCode", "N/A") # Get adminCode safely
            response_text = (
                f"File uploaded successfully!\n\n"
                f"Name: {gofile_data['data']['fileName']}\n"
                f"Download Link: {download_link}"
            )
            if admin_code != "N/A":
                 response_text += f"\nAdmin Code (to manage file): {admin_code}"
            await bot_message.edit_text(response_text)
        else:
            error_message = gofile_data.get('status', 'Unknown Gofile error')
            logger.error(f"Gofile.io API error: {error_message} - Full response: {gofile_data}")
            await bot_message.edit_text(f"Sorry, something went wrong while uploading to Gofile.io. Error: {error_message}")

    except AttributeError as e: # To catch potential issues if file_to_upload doesn't have expected attributes
        logger.error(f"Attribute error likely with file object: {e}", exc_info=True)
        await message.reply_text(f"An error occurred processing the file metadata: {e}")
    # telegram.error.TelegramError is not the base class for all errors in v20+
    # Use telegram.error.TelegramError for specific telegram errors if needed, or a more general exception
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        # Check if bot_message exists before trying to edit it
        if 'bot_message' in locals() and bot_message:
            try:
                await bot_message.edit_text(f"An unexpected error occurred: {e}")
            except Exception as edit_e: # If editing fails
                logger.error(f"Failed to edit message with error: {edit_e}")
                await message.reply_text(f"An unexpected error occurred: {e}")
        else:
            await message.reply_text(f"An unexpected error occurred: {e}")


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))

    # on non command i.e message - handle the file
    # Corrected usage of filters
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO),
        handle_file
    ))
    # If you want the bot to work in groups too, you can remove filters.ChatType.PRIVATE
    # or add another handler for groups. For simplicity, this one is for private chats.

    # Log all errors
    application.add_error_handler(error_handler)

    # Run the bot until the user presses Ctrl-C
    logger.info("Bot is starting...")
    application.run_polling()

async def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.error('Update "%s" caused error "%s"', update, context.error, exc_info=context.error)


if __name__ == '__main__':
    main()
