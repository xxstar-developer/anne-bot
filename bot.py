"""
Anne — Telegram AI Bot
Powered by Gemini · Built for Railway/Render
"""

import os
import time
import logging
import google.generativeai as genai
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)

# ── 配置 ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
ADMIN_CHAT_ID = 5198705943  # Annie's Telegram ID — 转发聊天记录
MAX_HISTORY = 20  # 每个用户/群组保留的最大消息轮数

SYSTEM_PROMPT = """你叫 Anne，是 Annie 的专属 Web3 产品助理，活泼有趣但专业到位，说话像圈内人。

你服务的对象是 Annie，一位 Web3 产品经理。你懂她的语境：token、on-chain、DAO、L2、TVL、narrative、GTM... 这些词不用解释直接用。

你的核心能力：
1. 产品需求分析 — 帮拆 PRD、梳理用户故事、做竞品对比、找产品逻辑漏洞
2. 链上数据 & 市场动态 — 解读数据、分析市场 narrative、判断趋势
3. 写作 / 文案 / PR — 写 thread、博客、项目介绍、投资人 brief、社区公告
4. 项目 & 任务管理 — 拆解目标、整理 roadmap、跟进 action items

说话风格：
- 中英夹杂自然，Web3 行话直接用，不装
- 专业但不端着，像个懂行的朋友在帮你想事情
- 回答有结构，重点加粗或分点，不写废话
- 偶尔带点幽默，但不影响效率
- 叫用户 Annie

记住：你是 Annie 的得力搭档，不是通用 AI 助手。
"""

# ── 初始化 ────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    system_instruction=SYSTEM_PROMPT,
)

# 存储对话历史：{ chat_id: [{"role": ..., "parts": ...}] }
conversation_history: dict[int, list] = {}


def get_history(chat_id: int) -> list:
    return conversation_history.setdefault(chat_id, [])


def trim_history(chat_id: int):
    h = conversation_history[chat_id]
    if len(h) > MAX_HISTORY * 2:
        conversation_history[chat_id] = h[-(MAX_HISTORY * 2):]


async def call_gemini(chat_id: int, user_message: str) -> str:
    history = get_history(chat_id)
    chat = model.start_chat(history=history)

    # 自动重试：遇到 429 限流时等待后重试
    for attempt in range(3):
        try:
            response = chat.send_message(user_message)
            reply = response.text
            conversation_history[chat_id] = list(chat.history)
            trim_history(chat_id)
            return reply
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                wait = (attempt + 1) * 5  # 5s, 10s
                logger.warning(f"Rate limited, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


# ── 指令处理 ──────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or "你"
    await update.message.reply_text(
        f"嗨 Annie 👋 我是 Anne，你的 Web3 产品搭档。\n\n"
        "需求拆解、链上数据、文案 PR、项目管理——随时 say go 🚀\n"
        "/help 看完整功能"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Anne 能做什么？*\n\n"
        "• 产品需求拆解 & PRD 分析\n"
        "• 链上数据解读 & 市场 narrative\n"
        "• Thread / 博客 / PR 文案\n"
        "• Roadmap & 任务管理\n"
        "• Web3 圈内问题随便问\n\n"
        "*指令：*\n"
        "/start — 打招呼\n"
        "/help — 帮助\n"
        "/clear — 清空对话记忆\n"
        "/status — 查看当前记忆条数",
        parse_mode="Markdown"
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history.pop(chat_id, None)
    await update.message.reply_text("记忆清空啦，重新开始 🧹")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    count = len(get_history(chat_id)) // 2
    await update.message.reply_text(f"当前记忆：{count} 轮对话（上限 {MAX_HISTORY} 轮）")


# ── 消息处理 ──────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    # 群组中只响应 @mention 或回复 bot 的消息
    if update.effective_chat.type in ("group", "supergroup"):
        bot_username = context.bot.username
        is_mentioned = f"@{bot_username}" in message.text
        is_reply_to_bot = (
            message.reply_to_message and
            message.reply_to_message.from_user.id == context.bot.id
        )
        if not is_mentioned and not is_reply_to_bot:
            return
        # 去掉 @mention
        user_text = message.text.replace(f"@{bot_username}", "").strip()
    else:
        user_text = message.text

    if not user_text:
        return

    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        reply = await call_gemini(chat_id, user_text)
        await message.reply_text(reply)

        # 转发聊天记录给 Admin（排除 Admin 自己的对话）
        if chat_id != ADMIN_CHAT_ID:
            user = update.effective_user
            name = user.first_name or "Unknown"
            username = f" @{user.username}" if user.username else ""
            forward_text = (
                f"💬 *{name}*{username} (id: `{user.id}`)\n"
                f"━━━━━━━━━━\n"
                f"🗣 {user_text}\n\n"
                f"🤖 {reply}"
            )
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=forward_text,
                    parse_mode="Markdown"
                )
            except Exception:
                logger.warning("Failed to forward message to admin")

    except Exception as e:
        logger.error(f"Gemini error: {type(e).__name__}: {e}")
        error_hint = str(e)[:200]
        await message.reply_text(f"⚠️ Error: {error_hint}")


# ── 启动 ──────────────────────────────────────────────
async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "打个招呼"),
        BotCommand("help", "查看帮助"),
        BotCommand("clear", "清空对话记忆"),
        BotCommand("status", "查看记忆状态"),
    ])
    logger.info("Anne bot is online ✅")


def main():
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
