import os
import io
import re
import requests
import asyncio
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

# ─────────────────────────────────────────
# ENV LOAD
# ─────────────────────────────────────────
load_dotenv()
BOT_TOKEN  = os.getenv("BOT_TOKEN")
OWNER_ID   = int(os.getenv("OWNER_ID"))
RENAME_TAG = os.getenv("RENAME_TAG", "_edited")

# ─────────────────────────────────────────
# STATES
# ─────────────────────────────────────────
UPLOADING       = 1
SHOWING_BUTTONS = 2
EDITING_NAME    = 3
EDITING_LINK    = 4
CONFIRMING      = 5

# ─────────────────────────────────────────
# TELEGRAM LINK PATTERN
# ─────────────────────────────────────────
TG_PATTERN = re.compile(
    r'^(?:https?://)?(?:t\.me|telegram\.(?:me|dog))|^tg://',
    re.IGNORECASE
)

# ─────────────────────────────────────────
# OWNER CHECK
# ─────────────────────────────────────────
async def owner_only(update: Update) -> bool:
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text(
            "⛔ Sorry, you are not authorized to use this bot."
        )
        return False
    return True

# ─────────────────────────────────────────
# LINK VALIDATOR
# ─────────────────────────────────────────
def validate_telegram_link(link: str) -> tuple[bool, str]:
    """
    Returns (is_valid, message)
    First checks format, then checks if link is reachable.
    """
    if not TG_PATTERN.match(link):
        return False, "❌ Invalid format. Please send a valid Telegram link (e.g. https://t.me/username)"

    try:
        response = requests.head(link, timeout=5, allow_redirects=True)
        if response.status_code == 200:
            return True, "✅ Link is valid and working!"
        elif response.status_code == 404:
            return False, "❌ Link not found on Telegram. Please check again."
        else:
            return True, "⚠️ Link format is valid but could not fully verify. Proceeding anyway."
    except requests.exceptions.RequestException:
        return True, "⚠️ Could not verify link reachability right now. Proceeding anyway."

# ─────────────────────────────────────────
# HTML PARSER — Extract Telegram Buttons
# ─────────────────────────────────────────
def extract_telegram_buttons(html_content: str) -> list[dict]:
    """
    Extract all unique Telegram links from HTML file.
    Returns list of dicts: {text, href}
    Deduplication by (text + href) pair.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    seen = set()
    buttons = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if TG_PATTERN.match(href):
            text = a.get_text(strip=True) or a.get("title", "") or "Unknown Button"
            key  = (text.lower(), href.lower())
            if key not in seen:
                seen.add(key)
                buttons.append({
                    "original_text": text,
                    "original_href": href,
                    "new_text":      text,
                    "new_href":      href,
                })

    return buttons

# ─────────────────────────────────────────
# HTML PATCHER — Apply Edits
# ─────────────────────────────────────────
def patch_html(html_content: str, buttons: list[dict]) -> str:
    """
    Replace old (text, href) with new (text, href) in HTML.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    for btn in buttons:
        for a in soup.find_all("a", href=True):
            if (
                a["href"].lower()          == btn["original_href"].lower() and
                a.get_text(strip=True).lower() == btn["original_text"].lower()
            ):
                a["href"]  = btn["new_href"]
                if a.string:
                    a.string = btn["new_text"]

    return str(soup)

# ─────────────────────────────────────────
# BUILD MAIN BUTTON LIST KEYBOARD
# ─────────────────────────────────────────
def build_button_list_keyboard(buttons: list[dict]) -> InlineKeyboardMarkup:
    keyboard = []
    for idx, btn in enumerate(buttons):
        keyboard.append([
            InlineKeyboardButton(
                text=f"🔘 {btn['new_text']}",
                callback_data=f"btn_{idx}"
            )
        ])
    keyboard.append([
        InlineKeyboardButton("✅ Done / Complete", callback_data="done")
    ])
    return InlineKeyboardMarkup(keyboard)

# ─────────────────────────────────────────
# BUILD EDIT OPTIONS KEYBOARD
# ─────────────────────────────────────────
def build_edit_keyboard(idx: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✏️ Edit Name", callback_data=f"edit_name_{idx}"),
            InlineKeyboardButton("🔗 Edit Link", callback_data=f"edit_link_{idx}"),
        ],
        [
            InlineKeyboardButton("⬅️ Back",      callback_data="back_to_list"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ─────────────────────────────────────────
# BUILD CONFIRM KEYBOARD
# ─────────────────────────────────────────
def build_confirm_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, Apply",  callback_data="confirm_yes"),
            InlineKeyboardButton("❌ Cancel",       callback_data="confirm_no"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ─────────────────────────────────────────
# /start
# ─────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await owner_only(update):
        return ConversationHandler.END

    ctx.user_data.clear()
    ctx.user_data["files"]   = {}   # filename -> html_content
    ctx.user_data["buttons"] = []   # unified deduplicated button list

    await update.message.reply_text(
        "👋 *Welcome!*\n\n"
        "Please send me your HTML file(s) one by one.\n"
        "When you are done uploading, type /done\n\n"
        "Type /help anytime for instructions.",
        parse_mode=ParseMode.MARKDOWN
    )
    return UPLOADING

# ─────────────────────────────────────────
# /help
# ─────────────────────────────────────────
async def help_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await owner_only(update):
        return

    await update.message.reply_text(
        "🧾 *BOT GUIDE*\n\n"
        "1️⃣ Send your HTML files (one by one).\n"
        "2️⃣ When all files are sent, type /done\n"
        "3️⃣ Bot will show all Telegram buttons found.\n"
        "4️⃣ Tap any button to view and edit its name or link.\n"
        "5️⃣ When editing is complete, tap ✅ Done.\n"
        "6️⃣ Your updated HTML file(s) will be sent back.\n\n"
        "⚠️ Session expires after 10 minutes of inactivity.\n"
        "🔄 Use /start to begin a new session anytime.",
        parse_mode=ParseMode.MARKDOWN
    )

# ─────────────────────────────────────────
# FILE RECEIVE HANDLER
# ─────────────────────────────────────────
async def receive_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await owner_only(update):
        return ConversationHandler.END

    doc = update.message.document

    # Only HTML files allowed
    if doc.mime_type not in ("text/html", "application/octet-stream") and \
       not doc.file_name.endswith(".html"):
        await update.message.reply_text("⚠️ Please send only .html files.")
        return UPLOADING

    filename = doc.file_name

    # Duplicate file check
    if filename in ctx.user_data.get("files", {}):
        await update.message.reply_text(
            f"⚠️ `{filename}` was already uploaded. Skipping duplicate.",
            parse_mode=ParseMode.MARKDOWN
        )
        return UPLOADING

    # Download file
    file_obj  = await doc.get_file()
    raw_bytes = await file_obj.download_as_bytearray()
    html_text = raw_bytes.decode("utf-8", errors="ignore")

    ctx.user_data["files"][filename] = html_text

    total = len(ctx.user_data["files"])
    await update.message.reply_text(
        f"✅ `{filename}` received! Total files: {total}\n"
        f"Send more files or type /done when finished.",
        parse_mode=ParseMode.MARKDOWN
    )
    return UPLOADING

# ─────────────────────────────────────────
# /done — Process all files
# ─────────────────────────────────────────
async def done_uploading(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await owner_only(update):
        return ConversationHandler.END

    files = ctx.user_data.get("files", {})
    if not files:
        await update.message.reply_text("⚠️ No files uploaded yet. Please send HTML files first.")
        return UPLOADING

    # Extract + deduplicate buttons across all files
    seen    = set()
    buttons = []

    for filename, html_content in files.items():
        extracted = extract_telegram_buttons(html_content)
        for btn in extracted:
            key = (btn["original_text"].lower(), btn["original_href"].lower())
            if key not in seen:
                seen.add(key)
                buttons.append(btn)

    if not buttons:
        await update.message.reply_text(
            "⚠️ No Telegram links found in your HTML files.\n"
            "Please check your files and try again with /start"
        )
        return ConversationHandler.END

    ctx.user_data["buttons"] = buttons

    total_files   = len(files)
    total_buttons = len(buttons)

    await update.message.reply_text(
        f"📂 *{total_files} file(s)* processed.\n"
        f"🔘 *{total_buttons} unique Telegram button(s)* found.\n\n"
        f"Tap any button below to edit its name or link:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_button_list_keyboard(buttons)
    )
    return SHOWING_BUTTONS

# ─────────────────────────────────────────
# CALLBACK: Button tapped from list
# ─────────────────────────────────────────
async def button_tapped(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query   = update.callback_query
    await query.answer()

    data    = query.data
    buttons = ctx.user_data.get("buttons", [])

    # ── Back to main list ──
    if data == "back_to_list":
        await query.edit_message_text(
            "🔘 *Button List*\nTap any button to view or edit:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_button_list_keyboard(buttons)
        )
        return SHOWING_BUTTONS

    # ── Done tapped ──
    if data == "done":
        edited = [b for b in buttons if
                  b["new_text"] != b["original_text"] or
                  b["new_href"] != b["original_href"]]

        if not edited:
            await query.edit_message_text(
                "⚠️ No changes were made.\n"
                "Do you still want to generate the file?",
                reply_markup=build_confirm_keyboard()
            )
        else:
            summary_lines = []
            for b in edited:
                summary_lines.append(
                    f"• *{b['original_text']}* → *{b['new_text']}*\n"
                    f"  `{b['original_href']}` → `{b['new_href']}`"
                )
            summary = "\n".join(summary_lines)
            await query.edit_message_text(
                f"📋 *Summary of changes:*\n\n{summary}\n\n"
                f"Proceed and generate updated file(s)?",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_confirm_keyboard()
            )
        return CONFIRMING

    # ── Individual button tapped ──
    if data.startswith("btn_"):
        idx = int(data.split("_")[1])
        if idx >= len(buttons):
            await query.answer("Invalid button.")
            return SHOWING_BUTTONS

        btn = buttons[idx]
        await query.edit_message_text(
            f"🔘 *Button Details:*\n\n"
            f"📝 Name : `{btn['new_text']}`\n"
            f"🔗 Link : `{btn['new_href']}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_edit_keyboard(idx)
        )
        return SHOWING_BUTTONS

    # ── Edit Name tapped ──
    if data.startswith("edit_name_"):
        idx = int(data.split("_")[2])
        ctx.user_data["editing_idx"]  = idx
        ctx.user_data["editing_field"] = "name"
        await query.edit_message_text(
            f"✏️ Send the *new name* for this button:\n\n"
            f"Current name: `{buttons[idx]['new_text']}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return EDITING_NAME

    # ── Edit Link tapped ──
    if data.startswith("edit_link_"):
        idx = int(data.split("_")[2])
        ctx.user_data["editing_idx"]   = idx
        ctx.user_data["editing_field"] = "link"
        await query.edit_message_text(
            f"🔗 Send the *new Telegram link* for this button:\n\n"
            f"Current link: `{buttons[idx]['new_href']}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return EDITING_LINK

    return SHOWING_BUTTONS

# ─────────────────────────────────────────
# RECEIVE NEW NAME
# ─────────────────────────────────────────
async def receive_new_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await owner_only(update):
        return ConversationHandler.END

    new_name = update.message.text.strip()
    if not new_name:
        await update.message.reply_text("⚠️ Name cannot be empty. Please send a valid name.")
        return EDITING_NAME

    idx     = ctx.user_data.get("editing_idx", 0)
    buttons = ctx.user_data.get("buttons", [])
    buttons[idx]["new_text"] = new_name

    await update.message.reply_text(
        f"✅ Button name updated to: *{new_name}*",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text(
        "🔘 *Button List*\nTap any button to view or edit:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_button_list_keyboard(buttons)
    )
    return SHOWING_BUTTONS

# ─────────────────────────────────────────
# RECEIVE NEW LINK
# ─────────────────────────────────────────
async def receive_new_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await owner_only(update):
        return ConversationHandler.END

    new_link = update.message.text.strip()
    is_valid, msg = validate_telegram_link(new_link)

    if not is_valid:
        await update.message.reply_text(
            f"{msg}\n\nPlease send a valid Telegram link."
        )
        return EDITING_LINK

    idx     = ctx.user_data.get("editing_idx", 0)
    buttons = ctx.user_data.get("buttons", [])
    buttons[idx]["new_href"] = new_link

    await update.message.reply_text(
        f"{msg}\n\nLink updated to:\n`{new_link}`",
        parse_mode=ParseMode.MARKDOWN
    )
    await update.message.reply_text(
        "🔘 *Button List*\nTap any button to view or edit:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_button_list_keyboard(buttons)
    )
    return SHOWING_BUTTONS

# ─────────────────────────────────────────
# CONFIRM — Apply edits and send files
# ─────────────────────────────────────────
async def confirm_apply(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_no":
        buttons = ctx.user_data.get("buttons", [])
        await query.edit_message_text(
            "🔘 *Button List*\nTap any button to view or edit:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_button_list_keyboard(buttons)
        )
        return SHOWING_BUTTONS

    # Apply edits
    files   = ctx.user_data.get("files",   {})
    buttons = ctx.user_data.get("buttons", [])

    await query.edit_message_text("⏳ Generating your updated file(s)...")

    for filename, html_content in files.items():
        patched = patch_html(html_content, buttons)

        # Build new filename
        name_part, ext_part = os.path.splitext(filename)
        new_filename = f"{name_part}{RENAME_TAG}{ext_part}"

        await query.message.reply_document(
            document=io.BytesIO(patched.encode("utf-8")),
            filename=new_filename,
            caption=f"✅ `{new_filename}` is ready!",
            parse_mode=ParseMode.MARKDOWN
        )

    await query.message.reply_text(
        "🎉 All files processed successfully!\n"
        "Type /start to begin a new session."
    )

    ctx.user_data.clear()
    return ConversationHandler.END

# ─────────────────────────────────────────
# TIMEOUT HANDLER
# ─────────────────────────────────────────
async def session_timeout(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "⏰ Session expired due to inactivity.\n"
        "Please type /start to begin again."
    )
    ctx.user_data.clear()
    return ConversationHandler.END

# ─────────────────────────────────────────
# CANCEL
# ─────────────────────────────────────────
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await owner_only(update):
        return ConversationHandler.END

    ctx.user_data.clear()
    await update.message.reply_text(
        "❌ Session cancelled.\nType /start to begin again."
    )
    return ConversationHandler.END

# ─────────────────────────────────────────
# UNAUTHORIZED FALLBACK
# ─────────────────────────────────────────
async def unauthorized(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.effective_message.reply_text(
            "⛔ Sorry, you are not authorized to use this bot."
        )

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    TIMEOUT_SECONDS = 600  # 10 minutes

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            UPLOADING: [
                MessageHandler(filters.Document.ALL, receive_file),
                CommandHandler("done", done_uploading),
                CommandHandler("help", help_command),
            ],
            SHOWING_BUTTONS: [
                CallbackQueryHandler(button_tapped),
            ],
            EDITING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_name),
            ],
            EDITING_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_link),
            ],
            CONFIRMING: [
                CallbackQueryHandler(confirm_apply),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.ALL, session_timeout),
        ],
        conversation_timeout=TIMEOUT_SECONDS,
    )

    app.add_handler(conv_handler)

    # Catch unauthorized users outside conversation
    app.add_handler(MessageHandler(filters.ALL, unauthorized))

    print("🤖 Bot started polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
