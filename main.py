import os
import io
import re
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import json
from datetime import datetime

# ======================== CONFIG ========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
RENAME_TAG = os.getenv("RENAME_TAG", "_edited")

print(f"🚀 Advanced HTML Editor Bot")
print(f"Owner: {OWNER_ID}, Tag: {RENAME_TAG}")

# ======================== HEALTH SERVER ========================
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        html = f"""
        <html><body style="font-family:Arial;text-align:center;padding:50px">
        <h1>🤖 HTML Button Editor Bot</h1>
        <h2 style="color:green">✅ ACTIVE</h2>
        <p><strong>Owner:</strong> {OWNER_ID}</p>
        <p><strong>Features:</strong> All Advanced Features Active</p>
        </body></html>
        """
        self.wfile.write(html.encode())
    def log_message(self, *args): pass

def health_server():
    HTTPServer(('0.0.0.0', int(os.getenv('PORT', 10000))), Health).serve_forever()

# ======================== TELEGRAM API ========================
def api_call(method, data=None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
        req = Request(url, urlencode(data).encode() if data else None)
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

def send_doc(chat_id, filename, content, caption=""):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        boundary = '----Boundary7MA4YWxk'
        
        parts = [
            f'--{boundary}\r\n',
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n',
        ]
        
        if caption:
            parts.extend([
                f'--{boundary}\r\n',
                f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n',
            ])
        
        parts.extend([
            f'--{boundary}\r\n',
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n',
            f'Content-Type: text/html\r\n\r\n',
            content,
            f'\r\n--{boundary}--\r\n'
        ])
        
        body = ''.join(parts).encode('utf-8')
        
        req = Request(url, body)
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"Doc error: {e}")
        return None

def get_file(file_id):
    try:
        result = api_call('getFile', {'file_id': file_id})
        if not result or not result.get('ok'):
            return None
        
        path = result['result']['file_path']
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"
        
        with urlopen(url, timeout=30) as r:
            return r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"File error: {e}")
        return None

# ======================== HTML PROCESSING ========================
def find_buttons(html):
    """Extract Telegram buttons from HTML"""
    buttons = []
    pattern = r'<a[^>]*href=["\']([^"\']*(?:t\.me|telegram\.me)[^"\']*)["\'][^>]*>(.*?)</a>'
    
    seen = set()
    for link, text in re.findall(pattern, html, re.I | re.S):
        clean = re.sub(r'<[^>]+>', '', text).strip()
        clean = re.sub(r'\s+', ' ', clean)
        
        if clean and len(clean) > 1:
            # Normalize link
            if not link.startswith('http'):
                link = 'https://' + link.lstrip('/')
            
            sig = (clean.lower(), link.lower())
            if sig not in seen:
                seen.add(sig)
                buttons.append({
                    'orig_txt': clean,
                    'orig_hr': link,
                    'new_txt': clean,
                    'new_hr': link,
                    'delete': False
                })
    
    return buttons

def patch_html(html, buttons, text_map, new_title):
    """Apply all modifications to HTML"""
    # 1. Update Page Title
    if new_title:
        if '<title>' in html:
            html = re.sub(r'<title>.*?</title>', f'<title>{new_title}</title>', html, flags=re.I | re.S)
        elif '<head>' in html:
            html = re.sub(r'<head>', f'<head>\n<title>{new_title}</title>', html, flags=re.I)
        else:
            html = f'<html><head><title>{new_title}</title></head><body>{html}</body></html>'
    
    # 2. Apply Button Changes
    for b in buttons:
        old_link_esc = re.escape(b['orig_hr'])
        old_txt_esc = re.escape(b['orig_txt'])
        
        if b['delete']:
            # Remove button
            pattern = f'<a[^>]*href=["\'][^"\']*{old_link_esc}[^"\']*["\'][^>]*>.*?</a>'
            html = re.sub(pattern, '', html, flags=re.I | re.S)
        else:
            # Update link
            html = re.sub(
                f'href=["\'][^"\']*{old_link_esc}[^"\']*["\']',
                f'href="{b["new_hr"]}"',
                html,
                flags=re.I
            )
            
            # Update text
            pattern = f'(<a[^>]*href=["\'][^"\']*{re.escape(b["new_hr"])}[^"\']*["\'][^>]*>)[^<]*{old_txt_esc}[^<]*(</a>)'
            html = re.sub(pattern, f'\\1{b["new_txt"]}\\2', html, flags=re.I)
    
    # 3. Apply Custom Text Replacements (with button protection)
    for old_txt, new_txt in text_map.items():
        # Find and replace, but skip inside Telegram buttons
        parts = re.split(r'(<a[^>]*href=["\'][^"\']*(?:t\.me|telegram\.me)[^"\']*["\'][^>]*>.*?</a>)', html, flags=re.I | re.S)
        
        for i in range(len(parts)):
            # Only replace in non-button parts (even indices)
            if i % 2 == 0:
                parts[i] = parts[i].replace(old_txt, new_txt)
        
        html = ''.join(parts)
    
    return html

# ======================== SESSION DATA ========================
sessions = {}

def get_session(user_id):
    if user_id not in sessions:
        sessions[user_id] = {
            'files': {},           # filename -> html_content
            'btns': [],            # deduplicated buttons
            'text_map': {},        # old_text -> new_text
            'custom_filename': None,
            'custom_title': None,
            'state': 'start',
            'edit_idx': None
        }
    return sessions[user_id]

# ======================== UI HELPERS ========================
def create_main_menu(session):
    """Create main menu keyboard"""
    btns = session['btns']
    kb = []
    
    # Show first 5 buttons
    for i, b in enumerate(btns[:5]):
        if b['delete']:
            status = "🔴"
            name = f"[DELETED] {b['orig_txt'][:15]}"
        elif b['new_txt'] != b['orig_txt'] or b['new_hr'] != b['orig_hr']:
            status = "🟡"
            name = b['new_txt'][:15]
        else:
            status = "⚪"
            name = b['orig_txt'][:15]
        
        if len(name) > 15:
            name += "..."
        
        kb.append([{'text': f"{status} {name}", 'callback_data': f"b_{i}"}])
    
    if len(btns) > 5:
        kb.append([{'text': f"... and {len(btns) - 5} more buttons", 'callback_data': 'show_all'}])
    
    # Global actions
    kb.append([
        {'text': '🔗 All Links Replace', 'callback_data': 'global_replace'},
        {'text': '🔍 Replace Custom Text', 'callback_data': 'find_text'}
    ])
    
    # Branding
    title_txt = f"Title: {session['custom_title'][:10]}..." if session['custom_title'] else "🏷️ Edit Page Title"
    fname_txt = f"File: {session['custom_filename'][:10]}..." if session['custom_filename'] else "📁 Rename File"
    
    kb.append([
        {'text': title_txt, 'callback_data': 'change_title'},
        {'text': fname_txt, 'callback_data': 'change_filename'}
    ])
    
    # Summary
    edited = len([b for b in btns if (b['new_txt'] != b['orig_txt'] or b['new_hr'] != b['orig_hr']) and not b['delete']])
    deleted = len([b for b in btns if b['delete']])
    texts = len(session['text_map'])
    
    kb.append([{'text': f"📊 Changes: {edited}E {deleted}D {texts}T", 'callback_data': 'summary'}])
    
    # Final actions
    kb.append([
        {'text': '🔄 Reset', 'callback_data': 'reset'},
        {'text': '✅ FINISH & GENERATE', 'callback_data': 'final'}
    ])
    
    return kb

# ======================== MESSAGE HANDLERS ========================
def handle_msg(msg):
    chat = msg['chat']['id']
    user = msg['from']['id']
    
    if user != OWNER_ID:
        send_msg(chat, "🚫 Access Denied")
        return
    
    session = get_session(user)
    
    # Commands
    if 'text' in msg:
        text = msg['text'].strip()
        
        if text == '/start':
            session['files'] = {}
            session['btns'] = []
            session['text_map'] = {}
            session['custom_filename'] = None
            session['custom_title'] = None
            session['state'] = 'uploading'
            
            send_msg(chat,
                "🚀 **Advanced HTML Button Editor**\n\n"
                "🎯 **Features:**\n"
                "• 🟢 Interactive editing\n"
                "• 🔵 Batch processing\n"
                "• 🟡 Smart deduplication\n"
                "• 🔴 Custom branding\n\n"
                "📤 **Send .html files**\n"
                "📋 **Type /done when ready**"
            )
        
        elif text == '/help':
            send_msg(chat,
                "📘 **Complete Guide:**\n\n"
                "**1. Individual Editing**\n"
                "• Edit button names\n"
                "• Change links\n"
                "• Delete buttons\n\n"
                "**2. Global Actions**\n"
                "• Replace all links at once\n"
                "• Custom text find & replace\n\n"
                "**3. Branding**\n"
                "• Set page title\n"
                "• Custom filename\n\n"
                "**4. Smart Features**\n"
                "• Auto-deduplication\n"
                "• Button name protection\n"
                "• Summary reports"
            )
        
        elif text == '/done':
            if not session['files']:
                send_msg(chat, "⚠️ No files uploaded")
                return
            
            send_msg(chat, "🔄 Processing files...")
            
            # Extract and deduplicate
            all_btns = []
            seen = set()
            
            for fname, html in session['files'].items():
                btns = find_buttons(html)
                for b in btns:
                    sig = (b['orig_txt'].lower(), b['orig_hr'].lower())
                    if sig not in seen:
                        seen.add(sig)
                        all_btns.append(b)
            
            session['btns'] = all_btns
            session['state'] = 'editing'
            
            send_msg(chat,
                f"✅ **Processing complete!**\n"
                f"📁 Files: {len(session['files'])}\n"
                f"🔗 Buttons: {len(all_btns)}"
            )
            
            show_main_menu(chat, user)
        
        # Handle various text inputs
        elif session['state'] == 'edit_name':
            idx = session.get('edit_idx')
            if idx is not None and idx < len(session['btns']):
                session['btns'][idx]['new_txt'] = text
                send_msg(chat, f"✅ Name updated: `{text}`")
                session['state'] = 'editing'
                show_main_menu(chat, user)
        
        elif session['state'] == 'edit_link':
            if 't.me' not in text.lower() and 'telegram.me' not in text.lower():
                send_msg(chat, "❌ Invalid Telegram link")
                return
            
            idx = session.get('edit_idx')
            if idx is not None and idx < len(session['btns']):
                session['btns'][idx]['new_hr'] = text
                send_msg(chat, f"✅ Link updated: `{text}`")
                session['state'] = 'editing'
                show_main_menu(chat, user)
        
        elif session['state'] == 'global_link':
            if 't.me' not in text.lower() and 'telegram.me' not in text.lower():
                send_msg(chat, "❌ Invalid Telegram link")
                return
            
            count = 0
            for b in session['btns']:
                if not b['delete']:
                    b['new_hr'] = text
                    count += 1
            
            send_msg(chat, f"✅ Updated {count} buttons to:\n`{text}`")
            session['state'] = 'editing'
            show_main_menu(chat, user)
        
        elif session['state'] == 'find_text':
            session['temp_old'] = text
            session['state'] = 'replace_text'
            send_msg(chat, f"🔍 Find: `{text}`\n\n📝 Now send replacement text:")
        
        elif session['state'] == 'replace_text':
            old = session.pop('temp_old', '')
            if old:
                session['text_map'][old] = text
                send_msg(chat,
                    f"✅ **Text replacement added:**\n"
                    f"📍 Find: `{old}`\n"
                    f"📍 Replace: `{text}`\n\n"
                    f"🛡️ Button names are protected"
                )
            session['state'] = 'editing'
            show_main_menu(chat, user)
        
        elif session['state'] == 'custom_title':
            session['custom_title'] = text
            send_msg(chat, f"✅ Page title set: `{text}`")
            session['state'] = 'editing'
            show_main_menu(chat, user)
        
        elif session['state'] == 'custom_filename':
            # Clean filename
            fname = re.sub(r'[^\w\-_]', '', text.replace(' ', '_'))
            session['custom_filename'] = fname
            send_msg(chat, f"✅ Filename set: `{fname}{RENAME_TAG}.html`")
            session['state'] = 'editing'
            show_main_menu(chat, user)
    
    # Files
    elif 'document' in msg:
        doc = msg['document']
        
        if not doc['file_name'].lower().endswith(('.html', '.htm')):
            send_msg(chat, "❌ HTML files only")
            return
        
        send_msg(chat, f"⏳ Downloading `{doc['file_name']}`...")
        
        html = get_file(doc['file_id'])
        if html:
            session['files'][doc['file_name']] = html
            btns = find_buttons(html)
            
            send_msg(chat,
                f"✅ **{doc['file_name']}**\n"
                f"📊 Found: {len(btns)} buttons\n"
                f"📁 Total: {len(session['files'])} files\n\n"
                f"Send more or /done"
            )
        else:
            send_msg(chat, "❌ Download failed. Try again.")

def show_main_menu(chat, user):
    session = get_session(user)
    
    text = (
        f"🎛️ **HTML Editor Control Panel**\n\n"
        f"📋 **Current Session:**\n"
        f"• Files: {len(session['files'])}\n"
        f"• Buttons: {len(session['btns'])}\n\n"
        f"🎯 **Choose option:**"
    )
    
    kb = create_main_menu(session)
    send_msg(chat, text, kb)

def handle_callback(cb):
    chat = cb['message']['chat']['id']
    user = cb['from']['id']
    data = cb['data']
    msg_id = cb['message']['message_id']
    
    if user != OWNER_ID:
        return
    
    session = get_session(user)
    
    if data.startswith('b_'):
        # Edit button
        idx = int(data.split('_')[1])
        session['edit_idx'] = idx
        
        b = session['btns'][idx]
        status = "🗑️ DELETED" if b['delete'] else ("✏️ MODIFIED" if b['new_txt'] != b['orig_txt'] or b['new_hr'] != b['orig_hr'] else "📋 ORIGINAL")
        
        kb = [
            [
                {'text': '✏️ Edit Name', 'callback_data': 'edit_name'},
                {'text': '🔗 Edit Link', 'callback_data': 'edit_link'}
            ],
            [{'text': '🗑️ Toggle Delete', 'callback_data': 'delete_btn'}],
            [{'text': '⬅️ Back', 'callback_data': 'back'}]
        ]
        
        edit_msg(chat, msg_id,
            f"🔘 **Button Editor**\n\n"
            f"**Status:** {status}\n"
            f"**Name:** `{b['new_txt']}`\n"
            f"**Link:** `{b['new_hr']}`\n\n"
            f"🎯 **Choose action:**",
            kb
        )
    
    elif data == 'edit_name':
        session['state'] = 'edit_name'
        edit_msg(chat, msg_id, "✏️ **Send new button name:**")
    
    elif data == 'edit_link':
        session['state'] = 'edit_link'
        edit_msg(chat, msg_id, "🔗 **Send new Telegram link:**")
    
    elif data == 'delete_btn':
        idx = session.get('edit_idx')
        if idx is not None:
            b = session['btns'][idx]
            b['delete'] = not b['delete']
            action = "marked for deletion" if b['delete'] else "restored"
            send_msg(chat, f"✅ Button {action}")
            show_main_menu(chat, user)
    
    elif data == 'global_replace':
        session['state'] = 'global_link'
        edit_msg(chat, msg_id,
            "🔗 **Global Link Replacement**\n\n"
            "⚠️ This will replace ALL Telegram links\n\n"
            "📝 Send the new link:"
        )
    
    elif data == 'find_text':
        session['state'] = 'find_text'
        edit_msg(chat, msg_id,
            "🔍 **Custom Text Replacement**\n\n"
            "🛡️ Button names are protected\n\n"
            "📝 Send text to find:"
        )
    
    elif data == 'change_title':
        session['state'] = 'custom_title'
        edit_msg(chat, msg_id,
            "🏷️ **Edit Page Title**\n\n"
            "This will be the browser tab title\n\n"
            "📝 Send new title:"
        )
    
    elif data == 'change_filename':
        session['state'] = 'custom_filename'
        edit_msg(chat, msg_id,
            f"📁 **Custom Filename**\n\n"
            f"Suffix `{RENAME_TAG}` will be added\n\n"
            f"📝 Send filename (without .html):"
        )
    
    elif data == 'reset':
        # Reset all changes
        for b in session['btns']:
            b['new_txt'] = b['orig_txt']
            b['new_hr'] = b['orig_hr']
            b['delete'] = False
        
        session['text_map'] = {}
        session['custom_filename'] = None
        session['custom_title'] = None
        
        send_msg(chat, "♻️ **All changes reset**")
        show_main_menu(chat, user)
    
    elif data == 'summary':
        # Show detailed summary
        btns = session['btns']
        edited = len([b for b in btns if (b['new_txt'] != b['orig_txt'] or b['new_hr'] != b['orig_hr']) and not b['delete']])
        deleted = len([b for b in btns if b['delete']])
        
        summary = (
            f"📊 **Detailed Summary**\n\n"
            f"📁 **Files:** {len(session['files'])}\n"
            f"🔗 **Total Buttons:** {len(btns)}\n"
            f"✏️ **Edited:** {edited}\n"
            f"🗑️ **Deleted:** {deleted}\n"
            f"📝 **Text Replacements:** {len(session['text_map'])}\n"
        )
        
        if session['custom_title']:
            summary += f"🏷️ **Title:** {session['custom_title'][:30]}\n"
        
        if session['custom_filename']:
            summary += f"📁 **Filename:** {session['custom_filename']}\n"
        
        kb = [[{'text': '⬅️ Back', 'callback_data': 'back'}]]
        edit_msg(chat, msg_id, summary, kb)
    
    elif data == 'final':
        # Show confirmation
        btns = session['btns']
        edited = len([b for b in btns if (b['new_txt'] != b['orig_txt'] or b['new_hr'] != b['orig_hr']) and not b['delete']])
        deleted = len([b for b in btns if b['delete']])
        
        confirm = (
            f"📊 **Final Generation Summary**\n\n"
            f"📁 Files: {len(session['files'])}\n"
            f"✏️ Buttons Edited: {edited}\n"
            f"🗑️ Buttons Deleted: {deleted}\n"
            f"📝 Text Replaced: {len(session['text_map'])}\n"
            f"🏷️ Custom Title: {'Yes' if session['custom_title'] else 'No'}\n"
            f"📁 Custom Filename: {'Yes' if session['custom_filename'] else 'No'}\n\n"
            f"🚀 **Ready to generate?**"
        )
        
        kb = [
            [
                {'text': '✅ Yes, Generate!', 'callback_data': 'confirm_yes'},
                {'text': '❌ No', 'callback_data': 'confirm_no'}
            ]
        ]
        
        edit_msg(chat, msg_id, confirm, kb)
    
    elif data == 'confirm_yes':
        # Generate files
        edit_msg(chat, msg_id, "⚡ **Generating files...**")
        
        files = session['files']
        btns = session['btns']
        text_map = session['text_map']
        custom_title = session['custom_title']
        custom_fname = session['custom_filename']
        
        for i, (orig_name, html) in enumerate(files.items(), 1):
            # Apply all changes
            new_html = patch_html(html, btns, text_map, custom_title)
            
            # Generate filename
            if custom_fname:
                if len(files) > 1:
                    fname = f"{custom_fname}_{i}{RENAME_TAG}.html"
                else:
                    fname = f"{custom_fname}{RENAME_TAG}.html"
            else:
                base = orig_name.replace('.html', '').replace('.htm', '')
                fname = f"{base}{RENAME_TAG}.html"
            
            # Send file
            send_doc(chat, fname, new_html, f"✅ Processed: {orig_name}")
        
        # Final summary
        edited = len([b for b in btns if (b['new_txt'] != b['orig_txt'] or b['new_hr'] != b['orig_hr']) and not b['delete']])
        deleted = len([b for b in btns if b['delete']])
        
        send_msg(chat,
            f"🎉 **Generation Complete!**\n\n"
            f"📊 **Final Stats:**\n"
            f"• Files: {len(files)}\n"
            f"• Edited: {edited}\n"
            f"• Deleted: {deleted}\n"
            f"• Text Replaced: {len(text_map)}\n\n"
            f"💾 **All files ready!**\n\n"
            f"🔄 /start for new session"
        )
        
        # Clear session
        sessions[user] = {
            'files': {}, 'btns': [], 'text_map': {},
            'custom_filename': None, 'custom_title': None,
            'state': 'start', 'edit_idx': None
        }
    
    elif data == 'confirm_no':
        send_msg(chat, "❌ Generation cancelled")
        show_main_menu(chat, user)
    
    elif data == 'back':
        show_main_menu(chat, user)

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
    
    print("🤖 Advanced Bot Ready!")
    print("Features: All Original Features Active")
    
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
            print("Bot stopped")
            break
        except Exception as e:
            print(f"Loop error: {e}")
            import time
            time.sleep(3)

if __name__ == '__main__':
    main()
