import os
import re
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import json

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
        self.wfile.write(b'HTML Editor Bot Active!')
    def log_message(self, *args): pass

def run_health():
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🌐 Health: {port}")
    server.serve_forever()

# Telegram Functions
def send_message(chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = urlencode({
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }).encode()
        req = Request(url, data=data)
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Send error: {e}")
        return None

def send_document(chat_id, filename, content):
    try:
        # Simple file sending via sendMessage with content
        send_message(chat_id, f"📄 **{filename}**\n\n```html\n{content[:500]}...\n```\n\n✅ File ready for download!")
        return True
    except Exception as e:
        print(f"❌ Document error: {e}")
        return False

def get_file_content(file_id):
    """Simulate getting file content - in real implementation, download from Telegram"""
    # For demo, return sample HTML with Telegram links
    return """<!DOCTYPE html>
<html>
<head><title>Sample Page</title></head>
<body>
    <h1>Welcome to Our Channel</h1>
    <a href="https://t.me/oldchannel">Join Our Channel</a>
    <p>Follow us for updates</p>
    <button onclick="window.open('https://t.me/oldgroup')">Join Group</button>
    <div>
        <a href="https://t.me/oldsupport">Contact Support</a>
    </div>
    <a href="https://telegram.me/oldnews">Get News</a>
</body>
</html>"""

def extract_telegram_buttons(html_content):
    """Extract all Telegram buttons from HTML"""
    buttons = []
    
    # Find all <a> tags with Telegram links
    a_pattern = r'<a[^>]*href=["\']([^"\']*(?:t\.me|telegram\.me)[^"\']*)["\'][^>]*>(.*?)</a>'
    a_matches = re.findall(a_pattern, html_content, re.IGNORECASE | re.DOTALL)
    
    for link, text in a_matches:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        if clean_text:
            buttons.append((clean_text, link))
    
    # Find button tags with onclick Telegram links  
    button_pattern = r'<button[^>]*onclick=["\'][^"\']*(?:window\.open|location\.href)[^"\']*["\']([^"\']*(?:t\.me|telegram\.me)[^"\']*)["\'][^>]*>(.*?)</button>'
    button_matches = re.findall(button_pattern, html_content, re.IGNORECASE | re.DOTALL)
    
    for link, text in button_matches:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        if clean_text:
            buttons.append((clean_text, link))
    
    # Remove duplicates and normalize links
    seen = set()
    unique_buttons = []
    
    for text, link in buttons:
        # Normalize link
        if link.startswith('//'):
            link = 'https:' + link
        elif not link.startswith('http'):
            link = 'https://' + link
            
        key = (text.lower(), link.lower())
        if key not in seen:
            seen.add(key)
            unique_buttons.append((text, link))
    
    return unique_buttons

def apply_changes(html_content, changes):
    """Apply button changes to HTML content"""
    buttons = extract_telegram_buttons(html_content)
    
    # Apply each change
    for button_num, new_name, new_link in changes:
        if 1 <= button_num <= len(buttons):
            old_name, old_link = buttons[button_num - 1]
            
            # Replace in HTML
            # Replace <a> tags
            old_a_pattern = f'<a([^>]*href=["\'][^"\']*{re.escape(old_link)}[^"\']*["\'][^>]*)>([^<]*{re.escape(old_name)}[^<]*)</a>'
            new_a = f'<a\\1>{new_name}</a>'
            html_content = re.sub(old_a_pattern, new_a, html_content, flags=re.IGNORECASE)
            
            # Update href attribute
            html_content = re.sub(
                f'href=["\'][^"\']*{re.escape(old_link)}[^"\']*["\']',
                f'href="{new_link}"',
                html_content,
                flags=re.IGNORECASE
            )
            
            # Replace button onclick
            button_pattern = f'onclick=["\'][^"\']*{re.escape(old_link)}[^"\']*["\']'
            new_onclick = f'onclick="window.open(\'{new_link}\')"'
            html_content = re.sub(button_pattern, new_onclick, html_content, flags=re.IGNORECASE)
    
    return html_content

def format_buttons_list(buttons):
    """Format buttons as numbered list"""
    if not buttons:
        return "❌ No Telegram buttons found in this file."
    
    text = "🔗 **Telegram Buttons Found:**\n\n"
    for i, (name, link) in enumerate(buttons, 1):
        text += f"`{i}.` **{name}**\n   `{link}`\n\n"
    
    text += "📝 **To edit a button, send:**\n"
    text += "`number | new name | new link`\n\n"
    text += "**Example:**\n"
    text += "`1 | Join New Channel | https://t.me/newchannel`\n\n"
    text += "📤 **When done, send:** `/generate`"
    
    return text

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
            user_sessions[user_id] = {'state': 'waiting_file', 'files': {}}
            send_message(chat_id,
                "🚀 **HTML Button Editor Bot**\n\n"
                "📤 **Send me an HTML file** containing Telegram buttons.\n"
                "🔍 I'll scan and show you all the buttons with numbers.\n"
                "✏️ You can then edit them with simple commands.\n\n"
                "📋 **Commands:**\n"
                "/help - Usage guide\n"
                "/cancel - Cancel session"
            )
        
        elif text.startswith('/help'):
            send_message(chat_id,
                "📘 **How to Use:**\n\n"
                "1️⃣ Send HTML file\n"
                "2️⃣ I'll show numbered button list\n"
                "3️⃣ Send: `number | new name | new link`\n"
                "4️⃣ Send `/generate` to get updated file\n\n"
                "**Example:**\n"
                "`1 | New Channel Name | https://t.me/newchannel`\n"
                "`2 | Updated Group | https://t.me/newgroup`\n\n"
                "✅ Simple and fast!"
            )
        
        elif text.startswith('/cancel'):
            if user_id in user_sessions:
                del user_sessions[user_id]
            send_message(chat_id, "❌ Session cancelled. Send /start to begin again.")
        
        elif text.startswith('/generate'):
            if user_id not in user_sessions or 'current_file' not in user_sessions[user_id]:
                send_message(chat_id, "⚠️ No file loaded. Please send an HTML file first.")
                return
            
            session = user_sessions[user_id]
            original_html = session['current_file']['content']
            filename = session['current_file']['name']
            changes = session.get('changes', [])
            
            if not changes:
                send_message(chat_id, "ℹ️ No changes made. Sending original file.")
                updated_html = original_html
            else:
                updated_html = apply_changes(original_html, changes)
                send_message(chat_id, f"✅ Applied {len(changes)} change(s)")
            
            # Generate new filename
            base_name = filename.replace('.html', '')
            new_filename = f"{base_name}{RENAME_TAG}.html"
            
            # Send updated file content
            send_message(chat_id, f"📄 **{new_filename}**\n\n```html\n{updated_html}\n```")
            send_message(chat_id, "🎉 **File generated successfully!**\n\nSend /start for new session.")
            
            # Clean session
            if user_id in user_sessions:
                del user_sessions[user_id]
        
        # Handle edit commands: "number | new name | new link"
        elif '|' in text and user_id in user_sessions and 'current_file' in user_sessions[user_id]:
            try:
                parts = [part.strip() for part in text.split('|')]
                if len(parts) != 3:
                    send_message(chat_id, "❌ **Invalid format!**\n\nUse: `number | new name | new link`")
                    return
                
                button_num = int(parts[0])
                new_name = parts[1]
                new_link = parts[2]
                
                # Validate link
                if not ('t.me' in new_link.lower() or 'telegram.me' in new_link.lower()):
                    send_message(chat_id, "⚠️ Please provide a valid Telegram link (t.me or telegram.me)")
                    return
                
                # Add to changes
                if 'changes' not in user_sessions[user_id]:
                    user_sessions[user_id]['changes'] = []
                
                # Remove existing change for this button
                user_sessions[user_id]['changes'] = [
                    c for c in user_sessions[user_id]['changes'] 
                    if c[0] != button_num
                ]
                
                # Add new change
                user_sessions[user_id]['changes'].append((button_num, new_name, new_link))
                
                send_message(chat_id, 
                    f"✅ **Button {button_num} updated:**\n"
                    f"📝 Name: `{new_name}`\n"
                    f"🔗 Link: `{new_link}`\n\n"
                    f"📊 Total changes: {len(user_sessions[user_id]['changes'])}\n\n"
                    f"Continue editing or send `/generate`"
                )
                
            except ValueError:
                send_message(chat_id, "❌ **Invalid button number!**\n\nUse: `number | new name | new link`")
            except Exception as e:
                send_message(chat_id, f"❌ Error processing command: {str(e)}")
    
    # Handle file uploads
    elif message.get('document'):
        doc = message['document']
        
        if not doc['file_name'].endswith('.html'):
            send_message(chat_id, "⚠️ **Please send only HTML files (.html)**")
            return
        
        # Get file content (in real bot, you'd download via file_id)
        html_content = get_file_content(doc['file_id'])
        
        # Extract buttons
        buttons = extract_telegram_buttons(html_content)
        
        if not buttons:
            send_message(chat_id, "❌ **No Telegram buttons found** in this HTML file.\n\nMake sure your HTML contains links like `https://t.me/channel`")
            return
        
        # Store in session
        if user_id not in user_sessions:
            user_sessions[user_id] = {}
        
        user_sessions[user_id]['current_file'] = {
            'name': doc['file_name'],
            'content': html_content
        }
        user_sessions[user_id]['changes'] = []
        
        # Send buttons list
        buttons_text = format_buttons_list(buttons)
        send_message(chat_id, buttons_text)

def get_updates(offset=0):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}"
        with urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Updates error: {e}")
        return None

def main():
    if not BOT_TOKEN or OWNER_ID == 0:
        print("❌ BOT_TOKEN or OWNER_ID missing!")
        return
    
    print("🚀 Starting HTML Button Editor Bot...")
    
    # Health server
    Thread(target=run_health, daemon=True).start()
    
    # Bot polling
    offset = 0
    print("🤖 Bot polling started!")
    
    while True:
        try:
            result = get_updates(offset)
            if not result or not result.get('ok'):
                continue
            
            for update in result.get('result', []):
                if 'message' in update:
                    handle_message(update['message'])
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
