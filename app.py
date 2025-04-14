from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import twitch_auth
import twitch_events
import requests
import threading
import time
import json
import os

# Before running code remember to start up ngrok server and set up all appropriate locations for the forwarded URL

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///twitch_events.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
socketio = SocketIO(app, cors_allowed_origins="*")
db = SQLAlchemy(app)

# Database models
class TwitchEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50))
    user_name = db.Column(db.String(50))
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.now)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50))
    message = db.Column(db.Text)
    tags = db.Column(db.Text)  # Store tags as JSON
    timestamp = db.Column(db.DateTime, default=datetime.now)

class StreamStat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    viewer_count = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.DateTime, default=datetime.now)

class AlertSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    alert_type = db.Column(db.String(50), unique=True)  # follow, sub, cheer, etc.
    duration = db.Column(db.Integer, default=5)         # seconds
    sound_effect = db.Column(db.String(100), default="default.wav")
    animation = db.Column(db.String(50), default="fade")
    enabled = db.Column(db.Boolean, default=True)
    min_value = db.Column(db.Integer, default=0)        # For bits, minimum to display
    font_size = db.Column(db.Integer, default=24)       # For text size
    
    @staticmethod
    def get_default_settings():
        default_settings = {
            "follow": {
                "duration": 5,
                "sound_effect": "follow.wav",
                "animation": "fade",
                "enabled": True,
                "min_value": 0,
                "font_size": 24
            },
            "subscription": {
                "duration": 8,
                "sound_effect": "sub.wav",
                "animation": "confetti",
                "enabled": True,
                "min_value": 0,
                "font_size": 28
            },
            "cheer": {
                "duration": 6,
                "sound_effect": "cheer.wav",
                "animation": "rain",
                "enabled": True,
                "min_value": 100,  # Minimum bits to display
                "font_size": 26
            },
            "raid": {
                "duration": 10,
                "sound_effect": "raid.wav",
                "animation": "slide",
                "enabled": True,
                "min_value": 0,
                "font_size": 30
            },
            "channel_points": {
                "duration": 4,
                "sound_effect": "redeem.wav",
                "animation": "bounce",
                "enabled": True,
                "min_value": 0,
                "font_size": 22
            }
        }
        return default_settings

# Serve static files
@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

@app.route("/")
def home():
    return f'<a href="{twitch_auth.get_oauth_url()}">🔗 Connect Twitch</a>'

@app.route("/callback")
def callback():
    print("🔗 Received callback request:", request.args)

    auth_code = request.args.get("code")
    if not auth_code:
        print("❌ No authorization code received!")
        return "❌ Authorization failed! No code received.", 400  

    # ✅ Get the broadcaster's access token, not the bot's
    access_token = twitch_auth.get_user_access_token(auth_code)

    if not access_token:
        print(f"❌ Failed to get access token for code: {auth_code}")
        return "❌ Failed to get access token", 400

    print("✅ Broadcaster access token retrieved successfully!")

    twitch_events.subscribe_to_twitch_events()  # ✅ Use broadcaster's token
    return "✅ Twitch Alerts Connected!"

@app.route("/overlay")
def overlay():
    return render_template("overlay.html")

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

# API endpoints for the dashboard
@app.route("/api/events")
def get_events():
    events = TwitchEvent.query.order_by(TwitchEvent.timestamp.desc()).limit(50).all()
    return jsonify([{
        "type": e.event_type,
        "data": json.loads(e.details),
        "time": e.timestamp.isoformat(),
        "user_name": e.user_name
    } for e in events])

@app.route("/api/stats")
def get_stats():
    # Get today's date at midnight
    today_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Count today's follows
    today_follows = TwitchEvent.query.filter(
        TwitchEvent.event_type == "channel.follow",
        TwitchEvent.timestamp >= today_midnight
    ).count()
    
    # Count today's subs
    today_subs = TwitchEvent.query.filter(
        TwitchEvent.event_type == "channel.subscribe",
        TwitchEvent.timestamp >= today_midnight
    ).count()
    
    # Get latest viewer count
    latest_stats = StreamStat.query.order_by(StreamStat.timestamp.desc()).first()
    viewer_count = latest_stats.viewer_count if latest_stats else 0
    
    # Calculate messages per minute
    one_minute_ago = datetime.now() - timedelta(minutes=1)
    messages_last_minute = ChatMessage.query.filter(
        ChatMessage.timestamp >= one_minute_ago
    ).count()
    
    return jsonify({
        "today_followers": today_follows,
        "today_subs": today_subs,
        "viewer_count": viewer_count,
        "messages_per_minute": messages_last_minute
    })

@app.route("/api/chat")
def get_chat():
    # Get recent chat messages
    messages = ChatMessage.query.order_by(ChatMessage.timestamp.desc()).limit(100).all()
    return jsonify([{
        "username": m.username,
        "message": m.message,
        "tags": json.loads(m.tags) if m.tags else {},
        "time": m.timestamp.isoformat()
    } for m in messages])

@app.route("/api/alert-settings", methods=["GET"])
def get_alert_settings():
    """Get all alert settings."""
    settings = AlertSettings.query.all()
    
    # If no settings exist, create defaults
    if not settings:
        default_settings = AlertSettings.get_default_settings()
        for alert_type, config in default_settings.items():
            new_setting = AlertSettings(
                alert_type=alert_type,
                **config
            )
            db.session.add(new_setting)
        db.session.commit()
        settings = AlertSettings.query.all()
    
    # Convert to dictionary
    result = {}
    for setting in settings:
        result[setting.alert_type] = {
            "duration": setting.duration,
            "sound_effect": setting.sound_effect,
            "animation": setting.animation,
            "enabled": setting.enabled,
            "min_value": setting.min_value,
            "font_size": setting.font_size
        }
    
    return jsonify(result)

@app.route("/api/alert-settings/<alert_type>", methods=["PUT"])
def update_alert_setting(alert_type):
    """Update settings for a specific alert type."""
    data = request.json
    
    setting = AlertSettings.query.filter_by(alert_type=alert_type).first()
    
    # If setting doesn't exist, create it
    if not setting:
        setting = AlertSettings(alert_type=alert_type)
        db.session.add(setting)
    
    # Update fields
    if "duration" in data:
        setting.duration = int(data["duration"])
    if "sound_effect" in data:
        setting.sound_effect = data["sound_effect"]
    if "animation" in data:
        setting.animation = data["animation"]
    if "enabled" in data:
        setting.enabled = bool(data["enabled"])
    if "min_value" in data:
        setting.min_value = int(data["min_value"])
    if "font_size" in data:
        setting.font_size = int(data["font_size"])
    
    db.session.commit()
    
    # Notify clients of the change
    socketio.emit("alert_settings_updated", {
        "type": alert_type,
        "settings": {
            "duration": setting.duration,
            "sound_effect": setting.sound_effect,
            "animation": setting.animation,
            "enabled": setting.enabled,
            "min_value": setting.min_value,
            "font_size": setting.font_size
        }
    })
    
    return jsonify({"success": True})

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.json
    if "challenge" in payload:
        return payload["challenge"]

    print("🚀 Twitch Event Received:", payload)

    event_type = payload["subscription"]["type"]
    event_data = payload["event"]
    
    # Store event in database
    user_name = event_data.get("user_name", "")
    if not user_name and event_type == "channel.raid":
        user_name = event_data.get("from_broadcaster_user_name", "")
    
    new_event = TwitchEvent(
        event_type=event_type,
        user_name=user_name,
        details=json.dumps(event_data)
    )
    db.session.add(new_event)
    db.session.commit()
    
    # Emit to websocket clients
    if event_type == "channel.channel_points_custom_reward_redemption.add":
        socketio.emit("twitch_alert", {
            "type": "channel_points",
            "data": {
                "user_name": event_data["user_name"],
                "reward": event_data["reward"]["title"],
                "message": event_data.get("user_input", ""),
                "reward_color": event_data["reward"].get("background_color", "")
            }
        })
    elif event_type == "channel.cheer":
        # Get minimum bits setting
        cheer_settings = AlertSettings.query.filter_by(alert_type="cheer").first()
        min_bits = cheer_settings.min_value if cheer_settings else 0
        
        # Only emit if bits are above minimum
        if int(event_data.get("bits", 0)) >= min_bits:
            socketio.emit("twitch_alert", {"type": event_type, "data": event_data})
    else:
        socketio.emit("twitch_alert", {"type": event_type, "data": event_data})

    return jsonify({"message": "Received"}), 200

def handle_chat_message(username, message, tags=None):
    # Create an application context for database operations
    with app.app_context():
        try:
            # Store message in database
            new_message = ChatMessage(
                username=username,
                message=message,
                tags=json.dumps(tags) if tags else None
            )
            db.session.add(new_message)
            db.session.commit()
            
            # Emit to websocket clients
            socketio.emit("chat_message", {
                "username": username,
                "message": message,
                "tags": tags or {}
            })
        except Exception as e:
            print(f"Error handling chat message: {e}")

def emit_system_message(text, level="info"):
    """Emit a system message to the dashboard.
    
    Args:
        text: The message text
        level: The message level (info, warning, error)
    """
    socketio.emit("system_message", {
        "text": text,
        "level": level,
        "timestamp": datetime.now().isoformat()
    })

# Function to periodically fetch viewer count
def fetch_viewer_count():
    """Background task to fetch viewer count from Twitch API periodically"""
    while True:
        try:
            # Only fetch when we have valid credentials
            if twitch_auth.config.USER_ACCESS_TOKEN:
                url = f"https://api.twitch.tv/helix/streams?user_id={twitch_auth.config.BROADCASTER_ID}"
                headers = {
                    "Client-ID": twitch_auth.config.CLIENT_ID,
                    "Authorization": f"Bearer {twitch_auth.config.USER_ACCESS_TOKEN}"
                }
                
                response = requests.get(url, headers=headers).json()
                stream_data = response.get("data", [])
                
                # Check if stream is live
                if stream_data:
                    viewer_count = stream_data[0].get("viewer_count", 0)
                    
                    # Store in database
                    new_stat = StreamStat(viewer_count=viewer_count)
                    db.session.add(new_stat)
                    db.session.commit()
                    
                    # Emit to websocket clients
                    socketio.emit("viewer_count", viewer_count)
                else:
                    # Stream is offline
                    socketio.emit("viewer_count", 0)
        except Exception as e:
            print(f"Error fetching viewer count: {e}")
        
        # Sleep for 1 minute
        time.sleep(60)

@socketio.on("connect")
def handle_connect():
    print("✅ WebSocket Client Connected!")
    client_type = request.args.get('client_type', 'overlay')
    print(f"Client connected with type: {client_type}")
    
    # Emit system message
    emit_system_message(f"Client connected with type: {client_type}")
    
    if client_type == 'dashboard':
        # For dashboard, send recent events for display but don't trigger alerts
        recent_events = TwitchEvent.query.order_by(TwitchEvent.timestamp.desc()).limit(10).all()
        for event in recent_events:
            socketio.emit("dashboard_event", {
                "type": event.event_type,
                "data": json.loads(event.details)
            })

# Create database tables before running
def initialize_database():
    with app.app_context():
        db.create_all()
        print("✅ Database initialized")
        
        # Ensure default alert settings exist
        if AlertSettings.query.count() == 0:
            default_settings = AlertSettings.get_default_settings()
            for alert_type, config in default_settings.items():
                new_setting = AlertSettings(
                    alert_type=alert_type,
                    **config
                )
                db.session.add(new_setting)
            db.session.commit()
            print("✅ Default alert settings created")

if __name__ == "__main__":
    try:
        # Initialize the database
        initialize_database()
        
        # Ensure static folder exists
        if not os.path.exists('static'):
            os.makedirs('static')
            os.makedirs('static/sounds')
            os.makedirs('static/images')
            print("✅ Created static folders")
        
        # Ensure bot authentication
        print("🔄 Ensuring bot authentication before starting...")
        twitch_auth.ensure_bot_token()  # Ensure bot token is valid or refresh it
        
        # Start background tasks
        print("🔄 Starting background tasks...")
        viewer_thread = threading.Thread(target=fetch_viewer_count, daemon=True)
        viewer_thread.start()
        
        print("✅ Bot authentication complete. Starting Twitch chat...")
        # Modify twitch_events.py to use our handle_chat_message function
        twitch_events.handle_chat_message = handle_chat_message
        twitch_events.start_twitch_chat()  # Start chat listener
        
        print("🚀 Starting Flask server...")
        socketio.run(app, host="0.0.0.0", port=5000)
    except KeyboardInterrupt:
        print("\n🛑 Server shutting down gracefully. Goodbye!\n")