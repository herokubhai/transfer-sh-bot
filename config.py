# config.py
import os

# Load configuration from environment variables
# These will be set directly on Seenode.com or in your local environment.

BOT_TOKEN = os.environ.get("8154490037:AAHIZ5v7tmBt-xDYjfk1iAo68_dNm7sXwoY")
API_ID_STR = os.environ.get("28203009")
API_HASH = os.environ.get("c385478ec9a0c322964bdd56175cef7b")
SESSION_STRING = os.environ.get("1AZWarzwBu3UVNQ3Eb6XzkxCdWBY7Uu0hAiSPivqs_PLVxnUT58gxWuCX3OLdKyxtafrkTfcsmQLxkL2g9bt8IwQ9SekQaT5KRxhq0f4fgypRtJIInUJEUJ5DgGrf6YZ8XtP9Gh9VOc8Lgi9ffcdIH9cWDLgX4g4EXwnchal90uYpaTfGXIpU1iA0d-DZqjc-arMQfWiOl3J40f2uROI9-4BlzXFeRH0dXs_BQx50zJR32jWgJ27bRwZAw0d6n_KENGu0jvpXz0oZ2K2Fp5Wigz_M5sJkBb0z5Xez1hXhKdrAzaRvyXYy1jQYpMLfU-g1-tjy22uEhRl_v5wRjFgchAJ-FwPK_1E=")
OWNER_ID_STR = os.environ.get("6401029823")  # Optional

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

# You can add other configurations here if needed
# Example: DEFAULT_GOFILE_SERVER = "store1"
