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

# -------------------- Хэндлер команды /start --------------------
@router.message(F.text == "/start")
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📘 Получить гайд", callback_data="get_material")]
    ])
    await message.answer(
        """Если Вы зашли в этот бот, значит, Ваши тревоги уже успели сильно вмешаться в жизнь. 
Частое сердцебиение 💓, потемнение в глазах 🌘, головокружение🌀, пот по спине😰, страх потерять рассудок...
Знакомо? 

Вероятно, Вы уже знаете, что такие наплывы страха называются паническими атаками. 
Эти состояния имеют чёткую внутреннюю закономерность - и когда Вы поймёте её, Вы сможете взять происходящее под контроль.

📘 Я приготовил материал, который поможет Вам разобраться, что запускает панические атаки, чем они поддерживаются и как перестать им подчиняться.  
Скачайте его — и дайте отпор страху! 💡""",
        reply_markup=kb
    )

# -------------------- Хэндлер нажатия на кнопку "Получить материал" --------------------
@router.callback_query(F.data == "get_material")
async def send_material(callback: CallbackQuery):
    # Сначала отправляем кружок
    if VIDEO_NOTE_FILE_ID:
        try:
            await bot.send_chat_action(chat_id=callback.message.chat.id, action="upload_video_note")
            await bot.send_video_note(chat_id=callback.message.chat.id, video_note=VIDEO_NOTE_FILE_ID)
            await asyncio.sleep(2)  # небольшая пауза, чтобы кружок успел отправиться
        except Exception as e:
            logger.warning(f"Не удалось отправить кружок: {e}")

    # Затем отправляем материал
    if LINK and os.path.exists(LINK):
        file = FSInputFile(LINK, filename="Выход из панического круга.pdf")
        await bot.send_document(chat_id=callback.message.chat.id, document=file, caption="Первый шаг сделан 💪")
    elif LINK and LINK.startswith("http"):
        await bot.send_message(chat_id=callback.message.chat.id, text=f"📘 Ваш материал доступен по ссылке: {LINK}")
    else:
        await bot.send_message(chat_id=callback.message.chat.id, text="⚠️ Файл не найден. Пожалуйста, попробуйте позже.")

    await callback.answer()

# -------------------- Запуск --------------------
async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
