import requests
import config
import urllib.parse
import os
import webbrowser
from config import CLIENT_ID, CLIENT_SECRET, BOT_CLIENT_ID, BOT_CLIENT_SECRET, REDIRECT_URI

SCOPES = [
    "channel:read:subscriptions",
    "bits:read",
    "moderator:read:followers",
    "channel:read:redemptions",
    "channel:manage:redemptions",
    "channel:manage:raids",
    "channel:manage:broadcast",
    "user:read:email",
    "chat:read",
    "chat:edit",
]

BOT_SCOPES = ["chat:read", "chat:edit"]  # Bot-only permissions
TOKEN_FILE = "bot_token.txt"  # Stores bot token locally


def _request_token(payload, client_id, client_secret):
    """Internal function to request an OAuth token from Twitch."""
    url = "https://id.twitch.tv/oauth2/token"
    payload.update({
        "client_id": client_id,
        "client_secret": client_secret
    })

    response = requests.post(url, data=payload).json()

    if "access_token" in response:
        return response
    else:
        print(f"❌ Error getting token: {response}")
        return None


### 🔹 MAIN ACCOUNT (BROADCASTER) AUTH ###
def get_oauth_url():
    """Generates OAuth URL for broadcaster authentication (event subscriptions, rewards, etc.)."""
    scope_str = " ".join(SCOPES)
    encoded_scope = urllib.parse.quote(scope_str)

    url = (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope={encoded_scope}"
    )

    print(f"🔗 Opening browser for broadcaster authentication: {url}")
    webbrowser.open(url)
    return url


def get_user_access_token(auth_code):
    """Gets a user access token for the broadcaster account."""
    print(f"🔄 Exchanging authorization code for token: {auth_code}")

    token_data = _request_token({
        "code": auth_code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI
    }, CLIENT_ID, CLIENT_SECRET)

    if token_data:
        config.USER_ACCESS_TOKEN = token_data["access_token"]
        config.REFRESH_TOKEN = token_data.get("refresh_token", "")

        print(f"✅ Broadcaster access token retrieved successfully: {config.USER_ACCESS_TOKEN[:10]}...")
        return config.USER_ACCESS_TOKEN
    else:
        print(f"❌ Failed to exchange authorization code. Response: {token_data}")
        return None

def refresh_user_access_token():
    """Refreshes the user access token when it expires."""
    if not config.REFRESH_TOKEN:
        print("❌ No refresh token available. Broadcaster must reauthenticate.")
        return None

    token_data = _request_token({
        "grant_type": "refresh_token",
        "refresh_token": config.REFRESH_TOKEN
    }, CLIENT_ID, CLIENT_SECRET)

    if token_data:
        config.USER_ACCESS_TOKEN = token_data["access_token"]
        config.REFRESH_TOKEN = token_data.get("refresh_token", "")
        print("🔄 Broadcaster access token refreshed.")

    return config.USER_ACCESS_TOKEN


def get_app_access_token():
    """Gets an app access token for general API use (not user-specific)."""
    token_data = _request_token({"grant_type": "client_credentials"}, CLIENT_ID, CLIENT_SECRET)
    return token_data.get("access_token") if token_data else None


### 🔹 BOT ACCOUNT AUTH ###
def get_bot_oauth_url():
    """Generates OAuth URL for bot authentication (chat only)."""
    scope_str = " ".join(BOT_SCOPES)
    encoded_scope = urllib.parse.quote(scope_str)

    url = (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={BOT_CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope={encoded_scope}"
    )

    print(f"🔗 Opening browser for bot authentication: {url}")
    webbrowser.open(url)
    return url


def load_bot_token():
    """Loads the bot token from a local file."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()
    return None


def save_bot_token(token):
    """Saves the bot token to a local file."""
    with open(TOKEN_FILE, "w") as f:
        f.write(token)


def get_bot_access_token(auth_code=None):
    """Gets a bot access token for chat authentication."""
    if auth_code:
        token_data = _request_token({
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI
        }, BOT_CLIENT_ID, BOT_CLIENT_SECRET)
    else:
        print("❌ No bot authorization code provided. Re-authentication required.")
        get_bot_oauth_url()
        return None

    if token_data:
        config.BOT_OAUTH_TOKEN = token_data["access_token"]
        save_bot_token(config.BOT_OAUTH_TOKEN)
        print(f"✅ Bot access token retrieved successfully.")
        return config.BOT_OAUTH_TOKEN

    return None


def ensure_bot_token():
    """Ensures the bot has a valid token before starting chat."""
    bot_token = load_bot_token()

    if bot_token:
        # Validate the token
        headers = {
            "Authorization": f"Bearer {bot_token}"
        }
        response = requests.get("https://id.twitch.tv/oauth2/validate", headers=headers)
        
        if response.status_code == 200:
            # Token is valid, format it correctly for IRC
            if bot_token.startswith("oauth:"):
                config.BOT_OAUTH_TOKEN = bot_token
            else:
                config.BOT_OAUTH_TOKEN = f"oauth:{bot_token}"
            print("✅ Using saved bot token.")
            return
        else:
            print("🔄 Existing bot token is invalid. Getting a new one.")
    
    print("🔄 No valid bot token found. Redirecting to Twitch for bot authentication.")
    get_bot_oauth_url()

