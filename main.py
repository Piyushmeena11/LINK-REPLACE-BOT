import os
import logging
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler

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
        self.wfile.write(b'Bot is running!')
    
    def log_message(self, *args): 
        pass

def health_server():
    try:
        port = int(os.getenv('PORT', 10000))
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        logger.info(f"Health server on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server error: {e}")

# Bot Commands
async def start_command(update: Update, context):
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("🚫 Not authorized")
        return
    
    await update.message.reply_text(
        "🚀 **Bot is working!**\n\n"
        "This is a test version.\n"
        "Send /test to verify functionality.",
        parse_mode='Markdown'
    )

async def test_command(update: Update, context):
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("🚫 Not authorized")
        return
    
    await update.message.reply_text("✅ Test successful! Bot is working perfectly.")

def main():
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN missing!")
        return
    
    if OWNER_ID == 0:
        logger.error("❌ OWNER_ID missing!")
        return
    
    logger.info("🚀 Starting bot...")
    
    # Start health server
    health_thread = Thread(target=health_server, daemon=True)
    health_thread.start()
    
    # Create bot application
    try:
        app = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        app.add_handler(CommandHandler('start', start_command))
        app.add_handler(CommandHandler('test', test_command))
        
        logger.info("🤖 Bot polling started!")
        app.run_polling(allowed_updates=['message'])
        
    except Exception as e:
        logger.error(f"❌ Bot error: {e}")

if __name__ == '__main__':
    main()
