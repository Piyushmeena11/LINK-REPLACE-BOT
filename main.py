import os
import io
import re
import json
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

# ======================== CONFIGURATION ========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
RENAME_TAG = os.getenv("RENAME_TAG", "_edited")

print(f"🚀 Advanced HTML Editor Bot Starting...")
print(f"🔒 Owner ID: {OWNER_ID}")
print(f"🏷️ Rename Tag: {RENAME_TAG}")

# ======================== CONSTANTS ========================
# Conversation States
UPLOADING, SHOWING_MENU, EDITING_NAME_VAL, EDITING_LINK_VAL = range(4)
SEARCH_OLD_TEXT, REPLACE_NEW_TEXT, GLOBAL_LINK_REPLACE = range(4, 7)
EDITING_FILENAME, EDITING_TITLE, CONFIRMING = range(7, 10)

# Patterns
TG_PATTERN = re.compile(r'^(?:https?://)?(?:t\.me|telegram\.(?:me|dog))|^tg://', re.I)
SESSION_TIMEOUT = timedelta(minutes=10)

# Button Colors (Telegram API v6.9+)
COLORS = {
    'primary': '🔵',
    'success': '🟢', 
    'danger': '🔴',
    'warning': '🟡',
    'info': '💙',
    'secondary': '⚪'
}

# ======================== HEALTH CHECK SERVER ========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        status_html = f"""
        <!DOCTYPE html>
        <html><head><title>HTML Editor Bot</title>
        <style>body{{font-family:Arial;text-align:center;padding:50px;background:#f0f8ff}}</style>
        </head><body>
        <h1>🤖 Advanced HTML Editor Bot</h1>
        <h2 style="color: green;">✅ ACTIVE</h2>
        <p><strong>Owner:</strong> {OWNER_ID}</p>
        <p><strong>Features:</strong> Interactive Editing, Batch Processing, Smart UI</p>
        <p><strong>Status:</strong> Ready for HTML files</p>
        <p><strong>Last Check:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body></html>
        """
        self.wfile.write(status_html.encode('utf-8'))
    
    def log_message(self, format, *args):
        pass  # Suppress access logs

def run_health_server():
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🌐 Health check server running on port {port}")
    server.serve_forever()

# ======================== UTILITY FUNCTIONS ========================
def init_user_data(ctx: ContextTypes.DEFAULT_TYPE):
    """Initialize user data structure"""
    if "files" not in ctx.user_data:
        ctx.user_data.update({
            "files": {},
            "btns": [],
            "text_map": {},
            "custom_filename": None,
            "custom_title": None,
            "last_activity": datetime.now(),
            "session_start": datetime.now()
        })

async def owner_only(update: Update) -> bool:
    """Check if user is authorized owner"""
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text(
            "🚫 **Access Denied**\n\nThis is a private bot.\nOnly the owner can use it.",
            parse_mode=ParseMode.MARKDOWN
        )
        return False
    return True

def check_session_timeout(ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if session has expired"""
    last_activity = ctx.user_data.get('last_activity', datetime.now() - SESSION_TIMEOUT)
    if datetime.now() - last_activity > SESSION_TIMEOUT:
        return True
    
    ctx.user_data['last_activity'] = datetime.now()
    return False

def update_activity(ctx: ContextTypes.DEFAULT_TYPE):
    """Update last activity timestamp"""
    ctx.user_data['last_activity'] = datetime.now()

def extract_buttons(html_content: str) -> List[Dict]:
    """Extract Telegram buttons from HTML with enhanced detection"""
    soup = BeautifulSoup(html_content, "html.parser")
    seen, buttons = set(), []
    
    # Enhanced patterns for better detection
    for element in soup.find_all(["a", "button"]):
        href = element.get("href", "")
        onclick = element.get("onclick", "")
        data_url = element.get("data-url", "")
        
        # Check various link sources
        link = href or data_url
        if onclick and "window.open" in onclick:
            # Extract link from onclick
            onclick_match = re.search(r'["\']([^"\']*(?:t\.me|telegram\.me)[^"\']*)["\']', onclick)
            if onclick_match:
                link = onclick_match.group(1)
        
        if TG_PATTERN.match(link):
            text = element.get_text(strip=True) or "Button"
            text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
            
            # Normalize link
            if not link.startswith(('http', 'tg://')):
                link = 'https://' + link.lstrip('/')
            
            signature = (text.lower(), link.lower())
            if signature not in seen:
                seen.add(signature)
                buttons.append({
                    "orig_txt": text,
                    "orig_hr": link,
                    "new_txt": text,
                    "new_hr": link,
                    "delete": False,
                    "element_type": element.name
                })
    
    return buttons

def patch_html(html_content: str, buttons: List[Dict], text_map: Dict[str, str], new_title: Optional[str]) -> str:
    """Apply all modifications to HTML content"""
    soup = BeautifulSoup(html_content, "html.parser")
    
    # 1. Update Page Title
    if new_title:
        title_tag = soup.find("title")
        if title_tag:
            title_tag.string = new_title
        else:
            # Create title tag
            if not soup.head:
                head_tag = soup.new_tag("head")
                if soup.html:
                    soup.html.insert(0, head_tag)
                else:
                    soup.insert(0, head_tag)
            
            title_tag = soup.new_tag("title")
            title_tag.string = new_title
            soup.head.append(title_tag)
    
    # 2. Update/Delete Buttons
    for button in buttons:
        # Find matching elements
        for element in soup.find_all(["a", "button"]):
            element_link = element.get("href", "") or element.get("data-url", "")
            element_text = element.get_text(strip=True)
            
            # Check onclick for buttons
            onclick = element.get("onclick", "")
            if onclick and "window.open" in onclick:
                onclick_match = re.search(r'["\']([^"\']*(?:t\.me|telegram\.me)[^"\']*)["\']', onclick)
                if onclick_match:
                    element_link = onclick_match.group(1)
            
            # Match by original content
            if (element_link.lower() == button["orig_hr"].lower() and 
                element_text.lower() == button["orig_txt"].lower()):
                
                if button["delete"]:
                    # Remove element completely
                    element.decompose()
                else:
                    # Update element
                    if element.name == "a":
                        element["href"] = button["new_hr"]
                    elif element.name == "button" and onclick:
                        element["onclick"] = f"window.open('{button['new_hr']}')"
                    elif element.get("data-url"):
                        element["data-url"] = button["new_hr"]
                    
                    # Update text content
                    element.clear()
                    element.append(button["new_txt"])
    
    # 3. Apply Custom Text Replacements (with button protection)
    for old_text, new_text in text_map.items():
        # Find all text nodes
        for element in soup.find_all(string=re.compile(re.escape(old_text), re.IGNORECASE)):
            # Skip if inside a Telegram button
            parent_button = element.find_parent(["a", "button"])
            if parent_button:
                parent_link = parent_button.get("href", "") or parent_button.get("data-url", "")
                if TG_PATTERN.match(parent_link):
                    continue  # Skip modification inside Telegram buttons
            
            # Replace text
            new_element = re.sub(re.escape(old_text), new_text, element, flags=re.IGNORECASE)
            element.replace_with(new_element)
    
    return str(soup)

def validate_telegram_link(link: str) -> bool:
    """Validate if link is a proper Telegram link"""
    if not TG_PATTERN.match(link):
        return False
    
    # Additional validation for proper format
    normalized = link.lower()
    if 'telegram.me' in normalized or 't.me' in normalized or normalized.startswith('tg://'):
        return True
    
    return False

# ======================== KEYBOARD HELPERS ========================
def create_main_menu_keyboard(ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """Create the main menu keyboard with colored buttons"""
    buttons = ctx.user_data.get("btns", [])
    custom_title = ctx.user_data.get("custom_title")
    custom_filename = ctx.user_data.get("custom_filename")
    
    # Calculate statistics
    edited_count = len([b for b in buttons if b["new_txt"] != b["orig_txt"] or b["new_hr"] != b["orig_hr"]])
    deleted_count = len([b for b in buttons if b["delete"]])
    text_replacements = len(ctx.user_data.get("text_map", {}))
    
    keyboard = []
    
    # Button list (max 5 shown)
    for i, button in enumerate(buttons[:5]):
        if button["delete"]:
            status = f"{COLORS['danger']} [DELETED] {button['orig_txt'][:20]}"
        elif button["new_txt"] != button["orig_txt"] or button["new_hr"] != button["orig_hr"]:
            status = f"{COLORS['warning']} {button['new_txt'][:20]}"
        else:
            status = f"{COLORS['secondary']} {button['orig_txt'][:20]}"
        
        if len(button["orig_txt"]) > 20:
            status += "..."
            
        keyboard.append([InlineKeyboardButton(status, callback_data=f"b_{i}")])
    
    # Show more buttons indicator
    if len(buttons) > 5:
        keyboard.append([InlineKeyboardButton(f"... and {len(buttons) - 5} more buttons", callback_data="show_all")])
    
    # Global actions
    keyboard.append([
        InlineKeyboardButton(f"{COLORS['info']} Global Link Replace", callback_data="global_replace"),
        InlineKeyboardButton(f"{COLORS['info']} Custom Text Replace", callback_data="find_text")
    ])
    
    # Branding options
    title_text = f"Title: {custom_title[:10]}..." if custom_title else "Edit Page Title"
    filename_text = f"File: {custom_filename[:10]}..." if custom_filename else "Custom Filename"
    
    keyboard.append([
        InlineKeyboardButton(f"{COLORS['primary']} {title_text}", callback_data="change_title"),
        InlineKeyboardButton(f"{COLORS['primary']} {filename_text}", callback_data="change_filename")
    ])
    
    # Summary and actions
    summary_text = f"Changes: {edited_count}E {deleted_count}D {text_replacements}T"
    keyboard.append([InlineKeyboardButton(f"{COLORS['secondary']} {summary_text}", callback_data="show_summary")])
    
    # Final actions
    keyboard.append([
        InlineKeyboardButton(f"{COLORS['danger']} Reset All", callback_data="reset"),
        InlineKeyboardButton(f"{COLORS['success']} Generate Files ✨", callback_data="final")
    ])
    
    return InlineKeyboardMarkup(keyboard)

def create_button_edit_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for individual button editing"""
    keyboard = [
        [
            InlineKeyboardButton(f"{COLORS['warning']} Edit Name", callback_data="edit_name"),
            InlineKeyboardButton(f"{COLORS['info']} Edit Link", callback_data="edit_link")
        ],
        [
            InlineKeyboardButton(f"{COLORS['danger']} Toggle Delete", callback_data="delete_btn")
        ],
        [
            InlineKeyboardButton(f"{COLORS['secondary']} ⬅️ Back", callback_data="back")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ======================== MESSAGE HANDLERS ========================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Start command handler"""
    if not await owner_only(update):
        return ConversationHandler.END
    
    ctx.user_data.clear()
    init_user_data(ctx)
    
    welcome_msg = (
        f"🚀 **Advanced HTML Button Editor**\n\n"
        f"🎯 **Features:**\n"
        f"• {COLORS['success']} Interactive button editing\n"
        f"• {COLORS['info']} Batch file processing\n"
        f"• {COLORS['warning']} Smart deduplication\n"
        f"• {COLORS['primary']} Custom branding options\n\n"
        f"📤 **Start by uploading .html files**\n"
        f"📋 **Then type /done when ready**\n\n"
        f"💡 **Tip:** Upload multiple files at once!"
    )
    
    await update.message.reply_text(welcome_msg, parse_mode=ParseMode.MARKDOWN)
    return UPLOADING

async def receive_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle file uploads with enhanced validation"""
    if not await owner_only(update):
        return ConversationHandler.END
    
    if check_session_timeout(ctx):
        await update.message.reply_text("⏱ **Session expired.** Please /start again.")
        return ConversationHandler.END
    
    init_user_data(ctx)
    update_activity(ctx)
    
    doc = update.message.document
    
    if not doc:
        await update.message.reply_text("❌ Please send a document file.")
        return UPLOADING
    
    if not doc.file_name.lower().endswith(('.html', '.htm')):
        await update.message.reply_text(
            "⚠️ **Invalid file type**\n\n"
            "Please send only HTML files:\n"
            "• .html files\n"
            "• .htm files"
        )
        return UPLOADING
    
    # Check file size (max 20MB)
    if doc.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("❌ File too large. Maximum size: 20MB")
        return UPLOADING
    
    try:
        # Download and process file
        await update.message.reply_text(f"⏳ Processing `{doc.file_name}`...")
        
        file_obj = await doc.get_file()
        file_bytes = await file_obj.download_as_bytearray()
        
        # Try different encodings
        html_content = None
        for encoding in ['utf-8', 'utf-8-sig', 'latin1', 'cp1252']:
            try:
                html_content = file_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        
        if html_content is None:
            html_content = file_bytes.decode('utf-8', errors='ignore')
        
        # Extract buttons
        buttons = extract_buttons(html_content)
        button_count = len(buttons)
        
        # Store file
        ctx.user_data["files"][doc.file_name] = html_content
        
        # Success message
        msg = f"✅ **{doc.file_name}**\n📊 Found: {button_count} Telegram buttons"
        
        if button_count == 0:
            msg += "\n⚠️ No Telegram links detected"
        
        msg += f"\n\n📁 Total files: {len(ctx.user_data['files'])}"
        msg += "\n📤 Send more files or /done to continue"
        
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error processing file: {str(e)}")
    
    return UPLOADING

async def done_uploading(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Process uploaded files and show main menu"""
    if not await owner_only(update):
        return ConversationHandler.END
    
    if check_session_timeout(ctx):
        await update.message.reply_text("⏱ **Session expired.** Please /start again.")
        return ConversationHandler.END
    
    init_user_data(ctx)
    update_activity(ctx)
    
    files = ctx.user_data.get("files", {})
    
    if not files:
        await update.message.reply_text("⚠️ No files uploaded. Please send HTML files first.")
        return UPLOADING
    
    await update.message.reply_text("🔄 **Processing files...**\n⚡ Extracting and deduplicating buttons...")
    
    # Extract and deduplicate buttons from all files
    all_buttons = []
    seen_signatures = set()
    
    for filename, content in files.items():
        file_buttons = extract_buttons(content)
        
        for button in file_buttons:
            signature = (button["orig_txt"].lower(), button["orig_hr"].lower())
            
            if signature not in seen_signatures:
                seen_signatures.add(signature)
                all_buttons.append(button)
    
    ctx.user_data["btns"] = all_buttons
    
    # Show summary and main menu
    summary = (
        f"📊 **Processing Complete!**\n\n"
        f"• 📁 Files: {len(files)}\n"
        f"• 🔗 Unique buttons: {len(all_buttons)}\n"
        f"• 🧠 Smart deduplication: Active\n\n"
        f"🎛️ **Control Panel Ready:**"
    )
    
    await update.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN)
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def show_main_menu(update_target, ctx: ContextTypes.DEFAULT_TYPE):
    """Display the main menu interface"""
    keyboard = create_main_menu_keyboard(ctx)
    
    menu_text = (
        f"🎛️ **HTML Editor Control Panel**\n\n"
        f"📋 **Current Session:**\n"
        f"• Files: {len(ctx.user_data.get('files', {}))}\n"
        f"• Buttons: {len(ctx.user_data.get('btns', []))}\n\n"
        f"🎯 **Choose an option below:**"
    )
    
    if hasattr(update_target, 'message'):
        await update_target.message.reply_text(menu_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    else:
        await update_target.edit_message_text(menu_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

# ======================== CALLBACK HANDLERS ========================
async def menu_click(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle main menu button clicks"""
    query = update.callback_query
    await query.answer()
    
    if check_session_timeout(ctx):
        await query.edit_message_text("⏱ **Session expired.** Please /start again.")
        return ConversationHandler.END
    
    init_user_data(ctx)
    update_activity(ctx)
    
    data = query.data
    
    if data == "final":
        return await handle_final_generation(query, ctx)
    
    elif data == "reset":
        return await handle_reset(query, ctx)
    
    elif data == "change_title":
        await query.edit_message_text(
            f"{COLORS['primary']} **Edit Page Title**\n\n"
            f"🏷️ **This will be the browser tab title**\n\n"
            f"📝 Send the new page title:"
        )
        return EDITING_TITLE
    
    elif data == "change_filename":
        await query.edit_message_text(
            f"{COLORS['primary']} **Custom Filename**\n\n"
            f"📁 **Set custom name for output files**\n"
            f"🏷️ **Suffix `{RENAME_TAG}` will be added**\n\n"
            f"📝 Send the filename (without extension):"
        )
        return EDITING_FILENAME
    
    elif data == "global_replace":
        await query.edit_message_text(
            f"{COLORS['info']} **Global Link Replacement**\n\n"
            f"🔗 **This will replace ALL Telegram links**\n"
            f"⚠️ **Affects all buttons in all files**\n\n"
            f"📝 Send the new Telegram link:"
        )
        return GLOBAL_LINK_REPLACE
    
    elif data == "find_text":
        await query.edit_message_text(
            f"{COLORS['info']} **Custom Text Replacement**\n\n"
            f"🔍 **Find and replace any text**\n"
            f"🛡️ **Button names are protected**\n\n"
            f"📝 Send the text to find:"
        )
        return SEARCH_OLD_TEXT
    
    elif data == "back":
        await show_main_menu(query, ctx)
        return SHOWING_MENU
    
    elif data.startswith("b_"):
        return await handle_button_selection(query, ctx, data)
    
    elif data == "show_summary":
        await show_session_summary(query, ctx)
        return SHOWING_MENU
    
    return SHOWING_MENU

async def handle_final_generation(query, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle final file generation with confirmation"""
    buttons = ctx.user_data.get("btns", [])
    
    # Calculate statistics
    edited_buttons = len([b for b in buttons if (b["new_txt"] != b["orig_txt"] or b["new_hr"] != b["orig_hr"]) and not b["delete"]])
    deleted_buttons = len([b for b in buttons if b["delete"]])
    text_replacements = len(ctx.user_data.get("text_map", {}))
    
    has_custom_title = bool(ctx.user_data.get("custom_title"))
    has_custom_filename = bool(ctx.user_data.get("custom_filename"))
    
    summary = (
        f"📊 **Final Generation Summary**\n\n"
        f"📁 **Files:** {len(ctx.user_data.get('files', {}))}\n"
        f"✏️ **Buttons Edited:** {edited_buttons}\n"
        f"🗑️ **Buttons Deleted:** {deleted_buttons}\n"
        f"📝 **Text Replaced:** {text_replacements}\n"
        f"🏷️ **Custom Title:** {'Yes' if has_custom_title else 'No'}\n"
        f"📁 **Custom Filename:** {'Yes' if has_custom_filename else 'No'}\n\n"
        f"🚀 **Ready to generate final files?**"
    )
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{COLORS['success']} Yes, Generate! 🚀", callback_data="confirm_yes"),
            InlineKeyboardButton(f"{COLORS['danger']} Cancel", callback_data="confirm_no")
        ]
    ])
    
    await query.edit_message_text(summary, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    return CONFIRMING

async def handle_reset(query, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Reset all changes"""
    # Reset button modifications
    for button in ctx.user_data.get("btns", []):
        button["new_txt"] = button["orig_txt"]
        button["new_hr"] = button["orig_hr"]
        button["delete"] = False
    
    # Reset other modifications
    ctx.user_data.update({
        "text_map": {},
        "custom_filename": None,
        "custom_title": None
    })
    
    await query.edit_message_text(f"{COLORS['success']} **All changes have been reset.**")
    await show_main_menu(query, ctx)
    return SHOWING_MENU

async def handle_button_selection(query, ctx: ContextTypes.DEFAULT_TYPE, data: str) -> int:
    """Handle individual button selection"""
    try:
        button_index = int(data.split("_")[1])
        buttons = ctx.user_data.get("btns", [])
        
        if 0 <= button_index < len(buttons):
            ctx.user_data["edit_idx"] = button_index
            button = buttons[button_index]
            
            # Show button details
            status = "🗑️ DELETED" if button["delete"] else ("✏️ MODIFIED" if button["new_txt"] != button["orig_txt"] or button["new_hr"] != button["orig_hr"] else "📋 ORIGINAL")
            
            details = (
                f"🔘 **Button Editor**\n\n"
                f"**Status:** {status}\n"
                f"**Name:** `{button['new_txt']}`\n"
                f"**Link:** `{button['new_hr']}`\n\n"
                f"🎯 **Choose action:**"
            )
            
            await query.edit_message_text(details, reply_markup=create_button_edit_keyboard(), parse_mode=ParseMode.MARKDOWN)
        
    except (ValueError, IndexError):
        await query.answer("❌ Invalid button selection")
    
    return SHOWING_MENU

async def show_session_summary(query, ctx: ContextTypes.DEFAULT_TYPE):
    """Show detailed session summary"""
    files = ctx.user_data.get("files", {})
    buttons = ctx.user_data.get("btns", [])
    text_map = ctx.user_data.get("text_map", {})
    
    session_start = ctx.user_data.get("session_start", datetime.now())
    session_duration = datetime.now() - session_start
    
    summary = (
        f"📊 **Detailed Session Summary**\n\n"
        f"⏱️ **Session Duration:** {session_duration.seconds // 60}m {session_duration.seconds % 60}s\n"
        f"📁 **Files Uploaded:** {len(files)}\n"
        f"🔗 **Unique Buttons:** {len(buttons)}\n\n"
        f"**File List:**\n"
    )
    
    for i, filename in enumerate(files.keys(), 1):
        summary += f"• {i}. `{filename}`\n"
    
    if text_map:
        summary += f"\n**Text Replacements:**\n"
        for old, new in text_map.items():
            summary += f"• `{old[:20]}` → `{new[:20]}`\n"
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"{COLORS['secondary']} ⬅️ Back", callback_data="back")
    ]])
    
    await query.edit_message_text(summary, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

# ======================== INPUT HANDLERS ========================
async def button_sub_click(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button editing sub-menu"""
    query = update.callback_query
    await query.answer()
    
    update_activity(ctx)
    button_index = ctx.user_data.get("edit_idx")
    buttons = ctx.user_data.get("btns", [])
    
    if button_index is None or not (0 <= button_index < len(buttons)):
        await query.edit_message_text("❌ Invalid button selection")
        return SHOWING_MENU
    
    button = buttons[button_index]
    
    if query.data == "delete_btn":
        # Toggle delete status
        button["delete"] = not button["delete"]
        action = "marked for deletion" if button["delete"] else "restored"
        
        await query.answer(f"✅ Button {action}")
        await show_main_menu(query, ctx)
        return SHOWING_MENU
    
    elif query.data == "edit_name":
        await query.edit_message_text(
            f"✏️ **Edit Button Name**\n\n"
            f"**Current:** `{button['new_txt']}`\n\n"
            f"📝 Send the new button name:"
        )
        return EDITING_NAME_VAL
    
    elif query.data == "edit_link":
        await query.edit_message_text(
            f"🔗 **Edit Button Link**\n\n"
            f"**Current:** `{button['new_hr']}`\n\n"
            f"📝 Send the new Telegram link:"
        )
        return EDITING_LINK_VAL
    
    return SHOWING_MENU

# Text input handlers
async def handle_title_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom title input"""
    if not await owner_only(update):
        return ConversationHandler.END
    
    title = update.message.text.strip()
    ctx.user_data["custom_title"] = title
    
    await update.message.reply_text(
        f"✅ **Page title set:**\n`{title}`",
        parse_mode=ParseMode.MARKDOWN
    )
    
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def handle_filename_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom filename input"""
    if not await owner_only(update):
        return ConversationHandler.END
    
    filename = update.message.text.strip().replace(" ", "_")
    # Remove any file extensions and invalid characters
    filename = re.sub(r'[^\w\-_]', '', filename)
    
    ctx.user_data["custom_filename"] = filename
    
    await update.message.reply_text(
        f"✅ **Custom filename set:**\n`{filename}{RENAME_TAG}.html`",
        parse_mode=ParseMode.MARKDOWN
    )
    
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def handle_button_name_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button name editing"""
    if not await owner_only(update):
        return ConversationHandler.END
    
    new_name = update.message.text.strip()
    button_index = ctx.user_data.get("edit_idx")
    buttons = ctx.user_data.get("btns", [])
    
    if button_index is not None and 0 <= button_index < len(buttons):
        buttons[button_index]["new_txt"] = new_name
        
        await update.message.reply_text(
            f"✅ **Button name updated:**\n`{new_name}`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def handle_button_link_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button link editing with validation"""
    if not await owner_only(update):
        return ConversationHandler.END
    
    new_link = update.message.text.strip()
    
    # Validate Telegram link
    if not validate_telegram_link(new_link):
        await update.message.reply_text(
            "❌ **Invalid Telegram link!**\n\n"
            "Please send a valid link:\n"
            "• https://t.me/channel\n"
            "• https://telegram.me/group\n"
            "• tg://resolve?domain=channel"
        )
        return EDITING_LINK_VAL
    
    button_index = ctx.user_data.get("edit_idx")
    buttons = ctx.user_data.get("btns", [])
    
    if button_index is not None and 0 <= button_index < len(buttons):
        buttons[button_index]["new_hr"] = new_link
        
        await update.message.reply_text(
            f"✅ **Button link updated:**\n`{new_link}`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def handle_global_link_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle global link replacement"""
    if not await owner_only(update):
        return ConversationHandler.END
    
    new_link = update.message.text.strip()
    
    if not validate_telegram_link(new_link):
        await update.message.reply_text(
            "❌ **Invalid Telegram link!**\n\n"
            "Please send a valid Telegram link."
        )
        return GLOBAL_LINK_REPLACE
    
    # Apply to all buttons
    buttons = ctx.user_data.get("btns", [])
    updated_count = 0
    
    for button in buttons:
        if not button["delete"]:
            button["new_hr"] = new_link
            updated_count += 1
    
    await update.message.reply_text(
        f"✅ **Global link replacement complete:**\n"
        f"📊 Updated {updated_count} buttons\n"
        f"🔗 New link: `{new_link}`",
        parse_mode=ParseMode.MARKDOWN
    )
    
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def handle_search_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text search input"""
    if not await owner_only(update):
        return ConversationHandler.END
    
    search_text = update.message.text.strip()
    ctx.user_data["temp_search"] = search_text
    
    await update.message.reply_text(
        f"🔍 **Search text set:**\n`{search_text}`\n\n"
        f"📝 **Now send the replacement text:**"
    )
    
    return REPLACE_NEW_TEXT

async def handle_replace_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text replacement input"""
    if not await owner_only(update):
        return ConversationHandler.END
    
    replace_text = update.message.text.strip()
    search_text = ctx.user_data.get("temp_search", "")
    
    if search_text:
        ctx.user_data.setdefault("text_map", {})[search_text] = replace_text
        ctx.user_data.pop("temp_search", None)
        
        await update.message.reply_text(
            f"✅ **Text replacement added:**\n"
            f"📍 Find: `{search_text}`\n"
            f"📍 Replace: `{replace_text}`\n\n"
            f"🛡️ Button names are protected from this replacement.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def final_confirmation(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle final confirmation and file generation"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_yes":
        return await generate_final_files(query, ctx)
    else:
        await query.edit_message_text("❌ **File generation cancelled.**")
        await show_main_menu(query, ctx)
        return SHOWING_MENU

async def generate_final_files(query, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Generate and send final HTML files"""
    await query.edit_message_text("⚡ **Generating files...**\n🔄 Applying all modifications...")
    
    files = ctx.user_data.get("files", {})
    buttons = ctx.user_data.get("btns", [])
    text_map = ctx.user_data.get("text_map", {})
    custom_title = ctx.user_data.get("custom_title")
    custom_filename = ctx.user_data.get("custom_filename")
    
    try:
        generated_files = []
        
        for i, (original_name, html_content) in enumerate(files.items(), 1):
            # Apply all modifications
            modified_html = patch_html(html_content, buttons, text_map, custom_title)
            
            # Generate filename
            if custom_filename:
                if len(files) > 1:
                    new_filename = f"{custom_filename}_{i}{RENAME_TAG}.html"
                else:
                    new_filename = f"{custom_filename}{RENAME_TAG}.html"
            else:
                base_name = os.path.splitext(original_name)[0]
                new_filename = f"{base_name}{RENAME_TAG}.html"
            
            # Create file object
            file_obj = io.BytesIO(modified_html.encode('utf-8'))
            file_obj.name = new_filename
            
            # Send file
            await query.message.reply_document(
                document=file_obj,
                filename=new_filename,
                caption=f"✅ **Generated:** `{new_filename}`\n📄 **Original:** `{original_name}`"
            )
            
            generated_files.append(new_filename)
        
        # Send completion summary
        completion_summary = (
            f"🎉 **Generation Complete!**\n\n"
            f"📊 **Final Summary:**\n"
            f"• 📁 Files generated: {len(generated_files)}\n"
            f"• ✏️ Buttons modified: {len([b for b in buttons if b['new_txt'] != b['orig_txt'] or b['new_hr'] != b['orig_hr']])}\n"
            f"• 🗑️ Buttons deleted: {len([b for b in buttons if b['delete']])}\n"
            f"• 📝 Text replacements: {len(text_map)}\n\n"
            f"💾 **All files ready for download above!**\n\n"
            f"🔄 **Start a new session with /start**"
        )
        
        await query.message.reply_text(completion_summary, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        await query.message.reply_text(f"❌ **Generation failed:** {str(e)}")
    
    # Clear session
    ctx.user_data.clear()
    return ConversationHandler.END

# ======================== APPLICATION SETUP ========================
def main():
    """Main application function"""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set BOT_TOKEN in environment variables!")
        return
    
    if OWNER_ID == 123456789:
        print("⚠️  Please set OWNER_ID in environment variables!")
        return
    
    print("🚀 Starting health check server...")
    health_thread = Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    print("🤖 Building Telegram application...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Create conversation handler
    conversation_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Document.ALL, receive_file)
        ],
        states={
            UPLOADING: [
                MessageHandler(filters.Document.ALL, receive_file),
                CommandHandler("done", done_uploading)
            ],
            SHOWING_MENU: [
                CallbackQueryHandler(menu_click, pattern="^(final|reset|global_replace|find_text|back|change_filename|change_title|b_.*|show_.*)$"),
                CallbackQueryHandler(button_sub_click, pattern="^(delete_btn|edit_name|edit_link)$")
            ],
            EDITING_NAME_VAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_name_edit)
            ],
            EDITING_LINK_VAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_link_edit)
            ],
            SEARCH_OLD_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_text_input)
            ],
            REPLACE_NEW_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_replace_text_input)
            ],
            GLOBAL_LINK_REPLACE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_global_link_input)
            ],
            EDITING_FILENAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_filename_input)
            ],
            EDITING_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_title_input)
            ],
            CONFIRMING: [
                CallbackQueryHandler(final_confirmation)
            ]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(conversation_handler)
    
    print(f"✅ Bot ready!")
    print(f"🔒 Owner: {OWNER_ID}")
    print(f"🏷️ Rename tag: {RENAME_TAG}")
    print("📱 Starting polling...")
    
    # Run the bot
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == '__main__':
    main()
