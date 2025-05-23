import logging
import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, Filters, CallbackContext

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
GOFILE_API_URL = "https://store1.gofile.io/uploadFile" # It's good practice to find the best server dynamically

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
        logger.error(f"Unexpected response format from Gofile getServer: {data}")
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
    if message.document:
        file_to_upload = message.document
        file_type = "document"
    elif message.video:
        file_to_upload = message.video
        file_type = "video"
    elif message.audio:
        file_to_upload = message.audio
        file_type = "audio"
    elif message.photo:
        # For photos, telegram sends multiple sizes. We'll take the largest one.
        file_to_upload = message.photo[-1]
        file_type = "photo"
    else:
        await message.reply_text("Sorry, I can only handle documents, videos, audio files, and photos.")
        return

    try:
        bot_message = await message.reply_text("Downloading your file...")
        new_file = await file_to_upload.get_file()
        file_path = new_file.file_path # This is a temporary URL from Telegram

        # Download the file from Telegram
        tg_file_response = requests.get(file_path, stream=True)
        tg_file_response.raise_for_status()

        file_name = file_to_upload.file_name
        if not file_name:
            # Generate a filename if not available (e.g., for photos)
            extension = file_path.split('.')[-1].split('?')[0] # get extension
            file_name = f"{file_type}_{file_to_upload.file_unique_id}.{extension}"


        await bot_message.edit_text(f"Uploading '{file_name}' to Gofile.io...")

        # Prepare for Gofile.io upload
        server = get_gofile_server()
        upload_url = f"https://{server}.gofile.io/uploadFile"

        files = {'file': (file_name, tg_file_response.content)}

        # Upload to Gofile.io
        gofile_response = requests.post(upload_url, files=files)
        gofile_response.raise_for_status() # Raise an exception for HTTP errors
        gofile_data = gofile_response.json()

        if gofile_data.get("status") == "ok":
            download_link = gofile_data["data"]["downloadPage"]
            await bot_message.edit_text(
                f"File uploaded successfully!\n\n"
                f"Name: {gofile_data['data']['fileName']}\n"
                f"Download Link: {download_link}\n"
                f"Admin Code (to manage file): {gofile_data['data']['adminCode']}"
            )
        else:
            logger.error(f"Gofile.io API error: {gofile_data.get('status')}")
            await bot_message.edit_text(f"Sorry, something went wrong while uploading to Gofile.io. Error: {gofile_data.get('status')}")

    except telegram.error.TelegramError as e:
        logger.error(f"Telegram API error: {e}")
        await message.reply_text(f"A Telegram error occurred: {e}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error: {e}")
        await bot_message.edit_text(f"A network error occurred while trying to upload your file: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        await bot_message.edit_text(f"An unexpected error occurred: {e}")


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))

    # on non command i.e message - handle the file
    application.add_handler(MessageHandler(
        Filters.Document.ALL | Filters.VIDEO | Filters.AUDIO | Filters.PHOTO,
        handle_file
    ))

    # Log all errors
    application.add_error_handler(error_handler)

    # Run the bot until the user presses Ctrl-C
    logger.info("Bot is starting...")
    application.run_polling()

async def error_handler(update: object, context: CallbackContext) -> None:
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)


if __name__ == '__main__':
    main()
