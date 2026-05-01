import os
import io
import re
import json
import asyncio
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.parse import urlencode

# ======================== BASIC CONFIGURATION ========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
RENAME_TAG = os.getenv("RENAME_TAG", "_edited")

print(f"🚀 HTML Editor Bot Starting...")
print(f"🔒 Owner ID: {OWNER_ID}")
print(f"🏷️ Rename Tag: {RENAME_TAG}")
print(f"🔑 Token: {'SET' if BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE' else 'MISSING'}")

# ======================== HEALTH CHECK ========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        html = f"""
        <!DOCTYPE html>
        <html><head><title>HTML Editor Bot Status</title></head>
        <body style="font-family: Arial; text-align: center; padding: 50px;">
        <h1>🤖 HTML Button Editor Bot</h1>
        <h2 style="color: green;">✅ RUNNING</h2>
        <p><strong>Owner:</strong> {OWNER_ID}</p>
        <p><strong>Token:</strong> {'Configured' if BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE' else 'Missing'}</p>
        <p><strong>Status:</strong> Ready for Telegram messages</p>
        <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body></html>
        """
        self.wfile.write(html.encode())
    
    def log_message(self, *args): pass

def run_health():
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🌐 Health server: {port}")
    server.serve_forever()

# ======================== TELEGRAM API ========================
def send_telegram_message(chat_id, text, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        req = Request(url, data=urlencode(data).encode())
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Send error: {e}")
        return None

def get_telegram_updates(offset=0):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {'offset': offset, 'timeout': 30}
        
        with urlopen(f"{url}?{urlencode(params)}", timeout=35) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Updates error: {e}")
        return None

def get_file_content(file_id):
    try:
        # Get file info
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
        with urlopen(url, timeout=10) as response:
            result = json.loads(response.read().decode())
            if not result.get('ok'):
                return None
            
            file_path = result['result']['file_path']
        
        # Download file
        download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        with urlopen(download_url, timeout=30) as response:
            content = response.read()
            return content.decode('utf-8', errors='ignore')
            
    except Exception as e:
        print(f"❌ File download error: {e}")
        return None

def send_document(chat_id, filename, content, caption=""):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        
        boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
        body_parts = [
            f'--{boundary}\r\n',
            'Content-Disposition: form-data; name="chat_id"\r\n\r\n',
            f'{chat_id}\r\n',
            f'--{boundary}\r\n',
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n',
            'Content-Type: text/html\r\n\r\n',
            content,
            f'\r\n--{boundary}--\r\n'
        ]
        
        body = ''.join(body_parts).encode('utf-8')
        
        req = Request(url, data=body)
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        
        with urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode())
            print(f"✅ File sent: {filename}")
            return result
            
    except Exception as e:
        print(f"❌ File send error: {e}")
        send_telegram_message(chat_id, f"❌ File sending failed.\n\nContent preview:\n```html\n{content[:1000]}...\n```")
        return None

# ======================== HTML PROCESSING ========================
def extract_telegram_buttons(html_content):
    """Simple telegram button extraction without BeautifulSoup"""
    buttons = []
    
    # Simple regex pattern for <a> tags with Telegram links
    pattern = r'<a[^>]*href=["\']([^"\']*(?:t\.me|telegram\.me)[^"\']*)["\'][^>]*>(.*?)</a>'
    
    matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
    
    seen = set()
    for link, text in matches:
        # Clean text
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        clean_text = re.sub(r'\s+', ' ', clean_text)
        
        if clean_text and len(clean_text) > 1:
            # Normalize link
            if not link.startswith('http'):
                link = 'https://' + link.lstrip('/')
            
            signature = (clean_text.lower(), link.lower())
            if signature not in seen:
                seen.add(signature)
                buttons.append({
                    'name': clean_text,
                    'link': link,
                    'new_name': clean_text,
                    'new_link': link,
                    'deleted': False
                })
    
    return buttons

def apply_button_changes(html_content, buttons):
    """Apply button modifications to HTML"""
    for button in buttons:
        if button['deleted']:
            # Remove button completely
            pattern = f'<a[^>]*href=["\'][^"\']*{re.escape(button["link"])}[^"\']*["\'][^>]*>.*?</a>'
            html_content = re.sub(pattern, '', html_content, flags=re.IGNORECASE | re.DOTALL)
        else:
            # Update button text and link
            old_link_escaped = re.escape(button['link'])
            new_link = button['new_link']
            new_name = button['new_name']
            
            # Replace href
            html_content = re.sub(
                f'href=["\'][^"\']*{old_link_escaped}[^"\']*["\']',
                f'href="{new_link}"',
                html_content,
                flags=re.IGNORECASE
            )
            
            # Replace text content
            pattern = f'(<a[^>]*href=["\'][^"\']*{re.escape(new_link)}[^"\']*["\'][^>]*>)[^<]*{re.escape(button["name"])}[^<]*(</a>)'
            replacement = f'\\1{new_name}\\2'
            html_content = re.sub(pattern, replacement, html_content, flags=re.IGNORECASE)
    
    return html_content

# ======================== USER SESSION ========================
user_sessions = {}

def init_session(user_id):
    user_sessions[user_id] = {
        'files': {},
        'buttons': [],
        'state': 'uploading',
        'last_activity': datetime.now()
    }

def check_owner(user_id):
    return user_id == OWNER_ID

def is_session_expired(user_id):
    if user_id not in user_sessions:
        return True
    
    last_activity = user_sessions[user_id]['last_activity']
    if datetime.now() - last_activity > timedelta(minutes=10):
        del user_sessions[user_id]
        return True
    
    user_sessions[user_id]['last_activity'] = datetime.now()
    return False

# ======================== MESSAGE HANDLERS ========================
def handle_message(message):
    chat_id = message['chat']['id']
    user_id = message['from']['id']
    
    # Owner check
    if not check_owner(user_id):
        send_telegram_message(chat_id, "🚫 **Access Denied**\n\nThis is a private bot.")
        return
    
    # Session timeout check
    if is_session_expired(user_id):
        send_telegram_message(chat_id, "⏱ **Session expired.** Send /start to begin again.")
        return
    
    # Handle text commands
    if 'text' in message:
        text = message['text'].strip()
        
        if text.startswith('/start'):
            init_session(user_id)
            send_telegram_message(chat_id,
                "🚀 **HTML Button Editor Bot**\n\n"
                "📤 **Send HTML files** with Telegram buttons\n"
                "📋 **Type /done** when finished uploading\n"
                "❓ **Type /help** for detailed guide\n\n"
                "🔒 **Private bot** - Owner only access"
            )
        
        elif text.startswith('/help'):
            send_telegram_message(chat_id,
                "📘 **Quick Guide:**\n\n"
                "1️⃣ Upload HTML files with Telegram links\n"
                "2️⃣ Send /done to process files\n"
                "3️⃣ Use inline buttons to edit\n"
                "4️⃣ Generate and download edited files\n\n"
                "🎯 **Features:**\n"
                "• Edit button names and links\n"
                "• Delete unwanted buttons\n"
                "• Global link replacement\n"
                "• Custom text replacement\n"
                "• Page title editing"
            )
        
        elif text.startswith('/done'):
            if user_id not in user_sessions or not user_sessions[user_id]['files']:
                send_telegram_message(chat_id, "⚠️ **No files uploaded.** Please send HTML files first.")
                return
            
            # Process files
            process_files(chat_id, user_id)
        
        else:
            # Handle editing inputs
            handle_text_input(chat_id, user_id, text)
    
    # Handle file uploads
    elif 'document' in message:
        handle_file_upload(chat_id, user_id, message['document'])

def handle_file_upload(chat_id, user_id, document):
    if user_id not in user_sessions:
        init_session(user_id)
    
    filename = document['file_name']
    
    if not filename.lower().endswith(('.html', '.htm')):
        send_telegram_message(chat_id, "❌ **Invalid file type.** Please send HTML files only.")
        return
    
    # Download file
    send_telegram_message(chat_id, f"⏳ **Processing:** `{filename}`...")
    
    html_content = get_file_content(document['file_id'])
    if not html_content:
        send_telegram_message(chat_id, "❌ **Download failed.** Please try again.")
        return
    
    # Store file
    user_sessions[user_id]['files'][filename] = html_content
    
    # Extract buttons for preview
    buttons = extract_telegram_buttons(html_content)
    
    send_telegram_message(chat_id,
        f"✅ **{filename}**\n"
        f"📊 **Found:** {len(buttons)} Telegram buttons\n"
        f"📁 **Total files:** {len(user_sessions[user_id]['files'])}\n\n"
        f"📤 **Send more files or /done to continue**"
    )

def process_files(chat_id, user_id):
    session = user_sessions[user_id]
    files = session['files']
    
    send_telegram_message(chat_id, "🔄 **Processing all files...**")
    
    # Extract and deduplicate all buttons
    all_buttons = []
    seen_signatures = set()
    
    for filename, html_content in files.items():
        file_buttons = extract_telegram_buttons(html_content)
        
        for button in file_buttons:
            signature = (button['name'].lower(), button['link'].lower())
            if signature not in seen_signatures:
                seen_signatures.add(signature)
                all_buttons.append(button)
    
    session['buttons'] = all_buttons
    session['state'] = 'editing'
    
    # Show main menu
    show_main_menu(chat_id, user_id)

def show_main_menu(chat_id, user_id):
    session = user_sessions[user_id]
    buttons = session['buttons']
    
    keyboard = []
    
    # Show first 5 buttons
    for i, button in enumerate(buttons[:5]):
        status = "🔴" if button['deleted'] else ("🟡" if button['new_name'] != button['name'] or button['new_link'] != button['link'] else "⚪")
        name = button['new_name'][:25] + ("..." if len(button['new_name']) > 25 else "")
        keyboard.append([{"text": f"{status} {name}", "callback_data": f"edit_{i}"}])
    
    if len(buttons) > 5:
        keyboard.append([{"text": f"... and {len(buttons) - 5} more buttons", "callback_data": "show_all"}])
    
    # Action buttons
    keyboard.extend([
        [
            {"text": "🔗 Global Link Replace", "callback_data": "global_link"},
            {"text": "📝 Text Replace", "callback_data": "text_replace"}
        ],
        [
            {"text": "🏷️ Page Title", "callback_data": "edit_title"},
            {"text": "📁 Filename", "callback_data": "custom_filename"}
        ],
        [
            {"text": "🔄 Reset All", "callback_data": "reset"},
            {"text": "✅ Generate Files", "callback_data": "generate"}
        ]
    ])
    
    text = (
        f"🎛️ **HTML Editor Control Panel**\n\n"
        f"📊 **Session Status:**\n"
        f"• Files: {len(session['files'])}\n"
        f"• Buttons: {len(buttons)}\n\n"
        f"🎯 **Choose an option:**"
    )
    
    send_telegram_message(chat_id, text, {"inline_keyboard": keyboard})

def handle_text_input(chat_id, user_id, text):
    # Handle various text inputs based on session state
    session = user_sessions[user_id]
    
    if session.get('waiting_for') == 'button_name':
        # Update button name
        button_idx = session.get('editing_button_idx')
        if button_idx is not None and button_idx < len(session['buttons']):
            session['buttons'][button_idx]['new_name'] = text
            send_telegram_message(chat_id, f"✅ **Button name updated:** `{text}`")
            del session['waiting_for']
            show_main_menu(chat_id, user_id)
    
    elif session.get('waiting_for') == 'button_link':
        # Update button link with validation
        if not ('t.me' in text.lower() or 'telegram.me' in text.lower()):
            send_telegram_message(chat_id, "❌ **Invalid link.** Please send a Telegram link.")
            return
        
        button_idx = session.get('editing_button_idx')
        if button_idx is not None and button_idx < len(session['buttons']):
            session['buttons'][button_idx]['new_link'] = text
            send_telegram_message(chat_id, f"✅ **Button link updated:** `{text}`")
            del session['waiting_for']
            show_main_menu(chat_id, user_id)
    
    elif session.get('waiting_for') == 'global_link':
        # Global link replacement
        if not ('t.me' in text.lower() or 'telegram.me' in text.lower()):
            send_telegram_message(chat_id, "❌ **Invalid link.** Please send a Telegram link.")
            return
        
        count = 0
        for button in session['buttons']:
            if not button['deleted']:
                button['new_link'] = text
                count += 1
        
        send_telegram_message(chat_id, f"✅ **Global replacement complete:** {count} buttons updated")
        del session['waiting_for']
        show_main_menu(chat_id, user_id)

def handle_callback_query(callback_query):
    chat_id = callback_query['message']['chat']['id']
    user_id = callback_query['from']['id']
    data = callback_query['data']
    message_id = callback_query['message']['message_id']
    
    # Owner check
    if not check_owner(user_id):
        return
    
    # Session check
    if is_session_expired(user_id):
        send_telegram_message(chat_id, "⏱ **Session expired.** Send /start to begin again.")
        return
    
    session = user_sessions[user_id]
    
    if data.startswith('edit_'):
        # Edit individual button
        button_idx = int(data.split('_')[1])
        session['editing_button_idx'] = button_idx
        
        button = session['buttons'][button_idx]
        
        keyboard = [
            [
                {"text": "✏️ Edit Name", "callback_data": "edit_name"},
                {"text": "🔗 Edit Link", "callback_data": "edit_link"}
            ],
            [{"text": "🗑️ Toggle Delete", "callback_data": "toggle_delete"}],
            [{"text": "⬅️ Back", "callback_data": "back"}]
        ]
        
        status = "🗑️ DELETED" if button['deleted'] else ("✏️ MODIFIED" if button['new_name'] != button['name'] or button['new_link'] != button['link'] else "📋 ORIGINAL")
        
        text = (
            f"🔘 **Button Editor**\n\n"
            f"**Status:** {status}\n"
            f"**Name:** `{button['new_name']}`\n"
            f"**Link:** `{button['new_link']}`\n\n"
            f"🎯 **Choose action:**"
        )
        
        # Edit message instead of sending new one
        edit_telegram_message(chat_id, message_id, text, {"inline_keyboard": keyboard})
    
    elif data == 'edit_name':
        session['waiting_for'] = 'button_name'
        edit_telegram_message(chat_id, message_id, "✏️ **Send the new button name:**")
    
    elif data == 'edit_link':
        session['waiting_for'] = 'button_link'
        edit_telegram_message(chat_id, message_id, "🔗 **Send the new Telegram link:**")
    
    elif data == 'toggle_delete':
        button_idx = session.get('editing_button_idx')
        if button_idx is not None:
            button = session['buttons'][button_idx]
            button['deleted'] = not button['deleted']
            action = "deleted" if button['deleted'] else "restored"
            
            send_telegram_message(chat_id, f"✅ **Button {action}**")
            show_main_menu(chat_id, user_id)
    
    elif data == 'global_link':
        session['waiting_for'] = 'global_link'
        edit_telegram_message(chat_id, message_id, "🔗 **Send the new link for ALL buttons:**")
    
    elif data == 'generate':
        generate_files(chat_id, user_id)
    
    elif data == 'back':
        show_main_menu(chat_id, user_id)

def edit_telegram_message(chat_id, message_id, text, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        data = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        req = Request(url, data=urlencode(data).encode())
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Edit error: {e}")
        return None

def generate_files(chat_id, user_id):
    session = user_sessions[user_id]
    
    send_telegram_message(chat_id, "⚡ **Generating files...**")
    
    files = session['files']
    buttons = session['buttons']
    
    for filename, original_html in files.items():
        # Apply all button changes
        modified_html = apply_button_changes(original_html, buttons)
        
        # Generate filename
        base_name = filename.replace('.html', '').replace('.htm', '')
        new_filename = f"{base_name}{RENAME_TAG}.html"
        
        # Send file
        send_document(chat_id, new_filename, modified_html, f"✅ Processed: {filename}")
    
    # Summary
    edited_count = len([b for b in buttons if b['new_name'] != b['name'] or b['new_link'] != b['link']])
    deleted_count = len([b for b in buttons if b['deleted']])
    
    send_telegram_message(chat_id,
        f"🎉 **Generation Complete!**\n\n"
        f"📊 **Summary:**\n"
        f"• Files: {len(files)}\n"
        f"• Buttons edited: {edited_count}\n"
        f"• Buttons deleted: {deleted_count}\n\n"
        f"🔄 **Send /start for new session**"
    )
    
    # Clear session
    del user_sessions[user_id]

# ======================== MAIN LOOP ========================
def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set BOT_TOKEN environment variable!")
        return
    
    if OWNER_ID == 123456789:
        print("⚠️ Please set OWNER_ID environment variable!")
        return
    
    # Start health server
    Thread(target=run_health, daemon=True).start()
    
    # Bot polling
    offset = 0
    print("🤖 Bot started! Waiting for messages...")
    
    while True:
        try:
            result = get_telegram_updates(offset)
            
            if not result or not result.get('ok'):
                continue
            
            for update in result.get('result', []):
                try:
                    if 'message' in update:
                        handle_message(update['message'])
                    elif 'callback_query' in update:
                        handle_callback_query(update['callback_query'])
                except Exception as e:
                    print(f"❌ Handle error: {e}")
                
                offset = update['update_id'] + 1
        
        except Exception as e:
            print(f"❌ Main loop error: {e}")
            import time
            time.sleep(5)

if __name__ == '__main__':
    main()
