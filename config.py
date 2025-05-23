# config.py
import os
import logging

# Create a logger for config.py specific messages (optional, but good practice)
# The main application's logging configuration in main.py will generally apply.
config_logger = logging.getLogger(__name__)
# Basic configuration for this logger can be set here if needed,
# but usually, the root/application logger config takes precedence.
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


# Load configuration variables from the environment
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID_STR = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
OWNER_ID_STR = os.environ.get("OWNER_ID")  # This is optional

# --- Validate and process mandatory variables ---
if not BOT_TOKEN:
    # Raising an error here will stop the program if main.py tries to import this
    raise ValueError("Configuration Error from config.py: BOT_TOKEN is not set in the environment.")
if not API_ID_STR:
    raise ValueError("Configuration Error from config.py: API_ID is not set in the environment.")
if not API_HASH:
    raise ValueError("Configuration Error from config.py: API_HASH is not set in the environment.")
if not SESSION_STRING:
    raise ValueError("Configuration Error from config.py: SESSION_STRING is not set in the environment. Please generate it first.")

# Convert API_ID from string to integer
try:
    API_ID = int(API_ID_STR)
except ValueError:
    raise ValueError("Configuration Error from config.py: API_ID must be an integer.")

# --- Process optional variables ---
OWNER_ID = None  # Default to None
if OWNER_ID_STR:
    try:
        OWNER_ID = int(OWNER_ID_STR)
        config_logger.info(f"OWNER_ID loaded from environment: {OWNER_ID}")
    except ValueError:
        # If OWNER_ID is provided but is not a valid integer, log a warning
        config_logger.warning("Warning from config.py: OWNER_ID is set in the environment but is not a valid integer. It will be ignored.")
else:
    # If OWNER_ID is not set, log an informational message
    config_logger.info("Info from config.py: OWNER_ID is not set in the environment (this is optional).")

# You can add other configuration variables here if needed
# config_logger.debug("config.py loaded successfully with all required variables processed.")
