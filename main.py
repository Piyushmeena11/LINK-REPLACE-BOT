import os
import re
import logging
import sys
from datetime import datetime, timedelta
from typing import List, Tuple
from urllib.parse import urlparse
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
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID_STR = os.getenv("OWNER_ID", "0")
RENAME_TAG = os.getenv("RENAME_TAG", "_edited")

logger.info(f"BOT_TOKEN: {'SET' if BOT_TOKEN else 'MISSING'}")
logger.info(f"OWNER_ID: {OWNER_ID_STR}")

try:
    OWNER_ID = int(OWNER_ID_STR)
except ValueError:
    logger.error(f"Invalid OWNER_ID: {OWNER_ID_STR}")
    sys.exit(1)

if not BOT_TOKEN or OWNER_ID == 0:
    logger.error("BOT_TOKEN or OWNER_ID missing!")
    sys.exit(1)

# States
COLLECTING_FILES, EDITING = range(2)
SESSION_TIMEOUT = timedelta(minutes=10)

# ======================== HEALTH CHECK ========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot running!')
    
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    logger.info(f"Health server on port {port}")
    server.serve_forever()

# ======================== SECURITY ========================
def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("🚫 Not authorized.")
            return ConversationHandler.END
        return await func(update, context)
    return wrapper

# ======================== UTILITIES ========================
def extract_telegram_links(html_content: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(html_content, 'html.parser')
    links = []
    seen = set()
    pattern = re.compile(r'(https?://)?(t\.me|telegram\.me)/\S+', re.IGNORECASE)
    
    for tag in soup.find_all(['a', 'button']):
        href = tag.get('href', '')
        text = tag.get_text(strip=True) or 'Unnamed Button'
        
        if pattern.search(href):
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

def check_timeout(context: ContextTypes.DEFAULT_TYPE) -> bool:
    if 'last_activity' not in context.user_data:
        return True
    last = context.user_data['last_activity']
    if datetime.now() - last > SESSION_TIMEOUT:
        return True
    context.user_data['last_activity'] = datetime.now()
    return False

# ======================== COMMANDS ========================
@owner_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['files'] = []
    context.user_data['last_activity'] = datetime.now()
    
    await update.message.reply_text(
        "🚀 **HTML Button Editor Bot**\n\n"
        "📤 Send HTML files with Telegram links.\n"
        "✅ Type /done when finished.\n"
        "❓ Type /help for guide.",
        parse_mode='Markdown'
    )
    return COLLECTING_FILES

@owner_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
📘 **Usage Guide**

1️⃣ Send HTML files
2️⃣ Type /done to edit
3️⃣ Click buttons to edit
4️⃣ Download edited files

**Commands:**
/start - New session
/help - This guide
/cancel - Cancel session
"""
    await update.message.reply_text(text, parse_mode='Markdown')

@owner_only
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Cancelled. /start to begin again.")
    return ConversationHandler.END

# ======================== FILE HANDLING ========================
@owner_only
async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if check_timeout(context):
        await update.message.reply_text("⏱ Session expired. /start again.")
        return ConversationHandler.END
    
    file = await update.message.document.get_file()
    
    if not update.message.document.file_name.endswith('.html'):
        await update.message.reply_text("⚠️ HTML files only.")
        return COLLECTING_FILES
    
    content = await file.download_as_bytearray()
    html = content.decode('utf-8')
    links = extract_telegram_links(html)
    
    if not links:
        await update.message.reply_text(f"⚠️ No Telegram links in {update.message.document.file_name}")
        return COLLECTING_FILES
    
    context.user_data['files'].append({
        'name': update.message.document.file_name,
        'content': html,
        'links': links,
        'edited_links': {i: {'text': text, 'link': link} for i, (text, link) in enumerate(links)}
    })
    
    await update.message.reply_text(
        f"✅ **{update.message.document.file_name}**\n"
        f"🔗 Found {len(links)} buttons\n\n"
        f"Send more or /done to edit.",
        parse_mode='Markdown'
    )
    return COLLECTING_FILES

@owner_only
async def done_collecting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if check_timeout(context):
        await update.message.reply_text("⏱ Session expired. /start again.")
        return ConversationHandler.END
    
    if not context.user_data.get('files'):
        await update.message.reply_text("⚠️ No files. Send HTML files first.")
        return COLLECTING_FILES
    
    context.user_data['current_file'] = 0
    context.user_data['edit_count'] = 0
    await show_buttons(update, context)
    return EDITING

async def show_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_idx = context.user_data['current_file']
    files = context.user_data['files']
    
    if file_idx >= len(files):
        await finalize(update, context)
        return ConversationHandler.END
    
    current = files[file_idx]
    keyboard = []
    
    for i, (text, link) in enumerate(current['links']):
        edited = current['edited_links'][i]
        status = "✏️" if edited != {'text': text, 'link': link} else "⚪️"
        keyboard.append([
            InlineKeyboardButton(f"{status} {edited['text'][:30]}", callback_data=f"select_{i}")
        ])
    
    keyboard.append([InlineKeyboardButton("✅ Done", callback_data="finalize")])
    
    text = (
        f"📄 **File {file_idx + 1}/{len(files)}:** {current['name']}\n"
        f"🔘 Select button to edit:\n"
        f"✏️ = Modified | ⚪️ = Original"
    )
    
    markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')

# ======================== EDITING ========================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if check_timeout(context):
        await query.message.edit_text("⏱ Session expired. /start again.")
        return ConversationHandler.END
    
    data = query.data
    
    if data.startswith("select_"):
        idx = int(data.split("_")[1])
        await show_edit_options(update, context, idx)
    elif data.startswith("edit_name_"):
        idx = int(data.split("_")[2])
        context.user_data['editing_button'] = idx
        context.user_data['editing_field'] = 'name'
        await query.message.edit_text("✏️ Send new button name:")
    elif data.startswith("edit_link_"):
        idx = int(data.split("_")[2])
        context.user_data['editing_button'] = idx
        context.user_data['editing_field'] = 'link'
        await query.message.edit_text("🔗 Send new Telegram link:")
    elif data == "back":
        await show_buttons(update, context)
    elif data == "finalize":
        await confirm_finalize(update, context)
    elif data == "confirm_yes":
        await finalize(update, context)
        return ConversationHandler.END
    elif data == "confirm_no":
        await show_buttons(update, context)
    
    return EDITING

async def show_edit_options(update: Update, context: ContextTypes.DEFAULT_TYPE, idx: int):
    file_idx = context.user_data['current_file']
    current = context.user_data['files'][file_idx]
    edited = current['edited_links'][idx]
    
    keyboard = [
        [InlineKeyboardButton("✏️ Edit Name", callback_data=f"edit_name_{idx}")],
        [InlineKeyboardButton("🔗 Edit Link", callback_data=f"edit_link_{idx}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")]
    ]
    
    await update.callback_query.message.edit_text(
        f"**Current Button:**\n"
        f"📝 Name: {edited['text']}\n"
        f"🔗 Link: {edited['link']}\n\n"
        f"What to edit?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def receive_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if check_timeout(context):
        await update.message.reply_text("⏱ Session expired. /start again.")
        return ConversationHandler.END
    
    if 'editing_button' not in context.user_data:
        return EDITING
    
    file_idx = context.user_data['current_file']
    button_idx = context.user_data['editing_button']
    field = context.user_data['editing_field']
    value = update.message.text.strip()
    
    current = context.user_data['files'][file_idx]
    
    if field == 'name':
        current['edited_links'][button_idx]['text'] = value
        context.user_data['edit_count'] += 1
        await update.message.reply_text(f"✅ Name updated: {value}")
    elif field == 'link':
        if not validate_telegram_link(value):
            await update.message.reply_text("⚠️ Invalid Telegram link!")
            return EDITING
        current['edited_links'][button_idx]['link'] = value
        context.user_data['edit_count'] += 1
        await update.message.reply_text(f"✅ Link updated: {value}")
    
    del context.user_data['editing_button']
    del context.user_data['editing_field']
    await show_buttons(update, context)
    return EDITING

async def confirm_finalize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = context.user_data.get('edit_count', 0)
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes", callback_data="confirm_yes"),
            InlineKeyboardButton("❌ No", callback_data="confirm_no")
        ]
    ]
    
    await update.callback_query.message.edit_text(
        f"📊 **Summary:**\n✏️ {count} edits made\n\nProceed?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def finalize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = context.user_data['files']
    
    if update.callback_query:
        await update.callback_query.message.edit_text("⏳ Generating files...")
    
    for file_data in files:
        html = file_data['content']
        
        for i, (orig_text, orig_link) in enumerate(file_data['links']):
            edited = file_data['edited_links'][i]
            html = replace_links_in_html(html, orig_link, edited['text'], edited['link'])
        
        base = os.path.splitext(file_data['name'])[0]
        filename = f"{base}{RENAME_TAG}.html"
        
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=html.encode('utf-8'),
            filename=filename,
            caption=f"✅ {filename}"
        )
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🎉 Done! /start for new session."
    )
    context.user_data.clear()

# ======================== MAIN ========================
def main():
    logger.info("🚀 Starting bot...")
    
    try:
        health_thread = Thread(target=run_health_server, daemon=True)
        health_thread.start()
        
        app = Application.builder().token(BOT_TOKEN).build()
        
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                COLLECTING_FILES: [
                    MessageHandler(filters.Document.ALL, receive_file),
                    CommandHandler('done', done_collecting),
                ],
                EDITING: [
                    CallbackQueryHandler(button_handler),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit),
                ],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            conversation_timeout=600
        )
        
        app.add_handler(conv_handler)
        app.add_handler(CommandHandler('help', help_command))
        
        logger.info("🤖 Bot polling started!")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
