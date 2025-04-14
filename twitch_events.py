import requests
import config
import twitch_auth
from config import BROADCASTER_ID
import websocket
import threading
import config
import re
import pygame
import json

# Initialize pygame for sound effects
pygame.mixer.init()
CLAP_SOUND = pygame.mixer.Sound("clap.wav")

# This variable will be set by app.py
handle_chat_message = None

def delete_existing_subscriptions():
    """Deletes all existing Twitch EventSub subscriptions to prevent duplicates."""
    access_token = twitch_auth.get_app_access_token()
    url = "https://api.twitch.tv/helix/eventsub/subscriptions"
    headers = {
        "Client-ID": config.CLIENT_ID,
        "Authorization": f"Bearer {access_token}"
    }

    response = requests.get(url, headers=headers).json()
    
    for sub in response.get("data", []):
        delete_url = f"{url}?id={sub['id']}"
        requests.delete(delete_url, headers=headers)
        print(f"🗑 Deleted subscription: {sub['id']}")

def subscribe_to_twitch_events():
    """Subscribes to Twitch EventSub webhooks for follow, sub, cheer, raid, and channel points."""
    delete_existing_subscriptions()

    app_access_token = twitch_auth.get_app_access_token()
    user_access_token = config.USER_ACCESS_TOKEN

    if not user_access_token:
        print("❌ Error: User access token is missing. Please re-authenticate.")
        return

    url = "https://api.twitch.tv/helix/eventsub/subscriptions"

    def subscribe(event_type, version, condition, token):
        headers = {
            "Client-ID": config.CLIENT_ID,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        data = {
            "type": event_type,
            "version": version,
            "condition": condition,
            "transport": {
                "method": "webhook",
                "callback": config.WEBHOOK_CALLBACK,
                "secret": config.WEBHOOK_SECRET
            }
        }
        response = requests.post(url, json=data, headers=headers)
        print(f"✅ Subscribed to {event_type}: {response.json()}")

    subscribe("channel.follow", "2", {"broadcaster_user_id": BROADCASTER_ID, "moderator_user_id": BROADCASTER_ID}, app_access_token)
    subscribe("channel.subscribe", "1", {"broadcaster_user_id": BROADCASTER_ID}, app_access_token)
    subscribe("channel.cheer", "1", {"broadcaster_user_id": BROADCASTER_ID}, app_access_token)
    subscribe("channel.raid", "1", {"to_broadcaster_user_id": BROADCASTER_ID}, app_access_token)
    subscribe("channel.channel_points_custom_reward_redemption.add", "1", {"broadcaster_user_id": BROADCASTER_ID}, app_access_token)

def parse_irc_tags(tag_string):
    """Parse IRC tags from the message prefix."""
    if not tag_string:
        return {}
    
    # Remove the @ prefix
    if tag_string.startswith('@'):
        tag_string = tag_string[1:]
    
    tags = {}
    for tag in tag_string.split(';'):
        if '=' in tag:
            key, value = tag.split('=', 1)
            tags[key] = value if value else None
    
    return tags

def on_message(ws, message):
    """Handles incoming messages from Twitch chat and responds to PING."""
    if message.startswith("PING"):
        ws.send("PONG :tmi.twitch.tv")
        return
    
    message_lines = message.split("\r\n")
    for line in message_lines:
        if not line.strip():
            continue

        if "NOTICE" in line or "JOIN" in line or "PART" in line:
            print(f"📢 System Alert: {line}")
        
        if "PRIVMSG" in line:
            try:
                # Parse more complex IRC message format with tags
                tags = {}
                if line.startswith('@'):
                    tags_part, rest = line.split(' ', 1)
                    tags = parse_irc_tags(tags_part)
                    line = rest
                
                # Extract username and message
                match = re.search(r":(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #\w+ :(.+)", line)
                if match:
                    user, message_content = match.groups()
                    
                    # Handle clap emote
                    if "procptClap" in message_content:
                        print(f"👏 {user} clapped!")
                        CLAP_SOUND.play()
                    
                    # If handle_chat_message function is set (by app.py), use it
                    if handle_chat_message:
                        # Create a copy of data to pass to the main thread
                        username = user
                        content = message_content
                        tags_copy = tags.copy() if tags else {}
                        
                        # Use threading to avoid blocking the WebSocket thread
                        threading.Thread(
                            target=lambda: handle_chat_message(username, content, tags_copy),
                            daemon=True
                        ).start()
                    
                    print(f"💬 {user}: {message_content}")
            except Exception as e:
                print(f"Error parsing chat message: {e}")

def on_open(ws):
    """Handles connection opening to Twitch Chat."""
    print("✅ Connected to Twitch Chat")
    
    # Use the token directly from config
    ws.send(f"PASS {config.BOT_OAUTH_TOKEN}")
    ws.send(f"NICK {config.TWITCH_BOT_NICKNAME}")
    ws.send(f"JOIN #{config.TWITCH_CHANNEL}")
    
    # Request capabilities for additional message data
    ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership")
    
    print(f"🔗 Joined #{config.TWITCH_CHANNEL} as {config.TWITCH_BOT_NICKNAME}")

def connect_twitch_chat():
    """Creates a WebSocket connection to Twitch Chat."""
    ws = websocket.WebSocketApp(
        config.TWITCH_CHAT_URL,
        on_message=on_message,
        on_open=on_open
    )
    ws.run_forever()

def start_twitch_chat():
    chat_thread = threading.Thread(target=connect_twitch_chat, daemon=True)
    chat_thread.start()

if __name__ == "__main__":
    subscribe_to_twitch_events()