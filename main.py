import os
import asyncio
import json
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.parse import urlencode

# Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

print(f"✅ Token: {'SET' if BOT_TOKEN else 'MISSING'}")
print(f"✅ Owner: {OWNER_ID}")

# Health Check Server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is running!')
    
    def log_message(self, *args):
        pass

def run_health():
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🌐 Health server on port {port}")
    server.serve_forever()

# Telegram Bot Functions
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
        print(f"❌ Send message error: {e}")
        return None

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

def handle_message(message):
    if not message.get('text'):
        return
    
    chat_id = message['chat']['id']
    user_id = message['from']['id']
    text = message['text']
    
    # Owner check
    if user_id != OWNER_ID:
        send_message(chat_id, "🚫 Not authorized")
        return
    
    if text == '/start':
        send_message(chat_id, 
            "🚀 **Bot is working!**\n\n"
            "✅ Authentication: OK\n"
            "✅ Health check: Running\n"
            "✅ Deployment: Successful\n\n"
            "Send /test to verify bot functionality."
        )
    elif text == '/test':
        send_message(chat_id, "✅ Test successful! Bot is fully operational.")
    elif text == '/status':
        send_message(chat_id, f"📊 **Status**\nBot Token: Active\nOwner ID: {OWNER_ID}\nHealth: OK")

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing!")
        return
    
    if OWNER_ID == 0:
        print("❌ OWNER_ID missing!")
        return
    
    print("🚀 Starting bot...")
    
    # Start health server
    health_thread = Thread(target=run_health, daemon=True)
    health_thread.start()
    
    # Bot polling loop
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
            print(f"❌ Bot error: {e}")
            import time
            time.sleep(5)

if __name__ == '__main__':
    main()
