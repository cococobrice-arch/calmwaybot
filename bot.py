import os
import asyncio
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile

# -------------------- Настройка логов --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- Загрузка переменных окружения --------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
LINK = os.getenv("LINK_TO_MATERIAL")
VIDEO_NOTE_FILE_ID = os.getenv("VIDEO_NOTE_FILE_ID")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")

# -------------------- Инициализация --------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# =========================================================
# 1. ПРИВЕТСТВЕННОЕ СООБЩЕНИЕ
# =========================================================
@router.message(F.text == "/start")
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📘 Получить гайд", callback_data="get_material")]
    ])
    await message.answer(
        """Если Вы зашли в этот бот, значит, Ваши тревоги уже успели сильно вмешаться в жизнь. 
Частое сердцебиение 💓, потемнение в глазах 🌘, головокружение🌀, пот по спине😰, страх потерять рассудок...
Знакомо? 

Вероятно, Вы уже знаете, что такие наплывы страха называются *паническими атаками*. 
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

    # Сначала отправляем кружок
    if VIDEO_NOTE_FILE_ID:
        try:
            await bot.send_chat_action(chat_id=chat_id, action="upload_video_note")
            await bot.send_video_note(chat_id=chat_id, video_note=VIDEO_NOTE_FILE_ID)
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Не удалось отправить кружок: {e}")

    # Затем отправляем материал
    if LINK and os.path.exists(LINK):
        file = FSInputFile(LINK, filename="Выход из панического круга.pdf")
        await bot.send_document(chat_id=chat_id, document=file, caption="Первый шаг сделан 💪")
    elif LINK and LINK.startswith("http"):
        await bot.send_message(chat_id=chat_id, text=f"📘 Ваш материал доступен по ссылке: {LINK}")
    else:
        await bot.send_message(chat_id=chat_id, text="⚠️ Файл не найден. Пожалуйста, попробуйте позже.")

    # Короткая пауза, чтобы не поменялся порядок сообщений
    await asyncio.sleep(2)

    # Планируем следующее сообщение через 2 минуты
    asyncio.create_task(send_followup_message(chat_id))

    await callback.answer()

# =========================================================
# 3. ОТЛОЖЕННОЕ СООБЩЕНИЕ
# =========================================================
async def send_followup_message(chat_id: int):
    await asyncio.sleep(120)  # 2 минуты задержки

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться", url="https://t.me/OcdAndAnxiety")]
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
    except Exception as e:
        logger.warning(f"Ошибка при отправке отложенного сообщения: {e}")

# =========================================================
# ЗАПУСК БОТА
# =========================================================
async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
