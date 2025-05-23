# config.py
import os

# Load configuration from environment variables
# These will be set directly on Seenode.com or in your local environment.

BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID_STR = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
OWNER_ID_STR = os.environ.get("OWNER_ID")  # Optional

# --- Validate and process mandatory variables ---
if not BOT_TOKEN:
    raise ValueError("Configuration Error: BOT_TOKEN is not set in the environment.")
if not API_ID_STR:
    raise ValueError("Configuration Error: API_ID is not set in the environment.")
if not API_HASH:
    raise ValueError("Configuration Error: API_HASH is not set in the environment.")
if not SESSION_STRING:
    raise ValueError("Configuration Error: SESSION_STRING is not set in the environment. Please generate it first.")

try:
    API_ID = int(API_ID_STR)
except ValueError:
    raise ValueError("Configuration Error: API_ID must be an integer.")

# --- Process optional variables ---
OWNER_ID = None
if OWNER_ID_STR:
    try:
        OWNER_ID = int(OWNER_ID_STR)
    except ValueError:
        print("Warning: OWNER_ID is set in the environment but is not a valid integer. It will be ignored.")
else:
    print("Info: OWNER_ID is not set in the environment (optional).")
