import os
import io
import re
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import json

# ======================== CONFIG ========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
RENAME_TAG = os.getenv("RENAME_TAG", "_edited")

print(f"🚀 Bot Starting...")
print(f"Owner: {OWNER_ID}, Tag: {RENAME_TAG}")

# ======================== HEALTH SERVER ========================
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot Running!')
    def log_message(self, *args): pass

def health_server():
    port = int(os.getenv('PORT', 10000))
    HTTPServer(('0.0.0.0', port), Health).serve_forever()

# ======================== TELEGRAM API ========================
def api_call(method, data=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
        if data:
            req = Request(url, urlencode(data).encode())
        else:
            req = Request(url)
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"API Error: {e}")
        return None

def send_msg(chat_id, text, keyboard=None):
    data = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    if keyboard:
        data['reply_markup'] = json.dumps({'inline_keyboard': keyboard})
    return api_call('sendMessage', data)

def edit_msg(chat_id, msg_id, text, keyboard=None):
    data = {'chat_id': chat_id, 'message_id': msg_id, 'text': text, 'parse_mode': 'Markdown'}
    if keyboard:
        data['reply_markup'] = json.dumps({'inline_keyboard': keyboard})
    return api_call('editMessageText', data)

def send_doc(chat_id, filename, content):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        boundary = '----Boundary7MA4YWxk'
        
        body = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
            f'Content-Type: text/html\r\n\r\n{content}\r\n'
            f'--{boundary}--\r\n'
        ).encode('utf-8')
        
        req = Request(url, body)
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"Doc send error: {e}")
        return None

def get_file(file_id):
    try:
        # Get file path
        result = api_call('getFile', {'file_id': file_id})
        if not result or not result.get('ok'):
            return None
        
        path = result['result']['file_path']
        
        # Download
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
        with urlopen(url, timeout=30) as r:
            return r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"File download error: {e}")
        return None

# ======================== HTML PROCESSING ========================
def find_buttons(html):
    """Simple button finder"""
    buttons = []
    pattern = r'<a[^>]*href=["\']([^"\']*(?:t\.me|telegram\.me)[^"\']*)["\'][^>]*>(.*?)</a>'
    
    for link, text in re.findall(pattern, html, re.I | re.S):
        clean = re.sub(r'<[^>]+>', '', text).strip()
        if clean:
            buttons.append({
                'name': clean,
                'link': link,
                'new_name': clean,
                'new_link': link,
                'del': False
            })
    
    return buttons

def apply_changes(html, buttons):
    """Apply button edits"""
    for b in buttons:
        if b['del']:
            # Remove
            pattern = f'<a[^>]*href=["\'][^"\']*{re.escape(b["link"])}[^"\']*["\'][^>]*>.*?</a>'
            html = re.sub(pattern, '', html, flags=re.I | re.S)
        else:
            # Update
            html = re.sub(
                f'href=["\'][^"\']*{re.escape(b["link"])}[^"\']*["\']',
                f'href="{b["new_link"]}"',
                html,
                flags=re.I
            )
            
            pattern = f'(<a[^>]*href=["\'][^"\']*{re.escape(b["new_link"])}[^"\']*["\'][^>]*>)[^<]*{re.escape(b["name"])}[^<]*(</a>)'
            html = re.sub(pattern, f'\\1{b["new_name"]}\\2', html, flags=re.I)
    
    return html

# ======================== SESSION DATA ========================
sessions = {}

def get_session(user_id):
    if user_id not in sessions:
        sessions[user_id] = {
            'files': {},
            'buttons': [],
            'state': 'start'
        }
    return sessions[user_id]

# ======================== MESSAGE HANDLERS ========================
def handle_msg(msg):
    chat = msg['chat']['id']
    user = msg['from']['id']
    
    # Owner check
    if user != OWNER_ID:
        send_msg(chat, "🚫 Access Denied")
        return
    
    session = get_session(user)
    
    # Commands
    if 'text' in msg:
        text = msg['text']
        
        if text == '/start':
            session['files'] = {}
            session['buttons'] = []
            session['state'] = 'uploading'
            
            send_msg(chat,
                "🚀 **HTML Button Editor**\n\n"
                "📤 Send .html files\n"
                "📋 Type /done when finished"
            )
        
        elif text == '/done':
            if not session['files']:
                send_msg(chat, "⚠️ No files uploaded")
                return
            
            # Process files
            send_msg(chat, "🔄 Processing...")
            
            all_btns = []
            seen = set()
            
            for fname, html in session['files'].items():
                btns = find_buttons(html)
                for b in btns:
                    sig = (b['name'].lower(), b['link'].lower())
                    if sig not in seen:
                        seen.add(sig)
                        all_btns.append(b)
            
            session['buttons'] = all_btns
            session['state'] = 'editing'
            
            show_menu(chat, user)
        
        elif session['state'] == 'edit_name':
            # Update name
            idx = session.get('edit_idx')
            if idx is not None and idx < len(session['buttons']):
                session['buttons'][idx]['new_name'] = text
                send_msg(chat, f"✅ Name updated: {text}")
                session['state'] = 'editing'
                show_menu(chat, user)
        
        elif session['state'] == 'edit_link':
            # Update link
            if 't.me' not in text.lower() and 'telegram.me' not in text.lower():
                send_msg(chat, "❌ Invalid Telegram link")
                return
            
            idx = session.get('edit_idx')
            if idx is not None and idx < len(session['buttons']):
                session['buttons'][idx]['new_link'] = text
                send_msg(chat, f"✅ Link updated: {text}")
                session['state'] = 'editing'
                show_menu(chat, user)
        
        elif session['state'] == 'global_link':
            # Global replace
            if 't.me' not in text.lower() and 'telegram.me' not in text.lower():
                send_msg(chat, "❌ Invalid Telegram link")
                return
            
            count = 0
            for b in session['buttons']:
                if not b['del']:
                    b['new_link'] = text
                    count += 1
            
            send_msg(chat, f"✅ Updated {count} buttons")
            session['state'] = 'editing'
            show_menu(chat, user)
    
    # Files
    elif 'document' in msg:
        doc = msg['document']
        
        if not doc['file_name'].lower().endswith(('.html', '.htm')):
            send_msg(chat, "❌ HTML files only")
            return
        
        send_msg(chat, f"⏳ Downloading {doc['file_name']}...")
        
        html = get_file(doc['file_id'])
        if html:
            session['files'][doc['file_name']] = html
            btns = find_buttons(html)
            
            send_msg(chat,
                f"✅ **{doc['file_name']}**\n"
                f"📊 {len(btns)} buttons found\n"
                f"📁 Total: {len(session['files'])} files\n\n"
                f"Send more or /done"
            )
        else:
            send_msg(chat, "❌ Download failed")

def show_menu(chat, user):
    session = get_session(user)
    btns = session['buttons']
    
    kb = []
    
    # Buttons (max 5)
    for i, b in enumerate(btns[:5]):
        status = "🔴" if b['del'] else ("🟡" if b['new_name'] != b['name'] or b['new_link'] != b['link'] else "⚪")
        name = b['new_name'][:20] + ("..." if len(b['new_name']) > 20 else "")
        kb.append([{'text': f"{status} {name}", 'callback_data': f"e_{i}"}])
    
    if len(btns) > 5:
        kb.append([{'text': f"... {len(btns) - 5} more", 'callback_data': 'more'}])
    
    # Actions
    kb.extend([
        [
            {'text': '🔗 Global Link', 'callback_data': 'global'},
            {'text': '✅ Generate', 'callback_data': 'gen'}
        ]
    ])
    
    text = (
        f"🎛️ **Control Panel**\n\n"
        f"📁 Files: {len(session['files'])}\n"
        f"🔗 Buttons: {len(btns)}\n\n"
        f"Choose option:"
    )
    
    send_msg(chat, text, kb)

def handle_callback(cb):
    chat = cb['message']['chat']['id']
    user = cb['from']['id']
    data = cb['data']
    msg_id = cb['message']['message_id']
    
    if user != OWNER_ID:
        return
    
    session = get_session(user)
    
    if data.startswith('e_'):
        # Edit button
        idx = int(data.split('_')[1])
        session['edit_idx'] = idx
        
        b = session['buttons'][idx]
        status = "🗑️ DELETED" if b['del'] else "📋 ACTIVE"
        
        kb = [
            [
                {'text': '✏️ Name', 'callback_data': 'name'},
                {'text': '🔗 Link', 'callback_data': 'link'}
            ],
            [{'text': '🗑️ Toggle Delete', 'callback_data': 'del'}],
            [{'text': '⬅️ Back', 'callback_data': 'back'}]
        ]
        
        edit_msg(chat, msg_id,
            f"🔘 **Button Editor**\n\n"
            f"Status: {status}\n"
            f"Name: `{b['new_name']}`\n"
            f"Link: `{b['new_link']}`\n\n"
            f"Choose action:",
            kb
        )
    
    elif data == 'name':
        session['state'] = 'edit_name'
        edit_msg(chat, msg_id, "✏️ Send new button name:")
    
    elif data == 'link':
        session['state'] = 'edit_link'
        edit_msg(chat, msg_id, "🔗 Send new Telegram link:")
    
    elif data == 'del':
        idx = session.get('edit_idx')
        if idx is not None:
            b = session['buttons'][idx]
            b['del'] = not b['del']
            send_msg(chat, f"✅ Button {'deleted' if b['del'] else 'restored'}")
            show_menu(chat, user)
    
    elif data == 'global':
        session['state'] = 'global_link'
        edit_msg(chat, msg_id, "🔗 Send new link for ALL buttons:")
    
    elif data == 'gen':
        # Generate files
        send_msg(chat, "⚡ Generating...")
        
        files = session['files']
        btns = session['buttons']
        
        for fname, html in files.items():
            new_html = apply_changes(html, btns)
            
            base = fname.replace('.html', '').replace('.htm', '')
            new_name = f"{base}{RENAME_TAG}.html"
            
            send_doc(chat, new_name, new_html)
        
        edited = len([b for b in btns if b['new_name'] != b['name'] or b['new_link'] != b['link']])
        deleted = len([b for b in btns if b['del']])
        
        send_msg(chat,
            f"🎉 **Done!**\n\n"
            f"📊 Summary:\n"
            f"• Files: {len(files)}\n"
            f"• Edited: {edited}\n"
            f"• Deleted: {deleted}\n\n"
            f"/start for new session"
        )
        
        # Clear
        sessions[user] = {'files': {}, 'buttons': [], 'state': 'start'}
    
    elif data == 'back':
        show_menu(chat, user)

# ======================== MAIN LOOP ========================
def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("❌ Set BOT_TOKEN!")
        return
    
    if OWNER_ID == 0:
        print("❌ Set OWNER_ID!")
        return
    
    print("Starting health server...")
    Thread(target=health_server, daemon=True).start()
    
    print("🤖 Bot ready!")
    
    offset = 0
    while True:
        try:
            result = api_call('getUpdates', {'offset': offset, 'timeout': 30})
            
            if result and result.get('ok'):
                for upd in result.get('result', []):
                    try:
                        if 'message' in upd:
                            handle_msg(upd['message'])
                        elif 'callback_query' in upd:
                            handle_callback(upd['callback_query'])
                    except Exception as e:
                        print(f"Handler error: {e}")
                    
                    offset = upd['update_id'] + 1
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Loop error: {e}")
            import time
            time.sleep(3)

if __name__ == '__main__':
    main()
