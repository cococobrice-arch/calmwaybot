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
        "Если Вы зашли в этот бот, значит, тревога уже успела сильно вмешаться в Вашу жизнь — то сердцебиение, то головокружение, то страх потерять рассудок.

На самом деле всё не так хаотично, как кажется. Эти состояния имеют чёткую внутреннюю закономерность - и когда Вы поймёте её, Вы сможете взять происходящее под контроль.

📘 Я приготовил материал, который поможет Вам разобраться, что запускает панические атаки и как перестать им подчиняться.  
Скачайте его — и дайте отпор страху через знание! 💡",
        reply_markup=kb
    )


# Хэндлер кнопки "Получить материал"
@dp.callback_query(F.data == "get_material")
async def send_material(callback: CallbackQuery):
    await callback.message.answer(f"Вот ссылка на материал: {LINK or '(ссылка пока не настроена)'}")

    VIDEO_NOTE_FILE_ID = os.getenv("VIDEO_NOTE_FILE_ID")
    if VIDEO_NOTE_FILE_ID:
        await bot.send_video_note(callback.from_user.id, video_note=VIDEO_NOTE_FILE_ID)
    else:
        await callback.message.answer("(Кружок пока не настроен — добавь VIDEO_NOTE_FILE_ID в .env)")

    await callback.message.answer("Короткий комментарий: начните с шага №1 сегодня вечером.")
    await callback.answer()


# Временный хэндлер для получения file_id кружка
@dp.message(F.video_note)
async def get_video_id(message: Message):
    await message.answer(f"file_id кружка:\n{message.video_note.file_id}")


async def main():
    logger.info("🤖 CalmWayBot is starting polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped gracefully.")
