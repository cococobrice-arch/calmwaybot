import os
import asyncio
import logging
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.exceptions import TelegramBadRequest

# -------------------- Настройка логов --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- Загрузка переменных окружения --------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
LINK = os.getenv("LINK_TO_MATERIAL")
VIDEO_NOTE_FILE_ID = os.getenv("VIDEO_NOTE_FILE_ID")
DB_PATH = os.getenv("DATABASE_PATH", "users.db")
CHANNEL_USERNAME = "@OcdAndAnxiety"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")

# -------------------- Инициализация --------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# =========================================================
# 0. БАЗА ДАННЫХ
# =========================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            source TEXT,
            step TEXT,
            subscribed INTEGER DEFAULT 0,
            last_action TEXT
        )
    """)
    conn.commit()
    conn.close()

def update_user(user_id: int, step: str = None, subscribed: int = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = cursor.fetchone()

    if exists:
        if step:
            cursor.execute("UPDATE users SET step=?, last_action=? WHERE user_id=?",
                           (step, datetime.now(), user_id))
        if subscribed is not None:
            cursor.execute("UPDATE users SET subscribed=?, last_action=? WHERE user_id=?",
                           (subscribed, datetime.now(), user_id))
    else:
        cursor.execute("INSERT INTO users (user_id, source, step, subscribed, last_action) VALUES (?, ?, ?, ?, ?)",
                       (user_id, "unknown", step or "start", subscribed or 0, datetime.now()))
    conn.commit()
    conn.close()

init_db()

# =========================================================
# 1. ПРИВЕТСТВЕННОЕ СООБЩЕНИЕ
# =========================================================
@router.message(F.text == "/start")
async def cmd_start(message: Message):
    update_user(message.from_user.id, step="start")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📘 Получить гайд", callback_data="get_material")]
    ])
    await message.answer(
        """Если Вы зашли в этот бот, значит, Ваши тревоги уже успели сильно вмешаться в жизнь. 
Частое сердцебиение 💓, потемнение в глазах 🌘, головокружение🌀, пот по спине😰, страх потерять рассудок...
Знакомо? 

Вероятно, Вы уже знаете, что такие наплывы страха называются <b>паническими атаками</b>. 
Эти состояния имеют чёткую внутреннюю закономерность - и когда Вы поймёте её, Вы сможете взять происходящее под контроль.

🖊 Я приготовил материал, который поможет Вам разобраться, что запускает панические атаки, чем они поддерживаются и как перестать им подчиняться.  
Скачайте его — и дайте отпор страху! 💡""",
        reply_markup=kb
    )

# =========================================================
# 2. ОТПРАВКА ГАЙДА
# =========================================================
@router.callback_query(F.data == "get_material")
async def send_material(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    update_user(chat_id, step="got_material")

    # Отправляем кружок
    if VIDEO_NOTE_FILE_ID:
        try:
            await bot.send_chat_action(chat_id=chat_id, action="upload_video_note")
            await bot.send_video_note(chat_id=chat_id, video_note=VIDEO_NOTE_FILE_ID)
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Не удалось отправить кружок: {e}")

    # Отправляем материал
    if LINK and os.path.exists(LINK):
        file = FSInputFile(LINK, filename="Выход из панического круга.pdf")
        await bot.send_document(chat_id=chat_id, document=file, caption="Первый шаг сделан 💪")
    elif LINK and LINK.startswith("http"):
        await bot.send_message(chat_id=chat_id, text=f"📘 Ваш материал доступен по ссылке: {LINK}")
    else:
        await bot.send_message(chat_id=chat_id, text="⚠️ Файл не найден. Пожалуйста, попробуйте позже.")

    await asyncio.sleep(2)
    asyncio.create_task(send_followup_message(chat_id))
    await callback.answer()

# =========================================================
# 3. СООБЩЕНИЕ С ПРЕДЛОЖЕНИЕМ ПОДПИСАТЬСЯ
# =========================================================
async def send_followup_message(chat_id: int):
    await asyncio.sleep(20)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться на канал", url="https://t.me/OcdAndAnxiety")]
        ]
    )

    text = (
        "У меня есть телеграм-канал, в котором я делюсь полезными нюансами о противодействии тревоге, "
        "а также развеиваю мифы о <i>не</i>работающих методах и лекарствах. "
        "Никакой воды, только практически применимая информация! 💧❌\n\n"
        'Например, я <a href="https://t.me/OcdAndAnxiety/16">писал пост</a> о том, как неправильное дыхание усиливает паническую атаку.\n\n'
        "Подписывайтесь и получайте действенные рекомендации! 👇🏽"
    )

    try:
        await bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        update_user(chat_id, step="followup_sent")
        asyncio.create_task(schedule_next_message(chat_id))
    except Exception as e:
        logger.warning(f"Ошибка при отправке follow-up сообщения: {e}")

# =========================================================
# 4. ПРОВЕРКА ПОДПИСКИ И ОТПРАВКА СЛЕДУЮЩЕГО СООБЩЕНИЯ
# =========================================================
async def schedule_next_message(chat_id: int):
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, chat_id)
        status = member.status
        is_subscribed = status in ["member", "administrator", "creator"]
        update_user(chat_id, subscribed=1 if is_subscribed else 0)

        delay = 30 if is_subscribed else 120  # 30 секунд / 2 минуты
        logger.info(f"Пользователь {chat_id}: подписан={is_subscribed}, сообщение через {delay} сек")

        await asyncio.sleep(delay)
        await send_chat_invite(chat_id)
    except TelegramBadRequest as e:
        logger.warning(f"Не удалось проверить подписку: {e}")

# =========================================================
# 5. СООБЩЕНИЕ О ЧАТЕ
# =========================================================
async def send_chat_invite(chat_id: int):
    text = (
        "Кстати, у меня есть чат, в котором Вы можете задавать вопросы "
        "и делиться опытом с другими участниками: https://t.me/Ocd_and_Anxiety_Chat"
    )
    try:
        await bot.send_message(chat_id, text)
        update_user(chat_id, step="chat_invite_sent")
    except Exception as e:
        logger.warning(f"Ошибка при отправке приглашения в чат: {e}")

# =========================================================
# 6. ЗАПУСК
# =========================================================
async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
