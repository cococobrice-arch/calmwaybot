import os
import asyncio
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile

# Настройка логов (для journalctl)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
LINK = os.getenv("LINK_TO_MATERIAL")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# Хэндлер команды /start
@dp.message(F.text == "/start")
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


# Хэндлер нажатия на кнопку "Получить материал"
@dp.callback_query(F.data == "get_material")
async def send_material(callback: CallbackQuery):
    if LINK and os.path.exists(LINK):
        file = FSInputFile(LINK, filename="Выход из панического круга.pdf")
        await callback.message.answer_document(file, caption="Первый шаг сделан 💪")
        await callback.answer()
    else:
        await callback.message.answer("⚠️ Файл не найден. Пожалуйста, попробуйте позже.")
        await callback.answer()


# Временный хэндлер для получения file_id кружка
@dp.message(F.video_note)
async def get_video_note_id(message: Message):
    await message.answer(f"File ID кружка:\n{message.video_note.file_id}")


# Основной запуск
async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
