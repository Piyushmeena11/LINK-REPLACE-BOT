import os
import re
import json
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import base64

# Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
RENAME_TAG = os.getenv("RENAME_TAG", "_STRANGE")

print(f"✅ Config loaded - Owner: {OWNER_ID}")

# Health Check
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'HTML Editor Bot Running!')
    def log_message(self, *args): pass

def run_health():
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🌐 Health server: {port}")
    server.serve_forever()

# Bot Session Storage
user_sessions = {}

# Telegram API Functions
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

def send_document(chat_id, filename, content):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        
        boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
        body = f'--{boundary}\r\n'
        body += f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        body += f'--{boundary}\r\n'
        body += f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        body += f'Content-Type: text/html\r\n\r\n{content}\r\n'
        body += f'--{boundary}--\r\n'
        
        req = Request(url, data=body.encode('utf-8'))
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Document send error: {e}")
        return None

def extract_telegram_links(html_content):
    """Extract Telegram links from HTML"""
    links = []
    # Simple regex to find Telegram links
    pattern = r'(https?://)?(t\.me|telegram\.me)/\S+'
    matches = re.findall(pattern, html_content, re.IGNORECASE)
    
    for match in matches[:5]:  # Max 5 links
        full_match = ''.join(match)
        if not full_match.startswith('http'):
            full_match = f'https://{full_match}'
        links.append(('Button', full_match))
    
    return links

def handle_message(message):
    if not message.get('text') and not message.get('document'):
        return
    
    chat_id = message['chat']['id']
    user_id = message['from']['id']
    
    # Owner check
    if user_id != OWNER_ID:
        send_message(chat_id, "🚫 Not authorized")
        return
    
    # Text commands
    if message.get('text'):
        text = message['text']
        
        if text == '/start':
            user_sessions[user_id] = {'files': [], 'state': 'collecting'}
            send_message(chat_id, 
                "🚀 **HTML Button Editor Bot**\n\n"
                "📤 Send me HTML file(s) containing Telegram links.\n"
                "✅ When done, type /done to start editing.\n"
                "❓ Type /help for guide."
            )
        
        elif text == '/help':
            send_message(chat_id,
                "📘 **Usage Guide**\n\n"
                "1️⃣ Send HTML files\n"
                "2️⃣ Type /done to edit\n" 
                "3️⃣ Click buttons to edit\n"
                "4️⃣ Download edited files\n\n"
                "**Commands:**\n"
                "/start - New session\n"
                "/help - This guide\n"
                "/cancel - Cancel session"
            )
        
        elif text == '/done':
            if user_id in user_sessions and user_sessions[user_id]['files']:
                files = user_sessions[user_id]['files']
                total_buttons = sum(len(f['links']) for f in files)
                
                send_message(chat_id, f"📊 **Summary:**\n{len(files)} files, {total_buttons} buttons found\n\n⏳ Processing...")
                
                # Send edited files
                for file_data in files:
                    base_name = file_data['name'].replace('.html', '')
                    new_filename = f"{base_name}{RENAME_TAG}.html"
                    send_document(chat_id, new_filename, file_data['content'])
                
                send_message(chat_id, "🎉 All files processed! Type /start for new session.")
                if user_id in user_sessions:
                    del user_sessions[user_id]
            else:
                send_message(chat_id, "⚠️ No files uploaded. Send HTML files first.")
        
        elif text == '/cancel':
            if user_id in user_sessions:
                del user_sessions[user_id]
            send_message(chat_id, "❌ Session cancelled. Type /start to begin again.")
    
    # File handling
    elif message.get('document'):
        doc = message['document']
        if not doc['file_name'].endswith('.html'):
            send_message(chat_id, "⚠️ Please send only HTML files.")
            return
        
        # Get file content (simplified - in real implementation you'd download the file)
        # For now, simulate finding links
        sample_html = f"""
        <!DOCTYPE html>
        <html>
        <body>
            <a href="https://t.me/sample_channel">Join Channel</a>
            <a href="https://t.me/another_channel">Another Link</a>
        </body>
        </html>
        """
        
        links = extract_telegram_links(sample_html)
        
        if user_id not in user_sessions:
            user_sessions[user_id] = {'files': [], 'state': 'collecting'}
        
        user_sessions[user_id]['files'].append({
            'name': doc['file_name'],
            'content': sample_html,
            'links': links
        })
        
        send_message(chat_id, 
            f"✅ **{doc['file_name']}**\n"
            f"🔗 Found {len(links)} Telegram buttons\n\n"
            f"Send more files or type /done to process."
        )

def get_updates(offset=0):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        if offset:
            url += f"?offset={offset}"
        
        with urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"❌ Get updates error: {e}")
        return None

def main():
    if not BOT_TOKEN or OWNER_ID == 0:
        print("❌ Config missing!")
        return
    
    print("🚀 Starting HTML Button Editor Bot...")
    
    # Start health server
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
