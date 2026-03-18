"""
Samuraizer Telegram Bot
Send URLs to the bot → they get analyzed and saved to the knowledge base.

Commands:
  /help    — show all commands
  /list    — browse KB with pagination
  /search  — search entries
  /setcat  — change an entry's category
  /suggest — get a random unread item (also sent automatically every N hours)

Setup:
  1. Create a bot via @BotFather and get the token
  2. Add TELEGRAM_BOT_TOKEN to your .env
  3. Optionally set DIGEST_INTERVAL_HOURS (default: 8)
  4. Run: python telegram_bot.py   (while server.py is also running)
"""

import os
import re
import json
import time
import logging
import requests
from datetime import timedelta

from telegram import Update, constants, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, MessageHandler, CommandHandler, CallbackQueryHandler,
    filters, ContextTypes,
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BOT_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SERVER_URL     = os.environ.get("SAMURAIZER_URL", "http://localhost:8000")
DIGEST_HOURS   = float(os.environ.get("DIGEST_INTERVAL_HOURS", "8"))
PAGE_SIZE      = 10

CATEGORY_EMOJI = {
    "tool":     "🔧",
    "agent":    "🤖",
    "mcp":      "🔌",
    "list":     "📋",
    "workflow": "🔄",
    "cve":      "🚨",
    "article":  "📄",
    "video":    "🎥",
    "playlist": "🎬",
    "skill":    "📚",
}

URL_RE = re.compile(r'https?://[^\s<>"\']+')

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📋 /list"),    KeyboardButton("🔍 /search")],
        [KeyboardButton("💡 /suggest"), KeyboardButton("✏️ /setcat")],
        [KeyboardButton("❓ /help")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Send a URL or pick a command…",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(URL_RE.findall(text)))


def _cat_emoji(category: str) -> str:
    return CATEGORY_EMOJI.get(category, "📌")


def _esc(text: str) -> str:
    """Escape special chars for Telegram MarkdownV2."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def _register_chat(bot_data: dict, chat_id: int):
    bot_data.setdefault("chat_ids", set()).add(chat_id)


def _fetch(path: str, **kwargs):
    return requests.get(f"{SERVER_URL}{path}", timeout=10, **kwargs)


def _patch(path: str, **kwargs):
    return requests.patch(f"{SERVER_URL}{path}", timeout=10, **kwargs)


# ---------------------------------------------------------------------------
# /help  /start
# ---------------------------------------------------------------------------

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_chat(context.bot_data, update.effective_chat.id)
    text = (
        "🥷 *Samuraizer*\n"
        "_Your cyber\\-security knowledge base_\n\n"
        "*📥 Analyze URLs*\n"
        "Just send any URL and I'll summarize it\\.\n\n"
        "*📚 Browse*\n"
        "/list — Browse all entries \\(paginated\\)\n"
        "/search \\<query\\> — Full\\-text search\n\n"
        "*✏️ Manage*\n"
        "/setcat \\<id\\> \\<category\\> — Change category\n"
        "_Example:_ `/setcat 42 tool`\n\n"
        "*💡 Discover*\n"
        "/suggest — Random unread item\n"
        f"_Auto\\-suggest every {_esc(str(int(DIGEST_HOURS)))}h_\n\n"
        "*Categories:*\n"
        "tool · agent · mcp · list · workflow\n"
        "cve · article · video · playlist"
    )
    await update.message.reply_text(
        text, parse_mode=constants.ParseMode.MARKDOWN_V2, reply_markup=MAIN_KEYBOARD
    )


# ---------------------------------------------------------------------------
# /list  (paginated)
# ---------------------------------------------------------------------------

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_chat(context.bot_data, update.effective_chat.id)
    page = int(context.args[0]) if context.args else 1
    try:
        entries = _fetch("/entries").json()
    except Exception as exc:
        await update.message.reply_text(f"❌ Could not fetch entries: {exc}")
        return
    text, markup = _build_list_page(entries, page)
    await update.message.reply_text(
        text, parse_mode=constants.ParseMode.MARKDOWN_V2, reply_markup=markup
    )


def _build_list_page(entries: list, page: int):
    total  = len(entries)
    if not total:
        return "📭 Your knowledge base is empty\\. Send me a URL to get started\\!", None

    pages  = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page   = max(1, min(page, pages))
    chunk  = entries[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    lines  = [f"📚 *Knowledge Base* — {total} entries\n"]
    for e in chunk:
        emoji  = _cat_emoji(e["category"])
        name   = _esc((e["name"] or e["url"])[:48])
        read_m = "●" if e.get("read") else "○"
        lines.append(f"{read_m} {emoji} `[{e['id']}]` {name}")

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀", callback_data=f"list:{page-1}"))
    buttons.append(InlineKeyboardButton(f"{page} / {pages}", callback_data="noop"))
    if page < pages:
        buttons.append(InlineKeyboardButton("▶", callback_data=f"list:{page+1}"))

    markup = InlineKeyboardMarkup([buttons]) if len(buttons) > 1 else None
    return "\n".join(lines), markup


# ---------------------------------------------------------------------------
# /setcat <id> <category>
# ---------------------------------------------------------------------------

async def cmd_setcat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_chat(context.bot_data, update.effective_chat.id)
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/setcat <id> <category>`\nExample: `/setcat 42 tool`",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    try:
        entry_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID must be a number\\.", parse_mode=constants.ParseMode.MARKDOWN_V2)
        return

    category = context.args[1].lower().strip()

    try:
        resp = _patch(f"/entries/{entry_id}", json={"category": category})
        if resp.status_code == 404:
            await update.message.reply_text(f"❌ Entry `#{entry_id}` not found\\.", parse_mode=constants.ParseMode.MARKDOWN_V2)
            return
        if not resp.ok:
            err = resp.json().get("error", resp.text)
            await update.message.reply_text(f"❌ {_esc(err)}", parse_mode=constants.ParseMode.MARKDOWN_V2)
            return

        entry = resp.json()
        emoji = _cat_emoji(category)
        name  = _esc(entry.get("name") or f"Entry #{entry_id}")
        await update.message.reply_text(
            f"{emoji} *{name}*\n✅ Category → `{_esc(category)}`",
            parse_mode=constants.ParseMode.MARKDOWN_V2,
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ {_esc(str(exc))}", parse_mode=constants.ParseMode.MARKDOWN_V2)


# ---------------------------------------------------------------------------
# /search <query>
# ---------------------------------------------------------------------------

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_chat(context.bot_data, update.effective_chat.id)
    if not context.args:
        await update.message.reply_text(
            "Usage: `/search <query>`", parse_mode=constants.ParseMode.MARKDOWN
        )
        return

    q = " ".join(context.args)
    try:
        entries = _fetch("/entries", params={"search": q}).json()
    except Exception as exc:
        await update.message.reply_text(f"❌ {_esc(str(exc))}", parse_mode=constants.ParseMode.MARKDOWN_V2)
        return

    if not entries:
        await update.message.reply_text(
            f"🔍 No results for *{_esc(q)}*", parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        return

    lines = [f"🔍 *{len(entries)} result{'s' if len(entries) != 1 else ''} for* `{_esc(q)}`\n"]
    for e in entries[:15]:
        emoji = _cat_emoji(e["category"])
        name  = _esc((e["name"] or e["url"])[:50])
        read_m = "●" if e.get("read") else "○"
        lines.append(f"{read_m} {emoji} `[{e['id']}]` {name}")

    if len(entries) > 15:
        lines.append(f"\n_…and {len(entries) - 15} more — use /list to browse_")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=constants.ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
    )


# ---------------------------------------------------------------------------
# /suggest  +  periodic digest
# ---------------------------------------------------------------------------

async def cmd_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_chat(context.bot_data, update.effective_chat.id)
    await _send_suggest(context, update.effective_chat.id, reply_to=update.message)


async def _send_suggest(context, chat_id: int, reply_to=None, exclude_id: int = None):
    try:
        params = {"exclude": exclude_id} if exclude_id else {}
        entry  = _fetch("/suggest", params=params).json()
    except Exception as exc:
        msg = f"❌ {_esc(str(exc))}"
        if reply_to:
            await reply_to.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN_V2)
        return

    if not entry:
        msg = "🎉 You've read everything\\! Nothing left unread\\."
        if reply_to:
            await reply_to.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN_V2)
        return

    text   = _format_suggest_card(entry)
    markup = _suggest_markup(entry["id"])
    kwargs = dict(parse_mode=constants.ParseMode.MARKDOWN_V2,
                  disable_web_page_preview=True, reply_markup=markup)

    if reply_to:
        await reply_to.reply_text(text, **kwargs)
    else:
        await context.bot.send_message(chat_id, text, **kwargs)


def _format_suggest_card(entry: dict) -> str:
    emoji    = _cat_emoji(entry["category"])
    name     = _esc(entry.get("name") or "—")
    cat      = _esc(entry["category"].upper())
    bullets  = "\n".join(f"  • {_esc(b)}" for b in entry["bullets"])
    tags     = entry.get("tags", [])
    tags_str = "  " + " ".join(f"\\#{_esc(t)}" for t in tags) if tags else ""
    url      = entry["url"]
    short    = _esc((url[:60] + "…") if len(url) > 63 else url)
    preview  = entry.get("preview", "")
    prev_str = f"\n\n_{_esc(preview[:200])}…_" if preview else ""

    return (
        f"📖 *Suggested Read*\n\n"
        f"{emoji} *{name}*  `{cat}`\n\n"
        f"{bullets}\n"
        f"{tags_str}{prev_str}\n\n"
        f"[{short}]({url})"
    )


def _suggest_markup(entry_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Mark as read", callback_data=f"read:{entry_id}"),
        InlineKeyboardButton("⏭ Skip",         callback_data=f"skip:{entry_id}"),
    ]])


async def _digest_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs every DIGEST_HOURS — sends a suggested unread item to all known chats."""
    for chat_id in context.bot_data.get("chat_ids", set()):
        try:
            await _send_suggest(context, chat_id)
        except Exception as exc:
            logger.warning("Digest failed for chat %s: %s", chat_id, exc)


# ---------------------------------------------------------------------------
# Callback queries  (list pagination · mark-read · skip)
# ---------------------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "noop":
        return

    # ── list pagination ──────────────────────────────────────────────────────
    if data.startswith("list:"):
        page = int(data.split(":")[1])
        try:
            entries = _fetch("/entries").json()
        except Exception:
            return
        text, markup = _build_list_page(entries, page)
        await query.edit_message_text(
            text, parse_mode=constants.ParseMode.MARKDOWN_V2, reply_markup=markup
        )

    # ── mark as read ─────────────────────────────────────────────────────────
    elif data.startswith("read:"):
        entry_id = int(data.split(":")[1])
        try:
            _patch(f"/entries/{entry_id}/read")
        except Exception:
            pass
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Read", callback_data="noop"),
            ]])
        )

    # ── skip to next suggestion ───────────────────────────────────────────────
    elif data.startswith("skip:"):
        entry_id = int(data.split(":")[1])
        try:
            entry = _fetch("/suggest", params={"exclude": entry_id}).json()
        except Exception:
            return
        if not entry:
            await query.edit_message_text(
                "🎉 No more unread items\\!", parse_mode=constants.ParseMode.MARKDOWN_V2
            )
            return
        await query.edit_message_text(
            _format_suggest_card(entry),
            parse_mode=constants.ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
            reply_markup=_suggest_markup(entry["id"]),
        )


# ---------------------------------------------------------------------------
# URL message handler
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_chat(context.bot_data, update.effective_chat.id)

    text = update.message.text or update.message.caption or ""
    urls = extract_urls(text)
    if not urls:
        return

    chat_id = update.effective_chat.id
    count   = len(urls)
    logger.info("Received %d URL(s) from chat %s", count, chat_id)

    status = await update.message.reply_text(
        f"🔍 Analyzing {count} URL{'s' if count > 1 else ''}…"
    )

    body        = {"url": urls[0]} if count == 1 else {"urls": urls}
    results     = []
    errors      = []
    last_edit_t = 0.0

    async def _update_status(msg: str):
        nonlocal last_edit_t
        if time.time() - last_edit_t < 1.0:
            return
        last_edit_t = time.time()
        try:
            await status.edit_text(msg)
        except Exception:
            pass

    try:
        with requests.post(
            f"{SERVER_URL}/analyze", json=body, stream=True, timeout=300
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            for chunk in resp.iter_content(chunk_size=None):
                buffer += chunk.decode("utf-8", errors="replace")
                lines, buffer = buffer.split("\n"), ""
                buffer = lines.pop()
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    url       = msg.get("url", "")
                    short_url = (url[:45] + "…") if len(url) > 48 else url
                    if msg.get("log"):
                        done  = len(results) + len(errors)
                        label = f"({done}/{count}) " if count > 1 else ""
                        await _update_status(
                            f"🔍 {label}`{short_url}`\n› {msg['log']}"
                        )
                    elif msg.get("entry"):
                        results.append((url, msg["entry"]))
                        done = len(results) + len(errors)
                        await _update_status(
                            f"✅ {done}/{count} done — analyzing next…"
                            if done < count else "✅ Done\\! Sending results…"
                        )
                    elif msg.get("error"):
                        errors.append((url, msg["error"]))
                        done = len(results) + len(errors)
                        await _update_status(f"⚠️ {done}/{count} — {msg['error'][:60]}")

    except requests.exceptions.ConnectionError:
        await status.edit_text(
            "❌ Cannot reach Samuraizer server.\nMake sure `python server.py` is running."
        )
        return
    except Exception as exc:
        logger.exception("Stream error")
        await status.edit_text(f"❌ Error: {exc}")
        return

    try:
        await status.delete()
    except Exception:
        pass

    for url, entry in results:
        await _send_result_card(context, chat_id, entry)

    for url, err in errors:
        short = (url[:50] + "…") if len(url) > 53 else url
        await context.bot.send_message(
            chat_id,
            f"❌ *Failed*\n`{short}`\n_{_esc(err)}_",
            parse_mode=constants.ParseMode.MARKDOWN_V2,
        )

    if not results and not errors:
        await context.bot.send_message(chat_id, "⚠️ No results returned\\.", parse_mode=constants.ParseMode.MARKDOWN_V2)


async def _send_result_card(context, chat_id: int, entry: dict):
    emoji   = _cat_emoji(entry["category"])
    name    = _esc(entry.get("name") or "—")
    cat     = _esc(entry["category"].upper())
    bullets = "\n".join(f"  • {_esc(b)}" for b in entry["bullets"])
    tags    = entry.get("tags", [])
    tags_str = "  " + " ".join(f"\\#{_esc(t)}" for t in tags) if tags else ""
    url     = entry["url"]
    short   = _esc((url[:60] + "…") if len(url) > 63 else url)

    text = (
        f"{emoji} *{name}*  `{cat}`\n"
        f"\n{bullets}\n"
        f"{tags_str}\n"
        f"\n[{short}]({url})"
    )

    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Mark as read", callback_data=f"read:{entry['id']}"),
    ]])

    await context.bot.send_message(
        chat_id, text,
        parse_mode=constants.ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
        reply_markup=markup,
    )


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN not set.\n"
            "Add it to your .env file and restart."
        )

    logger.info("Starting Samuraizer Telegram bot…")
    logger.info("Server: %s | Auto-suggest every %.1fh", SERVER_URL, DIGEST_HOURS)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",   cmd_help))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("list",    cmd_list))
    app.add_handler(CommandHandler("setcat",  cmd_setcat))
    app.add_handler(CommandHandler("search",  cmd_search))
    app.add_handler(CommandHandler("suggest", cmd_suggest))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, handle_message))

    app.job_queue.run_repeating(
        _digest_job,
        interval=timedelta(hours=DIGEST_HOURS),
        first=timedelta(hours=DIGEST_HOURS),
    )

    logger.info("Bot is running — send /help on Telegram.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
