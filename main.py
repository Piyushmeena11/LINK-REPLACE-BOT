import os
import re
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler
)

# ======================== CONFIG ========================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Debug environment variables
logger.info("=== ENVIRONMENT CHECK ===")
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID_STR = os.getenv("OWNER_ID", "0")
RENAME_TAG = os.getenv("RENAME_TAG", "_edited")

logger.info(f"BOT_TOKEN: {'SET' if BOT_TOKEN else 'MISSING'}")
logger.info(f"OWNER_ID: {OWNER_ID_STR}")
logger.info(f"RENAME_TAG: {RENAME_TAG}")

try:
    OWNER_ID = int(OWNER_ID_STR)
except ValueError:
    logger.error(f"Invalid OWNER_ID: {OWNER_ID_STR}")
    sys.exit(1)

if not BOT_TOKEN:
    logger.error("BOT_TOKEN is missing!")
    sys.exit(1)

if OWNER_ID == 0:
    logger.error("OWNER_ID is not set or invalid!")
    sys.exit(1)

logger.info("=== ENVIRONMENT CHECK PASSED ===")

# Conversation states
COLLECTING_FILES, EDITING = range(2)
SESSION_TIMEOUT = timedelta(minutes=10)

# ======================== HEALTH CHECK SERVER ========================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot is running!')
    
    def log_message(self, format, *args):
        pass

def run_health_server():
    try:
        port = int(os.getenv('PORT', 10000))
        server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
        logger.info(f"🌐 Health check server starting on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server error: {e}")

# ======================== SECURITY ========================
def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != OWNER_ID:
            await update.message.reply_text(
                "🚫 Sorry, you're not authorized to use this bot."
            )
            logger.warning(f"Unauthorized access attempt by user {user_id}")
            return ConversationHandler.END
        return await func(update, context)
    return wrapper

# ======================== UTILITIES ========================
def extract_telegram_links(html_content: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(html_content, 'html.parser')
    links = []
    seen = set()
    
    telegram_pattern = re.compile(r'(https?://)?(t\.me|telegram\.me)/\S+', re.IGNORECASE)
    
    for tag in soup.find_all(['a', 'button']):
        href = tag.get('href', '')
        text = tag.get_text(strip=True) or 'Unnamed Button'
        
        if telegram_pattern.search(href):
            link = href if href.startswith('http') else f'https://{href}'
            key = (text, link)
            if key not in seen:
                seen.add(key)
                links.append(key)
    
    return links[:5]

def validate_telegram_link(link: str) -> bool:
    try:
        parsed = urlparse(link)
        return parsed.netloc in ['t.me', 'telegram.me', 'www.t.me', 'www.telegram.me']
    except:
        return False

def replace_links_in_html(html_content: str, old_link: str, new_text: str, new_link: str) -> str:
    soup = BeautifulSoup(html_content, 'html.parser')
    
    for tag in soup.find_all(['a', 'button']):
        href = tag.get('href', '')
        if old_link in href or href in old_link:
            tag.string = new_text
            tag['href'] = new_link
    
    return str(soup)

def check_session_timeout(context: ContextTypes.DEFAULT_TYPE) -> bool:
    if 'last_activity' not in context.user_data:
        return True
    
    last_activity = context.user_data['last_activity']
    if datetime.now() - last_activity > SESSION_TIMEOUT:
        return True
    
    context.user_data['last_activity'] = datetime.now()
    return False

# ======================== BOT COMMANDS ========================
@owner_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['files'] = []
    context.user_data['last_activity'] = datetime.now()
    
    await update.message.reply_text(
        "🚀 **HTML Button Editor Bot**\n\n"
        "📤 Send me HTML file(s) containing Telegram links.\n"
        "✅ When done, type /done to start editing.\n"
        "❓ Need help? Type /help",
        parse_mode='Markdown'
    )
    return COLLECTING_FILES

@owner_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📘 **Bot Usage Guide**

1️⃣ Send HTML files with Telegram buttons
2️⃣ Type /done when all files are uploaded
3️⃣ Click buttons to edit Name or Link
4️⃣ Click ✅ Done to download edited files

**Commands:**
/start - Start new session
/help - Show this guide
/cancel - Cancel current session

**Features:**
• Max 5 buttons per file
• Duplicate detection
• Link validation
• 10-min session timeout
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

@owner_only
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Session cancelled. Type /start to begin again.")
    return ConversationHandler.END

# ======================== FILE HANDLING ========================
@owner_only
async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if check_session_timeout(context):
        await update.message.reply_text("⏱ Session expired. Please /start again.")
        return ConversationHandler.END
    
    file = await update.message.document.get_file()
    
    if not update.message.document.file_name.endswith('.html'):
        await update.message.reply_text("⚠️ Please send only HTML files.")
        return COLLECTING_FILES
    
    file_content = await file.download_as_bytearray()
    html_content = file_content.decode('utf-8')
    
    links = extract_telegram_links(html_content)
    
    if not links:
        await update.message.reply_text(
            f"⚠️ No Telegram links found in {update.message.document.file_name}"
        )
        return COLLECTING_FILES
    
    context.user_data['files'].append({
        'name': update.message.document.file_name,
        'content': html_content,
        'links': links,
        'edited_links': {i: {'text': text, 'link': link} for i, (text, link) in enumerate(links)}
    })
    
    await update.message.reply_text(
        f"✅ Received: **{update.message.document.file_name}**\n"
        f"🔗 Found {len(links)} Telegram button(s)\n\n"
        f"Send more files or type /done to edit.",
        parse_mode='Markdown'
    )
    return COLLECTING_FILES

@owner_only
async def done_collecting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if check_session_timeout(context):
        await update.message.reply_text("⏱ Session expired. Please /start again.")
        return ConversationHandler.END
    
    if not context.user_data.get('files'):
        await update.message.reply_text("⚠️ No files uploaded. Please send HTML files first.")
        return COLLECTING_FILES
    
    context.user_data['current_file'] = 0
    context.user_data['edit_count'] = 0
    
    await show_file_buttons(update, context)
    return EDITING

async def show_file_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_idx = context.user_data['current_file']
    files = context.user_data['files']
    
    if file_idx >= len(files):
        await finalize_editing(update, context)
        return ConversationHandler.END
    
    current_file = files[file_idx]
    keyboard = []
    
    for i, (text, link) in enumerate(current_file['links']):
        edited = current_file['edited_links'][i]
        status = "✏️" if edited != {'text': text, 'link': link} else "⚪️"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} {edited['text'][:30]}",
                callback_data=f"select_{i}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("✅ Done Editing", callback_data="finalize")
    ])
    
    message_text = (
        f"📄 **File {file_idx + 1}/{len(files)}:** {current_file['name']}\n"
        f"🔘 Select button to edit:\n"
        f"✏️ = Modified | ⚪️ = Original"
    )
    
    if update.callback_query:
        await update.callback_query.message.edit_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

# ======================== BUTTON EDITING ========================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if check_session_timeout(context):
        await query.message.edit_text("⏱ Session expired. Please /start again.")
        return ConversationHandler.END
    
    data = query.data
    
    if data.startswith("select_"):
        button_idx = int(data.split("_")[1])
        await show_edit_options(update, context, button_idx)
    elif data.startswith("edit_name_"):
        button_idx = int(data.split("_")[2])
        context.user_data['editing_button'] = button_idx
        context.user_data['editing_field'] = 'name'
        await query.message.edit_text("✏️ Send new button name:")
    elif data.startswith("edit_link_"):
        button_idx = int(data.split("_")[2])
        context.user_data['editing_button'] = button_idx
        context.user_data['editing_field'] = 'link'
        await query.message.edit_text("🔗 Send new Telegram link:")
    elif data == "back":
        await show_file_buttons(update, context)
    elif data == "finalize":
        await confirm_finalize(update, context)
    elif data == "confirm_yes":
        await finalize_editing(update, context)
        return ConversationHandler.END
    elif data == "confirm_no":
        await show_file_buttons(update, context)
    
    return EDITING

async def show_edit_options(update: Update, context: ContextTypes.DEFAULT_TYPE, button_idx: int):
    file_idx = context.user_data['current_file']
    current_file = context.user_data['files'][file_idx]
    edited = current_file['edited_links'][button_idx]
    
    keyboard = [
        [InlineKeyboardButton("✏️ Edit Name", callback_data=f"edit_name_{button_idx}")],
        [InlineKeyboardButton("🔗 Edit Link", callback_data=f"edit_link_{button_idx}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")]
    ]
    
    await update.callback_query.message.edit_text(
        f"**Current Button:**\n"
        f"📝 Name: {edited['text']}\n"
        f"🔗 Link: {edited['link']}\n\n"
        f"What do you want to edit?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def 
