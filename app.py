"""Mikrotik Hotspot User Management Backend - v2
Major overhaul with a redesigned UI, profile management, filtered exports, QR codes, and more."""
from flask import Flask, render_template, request, jsonify, g, redirect, url_for, session # Add session
from flask_cors import CORS
from flask_babel import Babel, get_locale, _ # Re-add get_locale
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf # Import CSRFProtect and generate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta, datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, cast, Date, extract
import librouteros
from librouteros.exceptions import TrapError
import socket
import json
import os
import sys
import logging
import random
import string
import re
import math
import io
import csv
from flask import Response
import base64

from apscheduler.schedulers.background import BackgroundScheduler

# Configure logging
# logging.basicConfig(level=logging.INFO) # Will be replaced by more detailed config

# --- Logging Configuration ---
logger = logging.getLogger(__name__) # Get logger for the app
# Note: Actual handler configuration will be done after app_config is loaded.

# --- Graceful Dependency Handling ---
# Attempt to import WeasyPrint for PDF export
try:
    from weasyprint import HTML as WeasyHTML
    WEASYPRINT_AVAILABLE = True
    logger.info("WeasyPrint library loaded successfully. PDF export is enabled.")
except (ImportError, OSError) as e:
    WEASYPRINT_AVAILABLE = False
    logger.warning("="*50)
    logger.warning("WeasyPrint could not be loaded. PDF export will be disabled.")
    logger.warning(f"Error: {e}")
    logger.warning("This is likely due to missing GTK+ system dependencies.")
    logger.warning("Please follow the installation steps for your OS:")
    logger.warning("https://doc.weasyprint.org/stable/first_steps.html#installation")
    logger.warning("="*50)


# Attempt to import qrcode for QR generation

babel = Babel() # Define Babel instance here

try:
    import qrcode
    from qrcode.image.styledpil import StyledPilImage
    from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False
    logger.warning("qrcode library not found. QR codes on vouchers will be disabled.")
    logger.warning("To enable this feature, please install it: pip install qrcode[pil]")


app = Flask(__name__)
CORS(app)

# Session management
SECRET_KEY_FALLBACK = "a_very_secret_and_stable_key_for_development_do_not_use_in_prod"
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', SECRET_KEY_FALLBACK)

# app_config is not available here yet. This check needs to be done after app_config is loaded.
# We will move this check to after app_config initialization.

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30) # Example: 30 minutes timeout

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page' # Redirect to login_page if @login_required fails
login_manager.session_protection = "strong"

# Initialize CSRF Protection
csrf = CSRFProtect()
csrf.init_app(app)
app.config["WTF_CSRF_HEADER_NAME"] = "X-CSRFToken" # Tell Flask-WTF to look for token in this header for AJAX

# Language configuration
app.config['LANGUAGES'] = ['en', 'ar', 'fr']
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'

babel.init_app(app) # Initialize Babel with app context here

# Database Configuration
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Will be set properly after config is loaded

db = SQLAlchemy()

# @babel.localeselector
# def get_locale_func():
#     # Try to get the language from the user's browser settings
#     # Ensure request context is available or handle appropriately if called outside request
#     if request:
#         return request.accept_languages.best_match(app.config['LANGUAGES'])
#     return app.config['BABEL_DEFAULT_LOCALE'] # Fallback

def get_base_path():
    """ Get base path for PyInstaller bundled app or normal script """
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return os.path.abspath(os.path.dirname(__file__))

class ConfigLoader:
    """Handles loading and managing application configuration."""
    def __init__(self, config_file='config.json'):
        self.config_file = os.path.join(get_base_path(), config_file)
        self.config = self._load_config()

    def _load_config(self):
        """Load configuration from config.json or create default if not exists."""
        default_config = {
            "scheduler": {
                "enabled": True,
                "job_interval_minutes": 60
            },
            "database": {
                "uri": f"sqlite:///{os.path.join(get_base_path(), 'hotspot_analytics.db')}"
            },
            "mikrotik": {
                "host": "192.168.88.1",
                "port": 8728,
                "username": "admin",
                "password": "",
                "use_ssl": False,
                "hotspot_login_url": "http://hotspot.setup/login"
            },
            "server": {
                "host": "0.0.0.0",
                "port": 5000,
                "debug": False,
                "log_file": "mikrotik_dashboard.log", 
                "log_level_console": "INFO", 
                "log_level_file": "INFO"     
            },
            "app_admin": {
                "username": "admin",
                "password_hash": "pbkdf2:sha256:600000$zR0gQY0gV0gY0gV0$c2df639e9e31b0cf9352d789a8f074d2f6a603cf8bd77a9a20addf32089e11f9" # Default for "changeme"
            }
        }

        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                loaded_config = json.load(f)
                # Deep merge with default to ensure new keys are present
                for key in ['scheduler', 'database', 'mikrotik', 'server', 'app_admin']:
                    if key in loaded_config and isinstance(default_config.get(key), dict) and isinstance(loaded_config.get(key), dict):
                        default_config[key].update(loaded_config[key])
                    elif key in loaded_config: # Handle cases where the value might not be a dict (e.g. if a user manually edits it)
                        default_config[key] = loaded_config[key]
                
                return default_config
        else:
            # If config file doesn't exist, write the full default_config
            with open(self.config_file, 'w') as f:
                json.dump(default_config, f, indent=4)
            return default_config

    def get_config(self):
        return self.config

    def update_config(self, new_config):
        self.config['mikrotik'].update(new_config.get('mikrotik', {}))
        self.config['server'].update(new_config.get('server', {}))
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=4)

    def reset_mikrotik_config_to_defaults(self):
        """Resets the Mikrotik part of the configuration to its original defaults."""
        # Get the original default settings as defined in _load_config
        # This is a bit indirect; _load_config itself returns a merged config.
        # For true defaults, we define it here or access a pristine default structure.
        # Let's re-fetch default structure as defined in _load_config's initial state.
        original_default_settings = { # Replicating the default structure from _load_config
            "host": "192.168.88.1",
            "port": 8728,
            "username": "admin",
            "password": "",
            "use_ssl": False,
            "hotspot_login_url": "http://hotspot.setup/login"
        }
        # The server part of the config should remain untouched by this.
        current_server_config = self.config.get('server', {}) 
        
        update_payload = {
            'mikrotik': original_default_settings,
            'server': current_server_config # Ensure server settings are preserved
        }
        # Instead of self.update_config which merges, we want to overwrite mikrotik section
        # and keep server section. So, construct the full new config.
        self.config['mikrotik'] = original_default_settings
        # self.config['server'] is already what it should be.
        
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=4)
        logger.info("Mikrotik configuration has been reset to defaults.")

    def update_admin_credentials(self, new_password_hash=None, new_username=None):
        """Safely updates admin username and/or password hash in the configuration."""
        updated = False
        if new_username and self.config['app_admin'].get('username') != new_username:
            self.config['app_admin']['username'] = new_username
            logger.info(f"Admin username updated to: {new_username}")
            updated = True
        if new_password_hash and self.config['app_admin'].get('password_hash') != new_password_hash:
            self.config['app_admin']['password_hash'] = new_password_hash
            logger.info("Admin password hash updated.")
            updated = True

        if updated:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            logger.info("Admin credentials saved to configuration file.")
        return updated


# Initialize ConfigLoader
config_loader = ConfigLoader()
app_config = config_loader.get_config()

# Enhanced SECRET_KEY check after app_config is loaded
if app.config['SECRET_KEY'] == SECRET_KEY_FALLBACK:
    if not app_config.get('server', {}).get('debug', False): # If debug is False (production-like)
        logger.error("CRITICAL SECURITY WARNING: FLASK_SECRET_KEY is not set and the application is NOT in debug mode. "
                     "Using the default, insecure key in a production environment is highly dangerous. "
                     "The application may be vulnerable to session hijacking and other attacks. "
                     "SET THE FLASK_SECRET_KEY ENVIRONMENT VARIABLE IMMEDIATELY using a strong, random value.")
    else: # Debug mode is True or not set (defaults to False but let's be explicit for the warning)
        logger.warning("WARNING: FLASK_SECRET_KEY environment variable not set. Using a default, insecure key for development. "
                       "Ensure this is set for any production deployment.")

# Set SQLAlchemy Database URI from loaded config
app.config['SQLALCHEMY_DATABASE_URI'] = app_config.get('database', {}).get('uri', f"sqlite:///{os.path.join(get_base_path(), 'hotspot_analytics_fallback.db')}")
logger.info(f"SQLAlchemy Database URI set to: {app.config['SQLALCHEMY_DATABASE_URI']}")

db.init_app(app)

# --- Setup Logging Handlers (after app_config is available) ---
def setup_logging(app_config_instance):
    _logger = logging.getLogger(__name__) # Use module-level logger
    _logger.setLevel(logging.INFO) # Default log level

    # Clear existing handlers if any (to avoid duplicate logs on reloads in dev)
    if _logger.hasHandlers():
        _logger.handlers.clear()

    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Console Handler
    ch = logging.StreamHandler()
    # Use log_level_console from server config, or default to INFO
    console_log_level_str = app_config_instance.get('server', {}).get('log_level_console', 'INFO').upper()
    console_log_level = getattr(logging, console_log_level_str, logging.INFO)
    ch.setLevel(console_log_level)
    ch.setFormatter(formatter)
    _logger.addHandler(ch)
    _logger.info(f"Console logging configured with level: {logging.getLevelName(ch.level)}") # Use ch.level for accuracy

    # File Handler
    try:
        log_file_path = app_config_instance.get('server', {}).get('log_file', 'mikrotik_dashboard.log')
        log_dir = os.path.dirname(log_file_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        fh = logging.FileHandler(log_file_path)
        file_log_level_str = app_config_instance.get('server', {}).get('log_level_file', 'INFO').upper()
        file_log_level = getattr(logging, file_log_level_str, logging.INFO) # Default to INFO if invalid
        fh.setLevel(file_log_level)
        fh.setFormatter(formatter)
        _logger.addHandler(fh)
        _logger.info(f"File logging configured to: {log_file_path} with level: {file_log_level_str}")
    except Exception as e:
        _logger.error(f"Failed to configure file logging: {e}", exc_info=True)

setup_logging(app_config) # Call the setup function with the loaded app_config

# --- Database Models ---
class UserActivityLog(db.Model):
    __tablename__ = 'user_activity_log'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    username = db.Column(db.String(255), index=True)
    profile = db.Column(db.String(255))
    bytes_in = db.Column(db.BigInteger) # Using BigInteger for byte counts
    bytes_out = db.Column(db.BigInteger)
    uptime_seconds = db.Column(db.Integer) # Store uptime in seconds for easier calculation

    def __repr__(self):
        return f'<UserActivityLog {self.username} @ {self.timestamp}>'

class SystemSnapshot(db.Model):
    __tablename__ = 'system_snapshot'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    active_users_count = db.Column(db.Integer)
    total_data_bytes_in = db.Column(db.BigInteger) # Aggregated from all users at snapshot time
    total_data_bytes_out = db.Column(db.BigInteger)

    def __repr__(self):
        return f'<SystemSnapshot @ {self.timestamp} - Active Users: {self.active_users_count}>'


# --- User Class for Flask-Login ---
class User(UserMixin):
    def __init__(self, id):
        self.id = id

    @staticmethod
    def get(user_id):
        admin_username = app_config.get('app_admin', {}).get('username')
        if user_id == admin_username:
            return User(user_id)
        return None

@login_manager.user_loader
def load_user(user_id):
    user = User.get(user_id)
    return user

# Define exempt endpoints that do not require a Mikrotik connection OR app login initially
MIKROTIK_EXEMPT_ENDPOINTS = {'login_page', 'app_login_route', 'initial_connect', 'static', 'get_translations'}
# CSRF protection will be enabled by default for all POST/PUT/DELETE requests.
# We might need to exempt specific routes if they are called from external systems not using our CSRF flow.
# For now, all internal POSTs should be protected. login_page and app_login are POST but are handled.

@app.before_request
def before_request_handler():
    logger.debug(f"before_request: endpoint='{request.endpoint}', path='{request.path}'")

    # 1. Flask-Login Authentication Check
    login_exempt_for_auth = request.endpoint in ['login_page', 'app_login_route', 'static', 'get_translations']
    
    # Removed temporary debug logging from here

    if not login_exempt_for_auth and not current_user.is_authenticated:
        logger.info(f"User not authenticated for endpoint '{request.endpoint}'. Redirecting to login page.")
        return redirect(url_for('login_page'))

    # 2. Mikrotik Connection Initialization (for authenticated users on non-exempt routes)
    # This step ensures g.mikrotik_api is populated if a connection exists,
    # but does NOT redirect if the connection is down for dashboard/API pages.
    # The frontend UI will handle the disconnected state for these pages.
    if current_user.is_authenticated and request.endpoint not in MIKROTIK_EXEMPT_ENDPOINTS:
        logger.debug(f"User authenticated. Endpoint '{request.endpoint}' is not Mikrotik exempt. Initializing Mikrotik API for 'g'.")
        get_mikrotik_api() # This will set g.mikrotik_api or g.mikrotik_api = None
        # No redirect here if api is None. Frontend will handle UI based on connection status.
        # Specific routes that absolutely cannot function without an API connection
        # (and where frontend cannot gracefully degrade) would need to check g.mikrotik_api themselves.
        # However, the goal is for the dashboard to be accessible.
    elif request.endpoint in MIKROTIK_EXEMPT_ENDPOINTS:
         logger.debug(f"Endpoint '{request.endpoint}' is exempt from Mikrotik connection logic in before_request.")
    # else: User not authenticated but endpoint is exempt from auth (e.g. /login), or other cases.

    return # Allow request


@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    global app_config
    logger.info("Processing logout request.")

    # Logout from Flask-Login session
    logout_user()
    logger.info("Flask-Login session ended.")

    # Reset Mikrotik configuration (original functionality)
    config_loader.reset_mikrotik_config_to_defaults()
    app_config = config_loader.get_config() # Reload global app_config

    if 'mikrotik_api' in g:
        g.pop('mikrotik_api', None)
    if 'mikrotik_connection' in g:
        conn_to_close = g.pop('mikrotik_connection', None)
        if conn_to_close and hasattr(conn_to_close, 'close'):
            try:
                conn_to_close.close()
                logger.info("Closed active Mikrotik connection from 'g' during logout.")
            except Exception as e:
                logger.error(f"Error closing connection from 'g' during logout: {e}")

    logger.info("User logged out from web app, Mikrotik configuration reset to defaults.")
    return jsonify({'success': True, 'message': _('Logged out successfully from web app and Mikrotik.')})

def _generate_vouchers_page_html(vouchers: list, hotspot_login_url: str, include_print_button: bool = True) -> str:
    # Read the logo file and encode it as Base64
    logo_path = os.path.join(get_base_path(), 'static', 'images', 'The IT Dad new logo.png')
    logo_base64 = ""
    try:
        with open(logo_path, "rb") as image_file:
            logo_base64 = base64.b64encode(image_file.read()).decode('utf-8')
        logo_mime_type = "image/png" # Assuming PNG, adjust if it could be other types
        logo_data_url = f"data:{logo_mime_type};base64,{logo_base64}"
    except FileNotFoundError:
        logger.warning(f"Logo file not found at {logo_path} for voucher generation.")
        logo_data_url = "" # Fallback or handle error

    html_parts = ["""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Hotspot Vouchers</title>
        <style>
            @page {
                size: A4 portrait;
                margin: 5mm;
            }
            body {
                margin: 0;
                padding: 0;
                font-family: 'Segoe UI', Arial, sans-serif;
                background-color: #f4f4f9;
                color: #333333;
                -webkit-print-color-adjust: exact; 
            }
            .print-button-container {
                text-align: center;
                padding: 20px;
            }
            .print-button {
                padding: 12px 25px;
                background-color: #007bff;
                color: #fff;
                border: none;
                border-radius: 5px;
                font-size: 16px;
                cursor: pointer;
                transition: background-color 0.2s;
            }
            .print-button:hover {
                background-color: #0056b3;
            }
            .voucher-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, 70mm); /* Updated width */
                gap: 8mm; /* Updated gap */
                padding: 10mm; /* Keep padding or adjust if needed */
                justify-content: center;
            }
            .voucher {
                width: 70mm; /* Updated width */
                height: 50mm; /* Updated height */
                background-color: #fff;
                border: 1px solid #ddd;
                border-radius: 8px;
                box-sizing: border-box;
                display: flex;
                flex-direction: column; 
                page-break-inside: avoid;
                overflow: hidden;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            }
            .voucher-header {
                background-color: #fff;
                color: #2A7ABF; /* Updated to Bright Blue from logo */
                border-bottom: 1.5px solid #2A7ABF; /* Updated to Bright Blue */
                padding: 5px 8px;
                text-align: center;
                font-weight: bold;
                font-size: 1.1em;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
            }
            .voucher-content {
                display: flex;
                flex-grow: 1; 
                padding: 5px;
                justify-content: space-between;
                align-items: center;
            }
            .voucher-qr {
                width: 24mm;
                height: 24mm;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 4px; 
            }
            .voucher-qr img {
                max-width: 100%;
                max-height: 100%;
                border-radius: 4px;
            }
            .voucher-details {
                flex-grow: 1;
                font-size: 0.9em; 
                color: #000000;
                display: flex;
                flex-direction: column;
                justify-content: center; 
                gap: 4px;
                padding-left: 8px;
            }
            .voucher-details p {
                margin: 0;
            }
            .voucher-details strong { 
                color: #333;
                font-weight: 500;
            }
            .voucher-details span { 
                font-family: 'Courier New', monospace;
                 color: #2A7ABF; /* Updated to Bright Blue */
                background-color: #f0f2f5;
                padding: 2px 5px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 1.1em; 
                word-break: break-all; 
            }
            .voucher-footer { 
                font-size: 7.5pt; 
                color: #555; 
                text-align: center;
                padding: 4px 5px;
                border-top: 1px solid #eee;
            }

            @media print {
                body { 
                    margin: 0; 
                    padding: 0; 
                    background-color: #fff;
                }
                .print-button-container { 
                    display: none; 
                }
                .voucher-grid {
                    display: flex;
                    flex-wrap: wrap;
                    justify-content: flex-start;
                    align-content: flex-start;
                    gap: 0; /* No gap, use margins for spacing */
                    width: 100%;
                    padding: 0;
                }
                .voucher {
                    border: 1px dashed #999; /* Cutting guides */
                    box-shadow: none;
                    border-radius: 0;
                    margin: 2mm; /* Space out vouchers for cutting */
                }
            }
        </style>
    </head>
    <body>
    """]

    if include_print_button:
        html_parts.append("""
        <div class="print-button-container">
            <button class="print-button" onclick="window.print();">🖨️ Print Vouchers</button>
        </div>
        """)

    html_parts.append('<div class="voucher-grid">')

    for voucher in vouchers:
        username = voucher.get('username', 'N/A')
        password = voucher.get('password', 'N/A')
        limit_uptime = voucher.get('limit-uptime', '') # Get limit-uptime
        profile_name = voucher.get('profile', '') # Get profile, though not currently displayed

        time_limit_display = "Unlimited"
        if limit_uptime and limit_uptime != '0s':
            time_limit_display = limit_uptime
        
        qr_code_b64 = None

        if QRCODE_AVAILABLE and hotspot_login_url:
            try:
                # Use a smaller box size for the compact voucher design
                qr_code_b64 = generate_qr_code_base64(hotspot_login_url, username, password)
            except Exception as e:
                logger.warning(f"QR generation failed for {username}: {e}")

        html_parts.append(f"""
        <div class="voucher">
            <div class="voucher-header">""")
        if logo_data_url:
            html_parts.append(f"""<img src="{logo_data_url}" alt="Logo" style="max-height: 16px; margin-right: 8px; vertical-align: middle;">""") # Reduced max-height
        html_parts.append("""Hotspot Voucher</div>
            <div class="voucher-content">
                <div class="voucher-qr">
        """)

        if qr_code_b64:
            html_parts.append(f'<img src="data:image/png;base64,{qr_code_b64}" alt="QR Code for {username}">')
        else:
            html_parts.append('<div style="font-size:0.8em; color:#aaa; text-align:center;">QR Not Available</div>')

        html_parts.append(f"""
                </div>
                <div class="voucher-details">
                    <p><strong>Username:</strong></p>
                    <p><span>{username}</span></p>
                    <p><strong>Password:</strong></p>
                    <p><span>{password}</span></p>
                    <p><strong>Time Limit:</strong></p>
                    <p><span>{time_limit_display}</span></p>
                </div>
            </div>
            <div class="voucher-footer">📞 +211 923 616 820 | ✉️ justinkulang@gmail.com</div>
        </div>
        """)

    html_parts.append("</div></body></html>")
    return ''.join(html_parts)
@app.route('/api/vouchers/view_batch_html', methods=['POST'])
def view_batch_vouchers_html():
    try:
        vouchers_json = request.form.get('vouchers_json', '[]')
        hotspot_login_url = request.form.get('hotspot_login_url', '')
        vouchers = json.loads(vouchers_json)

        if not vouchers:
            return Response("No voucher data provided.", mimetype='text/html', status=400)
        
        html_content = _generate_vouchers_page_html(vouchers, hotspot_login_url, include_print_button=True)
        return Response(html_content, mimetype='text/html')

    except json.JSONDecodeError:
        logger.error("Failed to decode vouchers_json from form data.")
        return Response("Invalid voucher data provided.", mimetype='text/html', status=400)
    except Exception as e:
        logger.error(f"Error generating voucher HTML view: {e}")
        return Response(f"An error occurred while generating vouchers: {e}", mimetype='text/html', status=500)

@app.route('/api/vouchers/download_batch_pdf', methods=['POST'])
def download_batch_vouchers_pdf():
    if not WEASYPRINT_AVAILABLE:
        logger.warning("PDF export attempted but WeasyPrint is not available.")
        return jsonify({'success': False, 'message': 'PDF generation library not available on the server.'}), 501

    try:
        vouchers_json = request.form.get('vouchers_json', '[]')
        hotspot_login_url = request.form.get('hotspot_login_url', '')
        vouchers = json.loads(vouchers_json)

        if not vouchers:
            return jsonify({'success': False, 'message': 'No voucher data provided.'}), 400
        
        # Generate HTML without the print button for PDF rendering
        html_content = _generate_vouchers_page_html(vouchers, hotspot_login_url, include_print_button=False)
        
        pdf_file = WeasyHTML(string=html_content).write_pdf()
        
        return Response(
            pdf_file,
            mimetype="application/pdf",
            headers={"Content-disposition": "attachment; filename=vouchers_batch.pdf"}
        )
    except json.JSONDecodeError:
        logger.error("Failed to decode vouchers_json for PDF export.")
        return jsonify({'success': False, 'message': 'Invalid voucher data provided for PDF export.'}), 400
    except Exception as e:
        logger.error(f"Error generating voucher PDF: {e}")
        # Check if it's a WeasyPrint specific error that might hint at system dependencies
        if "No X11 connection" in str(e) or "GTK" in str(e):
             logger.error("WeasyPrint PDF generation failed, possibly due to missing X11/GTK dependencies on the server.")
             return jsonify({'success': False, 'message': 'PDF generation failed on server due to missing dependencies. Please check server logs.'}), 500
        return jsonify({'success': False, 'message': f'An unexpected error occurred during PDF generation: {str(e)}'}), 500

def get_mikrotik_api():
    """Establishes and returns a single Mikrotik API connection per request."""
    logger.debug(f"get_mikrotik_api: Current Mikrotik config host from module-level app_config: {app_config['mikrotik'].get('host')}")
    if 'mikrotik_api' not in g:
        logger.debug("get_mikrotik_api: 'mikrotik_api' not in g. Attempting new connection.")
        # Fetch the latest config directly from the loader instance for new connections
        current_loaded_config = config_loader.get_config() 
        mikrotik_config = current_loaded_config['mikrotik']
        logger.debug(f"get_mikrotik_api: Using host from config_loader.get_config(): {mikrotik_config.get('host')}")
        
        host, port, username, password, use_ssl = (
            mikrotik_config['host'], mikrotik_config['port'],
            mikrotik_config['username'], mikrotik_config['password'],
            mikrotik_config.get('use_ssl', False)
        )
        # Basic check for placeholder/default config before attempting connection
        if host == "192.168.88.1" and username == "admin" and password == "" and not os.path.exists(config_loader.config_file):
             logger.warning("get_mikrotik_api: Attempting to connect with default placeholder config and no config file saved yet. Connection will likely fail or use defaults.")
        
        logger.info(f"Attempting to connect to Mikrotik: {host}:{port} (SSL: {use_ssl})")
        api_connection_object = None  # Temporary holder for the connection object
        try:
            api_connection_object = librouteros.connect(
                host=host, username=username, password=password, port=port, ssl=use_ssl
            )
            # If connect succeeds, then assign to g
            g.mikrotik_connection = api_connection_object
            g.mikrotik_api = api_connection_object # In librouteros, connect() returns the api object directly
            logger.info("Mikrotik connection established successfully in get_mikrotik_api.")
        except (librouteros.exceptions.LibRouterosError, TrapError, socket.error, ConnectionRefusedError, OSError) as e:
            logger.error(f"Mikrotik connection failed in get_mikrotik_api: {type(e).__name__} - {e}")
            if api_connection_object: # If connect() returned an object before erroring or during partial setup
                try:
                    logger.debug("Attempting to close potentially partial Mikrotik connection object after failure.")
                    api_connection_object.close()
                except Exception as close_e:
                    logger.error(f"Error closing partial Mikrotik connection object: {close_e}")
            g.mikrotik_api = None
            g.pop('mikrotik_connection', None) # Ensure it's removed from g
        except Exception as e: # Catch any other unexpected error during connection
            logger.error(f"Unexpected generic error during Mikrotik connection in get_mikrotik_api: {type(e).__name__} - {e}")
            if api_connection_object: # If connect() returned an object before erroring
                try:
                    logger.debug("Attempting to close potentially partial Mikrotik connection (generic exception).")
                    api_connection_object.close()
                except Exception as close_e:
                    logger.error(f"Error closing partial Mikrotik connection (generic exception): {close_e}")
            g.mikrotik_api = None
            g.pop('mikrotik_connection', None) # Ensure it's removed from g
    else:
        # This 'else' case should ideally not be hit frequently if teardown_connection runs after each request.
        # If it is hit, it implies g.mikrotik_api persisted, which means teardown might not have run.
        # For safety, we could add a check here too, but the primary model is new connection per request.
        logger.warning("get_mikrotik_api: Reusing existing Mikrotik API from 'g'. This is unexpected with current teardown logic.")
        # Potentially add a health check for existing g.mikrotik_api here if this path becomes common.
        # For now, assume teardown works and this path is rare.
    
    api_to_return = g.get('mikrotik_api', None)
    logger.debug(f"get_mikrotik_api: Returning API object: {'Exists' if api_to_return else 'None'}")
    return api_to_return

@app.teardown_appcontext
def teardown_connection(exception):
    """Closes the Mikrotik connection after each request."""
    mikrotik_connection = g.pop('mikrotik_connection', None)
    if mikrotik_connection:
        mikrotik_connection.close()
        logger.info("Mikrotik connection closed.")


class RouterOSService:
    """Service class for all Mikrotik RouterOS interactions."""
    def __init__(self):
        pass # Connection is managed globally via get_mikrotik_api

    def test_connection(self) -> tuple[bool, str]:
        """Test connection to Mikrotik router."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Connection failed: Could not establish API session. Check config and router status."
            identity_records = list(api.path('system', 'identity').select('name'))

            router_name = 'Mikrotik Router'
            if identity_records:
                router_name = identity_records[0].get('name', 'Mikrotik Router')

            return True, f"Connected successfully to {router_name}"
        except ConnectionError as e:
            logger.error(f"Connection test failed: {e}")
            return False, f"Connection failed: {e}"
        except Exception as e:
            logger.error(f"Unexpected error during connection test: {str(e)}")
            return False, f"Unexpected error during connection test: {str(e)}"

    def get_hotspot_users(self) -> list:
        """Get all hotspot users."""
        try:
            api = get_mikrotik_api()
            if api is None:
                logger.error("Error getting users: Mikrotik API not available.")
                return []
            users = list(api.path('ip', 'hotspot', 'user').select(
                '.id', 'name', 'password', 'profile', 'disabled', 'limit-uptime', 'limit-bytes-total',
                'uptime', 'bytes-in', 'bytes-out', 'comment', 'limit-bytes-in', 'limit-bytes-out'
            ))
            return users
        except Exception as e:
            logger.error(f"Error getting users: {str(e)}")
            return []

    def create_hotspot_user(self, user_data: dict) -> tuple[bool, str]:
        """Create new hotspot user."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            # Clean up potential None values before sending to router
            valid_user_data = {k: v for k, v in user_data.items() if v is not None}
            api.path('ip', 'hotspot', 'user').add(**valid_user_data)
            return True, "User created successfully"
        except (TrapError, Exception) as e:
            logger.error(f"Error creating user: {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"

    def edit_hotspot_user(self, username: str, new_data: dict) -> tuple[bool, str]:
        """Edit existing hotspot user."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            users = list(api.path('ip', 'hotspot', 'user').select('.id').where(name=username))
            if not users:
                return False, "User not found"
            
            user_id = users[0]['.id']
            api.path('ip', 'hotspot', 'user').set(**new_data, **{'.id': user_id})
            return True, "User updated successfully"
        except (TrapError, Exception) as e:
            logger.error(f"Error editing user '{username}': {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"

    def delete_hotspot_user(self, username: str) -> tuple[bool, str]:
        """Delete hotspot user."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            users = list(api.path('ip', 'hotspot', 'user').select('.id').where(name=username))
            if not users:
                return False, "User not found"

            user_id = users[0]['.id']
            api.path('ip', 'hotspot', 'user').remove(user_id)
            return True, "User deleted successfully"
        except (TrapError, Exception) as e:
            logger.error(f"Error deleting user '{username}': {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"
    
    def get_active_sessions(self) -> list:
        """Get active hotspot sessions."""
        try:
            api = get_mikrotik_api()
            if api is None:
                logger.error("Error getting active sessions: Mikrotik API not available.")
                return []
            sessions = list(api.path('ip', 'hotspot', 'active').select(
                'user', 'address', 'mac-address', 'uptime', 'bytes-in', 'bytes-out',
                'session-time-left', 'idle-time', '.id'
            ))
            return sessions
        except Exception as e:
            logger.error(f"Error getting active sessions: {str(e)}")
            return []

    def disconnect_user(self, active_id: str) -> tuple[bool, str]:
        """Disconnect active user session by its .id."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            api.path('ip', 'hotspot', 'active').remove(active_id)
            return True, "User disconnected successfully"
        except (TrapError, Exception) as e:
            logger.error(f"Error disconnecting user: {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"

    def get_user_profiles(self) -> list:
        """Get hotspot user profiles."""
        try:
            api = get_mikrotik_api()
            if api is None:
                logger.error("Error getting profiles: Mikrotik API not available.")
                return []
            profiles = list(api.path('ip', 'hotspot', 'user', 'profile').select(
                '.id', 'name', 'rate-limit', 'session-timeout', 'shared-users',
                'mac-cookie-timeout', 'keepalive-timeout'
            ))
            return profiles
        except Exception as e:
            logger.error(f"Error getting profiles: {str(e)}")
            return []
    
    def create_hotspot_profile(self, profile_data: dict) -> tuple[bool, str]:
        """Creates a new hotspot user profile."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            data_to_add = {k: v for k, v in profile_data.items() if v}
            api.path('ip', 'hotspot', 'user', 'profile').add(**data_to_add)
            return True, f"Profile '{profile_data['name']}' created successfully."
        except (TrapError, Exception) as e:
            logger.error(f"Error creating profile: {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"

    def edit_hotspot_profile(self, profile_id: str, new_data: dict) -> tuple[bool, str]:
        """Edits an existing hotspot user profile."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            api.path('ip', 'hotspot', 'user', 'profile').set(**new_data, **{'.id': profile_id})
            return True, "Profile updated successfully."
        except (TrapError, Exception) as e:
            logger.error(f"Error editing profile: {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"

    def delete_hotspot_profile(self, profile_id: str) -> tuple[bool, str]:
        """Deletes a hotspot user profile."""
        try:
            api = get_mikrotik_api()
            if api is None:
                return False, "Mikrotik connection not available"
            api.path('ip', 'hotspot', 'user', 'profile').remove(profile_id)
            return True, "Profile deleted successfully."
        except (TrapError, Exception) as e:
            logger.error(f"Error deleting profile: {str(e)}")
            return False, f"Mikrotik Error: {str(e)}"
    
    def _parse_ros_time(self, time_str: str) -> int:
        """Parses RouterOS time string (e.g., 1w2d3h4m5s) into seconds."""
        if not time_str:
            return 0
        total_seconds = 0
        matches = re.findall(r'(\d+)([wdhms])', time_str)
        for value, unit in matches:
            value = int(value)
            if unit == 'w': total_seconds += value * 604800
            elif unit == 'd': total_seconds += value * 86400
            elif unit == 'h': total_seconds += value * 3600
            elif unit == 'm': total_seconds += value * 60
            elif unit == 's': total_seconds += value
        return total_seconds

    def find_and_delete_expired_users(self) -> tuple[bool, str, int]:
        """Finds and deletes users who have exceeded their time or data limits."""
        try:
            api = get_mikrotik_api()
            if api is None: # Check if API connection failed initially
                return False, "Mikrotik connection not available", 0
            
            users = self.get_hotspot_users() 
            # get_hotspot_users itself will return [] if api was None, so this is safe.
            # However, if api was None for this call but not for the initial api check,
            # we might want to re-check. But the current pattern is one api per request.
            if not users and api is None: # If users list is empty because api became None
                 return False, "Mikrotik connection not available (users fetch failed)", 0

            deleted_count = 0
            errors = []

            for user in users:
                is_expired = False
                # Check time limit
                if user.get('limit-uptime') and user['limit-uptime'] != '0s':
                    limit_sec = self._parse_ros_time(user['limit-uptime'])
                    usage_sec = self._parse_ros_time(user.get('uptime', '0s'))
                    if limit_sec > 0 and usage_sec >= limit_sec:
                        is_expired = True

                # Check total data limit
                if not is_expired and user.get('limit-bytes-total') and int(user['limit-bytes-total']) > 0:
                    limit_bytes = int(user['limit-bytes-total'])
                    usage_bytes = int(user.get('bytes-in', 0)) + int(user.get('bytes-out', 0))
                    if usage_bytes >= limit_bytes:
                        is_expired = True
                
                if is_expired:
                    try:
                        api.path('ip', 'hotspot', 'user').remove(user['.id'])
                        deleted_count += 1
                        logger.info(f"Deleted expired user '{user['name']}'")
                    except Exception as e:
                        errors.append(user['name'])
                        logger.error(f"Failed to delete expired user '{user['name']}': {e}")
            
            message = f"Successfully deleted {deleted_count} expired user(s)."
            if errors:
                message += f" Failed to delete: {', '.join(errors)}."
            
            return True, message, deleted_count
        except Exception as e:
            logger.error(f"Error during expired user cleanup: {str(e)}")
            return False, f"An unexpected error occurred: {str(e)}", 0

    def get_basic_bandwidth_analytics(self) -> dict:
        """Calculates basic bandwidth analytics from hotspot user data."""
        users = self.get_hotspot_users() # This already handles API non-availability by returning []
        
        default_analytics = {
            'total_data_all_users': 0,
            'all_users_sorted_by_data': [],
            'data_usage_by_profile': {}
        }

        if not users: # Covers API failure or no users
            return default_analytics

        total_data_all_users = 0
        users_with_total_data = []
        data_by_profile = {}

        for user in users:
            try:
                # Ensure bytes are treated as numbers, default to 0 if not present or not convertible
                bytes_in = int(user.get('bytes-in', 0) or 0)
                bytes_out = int(user.get('bytes-out', 0) or 0)
            except ValueError: # Handle case where byte counts are not valid integers
                logger.warning(f"User '{user.get('name', 'Unknown')}' has invalid byte count, treating as 0.")
                bytes_in = 0
                bytes_out = 0
                
            user_total_data = bytes_in + bytes_out
            total_data_all_users += user_total_data

            users_with_total_data.append({
                'name': user.get('name'),
                'profile': user.get('profile'),
                'bytes_in': bytes_in,
                'bytes_out': bytes_out,
                'total_data': user_total_data,
                'comment': user.get('comment') 
            })

            profile_name = user.get('profile', 'N/A')
            data_by_profile[profile_name] = data_by_profile.get(profile_name, 0) + user_total_data
            
        sorted_users = sorted(users_with_total_data, key=lambda u: u['total_data'], reverse=True)

        return {
            'total_data_all_users': total_data_all_users,
            'all_users_sorted_by_data': sorted_users,
            'data_usage_by_profile': data_by_profile
        }

    def delete_users_by_profile(self, profile_name: str) -> tuple[bool, str, int]:
        """Deletes hotspot users belonging to a specific profile."""
        api = get_mikrotik_api()
        if api is None:
            return False, "Mikrotik connection not available", 0

        users = self.get_hotspot_users()
        if not users and get_mikrotik_api() is None: # Re-check API status if user list is empty
            return False, "Mikrotik connection not available (users fetch failed)", 0

        deleted_count = 0
        failed_count = 0
        users_to_delete_ids = []

        for user in users:
            if user.get('profile') == profile_name:
                users_to_delete_ids.append(user['.id'])

        if not users_to_delete_ids:
            return True, f"No users found for profile '{profile_name}'. Nothing to delete.", 0

        for user_id in users_to_delete_ids:
            try:
                api.path('ip', 'hotspot', 'user').remove(user_id)
                deleted_count += 1
            except (TrapError, Exception) as e:
                logger.error(f"Failed to delete user with ID '{user_id}' from profile '{profile_name}': {e}")
                failed_count += 1
        
        message = f"Successfully deleted {deleted_count} user(s) from profile '{profile_name}'."
        if failed_count > 0:
            message += f" Failed to delete {failed_count} user(s)."
        
        return True, message, deleted_count

    def delete_users_by_active_status(self, is_disabled: bool) -> tuple[bool, str, int]:
        """Deletes hotspot users based on their active (enabled/disabled) status."""
        api = get_mikrotik_api()
        if api is None:
            return False, "Mikrotik connection not available", 0

        users = self.get_hotspot_users()
        if not users and get_mikrotik_api() is None: # Re-check API status if user list is empty
            return False, "Mikrotik connection not available (users fetch failed)", 0

        deleted_count = 0
        failed_count = 0
        target_status_str = 'true' if is_disabled else 'false'
        users_to_delete_ids = []

        for user in users:
            if user.get('disabled') == target_status_str:
                users_to_delete_ids.append(user['.id'])
        
        status_desc = "disabled" if is_disabled else "active (enabled)"
        if not users_to_delete_ids:
            return True, f"No {status_desc} users found. Nothing to delete.", 0

        for user_id in users_to_delete_ids:
            try:
                api.path('ip', 'hotspot', 'user').remove(user_id)
                deleted_count += 1
            except (TrapError, Exception) as e:
                logger.error(f"Failed to delete user with ID '{user_id}' (status: {status_desc}): {e}")
                failed_count += 1
        
        message = f"Successfully deleted {deleted_count} {status_desc} user(s)."
        if failed_count > 0:
            message += f" Failed to delete {failed_count} user(s)."
            
        return True, message, deleted_count

    def get_historical_total_usage_over_time(self, start_date_str: str, end_date_str: str, interval: str = 'daily') -> list:
        """
        Aggregates total data usage (in and out) from SystemSnapshot over a specified period,
        grouped by day, week, or month.
        """
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1) # Include the whole end day
        except ValueError:
            logger.error("Invalid date format for historical usage. Use YYYY-MM-DD.")
            return []

        query = db.session.query(
            SystemSnapshot.timestamp,
            func.sum(SystemSnapshot.total_data_bytes_in).label('total_in'),
            func.sum(SystemSnapshot.total_data_bytes_out).label('total_out')
        ).filter(
            SystemSnapshot.timestamp >= start_date,
            SystemSnapshot.timestamp < end_date
        )

        if interval == 'daily':
            query = query.group_by(cast(SystemSnapshot.timestamp, Date))
        elif interval == 'weekly':
            # Group by year and week number
            query = query.group_by(extract('year', SystemSnapshot.timestamp), extract('week', SystemSnapshot.timestamp))
        elif interval == 'monthly':
            # Group by year and month number
            query = query.group_by(extract('year', SystemSnapshot.timestamp), extract('month', SystemSnapshot.timestamp))
        else:
            logger.warning(f"Unsupported interval: {interval}. Defaulting to daily.")
            query = query.group_by(cast(SystemSnapshot.timestamp, Date))
            interval = 'daily' # For correct date formatting later

        query = query.order_by(SystemSnapshot.timestamp)
        
        results = []
        for row in query.all():
            # Format timestamp based on interval for consistent output
            ts_obj = row.timestamp # This is the first timestamp in the group
            if interval == 'daily':
                formatted_ts = ts_obj.strftime('%Y-%m-%d')
            elif interval == 'weekly':
                # For weekly, use the date of the start of that week (Monday)
                start_of_week = ts_obj - timedelta(days=ts_obj.weekday())
                formatted_ts = start_of_week.strftime('%Y-%m-%d (Week %W)')
            elif interval == 'monthly':
                formatted_ts = ts_obj.strftime('%Y-%m')
            
            results.append({
                'timestamp': formatted_ts,
                'total_bytes_in': row.total_in or 0,
                'total_bytes_out': row.total_out or 0
            })
        return results

    def get_historical_peak_concurrent_users_over_time(self, start_date_str: str, end_date_str: str, interval: str = 'daily') -> list:
        """
        Finds the peak number of concurrent users from SystemSnapshot over a specified period,
        grouped by day, week, or month.
        """
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)
        except ValueError:
            logger.error("Invalid date format for peak concurrent users. Use YYYY-MM-DD.")
            return []

        query = db.session.query(
            SystemSnapshot.timestamp,
            func.max(SystemSnapshot.active_users_count).label('peak_users')
        ).filter(
            SystemSnapshot.timestamp >= start_date,
            SystemSnapshot.timestamp < end_date
        )

        if interval == 'daily':
            query = query.group_by(cast(SystemSnapshot.timestamp, Date))
        elif interval == 'weekly':
            query = query.group_by(extract('year', SystemSnapshot.timestamp), extract('week', SystemSnapshot.timestamp))
        elif interval == 'monthly':
            query = query.group_by(extract('year', SystemSnapshot.timestamp), extract('month', SystemSnapshot.timestamp))
        else: # Default to daily
            query = query.group_by(cast(SystemSnapshot.timestamp, Date))
            interval = 'daily'

        query = query.order_by(SystemSnapshot.timestamp)
        
        results = []
        for row in query.all():
            ts_obj = row.timestamp
            if interval == 'daily':
                formatted_ts = ts_obj.strftime('%Y-%m-%d')
            elif interval == 'weekly':
                start_of_week = ts_obj - timedelta(days=ts_obj.weekday())
                formatted_ts = start_of_week.strftime('%Y-%m-%d (Week %W)')
            elif interval == 'monthly':
                formatted_ts = ts_obj.strftime('%Y-%m')

            results.append({
                'timestamp': formatted_ts,
                'peak_users': row.peak_users or 0
            })
        return results

    def get_user_activity_history(self, username: str, start_date_str: str, end_date_str: str) -> list:
        """
        Retrieves activity (data usage, uptime) for a specific user over a period.
        This returns all snapshots for the user, frontend might need to aggregate/process.
        """
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)
        except ValueError:
            logger.error("Invalid date format for user activity history. Use YYYY-MM-DD.")
            return []

        logs = UserActivityLog.query.filter(
            UserActivityLog.username == username,
            UserActivityLog.timestamp >= start_date,
            UserActivityLog.timestamp < end_date
        ).order_by(UserActivityLog.timestamp).all()

        return [{
            'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'profile': log.profile,
            'bytes_in': log.bytes_in,
            'bytes_out': log.bytes_out,
            'uptime_seconds': log.uptime_seconds
        } for log in logs]

    # --- Bulk Action Service Methods ---
    def bulk_delete_hotspot_users(self, usernames: list[str]) -> tuple[int, int, list[str]]:
        """Deletes a list of hotspot users by their usernames."""
        api = get_mikrotik_api()
        if api is None:
            logger.error("Bulk delete: Mikrotik API not available.")
            return 0, len(usernames), usernames # success_count, fail_count, failed_usernames

        success_count = 0
        failed_usernames = []
        
        # Fetch all user IDs first to minimize API calls if direct ID removal is faster
        # However, librouteros client might not support bulk removal by a list of IDs directly.
        # Iterative removal by username is standard.
        all_users_details = {user['name']: user['.id'] for user in self.get_hotspot_users()}

        for username in usernames:
            user_id_to_delete = all_users_details.get(username)
            if not user_id_to_delete:
                logger.warning(f"Bulk delete: User '{username}' not found.")
                failed_usernames.append(username)
                continue
            try:
                api.path('ip', 'hotspot', 'user').remove(user_id_to_delete)
                success_count += 1
                logger.info(f"Bulk delete: Successfully deleted user '{username}'.")
            except (TrapError, Exception) as e:
                logger.error(f"Bulk delete: Error deleting user '{username}': {str(e)}")
                failed_usernames.append(username)
        
        return success_count, len(failed_usernames), failed_usernames

    def bulk_set_user_disabled_status(self, usernames: list[str], disabled: bool) -> tuple[int, int, list[str]]:
        """Enables or disables a list of hotspot users."""
        api = get_mikrotik_api()
        if api is None:
            logger.error(f"Bulk set disabled status: Mikrotik API not available.")
            return 0, len(usernames), usernames

        success_count = 0
        failed_usernames = []
        disabled_str = 'true' if disabled else 'false'
        action_str = "disable" if disabled else "enable"
        
        all_users_details = {user['name']: user['.id'] for user in self.get_hotspot_users()}

        for username in usernames:
            user_id_to_update = all_users_details.get(username)
            if not user_id_to_update:
                logger.warning(f"Bulk {action_str}: User '{username}' not found.")
                failed_usernames.append(username)
                continue
            try:
                api.path('ip', 'hotspot', 'user').set(**{'.id': user_id_to_update, 'disabled': disabled_str})
                success_count += 1
                logger.info(f"Bulk {action_str}: Successfully updated user '{username}'.")
            except (TrapError, Exception) as e:
                logger.error(f"Bulk {action_str}: Error updating user '{username}': {str(e)}")
                failed_usernames.append(username)
                
        return success_count, len(failed_usernames), failed_usernames

    def bulk_change_user_profile(self, usernames: list[str], new_profile: str) -> tuple[int, int, list[str]]:
        """Changes the profile for a list of hotspot users."""
        api = get_mikrotik_api()
        if api is None:
            logger.error("Bulk change profile: Mikrotik API not available.")
            return 0, len(usernames), usernames

        # Validate if profile exists (optional, but good practice)
        available_profiles = [p['name'] for p in self.get_user_profiles()]
        if new_profile not in available_profiles:
            logger.error(f"Bulk change profile: Target profile '{new_profile}' does not exist.")
            # Treat this as a global failure for this operation, or fail all users.
            # For now, let's assume the frontend validates this, or we fail all.
            return 0, len(usernames), usernames 

        success_count = 0
        failed_usernames = []
        
        all_users_details = {user['name']: user['.id'] for user in self.get_hotspot_users()}

        for username in usernames:
            user_id_to_update = all_users_details.get(username)
            if not user_id_to_update:
                logger.warning(f"Bulk change profile: User '{username}' not found.")
                failed_usernames.append(username)
                continue
            try:
                api.path('ip', 'hotspot', 'user').set(**{'.id': user_id_to_update, 'profile': new_profile})
                success_count += 1
                logger.info(f"Bulk change profile: Successfully changed profile for user '{username}' to '{new_profile}'.")
            except (TrapError, Exception) as e:
                logger.error(f"Bulk change profile: Error updating user '{username}': {str(e)}")
                failed_usernames.append(username)
                
        return success_count, len(failed_usernames), failed_usernames


router_os_service = RouterOSService()

# --- Helper Functions ---
def format_bytes_for_export(bytes_val):
    if not bytes_val or bytes_val == '0' or bytes_val == '': return "Unlimited"
    try:
        numeric_bytes = float(bytes_val)
        if numeric_bytes == 0: return "Unlimited"
        k = 1024
        sizes = ['B', 'KB', 'MB', 'GB', 'TB']
        if numeric_bytes < 1: return f"{numeric_bytes:.0f} B"
        i = min(len(sizes) - 1, int(math.floor(math.log(numeric_bytes) / math.log(k))))
        return f"{numeric_bytes / math.pow(k, i):.2f} {sizes[i]}"
    except (ValueError, TypeError):
        return str(bytes_val)

def generate_qr_code_base64(login_url, username, password):
    """Generates a QR code for login and returns a Base64 encoded string."""
    if not QRCODE_AVAILABLE: return None
    
    full_url = f"{login_url}?username={username}&password={password}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(full_url)
    qr.make(fit=True)
    
    img = qr.make_image(image_factory=StyledPilImage, module_drawer=RoundedModuleDrawer())
    
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

# --- Flask Routes ---
@app.route('/')
def login_page():
    """Serves the login page. If already logged into the app, redirects to dashboard."""
    if current_user.is_authenticated:
        api = get_mikrotik_api()
        if api:
            return redirect(url_for('index'))
    # For login page, generate and pass CSRF token if not using WTForms directly in template
    # However, login.html uses JS fetch, so token needs to be available to JS
    # One way is to render it in a meta tag or a script variable in login.html itself.
    # The dashboard route already does this for mikrotik_userman_dashboard.html
    # For login.html, we can add a similar mechanism or rely on a global JS var if set.
    # Let's ensure login.html can also get a CSRF token.
    # A simple way for login.html, since it's served by Flask, is to inject it.
    # This is typically done if the form is generated by Flask-WTF.
    # Since forms in login.html are custom, we'll handle token in JS.
    # The CSRF token is implicitly available via csrf_token() in templates,
    # or can be generated via generate_csrf() and passed to render_template.
    # For now, we assume JS will fetch it or have it available (see login.html modifications).
    return render_template('login.html')


@app.route('/app-login', methods=['POST'])
# This route is already protected by default by Flask-WTF's CSRF protection for POST requests.
# No need to add @csrf.exempt if we intend to protect it.
def app_login_route():
    """Handles web application login."""
    data = request.form
    username = data.get('app_username')
    password = data.get('app_password')

    admin_config = app_config.get('app_admin', {})
    admin_username = admin_config.get('username')
    admin_password_hashed = admin_config.get('password_hash')

    if not admin_username or not admin_password_hashed:
        logger.error("App admin username or password hash not configured in config.json.")
        return jsonify({'success': False, 'message': _('App login not configured on server.')}), 500

    if username == admin_username and check_password_hash(admin_password_hashed, password):
        user = User.get(username)
        if user:
            login_user(user, remember=True, duration=app.config['PERMANENT_SESSION_LIFETIME'])
            logger.info(f"User '{username}' logged in successfully to the web application.")
            return jsonify({'success': True, 'message': _('Web app login successful.')})
        else: # Should not happen if User.get is consistent
            logger.error(f"User.get failed for '{username}' after successful credential check.")
            return jsonify({'success': False, 'message': _('Login failed. User object could not be created.')}), 500
    else:
        logger.warning(f"Failed login attempt for app user '{username}'.")
        return jsonify({'success': False, 'message': _('Invalid web app username or password.')}), 401


@app.route('/dashboard')
@login_required # Protect this route
def index():
    """Serves the main dashboard page."""
    return render_template('mikrotik_userman_dashboard.html')

@app.route('/api/initial-connect', methods=['POST'])
# No @login_required here, as it's for the Mikrotik connection setup,
# but it should only be callable after app login.
# The before_request_handler already protects it if user is not authenticated.
def initial_connect():
    global app_config # Ensure we're updating the global app_config
    data = request.json
    host = data.get('host')
    port = data.get('port')
    username = data.get('username')
    password = data.get('password') # Password can be empty

    if not all([host, port is not None, username is not None]): # port can be 0, username can be empty string
        return jsonify({'success': False, 'message': 'Host, Port, and Username are required.'}), 400

    try:
        port = int(port)
        if not (0 <= port <= 65535): # Port 0 is technically valid for OS to pick one
            raise ValueError("Invalid port number")
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid port number. Must be between 0 and 65535.'}), 400

    logger.info(f"Attempting initial connection to Mikrotik: {host}:{port} with user: {username}")
    try:
        # Attempt connection
        temp_conn = librouteros.connect(
            host=host,
            username=username,
            password=password,
            port=port,
            ssl=app_config['mikrotik'].get('use_ssl', False) # Use current SSL setting or default
        )
        temp_conn.close() # Close if successful, we just tested it.
        logger.info("Initial connection test successful.")

        # Update config.json
        new_mikrotik_config = {
            "host": host,
            "port": port,
            "username": username,
            "password": password, # Save the password
            "use_ssl": app_config['mikrotik'].get('use_ssl', False), # Preserve existing SSL setting
            "hotspot_login_url": app_config['mikrotik'].get('hotspot_login_url', '') # Preserve existing
        }
        config_loader.update_config({'mikrotik': new_mikrotik_config})
        app_config = config_loader.get_config() # Reload app_config to reflect changes

        return jsonify({'success': True, 'message': 'Successfully connected and configuration saved.'})

    except (librouteros.exceptions.LibRouterosError, TrapError, socket.error, ConnectionRefusedError, OSError) as e:
        logger.error(f"Initial connection failed: {e}")
        # Sanitize error message for user
        error_message = str(e)
        if "authentication failed" in error_message.lower():
            return jsonify({'success': False, 'message': 'Authentication failed. Please check username and password.'}), 401
        elif "connection refused" in error_message.lower() or "timed out" in error_message.lower() or "no route to host" in error_message.lower():
            return jsonify({'success': False, 'message': 'Connection refused or timed out. Check IP address, port, and router firewall.'}), 400
        return jsonify({'success': False, 'message': f'Connection failed: {e}.'}), 400
    except Exception as e:
        logger.error(f"Unexpected error during initial connection: {e}")
        return jsonify({'success': False, 'message': f'An unexpected error occurred: {e}.'}), 500


@app.route('/api/test-connection', methods=['POST'])
@login_required
def test_connection():
    success, message = router_os_service.test_connection()
    return jsonify({'success': success, 'message': message})

@app.route('/api/config', methods=['GET'])
@login_required
def get_config_route():
    cfg = config_loader.get_config()
    # Add status of optional features
    cfg['features'] = {
        'pdf_export': WEASYPRINT_AVAILABLE,
        'qr_codes': QRCODE_AVAILABLE
    }
    # Add app_admin section but without password for security
    app_admin_secure = cfg.get('app_admin', {}).copy()
    app_admin_secure.pop('password_hash', None) # Remove password hash
    cfg['app_admin_display'] = app_admin_secure

    return jsonify(cfg)

@app.route('/api/config', methods=['POST'])
@login_required
def update_config_route():
    data = request.json
    # Prevent app_admin password_hash from being updated directly via this generic route
    # It should be handled by a dedicated password change route (not in scope for this subtask)
    if 'app_admin' in data:
        # If 'app_admin' is present, make sure it doesn't try to wipe/change password_hash
        # Best is to pop it and instruct user to use a dedicated mechanism if they want to change app user details
        data.pop('app_admin', None)
        # Or, more carefully, preserve existing password if username is updated
        # current_admin_config = config_loader.get_config().get('app_admin', {})
        # if 'username' in data.get('app_admin', {}): # if new username is provided
        #    data['app_admin']['password_hash'] = current_admin_config.get('password_hash')


    config_loader.update_config(data)
    return jsonify({'success': True, 'message': 'Configuration updated and saved.'})

@app.route('/api/admin/change-password', methods=['POST'])
@login_required
def change_admin_password():
    global app_config # Declare app_config as global at the beginning of the function
    data = request.json
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    confirm_password = data.get('confirm_password')

    if not all([current_password, new_password, confirm_password]):
        return jsonify({'success': False, 'message': _('All password fields are required.')}), 400

    if new_password != confirm_password:
        return jsonify({'success': False, 'message': _('New passwords do not match.')}), 400

    if len(new_password) < 8: # Example: Enforce minimum password length
        return jsonify({'success': False, 'message': _('New password must be at least 8 characters long.')}), 400

    admin_username = app_config.get('app_admin', {}).get('username')
    current_hash = app_config.get('app_admin', {}).get('password_hash')

    if not check_password_hash(current_hash, current_password):
        return jsonify({'success': False, 'message': _('Current password is incorrect.')}), 401 # Unauthorized

    new_hash = generate_password_hash(new_password)

    try:
        # Use the new method in ConfigLoader
        updated = config_loader.update_admin_credentials(new_password_hash=new_hash)
        if updated:
            # Reload app_config to reflect the change immediately for the current session if needed,
            # though for password hash it's mainly for next logins.
            # global app_config # This was the problematic duplicate
            app_config = config_loader.get_config()
            logger.info(f"Admin password changed successfully for user '{admin_username}'.")
            return jsonify({'success': True, 'message': _('Admin password changed successfully.')})
        else:
            # This case should ideally not be hit if logic is correct (e.g. hash is actually different)
            logger.warning("Admin password change requested, but new hash was same as old or not updated.")
            return jsonify({'success': False, 'message': _('Password not changed. New password might be the same as old.')})
    except Exception as e:
        logger.error(f"Error saving new admin password hash to config: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _('Could not save new password due to a server error.')}), 500


@app.route('/api/dashboard-stats', methods=['GET'])
@login_required
def get_dashboard_stats():
    users = router_os_service.get_hotspot_users()
    sessions = router_os_service.get_active_sessions()
    total_users = len(users)
    active_sessions = len(sessions)
    return jsonify({'total_users': total_users, 'active_sessions': active_sessions})

@app.route('/api/users', methods=['GET'])
@login_required
def get_users():
    users = router_os_service.get_hotspot_users()
    # Also include profiles in this response for convenience, as they are often needed together
    profiles = router_os_service.get_user_profiles()
    return jsonify({'users': users, 'profiles': profiles})

@app.route('/api/users', methods=['POST'])
@login_required
def create_user():
    data = request.json
    username = data.get('name')
    password = data.get('password')
    if not username or not password:
        return jsonify({'success': False, 'message': _('Username and password are required.')}), 400
    
    # Validate 'limit-bytes-total' if present
    if 'limit-bytes-total' in data and data['limit-bytes-total'] is not None:
        try:
            # Ensure it's an integer. The frontend sends it already multiplied (bytes).
            int(data['limit-bytes-total'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': _('Invalid Data Limit. Must be a whole number of bytes.')}), 400

    success, message = router_os_service.create_hotspot_user(data)
    return jsonify({'success': success, 'message': message}) # Assuming router_os_service returns translated messages or they are generic

@app.route('/api/bulk-create-users', methods=['POST'])
@login_required
def bulk_create_users():
    data = request.json
    number_of_users = data.get('number_of_users')
    profile = data.get('profile')
    username_length = int(data.get('username_length', 6))
    password_length = int(data.get('password_length', 8))

    username_prefix = data.get('username_prefix', '')
    username_charset_key = data.get('username_charset', 'alphanumeric')
    password_charset_key = data.get('password_charset', 'alphanumeric_symbols')
    comment_for_batch = data.get('comment_prefix', '')

    if not all([number_of_users, profile]):
        return jsonify({'success': False, 'message': _('Number of users and profile are required.')}), 400
    if int(number_of_users) <= 0:
        return jsonify({'success': False, 'message': _('Number of users must be positive.')}), 400

    # Define character sets
    safe_symbols = '!@#$%^&*-=+'
    charsets = {
        'alphanumeric': string.ascii_letters + string.digits,
        'alphanumeric_upper': string.ascii_uppercase + string.digits,
        'alphanumeric_lower': string.ascii_lowercase + string.digits,
        'numeric': string.digits,
        'alpha_upper': string.ascii_uppercase,
        'alpha_lower': string.ascii_lowercase,
        'alphanumeric_symbols': string.ascii_letters + string.digits + safe_symbols
    }
    username_chars = charsets.get(username_charset_key, charsets['alphanumeric'])
    password_chars = charsets.get(password_charset_key, charsets['alphanumeric_symbols'])

    base_user_data_keys = ['profile', 'limit-uptime', 'limit-bytes-total', 'server']
    base_user_data = {k: data[k] for k in base_user_data_keys if k in data and data[k]}

    # Validate 'limit-bytes-total' in base_user_data if present
    if 'limit-bytes-total' in base_user_data and base_user_data['limit-bytes-total'] is not None:
        try:
            # Ensure it's an integer. The frontend sends it already multiplied (bytes).
            int(base_user_data['limit-bytes-total'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': _('Invalid Data Limit for batch. Must be a whole number of bytes.')}), 400

    created_credentials = []
    errors = []
    
    for i in range(int(number_of_users)): # Changed loop variable from _ to i
        random_username_part = ''.join(random.choices(username_chars, k=username_length))
        username = username_prefix + random_username_part
        password = ''.join(random.choices(password_chars, k=password_length))
        
        user_data = base_user_data.copy()
        user_data['name'] = username
        user_data['password'] = password
        
        if comment_for_batch: # Use the batch comment if provided
            user_data['comment'] = comment_for_batch
        # else, no comment is set for the user

        success, msg = router_os_service.create_hotspot_user(user_data)
        if success:
            created_credentials.append({
                'username': username,
                'password': password,
                'limit-uptime': user_data.get('limit-uptime', 'Unlimited'), # Get from user_data used for creation
                'profile': user_data.get('profile', '') # Get profile from user_data
            })
        else:
            errors.append({'username': username, 'error': msg})

    return jsonify({
        'success': len(errors) == 0,
        'message': _("Created {0} users. Failed: {1}.").format(len(created_credentials), len(errors)),
        'created_credentials': created_credentials,
        'errors': errors
    })

@app.route('/api/users/<username>', methods=['PUT'])
@login_required
def edit_user(username: str):
    data = request.json
    if 'disabled' in data:
        data['disabled'] = 'true' if data['disabled'] else 'false'

    # Validate 'limit-bytes-total' if present
    if 'limit-bytes-total' in data and data['limit-bytes-total'] is not None:
        try:
            # Ensure it's an integer. The frontend sends it already multiplied (bytes).
            int(data['limit-bytes-total'])
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': _('Invalid Data Limit. Must be a whole number of bytes.')}), 400

    success, message = router_os_service.edit_hotspot_user(username, data)
    return jsonify({'success': success, 'message': message})

@app.route('/api/users/<username>', methods=['DELETE'])
@login_required
def delete_user(username: str):
    success, message = router_os_service.delete_hotspot_user(username)
    return jsonify({'success': success, 'message': message})

@app.route('/api/active-sessions', methods=['GET'])
@login_required
def get_active_sessions_route():
    sessions = router_os_service.get_active_sessions()
    return jsonify({'sessions': sessions})

@app.route('/api/disconnect-user/<active_id>', methods=['POST'])
@login_required
def disconnect_user_session(active_id: str):
    success, message = router_os_service.disconnect_user(active_id)
    return jsonify({'success': success, 'message': message})

@app.route('/api/delete-expired-users', methods=['POST'])
@login_required
def delete_expired_users_route():
    success, message, count = router_os_service.find_and_delete_expired_users()
    return jsonify({'success': success, 'message': message, 'deleted_count': count})

@app.route('/api/users/delete-by-profile/<profile_name>', methods=['DELETE'])
@login_required
def delete_users_by_profile_route(profile_name: str):
    try:
        success, message, deleted_count = router_os_service.delete_users_by_profile(profile_name)
        # Assuming message from service is already i18n or generic
        return jsonify({'success': success, 'message': message, 'deleted_count': deleted_count})
    except Exception as e:
        logger.error(f"Error in delete_users_by_profile_route for profile '{profile_name}': {str(e)}")
        user_message = _("An unexpected error occurred while deleting users by profile.")
        return jsonify({'success': False, 'message': user_message, 'deleted_count': 0}), 500

@app.route('/api/users/delete-by-active-status/<status>', methods=['DELETE'])
@login_required
def delete_users_by_active_status_route(status: str):
    is_disabled: bool
    if status.lower() == 'disabled':
        is_disabled = True
    elif status.lower() == 'active':
        is_disabled = False
    else:
        return jsonify({
            'success': False,
            'message': _('Invalid status parameter. Must be "active" or "disabled".'),
            'deleted_count': 0
        }), 400
    try:
        success, message, deleted_count = router_os_service.delete_users_by_active_status(is_disabled)
        return jsonify({'success': success, 'message': message, 'deleted_count': deleted_count})
    except Exception as e:
        status_desc = "disabled" if is_disabled else "active"
        logger.error(f"Error in delete_users_by_active_status_route for {status_desc} users: {str(e)}")
        user_message = _("An unexpected error occurred while deleting users by status.")
        return jsonify({'success': False, 'message': user_message, 'deleted_count': 0}), 500

# --- Profile Management Routes ---
@app.route('/api/profiles', methods=['GET'])
@login_required
def get_profiles_route():
    profiles = router_os_service.get_user_profiles()
    return jsonify({'profiles': profiles})

@app.route('/api/profiles', methods=['POST'])
@login_required
def create_profile_route():
    data = request.json
    if not data.get('name'):
        return jsonify({'success': False, 'message': _('Profile name is required.')}), 400
    success, message = router_os_service.create_hotspot_profile(data)
    return jsonify({'success': success, 'message': message})

@app.route('/api/profiles/<profile_id>', methods=['PUT'])
@login_required
def edit_profile_route(profile_id: str):
    data = request.json
    if not data:
        return jsonify({'success': False, 'message': _('No data provided for update.')}), 400
    success, message = router_os_service.edit_hotspot_profile(profile_id, data)
    return jsonify({'success': success, 'message': message})

@app.route('/api/profiles/<profile_id>', methods=['DELETE'])
@login_required
def delete_profile_route(profile_id: str):
    success, message = router_os_service.delete_hotspot_profile(profile_id)
    return jsonify({'success': success, 'message': message})

# --- UNIFIED EXPORT ROUTE ---
@app.route('/api/export-users', methods=['GET'])
@login_required
def export_users_route():
    export_format = request.args.get('format', 'json').lower()
    profile_filter = request.args.get('profile_filter')

    users = router_os_service.get_hotspot_users()

    if profile_filter:
        users = [user for user in users if user.get('profile') == profile_filter]

    if not users:
        return _("No users found for the selected criteria."), 404 # Ensure this response is handled by client

    if export_format == 'json':
        return jsonify(users)

    elif export_format == 'csv':
        si = io.StringIO()
        cw = csv.writer(si)
        headers = [
            'Username', 'Password', 'Profile', 'Time Limit',
            'Total Data Limit', 'Comment', 'Disabled'
        ]
        cw.writerow(headers)
        for user in users:
            row = [
                user.get('name', ''), user.get('password', ''), user.get('profile', ''),
                user.get('limit-uptime', _('Unlimited')), # Assuming Unlimited is a translated term
                format_bytes_for_export(user.get('limit-bytes-total')),
                user.get('comment', ''), user.get('disabled', 'false')
            ]
            cw.writerow(row)
        output = si.getvalue()
        filename_profile_part = profile_filter if profile_filter and profile_filter != 'All Profiles' else 'all'
        return Response(output, mimetype="text/csv", headers={"Content-disposition": f"attachment; filename=users_{filename_profile_part}.csv"})

    elif export_format == 'html_voucher' or export_format == 'pdf_voucher':
        vouchers_data = [
            {
                'username': u.get('name'),
                'password': u.get('password'),
                'limit-uptime': u.get('limit-uptime', 'Unlimited'),
                'profile': u.get('profile', '')
            } for u in users
        ]
        login_url = app_config['mikrotik'].get('hotspot_login_url', '')
        filename_profile_part = profile_filter if profile_filter and profile_filter != 'All Profiles' else 'all'

        if export_format == 'pdf_voucher':
            if not WEASYPRINT_AVAILABLE:
                return jsonify({"success": False, "message": _("PDF generation is disabled. Please install system dependencies for WeasyPrint and restart the application.")}), 501
            
            html_content = _generate_vouchers_page_html(vouchers_data, login_url, include_print_button=False)
            try:
                pdf_file = WeasyHTML(string=html_content).write_pdf()
                return Response(
                    pdf_file, 
                    mimetype="application/pdf", 
                    headers={"Content-disposition": f"attachment; filename=vouchers_{filename_profile_part}.pdf"}
                )
            except Exception as e:
                 logger.error(f"Failed to generate PDF from export route: {e}")
                 return jsonify({"success": False, "message": _("An unexpected error occurred during PDF generation: {error}").format(error=str(e))}), 500
        else: # html_voucher
            html_content = _generate_vouchers_page_html(vouchers_data, login_url, include_print_button=True)
            return Response(html_content, mimetype="text/html")
    else:
        return jsonify({"success": False, "message": _("Invalid export format.")}), 400

@app.route('/api/analytics/basic_summary', methods=['GET'])
@login_required
def get_basic_analytics_summary_route():
    try:
        logger.info("API: Fetching basic bandwidth analytics.")
        analytics_data = router_os_service.get_basic_bandwidth_analytics()
        return jsonify(analytics_data)
    except Exception as e:
        logger.error(f"API: Error fetching basic analytics: {str(e)}")
        return jsonify({'success': False, 'message': _('A server error occurred while fetching analytics: {error}').format(error=str(e))}), 500

# --- Historical Analytics API Endpoints ---
@app.route('/api/analytics/historical_usage', methods=['GET'])
@login_required
def get_historical_usage_route():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    interval = request.args.get('interval', 'daily') # daily, weekly, monthly

    if not start_date or not end_date:
        return jsonify({'success': False, 'message': 'start_date and end_date parameters are required.'}), 400
    
    try:
        data = router_os_service.get_historical_total_usage_over_time(start_date, end_date, interval)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"API: Error fetching historical usage: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _('A server error occurred while fetching historical usage data.')}), 500

@app.route('/api/analytics/historical_peak_users', methods=['GET'])
@login_required
def get_historical_peak_users_route():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    interval = request.args.get('interval', 'daily')

    if not start_date or not end_date:
        return jsonify({'success': False, 'message': 'start_date and end_date parameters are required.'}), 400

    try:
        data = router_os_service.get_historical_peak_concurrent_users_over_time(start_date, end_date, interval)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"API: Error fetching historical peak users: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _('A server error occurred while fetching historical peak users data.')}), 500

@app.route('/api/analytics/user_activity_history/<username>', methods=['GET'])
@login_required
def get_user_activity_history_route(username):
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if not start_date or not end_date:
        return jsonify({'success': False, 'message': 'start_date and end_date parameters are required.'}), 400

    try:
        data = router_os_service.get_user_activity_history(username, start_date, end_date)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        logger.error(f"API: Error fetching user activity history for {username}: {e}", exc_info=True)
        return jsonify({'success': False, 'message': _('A server error occurred while fetching user activity history.')}), 500

# --- Bulk Action API Endpoints ---
@app.route('/api/users/bulk-delete', methods=['POST'])
@login_required
def bulk_delete_users_route():
    data = request.json
    usernames = data.get('usernames', [])
    if not usernames:
        return jsonify({'success': False, 'message': _('No usernames provided for bulk deletion.')}), 400

    success_count, fail_count, failed_usernames = router_os_service.bulk_delete_hotspot_users(usernames)
    
    if fail_count == 0:
        message = _('Successfully deleted {count} users.').format(count=success_count)
        return jsonify({'success': True, 'message': message, 'success_count': success_count, 'fail_count': fail_count})
    else:
        message = _('Completed bulk deletion. Succeeded: {success_count}, Failed: {fail_count}. Users not deleted: {users}').format(
            success_count=success_count, fail_count=fail_count, users=', '.join(failed_usernames)
        )
        return jsonify({'success': False, 'message': message, 'success_count': success_count, 'fail_count': fail_count, 'failed_usernames': failed_usernames})

@app.route('/api/users/bulk-disable', methods=['POST'])
@login_required
def bulk_disable_users_route():
    data = request.json
    usernames = data.get('usernames', [])
    if not usernames:
        return jsonify({'success': False, 'message': _('No usernames provided for bulk disable.')}), 400

    success_count, fail_count, failed_usernames = router_os_service.bulk_set_user_disabled_status(usernames, disabled=True)
    
    if fail_count == 0:
        message = _('Successfully disabled {count} users.').format(count=success_count)
        return jsonify({'success': True, 'message': message, 'success_count': success_count, 'fail_count': fail_count})
    else:
        message = _('Completed bulk disable. Succeeded: {success_count}, Failed: {fail_count}. Users not disabled: {users}').format(
            success_count=success_count, fail_count=fail_count, users=', '.join(failed_usernames)
        )
        return jsonify({'success': False, 'message': message, 'success_count': success_count, 'fail_count': fail_count, 'failed_usernames': failed_usernames})

@app.route('/api/users/bulk-enable', methods=['POST'])
@login_required
def bulk_enable_users_route():
    data = request.json
    usernames = data.get('usernames', [])
    if not usernames:
        return jsonify({'success': False, 'message': _('No usernames provided for bulk enable.')}), 400

    success_count, fail_count, failed_usernames = router_os_service.bulk_set_user_disabled_status(usernames, disabled=False)

    if fail_count == 0:
        message = _('Successfully enabled {count} users.').format(count=success_count)
        return jsonify({'success': True, 'message': message, 'success_count': success_count, 'fail_count': fail_count})
    else:
        message = _('Completed bulk enable. Succeeded: {success_count}, Failed: {fail_count}. Users not enabled: {users}').format(
            success_count=success_count, fail_count=fail_count, users=', '.join(failed_usernames)
        )
        return jsonify({'success': False, 'message': message, 'success_count': success_count, 'fail_count': fail_count, 'failed_usernames': failed_usernames})

@app.route('/api/users/bulk-change-profile', methods=['POST'])
@login_required
def bulk_change_profile_route():
    data = request.json
    usernames = data.get('usernames', [])
    new_profile = data.get('profile')

    if not usernames:
        return jsonify({'success': False, 'message': _('No usernames provided for bulk profile change.')}), 400
    if not new_profile:
        return jsonify({'success': False, 'message': _('No new profile provided for bulk profile change.')}), 400

    success_count, fail_count, failed_usernames = router_os_service.bulk_change_user_profile(usernames, new_profile)

    if fail_count == 0:
        message = _('Successfully changed profile for {count} users to "{profile}".').format(count=success_count, profile=new_profile)
        return jsonify({'success': True, 'message': message, 'success_count': success_count, 'fail_count': fail_count})
    else:
        message = _('Completed bulk profile change to "{profile}". Succeeded: {success_count}, Failed: {fail_count}. Users not updated: {users}').format(
            profile=new_profile, success_count=success_count, fail_count=fail_count, users=', '.join(failed_usernames)
        )
        return jsonify({'success': False, 'message': message, 'success_count': success_count, 'fail_count': fail_count, 'failed_usernames': failed_usernames})


@app.route('/api/translations')
# This route is called by login.html, so it should be accessible without app login.
# Mikrotik connection is not needed for translations.
def get_translations():
    # Define all keys that the JavaScript side will need.
    # Using explicit keys allows for easier management and extraction for .po files.
    translations = {
        # Common alerts & messages
        'Loading...': _('Loading...'),
        'Successfully connected! Redirecting...': _('Successfully connected! Redirecting...'),
        'Connection failed. Please check details and try again.': _('Connection failed. Please check details and try again.'),
        'Network error or server is unreachable.': _('Network error or server is unreachable.'),
        'Operation successful': _('Operation successful'),
        'Operation failed': _('Operation failed'),
        'Are you sure?': _('Are you sure?'),
        'Saved': _('Saved'),
        'Deleted': _('Deleted'),
        'Updated': _('Updated'),
        'Created': _('Created'),
        'Connected': _('Connected'),
        'Disconnected': _('Disconnected'),
        'Connection test failed. Router might be unreachable.': _('Connection test failed. Router might be unreachable.'),
        'Configuration saved! Testing new connection...': _('Configuration saved! Testing new connection...'),
        'User created successfully!': _('User created successfully!'),
        'User updated successfully!': _('User updated successfully!'),
        'Profile updated successfully!': _('Profile updated successfully!'),
        'Profile created successfully!': _('Profile created successfully!'),
        'No users match the criteria.': _('No users match the criteria.'),
        'No active sessions found.': _('No active sessions found.'),
        'Could not load users.': _('Could not load users.'),
        'Could not load sessions.': _('Could not load sessions.'),
        'No profiles found.': _('No profiles found.'),
        'Loading users...': _('Loading users...'),
        'Loading sessions...': _('Loading sessions...'),
        'Loading profiles...': _('Loading profiles...'),
        'Loading analytics data...': _('Loading analytics data...'),
        'Total Data Transferred: Loading...': _('Total Data Transferred: Loading...'),
        'Could not load top user data.': _('Could not load top user data.'),
        'Could not load profile usage data.': _('Could not load profile usage data.'),
        'No user data usage available.': _('No user data usage available.'),
        'No profile usage data available.': _('No profile usage data available.'),
        'Total Data Transferred: Error loading data': _('Total Data Transferred: Error loading data'),
        'Connect': _('Connect'),
        'Connecting...': _('Connecting...'),
        'Refresh': _('Refresh'),
        'Test': _('Test'),
        'Testing...': _('Testing...'),
        'Save': _('Save'),
        'Saving...': _('Saving...'),
        'Delete': _('Delete'),
        'Deleting...': _('Deleting...'),
        'Disconnect': _('Disconnect'),
        'Disconnecting...': _('Disconnecting...'),
        'Add Profile': _('Add Profile'),
        'Edit Profile': _('Edit Profile'),
        'confirmLogout': _('Are you sure you want to logout?'),
        'confirmDeleteUser': _('Are you sure you want to delete user "{0}"?'),
        'confirmDisconnectUser': _('Are you sure you want to disconnect user "{0}"?'),
        'confirmDeleteProfile': _('Are you sure you want to delete profile "{0}"? This cannot be undone.'),
        'confirmDeleteExpiredUsers': _('Are you sure you want to find and delete ALL expired users? This action is permanent.'),
        'No generated voucher data available to view.': _('No generated voucher data available to view.'),
        'Hotspot Login URL is not set in Settings (under the Settings Tab). QR Codes cannot be generated for viewing if this is missing.': _('Hotspot Login URL is not set in Settings (under the Settings Tab). QR Codes cannot be generated for viewing if this is missing.'),
        'No generated voucher data available for PDF export.': _('No generated voucher data available for PDF export.'),
        'Hotspot Login URL is not set in Settings. QR Codes might be omitted in the PDF if this URL is required by the backend for them.': _('Hotspot Login URL is not set in Settings. QR Codes might be omitted in the PDF if this URL is required by the backend for them.'),
        'Unlimited': _('Unlimited'),
        'All Profiles': _('All Profiles'),
        'Select Profile': _('Select Profile'),
        'Disabled': _('Disabled'),
        'Active': _('Active'),
        'Logout failed unexpectedly. Please try again.': _('Logout failed unexpectedly. Please try again.'),
        'Expected JSON response from server for {0}, but received {1}.': _('Expected JSON response from server for {0}, but received {1}.'),
        'Total Data Transferred: {0}': _('Total Data Transferred: {0}'),
        'Edit User: {0}': _('Edit User: {0}'),
        'Edit Profile: {0}': _('Edit Profile: {0}'),
        'Add New Profile': _('Add New Profile'),
        'Profile {0} created successfully!': _('Profile {0} created successfully!'),
        'Profile {0} updated successfully!': _('Profile {0} updated successfully!'),
        'User "{0}" deleted.': _('User "{0}" deleted.'),
        'User disconnected.': _('User disconnected.'),
        'Profile "{0}" deleted.': _('Profile "{0}" deleted.'),
        'HTTP error! status: {0}': _('HTTP error! status: {0}'),
        'Connection failed (Error {0}). Please check details and try again.': _('Connection failed (Error {0}). Please check details and try again.'),

        # New keys for delete features
        'Delete Users by Profile': _('Delete Users by Profile'), # Title and button text
        'Select Profile to Delete Users From:': _('Select Profile to Delete Users From:'),
        'Delete Users by Active Status': _('Delete Users by Active Status'), # Title and button text
        'Select User Status to Delete:': _('Select User Status to Delete:'),
        'Active Users': _('Active Users'), # Option in select
        'Disabled Users': _('Disabled Users'), # Option in select
        '-- Select Profile --': _('-- Select Profile --'), # Default option for profile select
        '-- Select Status --': _('-- Select Status --'), # Default option for status select
        
        # JavaScript alert/confirm messages
        'Please select a profile to delete users from.': _('Please select a profile to delete users from.'),
        'Are you sure you want to delete ALL users from profile "{0}"? This action cannot be undone and is permanent.': _('Are you sure you want to delete ALL users from profile "{0}"? This action cannot be undone and is permanent.'),
        'Please select a user status to delete.': _('Please select a user status to delete.'),
        'Are you sure you want to delete all {0} users? This action cannot be undone and is permanent.': _('Are you sure you want to delete all {0} users? This action cannot be undone and is permanent.'),
        
        # Messages from backend that might be displayed via showAlert if not already translated by Flask
        # These are examples; actual messages from backend routes are already wrapped in _()
        # 'Successfully deleted {0} user(s) from profile "{1}".': _('Successfully deleted {0} user(s) from profile "{1}".'),
        # 'Successfully deleted {0} {1} user(s).': _('Successfully deleted {0} {1} user(s).'),
        # 'Failed to delete users from profile "{0}".': _('Failed to delete users from profile "{0}".'),
        # 'Failed to delete {0} user(s).': _('Failed to delete {0} user(s).'),
        'Operation failed, no users deleted.': _('Operation failed, no users deleted.'),
        'Successfully processed users for profile {0}. Deleted {1} user(s).': _('Successfully processed users for profile {0}. Deleted {1} user(s).'),
        'Failed to delete users from profile {0}.': _('Failed to delete users from profile {0}.'),
        'Successfully processed {0} users. Deleted {1} user(s).': _('Successfully processed {0} users. Deleted {1} user(s).'),
        'Failed to delete {0} users.': _('Failed to delete {0} users.'),

        # Admin Password Change Feature
        'Change Admin Password': _('Change Admin Password'),
        'Current Password': _('Current Password'),
        'New Password': _('New Password'),
        'Confirm New Password': _('Confirm New Password'),
        'Change Password': _('Change Password'),
        'All password fields are required.': _('All password fields are required.'),
        'New passwords do not match.': _('New passwords do not match.'),
        'New password must be at least 8 characters long.': _('New password must be at least 8 characters long.'),
        'Current password is incorrect.': _('Current password is incorrect.'),
        'Admin password changed successfully.': _('Admin password changed successfully.'),
        'Admin password changed successfully. You may need to log in again with your new password if your session is invalidated.': _('Admin password changed successfully. You may need to log in again with your new password if your session is invalidated.'),

        # Persistent connection error messages
        'Network error or server is unreachable. Please check your connection and the server status. You may need to <a href="#" onclick="navigateToTab(\'settings\'); return false;">reconfigure settings</a> or refresh the page.': _('Network error or server is unreachable. Please check your connection and the server status. You may need to <a href="#" onclick="navigateToTab(\'settings\'); return false;">reconfigure settings</a> or refresh the page.'),
        'Network Error': _('Network Error'),
        'An unexpected error occurred.': _('An unexpected error occurred.'),

        # Input Validation Messages
        'Invalid Data Limit. Must be a whole number of bytes.': _('Invalid Data Limit. Must be a whole number of bytes.'),
        'Invalid Data Limit for batch. Must be a whole number of bytes.': _('Invalid Data Limit for batch. Must be a whole number of bytes.'),

        # Feature availability messages
        'PDF export is not available. Server may be missing dependencies.': _('PDF export is not available. Server may be missing dependencies.'),
        '(PDF export disabled)': _('(PDF export disabled)'),
        'PDF voucher export is not available. Server may be missing dependencies.': _('PDF voucher export is not available. Server may be missing dependencies.')
    }
    return jsonify(translations)

if __name__ == '__main__':
    server_config = app_config['server']
    print("="*40)
    print(_("  Mikrotik Hotspot Management System v2"))
    print("="*40)
    print(f"\n✅ {_('Dashboard available at:')} http://{server_config['host']}:{server_config['port']}")
    
    with app.app_context():
        db.create_all()
        logger.info("Database tables created (if they didn't exist).")

    # --- Scheduler Setup ---
    def log_router_data_job():
        """Scheduled job to log data from the Mikrotik router."""
        with app.app_context(): # Ensure app context for db and config access
            logger.info("Scheduler: Running log_router_data_job...")
            try:
                # Check if Mikrotik API is available (similar to how it's done in routes)
                # This requires a request context for 'g', so we use a direct service call pattern
                # or ensure the service method itself can acquire the API if not in 'g'.
                # For simplicity, let's assume router_os_service methods can be called.
                # If they rely on 'g', this job would need to simulate parts of a request context
                # or the service methods need refactoring.
                # Assuming router_os_service.get_hotspot_users() and get_active_sessions()
                # can establish their own connection if needed, or we pass the app explicitly.

                # Re-instantiate RouterOSService or ensure it can work outside request context
                # For this job, it's better if RouterOSService can be instantiated and used directly.
                # Let's assume its methods like get_hotspot_users correctly use get_mikrotik_api(),
                # which in turn might need app context if 'g' is not available.
                # Since we are in app_context(), get_mikrotik_api() *should* work.
                
                # Ensure Mikrotik API is available (mimicking get_mikrotik_api without 'g')
                current_config = config_loader.get_config()
                mikrotik_cfg = current_config['mikrotik']
                temp_api = None
                connection_attempts = 3
                attempt_delay_seconds = 10

                for attempt in range(connection_attempts):
                    try:
                        logger.info(f"Scheduler: Attempting to connect to Mikrotik (Attempt {attempt + 1}/{connection_attempts})...")
                        temp_api = librouteros.connect(
                            host=mikrotik_cfg['host'],
                            username=mikrotik_cfg['username'],
                            password=mikrotik_cfg['password'],
                            port=mikrotik_cfg['port'],
                            ssl=mikrotik_cfg.get('use_ssl', False),
                            timeout=10 # Add a connection timeout
                        )
                        logger.info("Scheduler: Successfully connected to Mikrotik for data logging.")
                        break # Exit loop on successful connection
                    except (librouteros.exceptions.LibRouterosError, socket.error, ConnectionRefusedError, OSError) as api_conn_e:
                        logger.warning(f"Scheduler: Connection attempt {attempt + 1} failed: {api_conn_e}")
                        if attempt < connection_attempts - 1:
                            logger.info(f"Scheduler: Retrying in {attempt_delay_seconds} seconds...")
                            import time # Import time module for sleep
                            time.sleep(attempt_delay_seconds)
                        else:
                            logger.error("Scheduler: All connection attempts failed. Cannot log router data.")
                            return # Exit job if all connection attempts fail
                    except Exception as e: # Catch any other unexpected error during connect
                        logger.error(f"Scheduler: Unexpected error during Mikrotik connection attempt {attempt + 1}: {e}", exc_info=True)
                        if attempt < connection_attempts - 1:
                             logger.info(f"Scheduler: Retrying in {attempt_delay_seconds} seconds...")
                             import time
                             time.sleep(attempt_delay_seconds)
                        else:
                            logger.error("Scheduler: All connection attempts failed due to unexpected error. Cannot log router data.")
                            return

                if not temp_api: # Should be redundant if return is hit above, but as a safeguard
                    logger.error("Scheduler: Mikrotik API not available after retry attempts.")
                    return

                # --- Fetch Data using the temporary API connection ---
                try:
                    users_raw = list(temp_api.path('ip', 'hotspot', 'user').select(
                        '.id', 'name', 'profile', 'uptime', 'bytes-in', 'bytes-out'
                    ))
                    active_sessions_raw = list(temp_api.path('ip', 'hotspot', 'active').select('.id'))
                except Exception as fetch_e:
                    logger.error(f"Scheduler: Error fetching data from Mikrotik: {fetch_e}")
                    if temp_api: temp_api.close()
                    return
                finally:
                    if temp_api: temp_api.close()


                current_time = datetime.utcnow()
                total_bytes_in_snapshot = 0
                total_bytes_out_snapshot = 0

                for user_data_raw in users_raw:
                    try:
                        uptime_str = user_data_raw.get('uptime', '0s')
                        uptime_sec = router_os_service._parse_ros_time(uptime_str) # Use existing parser

                        bytes_in_val = int(user_data_raw.get('bytes-in', 0) or 0)
                        bytes_out_val = int(user_data_raw.get('bytes-out', 0) or 0)
                        
                        log_entry = UserActivityLog(
                            timestamp=current_time,
                            username=user_data_raw.get('name'),
                            profile=user_data_raw.get('profile'),
                            bytes_in=bytes_in_val,
                            bytes_out=bytes_out_val,
                            uptime_seconds=uptime_sec
                        )
                        db.session.add(log_entry)
                        
                        total_bytes_in_snapshot += bytes_in_val
                        total_bytes_out_snapshot += bytes_out_val
                    except Exception as e_user:
                        logger.error(f"Scheduler: Error processing user {user_data_raw.get('name', 'N/A')} for logging: {e_user}")

                snapshot_entry = SystemSnapshot(
                    timestamp=current_time,
                    active_users_count=len(active_sessions_raw),
                    total_data_bytes_in=total_bytes_in_snapshot,
                    total_data_bytes_out=total_bytes_out_snapshot
                )
                db.session.add(snapshot_entry)

                db.session.commit()
                logger.info(f"Scheduler: Successfully logged data for {len(users_raw)} users and system snapshot.")

            except Exception as e:
                logger.error(f"Scheduler: Unhandled exception in log_router_data_job: {e}", exc_info=True)
                db.session.rollback()


    scheduler_config = app_config.get('scheduler', {})
    if scheduler_config.get('enabled', False) and (os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug):
        scheduler = BackgroundScheduler(daemon=True)
        job_interval_minutes = scheduler_config.get('job_interval_minutes', 60)
        scheduler.add_job(log_router_data_job, 'interval', minutes=job_interval_minutes)
        scheduler.start()
        logger.info(f"Scheduler started. Logging data every {job_interval_minutes} minutes.")
    elif not scheduler_config.get('enabled', False):
        logger.info("Scheduler is disabled in configuration.")
    else:
        logger.info("Scheduler not started (app in debug/reloader mode or WERKZEUG_RUN_MAIN not true).")

    app.run(host=server_config['host'], port=server_config['port'], debug=server_config['debug'])