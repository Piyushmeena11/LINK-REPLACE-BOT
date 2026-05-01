import os
import io
import re
import requests
import asyncio
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

# For Render deployment (no nest_asyncio needed)
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# ======================== HEALTH CHECK (For Render) ========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Bot Running!')
    def log_message(self, *args): pass

def health_server():
    port = int(os.getenv('PORT', 10000))
    HTTPServer(('0.0.0.0', port), HealthHandler).serve_forever()

# ======================== CONFIGURATION ========================
BOT_TOKEN  = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_ID   = int(os.getenv("OWNER_ID", "123456789"))
RENAME_TAG = os.getenv("RENAME_TAG", "_edited")

print(f"🚀 Bot Starting - Owner: {OWNER_ID}, Tag: {RENAME_TAG}")

# States
UPLOADING, SHOWING_MENU, EDITING_NAME_VAL, EDITING_LINK_VAL = range(4)
SEARCH_OLD_TEXT, REPLACE_NEW_TEXT, GLOBAL_LINK_REPLACE = range(4, 7)
EDITING_FILENAME, EDITING_TITLE, CONFIRMING = range(7, 10)

TG_PATTERN = re.compile(r'^(?:https?://)?(?:t\.me|telegram\.(?:me|dog))|^tg://', re.I)

# --- Initialization Helper ---
def init_user_data(ctx):
    if "files" not in ctx.user_data:
        ctx.user_data.update({
            "files": {}, 
            "btns": [], 
            "text_map": {}, 
            "custom_filename": None,
            "custom_title": None
        })

# --- Logic Functions ---
async def owner_only(update: Update) -> bool:
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text("⛔ Unauthorized.")
        return False
    return True

def extract_buttons(html):
    soup = BeautifulSoup(html, "html.parser")
    seen, buttons = set(), []
    for a in soup.find_all("a", href=True):
        if TG_PATTERN.match(a["href"]):
            txt, hr = a.get_text(strip=True) or "Button", a["href"]
            if (txt.lower(), hr.lower()) not in seen:
                seen.add((txt.lower(), hr.lower()))
                buttons.append({"orig_txt": txt, "orig_hr": hr, "new_txt": txt, "new_hr": hr, "delete": False})
    return buttons

def patch_html(html, buttons, text_map, new_title):
    soup = BeautifulSoup(html, "html.parser")
    # 1. Page Title Update
    if new_title:
        if soup.title: 
            soup.title.string = new_title
        else:
            new_tag = soup.new_tag("title")
            new_tag.string = new_title
            if soup.head: 
                soup.head.append(new_tag)
    
    # 2. Buttons Update
    for b in buttons:
        for a in soup.find_all("a", href=True):
            if a["href"].lower() == b["orig_hr"].lower() and a.get_text(strip=True).lower() == b["orig_txt"].lower():
                if b["delete"]: 
                    a.decompose()
                else:
                    a["href"] = b["new_hr"]
                    a.clear()
                    a.append(b["new_txt"])
    
    # 3. Custom Text Update
    for old, new in text_map.items():
        target = re.compile(re.escape(old), re.IGNORECASE)
        for element in soup.find_all(string=target):
            if element.find_parent("a", href=True) and TG_PATTERN.match(element.find_parent("a")["href"]): 
                continue
            element.replace_with(target.sub(new, element))
    
    return str(soup)

# --- Handlers ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update): 
        return ConversationHandler.END
    ctx.user_data.clear()
    init_user_data(ctx)
    await update.message.reply_text("👋 Hi! Send **.html** files or type /done")
    return UPLOADING

async def receive_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update): 
        return ConversationHandler.END
    
    init_user_data(ctx)
    doc = update.message.document
    
    if not doc or not doc.file_name.lower().endswith(".html"):
        await update.message.reply_text("❌ Send only .html files.")
        return UPLOADING
    
    try:
        # Progress message
        progress_msg = await update.message.reply_text(f"⏳ Downloading `{doc.file_name}`...")
        
        # Download with timeout
        f = await asyncio.wait_for(doc.get_file(), timeout=30)
        b = await asyncio.wait_for(f.download_as_bytearray(), timeout=60)
        
        # Decode
        html_content = b.decode("utf-8", errors="ignore")
        
        # Store
        ctx.user_data["files"][doc.file_name] = html_content
        
        # Update message
        await progress_msg.edit_text(f"✅ Received {doc.file_name}. More? or /done")
        
    except asyncio.TimeoutError:
        await update.message.reply_text("❌ Download timeout. File too large or slow connection.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
    
    return UPLOADING

async def show_main_menu(update_target, ctx):
    btns = ctx.user_data["btns"]
    c_title = ctx.user_data.get("custom_title")
    kb = []
    
    for i, b in enumerate(btns):
        status = "❌ [DEL]" if b["delete"] else f"🔘 {b['new_txt']}"
        kb.append([InlineKeyboardButton(status, callback_data=f"b_{i}")])
    
    kb.append([
        InlineKeyboardButton("🔗 All Links Replace", callback_data="global_replace"), 
        InlineKeyboardButton("🔍 Replace Custom Text", callback_data="find_text")
    ])
    
    t_btn = f"🏷️ Title: {c_title[:15]}..." if c_title else "🏷️ Edit Page Title"
    kb.append([
        InlineKeyboardButton(t_btn, callback_data="change_title"),
        InlineKeyboardButton("📁 Rename File", callback_data="change_filename")
    ])
    
    kb.append([
        InlineKeyboardButton("🔄 Reset", callback_data="reset"),
        InlineKeyboardButton("✅ FINISH & GENERATE", callback_data="final")
    ])
    
    msg = "Main Menu: Choose an option to edit your HTML files."
    
    if isinstance(update_target, Update): 
        await update_target.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    else: 
        await update_target.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def done_uploading(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update): 
        return ConversationHandler.END
    
    init_user_data(ctx)
    files = ctx.user_data.get("files")
    
    if not files: 
        return UPLOADING
    
    all_btns, seen = [], set()
    
    for content in files.values():
        for b in extract_buttons(content):
            if (b["orig_txt"].lower(), b["orig_hr"].lower()) not in seen:
                seen.add((b["orig_txt"].lower(), b["orig_hr"].lower()))
                all_btns.append(b)
    
    ctx.user_data["btns"] = all_btns
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def menu_click(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    init_user_data(ctx)
    
    if query.data == "final":
        # Calculate Summary
        btns = ctx.user_data["btns"]
        edited_b = len([b for b in btns if (b["new_txt"] != b["orig_txt"] or b["new_hr"] != b["orig_hr"]) and not b["delete"]])
        deleted_b = len([b for b in btns if b["delete"]])
        texts = len(ctx.user_data["text_map"])
        
        summary = (
            f"📊 **Project Summary:**\n"
            f"• Files: {len(ctx.user_data['files'])}\n"
            f"• Buttons Edited: {edited_b}\n"
            f"• Buttons Deleted: {deleted_b}\n"
            f"• Text Replaced: {texts}\n"
            f"• New Title: {'Yes' if ctx.user_data['custom_title'] else 'No'}\n\n"
            f"Apply and generate?"
        )
        
        await query.edit_message_text(
            summary, 
            parse_mode=ParseMode.MARKDOWN, 
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Yes, Go!", callback_data="y"), 
                InlineKeyboardButton("No", callback_data="n")
            ]])
        )
        return CONFIRMING
    
    if query.data == "reset":
        for b in ctx.user_data["btns"]: 
            b["new_txt"], b["new_hr"], b["delete"] = b["orig_txt"], b["orig_hr"], False
        ctx.user_data.update({"text_map": {}, "custom_filename": None, "custom_title": None})
        await query.message.reply_text("🔄 Edits Reset.")
        await show_main_menu(query, ctx)
        return SHOWING_MENU
    
    if query.data == "change_title":
        await query.edit_message_text("🏷️ Send the **New Page Title** (Browser Tab Name):")
        return EDITING_TITLE
    
    if query.data == "change_filename":
        await query.edit_message_text("📁 Send the **New Filename** (Suffix will be added):")
        return EDITING_FILENAME
    
    if query.data == "global_replace":
        await query.edit_message_text("🔗 Send NEW LINK for ALL buttons:")
        return GLOBAL_LINK_REPLACE
    
    if query.data == "find_text":
        await query.edit_message_text("🔍 Word to find:")
        return SEARCH_OLD_TEXT
    
    if query.data == "back":
        await show_main_menu(query, ctx)
        return SHOWING_MENU
    
    idx = int(query.data.split("_")[1])
    ctx.user_data["edit_idx"] = idx
    b = ctx.user_data["btns"][idx]
    
    kb = [
        [
            InlineKeyboardButton("✏️ Name", callback_data="edit_name"), 
            InlineKeyboardButton("🔗 Link", callback_data="edit_link")
        ],
        [
            InlineKeyboardButton("🗑️ Delete", callback_data="delete_btn"), 
            InlineKeyboardButton("⬅️ Back", callback_data="back")
        ]
    ]
    
    await query.edit_message_text(
        f"Button: {b['new_txt']}\nLink: {b['new_hr']}", 
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return SHOWING_MENU

async def button_sub_click(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx, btns = ctx.user_data["edit_idx"], ctx.user_data["btns"]
    
    if query.data == "delete_btn":
        btns[idx]["delete"] = not btns[idx]["delete"]
        await show_main_menu(query, ctx)
        return SHOWING_MENU
    
    if query.data == "edit_name":
        await query.edit_message_text("New Name?")
        return EDITING_NAME_VAL
    
    if query.data == "edit_link":
        await query.edit_message_text("New Link?")
        return EDITING_LINK_VAL
    
    return SHOWING_MENU

async def handle_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["custom_title"] = update.message.text.strip()
    await update.message.reply_text(f"✅ Title set to: {ctx.user_data['custom_title']}")
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def handle_filename(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["custom_filename"] = update.message.text.strip().replace(" ", "_")
    await update.message.reply_text(f"✅ Filename set.")
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def handle_val_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    idx, btns = ctx.user_data["edit_idx"], ctx.user_data["btns"]
    
    if ctx.user_data.get("state_ref") == "name": 
        btns[idx]["new_txt"] = val
    else: 
        btns[idx]["new_hr"] = val
    
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def handle_global_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    
    if TG_PATTERN.match(val):
        for b in ctx.user_data["btns"]: 
            b["new_hr"] = val
        await update.message.reply_text("✅ Updated.")
        await show_main_menu(update, ctx)
        return SHOWING_MENU

async def handle_search_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["temp_old"] = update.message.text.strip()
    await update.message.reply_text("Replacement?")
    return REPLACE_NEW_TEXT

async def handle_replace_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["text_map"][ctx.user_data.pop("temp_old")] = update.message.text.strip()
    await update.message.reply_text("✅ Saved.")
    await show_main_menu(update, ctx)
    return SHOWING_MENU

async def final_finish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "y":
        await query.edit_message_text("⏳ Processing...")
        
        c_name = ctx.user_data.get("custom_filename")
        c_title = ctx.user_data.get("custom_title")
        files = ctx.user_data["files"]
        
        for i, (orig_name, content) in enumerate(files.items(), 1):
            out = patch_html(content, ctx.user_data["btns"], ctx.user_data["text_map"], c_title)
            base = f"{c_name}_{i}" if c_name and len(files) > 1 else (c_name or os.path.splitext(orig_name)[0])
            
            await query.message.reply_document(
                document=io.BytesIO(out.encode()), 
                filename=f"{base}{RENAME_TAG}.html"
            )
        
        await query.message.reply_text("🎉 Finished!")
    else: 
        await query.message.reply_text("Cancelled.")
    
    ctx.user_data.clear()
    return ConversationHandler.END

# --- Application ---
def main():
    # Start health server for Render
    Thread(target=health_server, daemon=True).start()
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.Document.ALL, receive_file)],
        states={
            UPLOADING: [
                MessageHandler(filters.Document.ALL, receive_file), 
                CommandHandler("done", done_uploading)
            ],
            SHOWING_MENU: [
                CallbackQueryHandler(menu_click, pattern="^(final|reset|global_replace|find_text|back|change_filename|change_title|b_.*)$"), 
                CallbackQueryHandler(button_sub_click, pattern="^(delete_btn|edit_name|edit_link)$")
            ],
            EDITING_NAME_VAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: (c.user_data.update({"state_ref": "name"}), handle_val_edit(u, c))[1])
            ],
            EDITING_LINK_VAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: (c.user_data.update({"state_ref": "link"}), handle_val_edit(u, c))[1])
            ],
            SEARCH_OLD_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_text)
            ],
            REPLACE_NEW_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_replace_text)
            ],
            GLOBAL_LINK_REPLACE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_global_link)
            ],
            EDITING_FILENAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_filename)
            ],
            EDITING_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_title)
            ],
            CONFIRMING: [
                CallbackQueryHandler(final_finish)
            ],
        },
        fallbacks=[CommandHandler("start", start)]
    ))
    
    print("🤖 Bot Ready! Starting polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
