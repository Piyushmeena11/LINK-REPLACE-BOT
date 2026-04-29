import os
import logging
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

logger.info(f"Token: {'OK' if BOT_TOKEN else 'MISSING'}")
logger.info(f"Owner: {OWNER_ID}")

# Health Check
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, *args): pass

def health_server():
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    logger.info(f"Health: {port}")
    server.serve_forever()

# Simple Bot
async def start(update: Update, context):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Not authorized")
        return
    await update.message.reply_text("🚀 Bot works! Send /test")

async def test(update: Update, context):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text("✅ Test successful!")

def main():
    if not BOT_TOKEN:
        logger.error("NO TOKEN")
        return
    
    # Health thread
    Thread(target=health_server, daemon=True).start()
    
    # Bot
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('test', test))
    
    logger.info("🚀 STARTING...")
    app.run_polling()

if __name__ == '__main__':
    from telegram.ext import CommandHandler
    main()
