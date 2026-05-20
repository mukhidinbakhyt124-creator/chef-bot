import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import anthropic

# ── Логирование ─────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Клиент Anthropic ─────────────────────────────────────────────────────────
anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = """Ты — дружелюбный шеф-повар-помощник по имени «Шеф Алибек».
Твоя задача — помогать людям готовить вкусные блюда из тех продуктов, которые у них есть дома.

Правила:
1. Всегда отвечай на русском языке.
2. Когда пользователь называет продукты — предложи 2–3 блюда (только названия + 1 строка описания).
3. Когда пользователь выбирает блюдо — дай чёткий пошаговый рецепт с временем готовки.
4. Учитывай диетические ограничения, если пользователь их упоминает.
5. Будь позитивным, добавляй 1–2 кулинарных совета.
6. Если продуктов совсем мало — предложи что-то простое и ободри пользователя.
7. Форматируй рецепты красиво: используй эмодзи, разделяй шаги."""

# ── Хранилище сессий (в памяти) ──────────────────────────────────────────────
user_sessions: dict[int, list[dict]] = {}


def get_history(user_id: int) -> list[dict]:
    return user_sessions.setdefault(user_id, [])


def add_message(user_id: int, role: str, content: str) -> None:
    history = get_history(user_id)
    history.append({"role": role, "content": content})
    # Держим не более 20 сообщений (10 пар)
    if len(history) > 20:
        user_sessions[user_id] = history[-20:]


def ask_claude(user_id: int, user_text: str) -> str:
    add_message(user_id, "user", user_text)
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=get_history(user_id),
    )
    reply = response.content[0].text
    add_message(user_id, "assistant", reply)
    return reply


# ── Хэндлеры ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_sessions.pop(user_id, None)  # сброс истории

    keyboard = [
        [InlineKeyboardButton("🥗 Здоровое питание", callback_data="diet_healthy")],
        [InlineKeyboardButton("🍖 Мясные блюда", callback_data="diet_meat")],
        [InlineKeyboardButton("🌿 Вегетарианское", callback_data="diet_veg")],
        [InlineKeyboardButton("⚡ Быстро (до 15 мин)", callback_data="diet_fast")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👨‍🍳 *Привет! Я Шеф Алибек — твой личный кулинарный помощник!*\n\n"
        "Просто напиши, какие продукты у тебя есть дома, и я предложу вкусные рецепты.\n\n"
        "Например:\n"
        "• _«Яйца, помидоры, лук, сыр»_\n"
        "• _«Курица, картошка, морковь»_\n"
        "• _«Только макароны и масло»_ 😄\n\n"
        "Или выбери предпочтение:",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "ℹ️ *Как пользоваться ботом:*\n\n"
        "1️⃣ Напиши список продуктов, которые есть дома\n"
        "2️⃣ Выбери понравившееся блюдо из моих предложений\n"
        "3️⃣ Получи подробный рецепт\n"
        "4️⃣ Готовь и наслаждайся! 🍽️\n\n"
        "Команды:\n"
        "/start — начать заново\n"
        "/clear — очистить историю\n"
        "/help — эта справка",
        parse_mode="Markdown",
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_sessions.pop(update.effective_user.id, None)
    await update.message.reply_text(
        "🗑️ История очищена! Напиши новые продукты — придумаем что-нибудь вкусное."
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    messages_map = {
        "diet_healthy": "Я предпочитаю здоровое питание. Что можно приготовить полезного?",
        "diet_meat":    "Я люблю мясные блюда. Что посоветуешь?",
        "diet_veg":     "Я вегетарианец. Какие блюда без мяса можешь предложить?",
        "diet_fast":    "Мне нужно что-то быстрое — не дольше 15 минут. Что приготовить?",
    }

    user_text = messages_map.get(query.data, "Расскажи, что можно приготовить.")
    await query.edit_message_text(f"✅ Выбрано: _{user_text}_", parse_mode="Markdown")

    await context.bot.send_chat_action(query.message.chat_id, "typing")
    reply = ask_claude(query.from_user.id, user_text)
    await context.bot.send_message(query.message.chat_id, reply, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text.strip()
    if not user_text:
        return

    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        reply = ask_claude(update.effective_user.id, user_text)
        await update.message.reply_text(reply, parse_mode="Markdown")
    except Exception as e:
        logger.error("Claude API error: %s", e)
        await update.message.reply_text(
            "⚠️ Что-то пошло не так. Попробуй ещё раз или напиши /start."
        )


# ── Запуск ───────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("Укажи TELEGRAM_BOT_TOKEN в переменных окружения!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🍳 Шеф Алибек запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
