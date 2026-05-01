import os
import re
import json
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.parse import urlencode

# Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
RENAME_TAG = os.getenv("RENAME_TAG", "_STRANGE")

print(f"✅ Bot Config: Owner={OWNER_ID}, Tag={RENAME_TAG}")

# User sessions
user_sessions = {}

# Health Check
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'HTML Editor Bot with Inline Buttons!')
    def log_message(self, *args): pass

def run_health():
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🌐 Health: {port}")
    server.serve_forever()

# Telegram Functions
def send_message(chat_id, text, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        data_encoded = urlencode(data).encode()
        req = Request(url, data=data_encoded)
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Send error: {e}")
        return None

def edit_message(chat_id, message_id, text, reply_markup=None):
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
        
        data_encoded = urlencode(data).encode()
        req = Request(url, data=data_encoded)
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Edit error: {e}")
        return None

def answer_callback(callback_query_id, text=""):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        data = urlencode({
            'callback_query_id': callback_query_id,
            'text': text
        }).encode()
        req = Request(url, data=data)
        with urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Callback error: {e}")
        return None

def get_file_info(file_id):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
        with urlopen(url, timeout=10) as response:
            result = json.loads(response.read().decode())
            if result.get('ok'):
                return result['result']
            return None
    except Exception as e:
        print(f"❌ File info error: {e}")
        return None

def download_file_content(file_path):
    try:
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        with urlopen(url, timeout=30) as response:
            content = response.read()
            try:
                return content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    return content.decode('latin-1')
                except UnicodeDecodeError:
                    return content.decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"❌ Download error: {e}")
        return None

def extract_telegram_buttons(html_content):
    """Extract all Telegram buttons from HTML"""
    buttons = []
    
    # Pattern 1: <a href="telegram_link">Button Text</a>
    a_pattern = r'<a[^>]*href=["\']([^"\']*(?:t\.me|telegram\.me)[^"\']*)["\'][^>]*>(.*?)</a>'
    a_matches = re.findall(a_pattern, html_content, re.IGNORECASE | re.DOTALL)
    
    for link, text in a_matches:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        if clean_text:
            buttons.append((clean_text, link.strip()))
    
    # Pattern 2: <button onclick="window.open('telegram_link')">Text</button>
    button_pattern1 = r'<button[^>]*onclick=["\'][^"\']*(?:window\.open|location\.href)[^"\']*["\']([^"\']*(?:t\.me|telegram\.me)[^"\']*)["\'][^>]*>(.*?)</button>'
    button_matches1 = re.findall(button_pattern1, html_content, re.IGNORECASE | re.DOTALL)
    
    for link, text in button_matches1:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        if clean_text:
            buttons.append((clean_text, link.strip()))
    
    # Remove duplicates and normalize
    seen = set()
    unique_buttons = []
    
    for text, link in buttons:
        if link.startswith('//'):
            link = 'https:' + link
        elif not link.startswith('http'):
            link = 'https://' + link.lstrip('/')
        
        text = re.sub(r'\s+', ' ', text).strip()
        
        if len(text) >= 2:
            key = (text.lower().strip(), link.lower().strip())
            if key not in seen and text and link:
                seen.add(key)
                unique_buttons.append((text, link))
    
    return unique_buttons

def apply_changes(html_content, changes):
    """Apply button changes to HTML content"""
    buttons = extract_telegram_buttons(html_content)
    
    for button_idx, new_name, new_link in changes:
        if 0 <= button_idx < len(buttons):
            old_name, old_link = buttons[button_idx]
            
            # Escape for regex
            old_name_escaped = re.escape(old_name)
            old_link_escaped = re.escape(old_link)
            
            # Replace link in href attributes
            html_content = re.sub(
                f'href=["\'][^"\']*{old_link_escaped}[^"\']*["\']',
                f'href="{new_link}"',
                html_content,
                flags=re.IGNORECASE
            )
            
            # Replace in onclick attributes
            html_content = re.sub(
                f'onclick=["\'][^"\']*{old_link_escaped}[^"\']*["\']',
                f'onclick="window.open(\'{new_link}\')"',
                html_content,
                flags=re.IGNORECASE
            )
            
            # Replace button text in <a> tags
            html_content = re.sub(
                f'(<a[^>]*href=["\'][^"\']*{re.escape(new_link)}[^"\']*["\'][^>]*>)[^<]*{old_name_escaped}[^<]*(</a>)',
                f'\\1{new_name}\\2',
                html_content,
                flags=re.IGNORECASE
            )
            
            # Replace button text in <button> tags
            html_content = re.sub(
                f'(<button[^>]*>[^<]*){old_name_escaped}([^<]*</button>)',
                f'\\1{new_name}\\2',
                html_content,
                flags=re.IGNORECASE
            )
    
    return html_content

def create_buttons_keyboard(buttons, changes, page=0):
    """Create inline keyboard with buttons"""
    keyboard = []
    
    # Show 8 buttons per page (2 rows of 4)
    buttons_per_page = 8
    start_idx = page * buttons_per_page
    end_idx = min(start_idx + buttons_per_page, len(buttons))
    
    # Create button grid (2 columns)
    for i in range(start_idx, end_idx, 2):
        row = []
        
        # First button
        button_text, _ = buttons[i]
        display_text = button_text[:25] + "..." if len(button_text) > 25 else button_text
        
        # Add ✅ if edited
        if any(change[0] == i for change in changes):
            display_text = f"✅ {display_text}"
        else:
            display_text = f"📝 {display_text}"
            
        row.append({
            "text": display_text,
            "callback_data": f"edit_{i}"
        })
        
        # Second button (if exists)
        if i + 1 < end_idx:
            button_text2, _ = buttons[i + 1]
            display_text2 = button_text2[:25] + "..." if len(button_text2) > 25 else button_text2
            
            if any(change[0] == i + 1 for change in changes):
                display_text2 = f"✅ {display_text2}"
            else:
                display_text2 = f"📝 {display_text2}"
                
            row.append({
                "text": display_text2,
                "callback_data": f"edit_{i+1}"
            })
        
        keyboard.append(row)
    
    # Navigation buttons
    nav_row = []
    if page > 0:
        nav_row.append({"text": "⬅️ Previous", "callback_data": f"page_{page-1}"})
    
    if end_idx < len(buttons):
        nav_row.append({"text": "Next ➡️", "callback_data": f"page_{page+1}"})
    
    if nav_row:
        keyboard.append(nav_row)
    
    # Generate file button
    changes_count = len(changes)
    generate_text = f"🎉 Generate File ({changes_count} changes)" if changes_count > 0 else "🎉 Generate File"
    keyboard.append([{"text": generate_text, "callback_data": "generate"}])
    
    return {"inline_keyboard": keyboard}

def show_buttons_interface(chat_id, message_id, filename, buttons, changes, page=0):
    """Show the main buttons interface"""
    if not buttons:
        text = f"❌ **No Telegram buttons found** in `{filename}`\n\nMake sure your HTML contains Telegram links!"
        keyboard = {"inline_keyboard": [[{"text": "🔄 Upload New File", "callback_data": "new_file"}]]}
        
        if message_id:
            edit_message(chat_id, message_id, text, keyboard)
        else:
            send_message(chat_id, text, keyboard)
        return
    
    # Create header text
    total_pages = (len(buttons) - 1) // 8 + 1
    changes_count = len(changes)
    
    text = f"🔗 **Telegram Buttons in `{filename}`**\n\n"
    text += f"📊 **Found:** {len(buttons)} buttons"
    
    if total_pages > 1:
        text += f" (Page {page + 1}/{total_pages})"
    
    if changes_count > 0:
        text += f"\n✅ **Changes:** {changes_count}"
    
    text += "\n\n📝 **Click any button to edit it:**"
    
    # Create keyboard
    keyboard = create_buttons_keyboard(buttons, changes, page)
    
    # Send or edit message
    if message_id:
        edit_message(chat_id, message_id, text, keyboard)
    else:
        send_message(chat_id, text, keyboard)

def handle_message(message):
    if not message.get('text') and not message.get('document'):
        return
    
    chat_id = message['chat']['id']
    user_id = message['from']['id']
    
    # Owner check
    if user_id != OWNER_ID:
        send_message(chat_id, "🚫 Sorry, you're not authorized to use this bot.")
        return
    
    # Handle text messages
    if message.get('text'):
        text = message['text'].strip()
        
        if text.startswith('/start'):
            user_sessions[user_id] = {'state': 'waiting_file'}
            send_message(chat_id,
                "🚀 **HTML Button Editor Bot**\n\n"
                "📤 **Send me an HTML file** with Telegram buttons.\n"
                "🔍 I'll show them as **clickable buttons** for easy editing.\n"
                "✏️ Click → Edit → Generate!\n\n"
                "📋 **Commands:**\n"
                "/help - Usage guide\n"
                "/cancel - Cancel session"
            )
        
        elif text.startswith('/help'):
            send_message(chat_id,
                "📘 **Step-by-Step Guide:**\n\n"
                "1️⃣ **Upload** HTML file with Telegram links\n"
                "2️⃣ **Click** any button to edit it\n"
                "3️⃣ **Send** new details as: `Name | Link`\n"
                "4️⃣ **Generate** updated file when done\n\n"
                "**Edit Format:**\n"
                "`Premium Channel | https://t.me/premium`\n\n"
                "✅ **Visual, fast, and easy!**"
            )
        
        elif text.startswith('/cancel'):
            if user_id in user_sessions:
                del user_sessions[user_id]
            send_message(chat_id, "❌ Session cancelled. Send /start to begin again.")
        
        # Handle edit input
        elif user_id in user_sessions and user_sessions[user_id].get('state') == 'editing':
            if '|' not in text:
                send_message(chat_id,
                    "❌ **Invalid format!**\n\n"
                    "✅ **Correct format:**\n"
                    "`New Name | New Link`\n\n"
                    "**Example:**\n"
                    "`Premium Channel | https://t.me/premium`"
                )
                return
            
            parts = [part.strip() for part in text.split('|', 1)]
            if len(parts) != 2:
                send_message(chat_id, "❌ **Please use format:** `Name | Link`")
                return
            
            new_name, new_link = parts
            
            if not ('t.me' in new_link.lower() or 'telegram.me' in new_link.lower()):
                send_message(chat_id, "⚠️ **Invalid link!** Please use Telegram links (t.me or telegram.me)")
                return
            
            session = user_sessions[user_id]
            button_idx = session['editing_button']
            
            # Update changes
            if 'changes' not in session:
                session['changes'] = []
            
            # Remove existing change for this button
            session['changes'] = [c for c in session['changes'] if c[0] != button_idx]
            
            # Add new change
            session['changes'].append((button_idx, new_name, new_link))
            
            # Show updated interface
            session['state'] = 'viewing'
            session.pop('editing_button', None)
            
            send_message(chat_id,
                f"✅ **Button updated!**\n\n"
                f"**New Name:** `{new_name}`\n"
                f"**New Link:** `{new_link}`\n\n"
                f"📊 **Total changes:** {len(session['changes'])}"
            )
            
            # Show updated buttons interface
            show_buttons_interface(
                chat_id, None,
                session['filename'],
                session['buttons'],
                session['changes'],
                session.get('page', 0)
            )
    
    # Handle file uploads
    elif message.get('document'):
        doc = message['document']
        
        if not (doc['file_name'].endswith('.html') or doc['file_name'].endswith('.htm')):
            send_message(chat_id, "⚠️ **Please send HTML files only** (.html or .htm)")
            return
        
        send_message(chat_id, f"⏳ **Processing** `{doc['file_name']}`...\n📥 Downloading and scanning...")
        
        # Get and download file
        file_info = get_file_info(doc['file_id'])
        if not file_info:
            send_message(chat_id, "❌ **Error getting file info.** Please try again.")
            return
        
        html_content = download_file_content(file_info['file_path'])
        if not html_content:
            send_message(chat_id, "❌ **Error downloading file.** Please try again.")
            return
        
        # Extract buttons
        buttons = extract_telegram_buttons(html_content)
        
        # Store in session
        if user_id not in user_sessions:
            user_sessions[user_id] = {}
        
        user_sessions[user_id].update({
            'state': 'viewing',
            'filename': doc['file_name'],
            'html_content': html_content,
            'buttons': buttons,
            'changes': [],
            'page': 0
        })
        
        # Show buttons interface
        show_buttons_interface(chat_id, None, doc['file_name'], buttons, [], 0)

def handle_callback_query(callback_query):
    chat_id = callback_query['message']['chat']['id']
    user_id = callback_query['from']['id']
    message_id = callback_query['message']['message_id']
    callback_data = callback_query['data']
    
    # Owner check
    if user_id != OWNER_ID:
        answer_callback(callback_query['id'], "🚫 Not authorized")
        return
    
    answer_callback(callback_query['id'])
    
    if user_id not in user_sessions:
        send_message(chat_id, "⚠️ Session expired. Send /start to begin again.")
        return
    
    session = user_sessions[user_id]
    
    if callback_data.startswith('edit_'):
        # Edit button
        button_idx = int(callback_data.split('_')[1])
        
        if 0 <= button_idx < len(session['buttons']):
            button_name, button_link = session['buttons'][button_idx]
            
            session['state'] = 'editing'
            session['editing_button'] = button_idx
            
            edit_message(chat_id, message_id,
                f"✏️ **Editing Button:**\n\n"
                f"**Current Name:** `{button_name}`\n"
                f"**Current Link:** `{button_link}`\n\n"
                f"📝 **Send new details as:**\n"
                f"`New Name | New Link`\n\n"
                f"**Example:**\n"
                f"`Premium Channel | https://t.me/premium`",
                {"inline_keyboard": [[{"text": "❌ Cancel", "callback_data": "cancel_edit"}]]}
            )
    
    elif callback_data.startswith('page_'):
        # Page navigation
        page = int(callback_data.split('_')[1])
        session['page'] = page
        
        show_buttons_interface(
            chat_id, message_id,
            session['filename'],
            session['buttons'],
            session['changes'],
            page
        )
    
    elif callback_data == 'cancel_edit':
        # Cancel editing
        session['state'] = 'viewing'
        session.pop('editing_button', None)
        
        show_buttons_interface(
            chat_id, message_id,
            session['filename'],
            session['buttons'],
            session['changes'],
            session.get('page', 0)
        )
    
    elif callback_data == 'generate':
        # Generate updated file
        if not session.get('changes'):
            answer_callback(callback_query['id'], "No changes made!")
            return
        
        edit_message(chat_id, message_id,
            f"⏳ **Generating updated file...**\n\n"
            f"📊 **Applying {len(session['changes'])} changes**"
        )
        
        # Apply changes
        updated_html = apply_changes(session['html_content'], session['changes'])
        
        # Generate filename
        base_name = session['filename'].replace('.html', '').replace('.htm', '')
        new_filename = f"{base_name}{RENAME_TAG}.html"
        
        # Send file content
        if len(updated_html) > 3000:
            preview = updated_html[:3000] + "\n\n... (file truncated for display)"
        else:
            preview = updated_html
        
        send_message(chat_id, f"📄 **{new_filename}**\n\n```html\n{preview}\n```")
        
        if len(updated_html) > 3000:
            send_message(chat_id, f"📊 **Full file size:** {len(updated_html)} characters")
        
        send_message(chat_id,
            "🎉 **File generated successfully!**\n\n"
            "📋 **Summary:**\n"
            f"✅ Changes applied: {len(session['changes'])}\n"
            f"📄 File: `{new_filename}`\n\n"
            "Send /start for new session."
        )
        
        # Clean session
        if user_id in user_sessions:
            del user_sessions[user_id]
    
    elif callback_data == 'new_file':
        # Start new file upload
        user_sessions[user_id] = {'state': 'waiting_file'}
        edit_message(chat_id, message_id,
            "📤 **Send me a new HTML file** with Telegram buttons to edit."
        )

def get_updates(offset=0):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
        with urlopen(url, timeout=35) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Updates error: {e}")
        return None

def main():
    if not BOT_TOKEN or OWNER_ID == 0:
        print("❌ BOT_TOKEN or OWNER_ID missing!")
        return
    
    print("🚀 Starting Inline Buttons HTML Editor Bot...")
    
    # Health server
    Thread(target=run_health, daemon=True).start()
    
    # Bot polling
    offset = 0
    print("🤖 Bot with inline buttons started!")
    
    while True:
        try:
            result = get_updates(offset)
            if not result or not result.get('ok'):
                continue
            
            for update in result.get('result', []):
                if 'message' in update:
                    handle_message(update['message'])
                elif 'callback_query' in update:
                    handle_callback_query(update['callback_query'])
                
                offset = update['update_id'] + 1
        
        except KeyboardInterrupt:
            print("🛑 Bot stopped")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            import time
            time.sleep(5)

if __name__ == '__main__':
    main()
