import os
import asyncio
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# Настройка логов (чтобы journalctl показывал события)
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
        [InlineKeyboardButton(text="Получить материал", callback_data="get_material")]
    ])
    await message.answer(
        """Если Вы зашли в этот бот, значит, тревога уже успела сильно нарушить в Вашу жизнь... То сердцебиение, то головокружение, то страх потерять рассудок😱

На самом деле всё не так хаотично, как кажется. Эти состояния имеют понятные изученные механизмы — и когда Вы поймёте их, Вы сможете взять происходящее под контроль.

📘 Я приготовил материал, который поможет Вам разобраться, что запускает панические атаки и как перестать им подчиняться.  
Скачайте его — и дайте отпор страху через знание! 💡""",
        reply_markup=kb
    )


# Хэндлер нажатия на кнопку "Получить материал"
@dp.callback_query(F.data == "get_material")
async def send_material(callback: CallbackQuery):
    if LINK:
        await callback.message.answer_document(document=LINK)
        await callback.answer()
    else:
        await callback.message.answer("⚠️ Ссылка на материал не найдена. Пожалуйста, попробуйте позже.")
        await callback.answer()


# Основной запуск
async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
