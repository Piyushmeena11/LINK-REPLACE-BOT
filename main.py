import os
import re
import json
import asyncio
from typing import List, Dict, Tuple, Set
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from collections import defaultdict

# ======================== CONFIG ========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
RENAME_TAG = os.getenv("RENAME_TAG", "_edited")

print(f"🚀 Advanced HTML Editor Bot - Owner: {OWNER_ID}")

# ======================== GLOBAL VARIABLES ========================
user_sessions = {}
SESSION_TIMEOUT = timedelta(minutes=10)

# Button color themes (Telegram API v6.9+)
BUTTON_COLORS = {
    'primary': '🔵',
    'success': '🟢', 
    'danger': '🔴',
    'warning': '🟡',
    'info': '🔵',
    'secondary': '⚪'
}

# ======================== HEALTH CHECK ========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        response = """
        <!DOCTYPE html>
        <html><head><title>Advanced HTML Editor Bot</title></head>
        <body style="font-family: Arial; text-align: center; padding: 50px;">
        <h1>🤖 Advanced HTML Editor Bot</h1>
        <p>Status: <span style="color: green;">ACTIVE</span></p>
        <p>Features: Interactive Editing, Batch Processing, Smart Deduplication</p>
        </body></html>
        """
        self.wfile.write(response.encode())
    
    def log_message(self, *args): pass

def run_health_server():
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🌐 Health server running on port {port}")
    server.serve_forever()

# ======================== TELEGRAM API FUNCTIONS ========================
def send_message(chat_id, text, reply_markup=None, parse_mode='Markdown'):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode
        }
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        req = Request(url, data=urlencode(data).encode())
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Send message error: {e}")
        return None

def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode='Markdown'):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        data = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'parse_mode': parse_mode
        }
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        req = Request(url, data=urlencode(data).encode())
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Edit message error: {e}")
        return None

def answer_callback(query_id, text="", show_alert=False):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        data = {
            'callback_query_id': query_id,
            'text': text,
            'show_alert': show_alert
        }
        req = Request(url, data=urlencode(data).encode())
        with urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Callback answer error: {e}")
        return None

def get_file_info(file_id):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
        with urlopen(url, timeout=10) as response:
            result = json.loads(response.read().decode())
            return result['result'] if result.get('ok') else None
    except Exception as e:
        print(f"❌ File info error: {e}")
        return None

def download_file_content(file_path):
    try:
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        with urlopen(url, timeout=30) as response:
            content = response.read()
            # Try different encodings
            for encoding in ['utf-8', 'utf-8-sig', 'latin1', 'cp1252']:
                try:
                    return content.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return content.decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"❌ Download error: {e}")
        return None

def send_document_file(chat_id, filename, content, caption=""):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        
        boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
        body_parts = []
        
        # Chat ID
        body_parts.append(f'--{boundary}\r\n')
        body_parts.append('Content-Disposition: form-data; name="chat_id"\r\n\r\n')
        body_parts.append(f'{chat_id}\r\n')
        
        # Caption
        if caption:
            body_parts.append(f'--{boundary}\r\n')
            body_parts.append('Content-Disposition: form-data; name="caption"\r\n\r\n')
            body_parts.append(f'{caption}\r\n')
        
        # Document
        body_parts.append(f'--{boundary}\r\n')
        body_parts.append(f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n')
        body_parts.append('Content-Type: text/html; charset=utf-8\r\n\r\n')
        body_parts.append(content)
        body_parts.append(f'\r\n--{boundary}--\r\n')
        
        body = ''.join(body_parts)
        
        req = Request(url, data=body.encode('utf-8'))
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        
        with urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode())
            print(f"✅ File sent successfully: {filename}")
            return result
            
    except Exception as e:
        print(f"❌ Document send error: {e}")
        # Fallback
        send_message(chat_id, f"❌ File sending failed.\n\n📄 **{filename}**\n\n```html\n{content[:2000]}...\n```")
        return None

# ======================== HTML PROCESSING FUNCTIONS ========================
class TelegramButton:
    def __init__(self, name: str, link: str, file_origin: str, element_type: str = 'a'):
        self.name = name
        self.link = link
        self.file_origin = file_origin
        self.element_type = element_type
        self.is_deleted = False
        self.new_name = None
        self.new_link = None
    
    @property
    def display_name(self):
        return self.new_name or self.name
    
    @property
    def display_link(self):
        return self.new_link or self.link
    
    @property
    def is_modified(self):
        return self.new_name is not None or self.new_link is not None
    
    def get_signature(self):
        """Create signature for deduplication"""
        return (self.name.lower().strip(), self.normalize_link(self.link))
    
    @staticmethod
    def normalize_link(link):
        """Normalize Telegram links for comparison"""
        link = link.lower().strip()
        if link.startswith('//'):
            link = 'https:' + link
        elif not link.startswith('http'):
            link = 'https://' + link.lstrip('/')
        # Remove trailing slashes, query parameters for comparison
        link = re.sub(r'[/?&#].*$', '', link)
        return link

def extract_telegram_buttons(html_content: str, filename: str) -> List[TelegramButton]:
    """Extract all Telegram buttons with advanced pattern matching"""
    buttons = []
    
    # Enhanced patterns for different button types
    patterns = [
        # Standard <a href> tags
        (r'<a[^>]*href=["\']([^"\']*(?:t\.me|telegram\.me|tg://)[^"\']*)["\'][^>]*>(.*?)</a>', 'a'),
        # Button with onclick
        (r'<button[^>]*onclick=["\'][^"\']*(?:window\.open|location\.href)[^"\']*["\']([^"\']*(?:t\.me|telegram\.me|tg://)[^"\']*)["\'][^>]*>(.*?)</button>', 'button'),
        # Input buttons with data attributes
        (r'<input[^>]*data-url=["\']([^"\']*(?:t\.me|telegram\.me|tg://)[^"\']*)["\'][^>]*value=["\']([^"\']*)["\']', 'input'),
        # Div with data-href
        (r'<div[^>]*data-href=["\']([^"\']*(?:t\.me|telegram\.me|tg://)[^"\']*)["\'][^>]*>(.*?)</div>', 'div'),
    ]
    
    for pattern, element_type in patterns:
        matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
        
        for match in matches:
            if element_type == 'input':
                link, name = match
            else:
                link, name = match
            
            # Clean button name
            clean_name = re.sub(r'<[^>]+>', '', name).strip()
            clean_name = re.sub(r'\s+', ' ', clean_name)
            
            if clean_name and len(clean_name) >= 2:
                # Normalize link
                if link.startswith('//'):
                    link = 'https:' + link
                elif not link.startswith('http') and not link.startswith('tg:'):
                    link = 'https://' + link.lstrip('/')
                
                button = TelegramButton(clean_name, link.strip(), filename, element_type)
                buttons.append(button)
    
    return buttons

def group_buttons_by_signature(buttons: List[TelegramButton]) -> Dict[str, List[TelegramButton]]:
    """Group similar buttons for smart deduplication"""
    groups = defaultdict(list)
    
    for button in buttons:
        signature = button.get_signature()
        sig_key = f"{signature[0]}|{signature[1]}"
        groups[sig_key].append(button)
    
    return dict(groups)

def apply_global_link_replacement(html_content: str, old_pattern: str, new_link: str) -> str:
    """Replace all Telegram links globally"""
    # Pattern to match any Telegram link
    telegram_pattern = r'(https?://)?(t\.me|telegram\.me|tg://)[^\s"\'<>]*'
    
    if old_pattern.lower() == 'all':
        # Replace all Telegram links
        def replace_func(match):
            return new_link
        result = re.sub(telegram_pattern, replace_func, html_content, flags=re.IGNORECASE)
    else:
        # Replace specific pattern
        escaped_pattern = re.escape(old_pattern)
        result = re.sub(escaped_pattern, new_link, html_content, flags=re.IGNORECASE)
    
    return result

def apply_custom_text_replacement(html_content: str, search_text: str, replace_text: str, preserve_buttons: bool = True) -> str:
    """Advanced text replacement with button preservation"""
    if not preserve_buttons:
        return html_content.replace(search_text, replace_text)
    
    # Extract all button areas to preserve them
    button_patterns = [
        r'<a[^>]*href=["\'][^"\']*(?:t\.me|telegram\.me|tg://)[^"\']*["\'][^>]*>.*?</a>',
        r'<button[^>]*onclick=["\'][^"\']*(?:t\.me|telegram\.me|tg://)[^"\']*["\'][^>]*>.*?</button>',
    ]
    
    protected_areas = []
    placeholder_map = {}
    
    # Replace button areas with placeholders
    for i, pattern in enumerate(button_patterns):
        matches = list(re.finditer(pattern, html_content, re.IGNORECASE | re.DOTALL))
        for j, match in enumerate(matches):
            placeholder = f"__PROTECTED_BUTTON_{i}_{j}__"
            protected_areas.append((placeholder, match.group(0)))
            placeholder_map[placeholder] = match.group(0)
            html_content = html_content[:match.start()] + placeholder + html_content[match.end():]
    
    # Perform text replacement
    html_content = html_content.replace(search_text, replace_text)
    
    # Restore protected areas
    for placeholder, original in protected_areas:
        html_content = html_content.replace(placeholder, original)
    
    return html_content

def apply_individual_button_changes(html_content: str, button: TelegramButton) -> str:
    """Apply individual button changes"""
    if button.is_deleted:
        # Remove button completely
        patterns = [
            f'<a[^>]*href=["\'][^"\']*{re.escape(button.link)}[^"\']*["\'][^>]*>.*?</a>',
            f'<button[^>]*onclick=["\'][^"\']*{re.escape(button.link)}[^"\']*["\'][^>]*>.*?</button>',
        ]
        
        for pattern in patterns:
            html_content = re.sub(pattern, '', html_content, flags=re.IGNORECASE | re.DOTALL)
        
        return html_content
    
    # Update name and/or link
    old_name_escaped = re.escape(button.name)
    old_link_escaped = re.escape(button.link)
    
    # Replace link in href attributes
    if button.new_link:
        html_content = re.sub(
            f'href=["\'][^"\']*{old_link_escaped}[^"\']*["\']',
            f'href="{button.display_link}"',
            html_content,
            flags=re.IGNORECASE
        )
        
        # Replace in onclick attributes
        html_content = re.sub(
            f'onclick=["\'][^"\']*{old_link_escaped}[^"\']*["\']',
            f'onclick="window.open(\'{button.display_link}\')"',
            html_content,
            flags=re.IGNORECASE
        )
    
    # Replace button text
    if button.new_name:
        # For <a> tags
        html_content = re.sub(
            f'(<a[^>]*href=["\'][^"\']*{re.escape(button.display_link)}[^"\']*["\'][^>]*>)[^<]*{old_name_escaped}[^<]*(</a>)',
            f'\\1{button.display_name}\\2',
            html_content,
            flags=re.IGNORECASE
        )
        
        # For <button> tags
        html_content = re.sub(
            f'(<button[^>]*>[^<]*){old_name_escaped}([^<]*</button>)',
            f'\\1{button.display_name}\\2',
            html_content,
            flags=re.IGNORECASE
        )
    
    return html_content

def update_html_title(html_content: str, new_title: str) -> str:
    """Update HTML page title"""
    # Replace existing title
    title_pattern = r'<title[^>]*>.*?</title>'
    if re.search(title_pattern, html_content, re.IGNORECASE | re.DOTALL):
        html_content = re.sub(title_pattern, f'<title>{new_title}</title>', html_content, flags=re.IGNORECASE | re.DOTALL)
    else:
        # Add title to head
        head_pattern = r'<head[^>]*>'
        if re.search(head_pattern, html_content, re.IGNORECASE):
            html_content = re.sub(head_pattern, f'\\g<0>\n<title>{new_title}</title>', html_content, flags=re.IGNORECASE)
    
    return html_content

# ======================== UI FUNCTIONS ========================
def create_main_menu_keyboard(session_data: dict) -> dict:
    """Create main menu with colored buttons"""
    files_count = len(session_data.get('files', {}))
    buttons_count = len(session_data.get('deduplicated_buttons', {}))
    changes_count = sum(1 for group in session_data.get('deduplicated_buttons', {}).values() 
                       for btn in group if btn.is_modified or btn.is_deleted)
    
    keyboard = []
    
    # File info
    if files_count > 0:
        keyboard.append([{
            "text": f"📁 Files: {files_count} | 🔗 Buttons: {buttons_count}",
            "callback_data": "info"
        }])
    
    # Main editing options
    if buttons_count > 0:
        keyboard.append([
            {"text": f"🔵 Edit Individual Buttons", "callback_data": "edit_individual"},
            {"text": f"🟢 Global Link Replace", "callback_data": "global_replace"}
        ])
        
        keyboard.append([
            {"text": f"🟡 Custom Text Replace", "callback_data": "text_replace"},
            {"text": f"🔵 Page Title", "callback_data": "edit_title"}
        ])
        
        keyboard.append([
            {"text": f"🟠 Custom Filename", "callback_data": "edit_filename"}
        ])
        
        # Changes and generate
        if changes_count > 0:
            keyboard.append([
                {"text": f"🔴 Reset All ({changes_count})", "callback_data": "reset_all"},
                {"text": f"🟢 Generate Files", "callback_data": "generate"}
            ])
        else:
            keyboard.append([
                {"text": f"⚪ No Changes Yet", "callback_data": "no_changes"},
                {"text": f"📄 Generate Original", "callback_data": "generate"}
            ])
    
    # Always available options
    keyboard.append([
        {"text": f"🔄 Upload New Files", "callback_data": "new_upload"},
        {"text": f"❌ Cancel Session", "callback_data": "cancel"}
    ])
    
    return {"inline_keyboard": keyboard}

def create_individual_buttons_keyboard(deduplicated_buttons: dict, page: int = 0) -> dict:
    """Create keyboard for individual button editing"""
    keyboard = []
    buttons_per_page = 6
    
    button_items = list(deduplicated_buttons.items())
    start_idx = page * buttons_per_page
    end_idx = min(start_idx + buttons_per_page, len(button_items))
    
    for i in range(start_idx, end_idx):
        sig_key, button_group = button_items[i]
        representative = button_group[0]
        
        # Status indicator
        if representative.is_deleted:
            status = "🔴"
            display_name = f"[DELETED] {representative.name[:20]}"
        elif representative.is_modified:
            status = "🟡"
            display_name = f"{representative.display_name[:20]}"
        else:
            status = "⚪"
            display_name = representative.name[:20]
        
        if len(display_name) > 20:
            display_name += "..."
        
        keyboard.append([{
            "text": f"{status} {display_name} ({len(button_group)} files)",
            "callback_data": f"btn_{i}"
        }])
    
    # Navigation
    nav_row = []
    if page > 0:
        nav_row.append({"text": "⬅️ Previous", "callback_data": f"btn_page_{page-1}"})
    if end_idx < len(button_items):
        nav_row.append({"text": "Next ➡️", "callback_data": f"btn_page_{page+1}"})
    
    if nav_row:
        keyboard.append(nav_row)
    
    # Back button
    keyboard.append([{"text": "🔙 Back to Main Menu", "callback_data": "main_menu"}])
    
    return {"inline_keyboard": keyboard}

def create_button_edit_keyboard(button: TelegramButton) -> dict:
    """Create keyboard for editing individual button"""
    keyboard = []
    
    # Edit options
    keyboard.append([
        {"text": "✏️ Edit Name", "callback_data": "edit_name"},
        {"text": "🔗 Edit Link", "callback_data": "edit_link"}
    ])
    
    # Delete toggle
    if button.is_deleted:
        keyboard.append([{"text": "♻️ Restore Button", "callback_data": "toggle_delete"}])
    else:
        keyboard.append([{"text": "🗑️ Delete Button", "callback_data": "toggle_delete"}])
    
    # Navigation
    keyboard.append([
        {"text": "🔙 Back to Buttons", "callback_data": "back_to_buttons"},
        {"text": "🏠 Main Menu", "callback_data": "main_menu"}
    ])
    
    return {"inline_keyboard": keyboard}

# ======================== SESSION MANAGEMENT ========================
def check_session_timeout(user_id: int) -> bool:
    """Check if session has timed out"""
    if user_id not in user_sessions:
        return True
    
    session = user_sessions[user_id]
    last_activity = session.get('last_activity', datetime.now() - SESSION_TIMEOUT)
    
    if datetime.now() - last_activity > SESSION_TIMEOUT:
        del user_sessions[user_id]
        return True
    
    session['last_activity'] = datetime.now()
    return False

def update_session_activity(user_id: int):
    """Update last activity timestamp"""
    if user_id in user_sessions:
        user_sessions[user_id]['last_activity'] = datetime.now()

def initialize_session(user_id: int):
    """Initialize new user session"""
    user_sessions[user_id] = {
        'state': 'collecting_files',
        'files': {},  # filename -> html_content
        'buttons': {},  # filename -> List[TelegramButton]
        'deduplicated_buttons': {},  # signature -> List[TelegramButton]
        'global_replacements': [],
        'text_replacements': [],
        'custom_title': None,
        'custom_filename': None,
        'last_activity': datetime.now(),
        'page': 0,
        'current_button_idx': None,
        'temp_data': {}
    }

# ======================== MESSAGE HANDLERS ========================
def handle_document_message(message: dict):
    """Handle uploaded HTML files with auto-start"""
    chat_id = message['chat']['id']
    user_id = message['from']['id']
    
    if user_id != OWNER_ID:
        send_message(chat_id, "🚫 Sorry, you're not authorized to use this bot.")
        return
    
    doc = message['document']
    
    if not (doc['file_name'].endswith('.html') or doc['file_name'].endswith('.htm')):
        send_message(chat_id, "⚠️ **Please send HTML files only** (.html or .htm)")
        return
    
    # Auto-initialize session
    if user_id not in user_sessions:
        initialize_session(user_id)
    
    update_session_activity(user_id)
    session = user_sessions[user_id]
    
    send_message(chat_id, f"⏳ **Processing** `{doc['file_name']}`...\n📥 Downloading and analyzing...")
    
    # Download file
    file_info = get_file_info(doc['file_id'])
    if not file_info:
        send_message(chat_id, "❌ **Error getting file info.** Please try again.")
        return
    
    html_content = download_file_content(file_info['file_path'])
    if not html_content:
        send_message(chat_id, "❌ **Error downloading file.** Please try again.")
        return
    
    # Extract buttons
    buttons = extract_telegram_buttons(html_content, doc['file_name'])
    
    # Store in session
    session['files'][doc['file_name']] = html_content
    session['buttons'][doc['file_name']] = buttons
    
    send_message(chat_id, 
        f"✅ **{doc['file_name']}**\n"
        f"📊 Found: {len(buttons)} Telegram buttons\n\n"
        f"📤 Send more files or type `/done` to start editing!"
    )

def handle_text_message(message: dict):
    """Handle text commands and user inputs"""
    chat_id = message['chat']['id']
    user_id = message['from']['id']
    text = message.get('text', '').strip()
    
    if user_id != OWNER_ID:
        send_message(chat_id, "🚫 Sorry, you're not authorized to use this bot.")
        return
    
    # Check session timeout
    if check_session_timeout(user_id):
        send_message(chat_id, "⏱ **Session expired.** Upload HTML files to start again.")
        return
    
    update_session_activity(user_id)
    session = user_sessions[user_id]
    
    # Handle commands
    if text.startswith('/start'):
        initialize_session(user_id)
        send_message(chat_id,
            "🚀 **Advanced HTML Editor Bot**\n\n"
            "🎯 **Features:**\n"
            "• 📤 **Auto-Start**: Just upload HTML files!\n"
            "• 🔄 **Batch Processing**: Multiple files at once\n"
            "• 🧠 **Smart Deduplication**: Edit similar buttons once\n"
            "• 🎨 **Interactive UI**: Colored buttons & advanced options\n"
            "• 🔧 **Multi-Level Editing**: Individual, Global & Custom\n\n"
            "📋 **Quick Start:**\n"
            "1. Upload HTML files\n"
            "2. Send `/done` when ready\n"
            "3. Use interactive menus to edit\n"
            "4. Generate updated files\n\n"
            "🔒 **Private Bot** - Owner Only Access"
        )
    
    elif text.startswith('/done'):
        if not session.get('files'):
            send_message(chat_id, "⚠️ **No files uploaded.** Please upload HTML files first.")
            return
        
        # Process deduplication
        process_files_for_editing(chat_id, user_id)
    
    elif text.startswith('/cancel'):
        if user_id in user_sessions:
            del user_sessions[user_id]
        send_message(chat_id, "❌ **Session cancelled.** Upload HTML files to start again.")
    
    elif text.startswith('/help'):
        send_message(chat_id,
            "📘 **Advanced HTML Editor Bot Guide**\n\n"
            "🎯 **Main Features:**\n\n"
            "**1. Individual Button Editing**\n"
            "• Edit button names\n"
            "• Change links\n"
            "• Delete buttons completely\n\n"
            "**2. Global Link Replacement**\n"
            "• Replace all Telegram links at once\n"
            "• Pattern-based replacement\n\n"
            "**3. Custom Text Search & Replace**\n"
            "• Find and replace any text\n"
            "• Smart button preservation\n\n"
            "**4. Branding Options**\n"
            "• Custom page titles\n"
            "• Custom filenames\n\n"
            "**5. Smart Features**\n"
            "• Deduplication system\n"
            "• 10-minute session timeout\n"
            "• Interactive summary reports\n\n"
            "🚀 **Just upload HTML files to start!**"
        )
    
    # Handle user inputs based on session state
    elif session.get('state') == 'editing':
        handle_editing_input(chat_id, user_id, text)

def process_files_for_editing(chat_id: int, user_id: int):
    """Process uploaded files and start editing interface"""
    session = user_sessions[user_id]
    
    send_message(chat_id, "🔄 **Processing files for editing...**\n⚡ Analyzing and deduplicating buttons...")
    
    # Collect all buttons
    all_buttons = []
    for filename, buttons in session['buttons'].items():
        all_buttons.extend(buttons)
    
    if not all_buttons:
        send_message(chat_id, "❌ **No Telegram buttons found** in uploaded files.\n\nMake sure your HTML files contain Telegram links (t.me, telegram.me)")
        return
    
    # Smart deduplication
    deduplicated = group_buttons_by_signature(all_buttons)
    session['deduplicated_buttons'] = deduplicated
    session['state'] = 'editing'
    
    # Show main menu
    show_main_menu(chat_id, user_id)

def show_main_menu(chat_id: int, user_id: int):
    """Show main editing menu"""
    session = user_sessions[user_id]
    
    files_count = len(session['files'])
    button_groups_count = len(session['deduplicated_buttons'])
    total_buttons = sum(len(group) for group in session['deduplicated_buttons'].values())
    
    text = (
        f"🎛️ **Advanced HTML Editor Control Panel**\n\n"
        f"📊 **Current Session:**\n"
        f"• 📁 Files: {files_count}\n"
        f"• 🔗 Unique Buttons: {button_groups_count}\n"
        f"• 📋 Total Instances: {total_buttons}\n\n"
        f"🎯 **Choose editing mode:**"
    )
    
    keyboard = create_main_menu_keyboard(session)
    send_message(chat_id, text, keyboard)

def handle_editing_input(chat_id: int, user_id: int, text: str):
    """Handle user input during editing states"""
    session = user_sessions[user_id]
    temp_data = session.get('temp_data', {})
    
    if session.get('input_state') == 'edit_name':
        # Update button name
        button_idx = session.get('current_button_idx')
        if button_idx is not None:
            button_items = list(session['deduplicated_buttons'].items())
            if 0 <= button_idx < len(button_items):
                sig_key, button_group = button_items[button_idx]
                for button in button_group:
                    button.new_name = text
                
                send_message(chat_id, f"✅ **Button name updated to:** `{text}`")
                session.pop('input_state', None)
                show_button_edit_menu(chat_id, user_id, button_idx)
    
    elif session.get('input_state') == 'edit_link':
        # Validate and update button link
        if not ('t.me' in text.lower() or 'telegram.me' in text.lower() or 'tg://' in text.lower()):
            send_message(chat_id, "⚠️ **Invalid link!** Please use Telegram links (t.me, telegram.me, or tg://)")
            return
        
        button_idx = session.get('current_button_idx')
        if button_idx is not None:
            button_items = list(session['deduplicated_buttons'].items())
            if 0 <= button_idx < len(button_items):
                sig_key, button_group = button_items[button_idx]
                for button in button_group:
                    button.new_link = text
                
                send_message(chat_id, f"✅ **Button link updated to:** `{text}`")
                session.pop('input_state', None)
                show_button_edit_menu(chat_id, user_id, button_idx)
    
    elif session.get('input_state') == 'global_replace_from':
        temp_data['global_old'] = text
        session['temp_data'] = temp_data
        session['input_state'] = 'global_replace_to'
        send_message(chat_id, f"🔗 **Original pattern set:** `{text}`\n\n📝 **Now send the new link:**")
    
    elif session.get('input_state') == 'global_replace_to':
        old_pattern = temp_data.get('global_old', '')
        session['global_replacements'].append((old_pattern, text))
        session.pop('input_state', None)
        session.pop('temp_data', None)
        
        send_message(chat_id, 
            f"✅ **Global replacement added:**\n"
            f"📍 From: `{old_pattern}`\n"
            f"📍 To: `{text}`\n\n"
            f"🔄 This will be applied when generating files."
        )
        show_main_menu(chat_id, user_id)
    
    elif session.get('input_state') == 'text_replace_from':
        temp_data['text_old'] = text
        session['temp_data'] = temp_data
        session['input_state'] = 'text_replace_to'
        send_message(chat_id, f"🔍 **Search text set:** `{text}`\n\n📝 **Now send the replacement text:**")
    
    elif session.get('input_state') == 'text_replace_to':
        old_text = temp_data.get('text_old', '')
        session['text_replacements'].append((old_text, text))
        session.pop('input_state', None)
        session.pop('temp_data', None)
        
        send_message(chat_id,
            f"✅ **Text replacement added:**\n"
            f"📍 From: `{old_text}`\n"
            f"📍 To: `{text}`\n\n"
            f"🔄 This will be applied when generating files.\n"
            f"⚠️ Button names are protected from this replacement."
        )
        show_main_menu(chat_id, user_id)
    
    elif session.get('input_state') == 'edit_title':
        session['custom_title'] = text
        session.pop('input_state', None)
        send_message(chat_id, f"✅ **Page title updated to:** `{text}`")
        show_main_menu(chat_id, user_id)
    
    elif session.get('input_state') == 'edit_filename':
        session['custom_filename'] = text
        session.pop('input_state', None)
        send_message(chat_id, f"✅ **Custom filename set to:** `{text}`")
        show_main_menu(chat_id, user_id)

def show_button_edit_menu(chat_id: int, user_id: int, button_idx: int):
    """Show individual button editing menu"""
    session = user_sessions[user_id]
    button_items = list(session['deduplicated_buttons'].items())
    
    if not (0 <= button_idx < len(button_items)):
        send_message(chat_id, "❌ Invalid button index")
        return
    
    sig_key, button_group = button_items[button_idx]
    representative = button_group[0]
    
    status = "🔴 DELETED" if representative.is_deleted else ("🟡 MODIFIED" if representative.is_modified else "⚪ ORIGINAL")
    
    text = (
        f"✏️ **Button Editor**\n\n"
        f"**Status:** {status}\n"
        f"**Name:** `{representative.display_name}`\n"
        f"**Link:** `{representative.display_link}`\n"
        f"**Found in:** {len(button_group)} file(s)\n\n"
        f"**Files:** {', '.join(btn.file_origin for btn in button_group[:3])}"
        f"{'...' if len(button_group) > 3 else ''}\n\n"
        f"🎯 **Choose action:**"
    )
    
    keyboard = create_button_edit_keyboard(representative)
    session['current_button_idx'] = button_idx
    
    send_message(chat_id, text, keyboard)

# ======================== CALLBACK QUERY HANDLER ========================
def handle_callback_query(callback_query: dict):
    """Handle all callback queries from inline keyboards"""
    chat_id = callback_query['message']['chat']['id']
    user_id = callback_query['from']['id']
    message_id = callback_query['message']['message_id']
    data = callback_query['data']
    
    if user_id != OWNER_ID:
        answer_callback(callback_query['id'], "🚫 Not authorized")
        return
    
    if check_session_timeout(user_id):
        answer_callback(callback_query['id'], "⏱ Session expired")
        edit_message(chat_id, message_id, "⏱ **Session expired.** Upload HTML files to start again.")
        return
    
    answer_callback(callback_query['id'])
    update_session_activity(user_id)
    session = user_sessions[user_id]
    
    # Route callbacks
    if data == 'main_menu':
        show_main_menu(chat_id, user_id)
    
    elif data == 'edit_individual':
        show_individual_buttons_menu(chat_id, user_id, message_id)
    
    elif data == 'global_replace':
        start_global_replacement(chat_id, user_id, message_id)
    
    elif data == 'text_replace':
        start_text_replacement(chat_id, user_id, message_id)
    
    elif data == 'edit_title':
        start_title_editing(chat_id, user_id, message_id)
    
    elif data == 'edit_filename':
        start_filename_editing(chat_id, user_id, message_id)
    
    elif data.startswith('btn_'):
        handle_button_selection(chat_id, user_id, message_id, data)
    
    elif data == 'edit_name':
        start_button_name_editing(chat_id, user_id, message_id)
    
    elif data == 'edit_link':
        start_button_link_editing(chat_id, user_id, message_id)
    
    elif data == 'toggle_delete':
        toggle_button_deletion(chat_id, user_id, message_id)
    
    elif data == 'back_to_buttons':
        show_individual_buttons_menu(chat_id, user_id, message_id)
    
    elif data == 'reset_all':
        reset_all_changes(chat_id, user_id, message_id)
    
    elif data == 'generate':
        generate_final_files(chat_id, user_id)
    
    elif data == 'cancel':
        if user_id in user_sessions:
            del user_sessions[user_id]
        edit_message(chat_id, message_id, "❌ **Session cancelled.** Upload HTML files to start again.")
    
    elif data == 'new_upload':
        initialize_session(user_id)
        edit_message(chat_id, message_id, "📤 **Ready for new files!** Upload HTML files to start editing.")

def show_individual_buttons_menu(chat_id: int, user_id: int, message_id: int):
    """Show list of individual buttons for editing"""
    session = user_sessions[user_id]
    page = session.get('page', 0)
    
    text = (
        f"🔗 **Individual Button Editor**\n\n"
        f"📊 **{len(session['deduplicated_buttons'])} unique button groups found**\n"
        f"🎯 Click any button to edit its name, link, or delete it:\n\n"
        f"**Legend:**\n"
        f"⚪ Original • 🟡 Modified • 🔴 Deleted"
    )
    
    keyboard = create_individual_buttons_keyboard(session['deduplicated_buttons'], page)
    edit_message(chat_id, message_id, text, keyboard)

def handle_button_selection(chat_id: int, user_id: int, message_id: int, data: str):
    """Handle button selection for editing"""
    if data.startswith('btn_page_'):
        page = int(data.split('_')[2])
        user_sessions[user_id]['page'] = page
        show_individual_buttons_menu(chat_id, user_id, message_id)
    else:
        button_idx = int(data.split('_')[1])
        edit_message(chat_id, message_id, "⏳ Loading button editor...")
        show_button_edit_menu(chat_id, user_id, button_idx)

def start_global_replacement(chat_id: int, user_id: int, message_id: int):
    """Start global link replacement process"""
    session = user_sessions[user_id]
    
    edit_message(chat_id, message_id,
        "🌐 **Global Link Replacement**\n\n"
        "🎯 **This feature replaces ALL matching Telegram links at once.**\n\n"
        "📝 **Send the link pattern to replace:**\n"
        "• Send `all` to replace ALL Telegram links\n"
        "• Send specific link like `https://t.me/oldchannel`\n"
        "• Send domain like `t.me/oldchannel`\n\n"
        "⚠️ **This affects ALL files simultaneously.**",
        {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
    )
    
    session['input_state'] = 'global_replace_from'

def start_text_replacement(chat_id: int, user_id: int, message_id: int):
    """Start custom text replacement process"""
    session = user_sessions[user_id]
    
    edit_message(chat_id, message_id,
        "📝 **Custom Text Search & Replace**\n\n"
        "🎯 **Find and replace any text in your HTML files.**\n\n"
        "📝 **Send the text to search for:**\n"
        "• Can be any word, phrase, or HTML content\n"
        "• Case-sensitive matching\n"
        "• Button names are automatically protected\n\n"
        "⚠️ **This affects ALL files simultaneously.**",
        {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
    )
    
    session['input_state'] = 'text_replace_from'

def start_title_editing(chat_id: int, user_id: int, message_id: int):
    """Start HTML title editing"""
    session = user_sessions[user_id]
    
    edit_message(chat_id, message_id,
        "📰 **HTML Page Title Editor**\n\n"
        "🎯 **This updates the `<title>` tag in your HTML files.**\n"
        "📱 **This is what appears in browser tabs.**\n\n"
        "📝 **Send the new page title:**\n"
        "• Will be applied to ALL files\n"
        "• Replaces existing title or adds new one\n\n"
        "💡 **Example:** `My Awesome Channel - Join Now!`",
        {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
    )
    
    session['input_state'] = 'edit_title'

def start_filename_editing(chat_id: int, user_id: int, message_id: int):
    """Start custom filename setting"""
    session = user_sessions[user_id]
    
    edit_message(chat_id, message_id,
        f"📁 **Custom Filename Editor**\n\n"
        f"🎯 **Set a custom base name for output files.**\n\n"
        f"📝 **Send the new filename (without extension):**\n"
        f"• Example: `my_edited_page`\n"
        f"• Will become: `my_edited_page{RENAME_TAG}.html`\n"
        f"• Applied to all generated files\n\n"
        f"⚠️ **Leave blank to use original filenames.**",
        {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "main_menu"}]]}
    )
    
    session['input_state'] = 'edit_filename'

def start_button_name_editing(chat_id: int, user_id: int, message_id: int):
    """Start editing button name"""
    session = user_sessions[user_id]
    button_idx = session.get('current_button_idx')
    
    if button_idx is None:
        send_message(chat_id, "❌ Error: No button selected")
        return
    
    button_items = list(session['deduplicated_buttons'].items())
    representative = button_items[button_idx][1][0]
    
    edit_message(chat_id, message_id,
        f"✏️ **Edit Button Name**\n\n"
        f"**Current name:** `{representative.display_name}`\n\n"
        f"📝 **Send the new button name:**\n"
        f"• Will be applied to all {len(button_items[button_idx][1])} instances\n"
        f"• Keep it descriptive and clear\n\n"
        f"💡 **Example:** `Join Premium Channel`",
        {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": f"btn_{button_idx}"}]]}
    )
    
    session['input_state'] = 'edit_name'

def start_button_link_editing(chat_id: int, user_id: int, message_id: int):
    """Start editing button link"""
    session = user_sessions[user_id]
    button_idx = session.get('current_button_idx')
    
    if button_idx is None:
        send_message(chat_id, "❌ Error: No button selected")
        return
    
    button_items = list(session['deduplicated_buttons'].items())
    representative = button_items[button_idx][1][0]
    
    edit_message(chat_id, message_id,
        f"🔗 **Edit Button Link**\n\n"
        f"**Current link:** `{representative.display_link}`\n\n"
        f"📝 **Send the new Telegram link:**\n"
        f"• Must be a valid Telegram link\n"
        f"• Supported: t.me, telegram.me, tg://\n"
        f"• Will be applied to all {len(button_items[button_idx][1])} instances\n\n"
        f"💡 **Example:** `https://t.me/mynewchannel`",
        {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": f"btn_{button_idx}"}]]}
    )
    
    session['input_state'] = 'edit_link'

def toggle_button_deletion(chat_id: int, user_id: int, message_id: int):
    """Toggle button deletion status"""
    session = user_sessions[user_id]
    button_idx = session.get('current_button_idx')
    
    if button_idx is None:
        send_message(chat_id, "❌ Error: No button selected")
        return
    
    button_items = list(session['deduplicated_buttons'].items())
    if 0 <= button_idx < len(button_items):
        sig_key, button_group = button_items[button_idx]
        
        # Toggle deletion status
        new_status = not button_group[0].is_deleted
        for button in button_group:
            button.is_deleted = new_status
        
        action = "marked for deletion" if new_status else "restored"
        send_message(chat_id, f"✅ **Button {action}** ({len(button_group)} instances)")
        
        show_button_edit_menu(chat_id, user_id, button_idx)

def reset_all_changes(chat_id: int, user_id: int, message_id: int):
    """Reset all changes made to buttons"""
    session = user_sessions[user_id]
    
    # Reset all button modifications
    for button_group in session['deduplicated_buttons'].values():
        for button in button_group:
            button.new_name = None
            button.new_link = None
            button.is_deleted = False
    
    # Reset other modifications
    session['global_replacements'] = []
    session['text_replacements'] = []
    session['custom_title'] = None
    session['custom_filename'] = None
    
    edit_message(chat_id, message_id, "♻️ **All changes have been reset.**")
    show_main_menu(chat_id, user_id)

def generate_final_files(chat_id: int, user_id: int):
    """Generate and send final edited files"""
    session = user_sessions[user_id]
    
    send_message(chat_id, "⚡ **Generating final files...**\n🔄 Applying all modifications...")
    
    # Count changes for summary
    button_changes = 0
    deleted_buttons = 0
    
    for button_group in session['deduplicated_buttons'].values():
        for button in button_group:
            if button.is_deleted:
                deleted_buttons += 1
            elif button.is_modified:
                button_changes += 1
    
    # Process each file
    processed_files = {}
    
    for filename, original_html in session['files'].items():
        html_content = original_html
        
        # Apply individual button changes
        for button_group in session['deduplicated_buttons'].values():
            for button in button_group:
                if button.file_origin == filename:
                    html_content = apply_individual_button_changes(html_content, button)
        
        # Apply global link replacements
        for old_pattern, new_link in session['global_replacements']:
            html_content = apply_global_link_replacement(html_content, old_pattern, new_link)
        
        # Apply custom text replacements
        for search_text, replace_text in session['text_replacements']:
            html_content = apply_custom_text_replacement(html_content, search_text, replace_text, True)
        
        # Update title if set
        if session.get('custom_title'):
            html_content = update_html_title(html_content, session['custom_title'])
        
        processed_files[filename] = html_content
    
    # Generate filenames
    custom_base = session.get('custom_filename')
    
    # Send processed files
    for original_filename, final_html in processed_files.items():
        if custom_base:
            # Use custom filename for all files
            new_filename = f"{custom_base}{RENAME_TAG}.html"
            if len(processed_files) > 1:
                # Add index for multiple files
                index = list(processed_files.keys()).index(original_filename) + 1
                new_filename = f"{custom_base}_{index}{RENAME_TAG}.html"
        else:
            # Use original filename with tag
            base_name = original_filename.replace('.html', '').replace('.htm', '')
            new_filename = f"{base_name}{RENAME_TAG}.html"
        
        # Send file
        send_document_file(
            chat_id,
            new_filename,
            final_html,
            f"✅ Processed: {original_filename} → {new_filename}"
        )
    
    # Send summary report
    summary_text = (
        f"🎉 **Processing Complete!**\n\n"
        f"📊 **Summary Report:**\n"
        f"• 📁 Files processed: {len(processed_files)}\n"
        f"• ✏️ Buttons modified: {button_changes}\n"
        f"• 🗑️ Buttons deleted: {deleted_buttons}\n"
        f"• 🌐 Global replacements: {len(session['global_replacements'])}\n"
        f"• 📝 Text replacements: {len(session['text_replacements'])}\n"
    )
    
    if session.get('custom_title'):
        summary_text += f"• 📰 Custom title: `{session['custom_title']}`\n"
    
    if session.get('custom_filename'):
        summary_text += f"• 📁 Custom filename: `{session['custom_filename']}`\n"
    
    summary_text += f"\n🔒 **Session completed.** Upload new files to start again."
    
    send_message(chat_id, summary_text)
    
    # Clear session
    del user_sessions[user_id]

# ======================== MAIN UPDATE HANDLER ========================
def get_updates(offset: int = 0) -> dict:
    """Get updates from Telegram"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {
            'offset': offset,
            'timeout': 30,
            'allowed_updates': json.dumps(['message', 'callback_query'])
        }
        
        with urlopen(f"{url}?{urlencode(params)}", timeout=35) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Get updates error: {e}")
        return {}

def handle_update(update: dict):
    """Handle incoming update"""
    try:
        if 'message' in update:
            message = update['message']
            
            if 'document' in message:
                handle_document_message(message)
            elif 'text' in message:
                handle_text_message(message)
        
        elif 'callback_query' in update:
            handle_callback_query(update['callback_query'])
            
    except Exception as e:
        print(f"❌ Handle update error: {e}")
        # Try to send error to user if possible
        try:
            if 'message' in update and update['message']['from']['id'] == OWNER_ID:
                send_message(
                    update['message']['chat']['id'],
                    f"❌ **Error processing your request.**\n\nTechnical details: `{str(e)}`"
                )
        except:
            pass

# ======================== MAIN FUNCTION ========================
def main():
    """Main bot function"""
    if not BOT_TOKEN or OWNER_ID == 0:
        print("❌ BOT_TOKEN and OWNER_ID must be set!")
        return
    
    print("🚀 Starting Advanced Interactive HTML Editor Bot...")
    print(f"🔒 Owner-only access: {OWNER_ID}")
    print(f"🏷️ Rename tag: {RENAME_TAG}")
    
    # Start health server
    health_thread = Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    # Bot polling loop
    offset = 0
    print("🤖 Bot is now running with advanced features!")
    print("📱 Features: Auto-start, Batch processing, Smart deduplication")
    print("🎨 UI: Colored buttons, Interactive menus, Multi-level editing")
    
    while True:
        try:
            result = get_updates(offset)
            
            if not result.get('ok'):
                continue
            
            for update in result.get('result', []):
                handle_update(update)
                offset = update['update_id'] + 1
                
        except KeyboardInterrupt:
            print("🛑 Bot stopped by user")
            break
        except Exception as e:
            print(f"❌ Main loop error: {e}")
            import time
            time.sleep(5)

if __name__ == '__main__':
    main()
