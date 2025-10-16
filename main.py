import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# Загружаем настройки из .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
LINK = os.getenv("LINK_TO_MATERIAL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хэндлер команды /start
@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Получить материал", callback_data="get_material")]
    ])
    await message.answer(
        "Привет! Я подготовил бесплатный материал по улучшению сна. Дать ссылку?",
        reply_markup=kb
    )

# Хэндлер кнопки "Получить материал"
@dp.callback_query(F.data == "get_material")
async def send_material(callback: CallbackQuery):
    # 1) Ссылка
    await callback.message.answer(f"Вот ссылка на материал: {LINK}")

    # 2) Кружок (если file_id добавлен)
    VIDEO_NOTE_FILE_ID = os.getenv("VIDEO_NOTE_FILE_ID")  # добавь в .env, когда узнаешь
    if VIDEO_NOTE_FILE_ID:
        await bot.send_video_note(callback.from_user.id, video_note=VIDEO_NOTE_FILE_ID)
    else:
        await callback.message.answer("(Кружок пока не настроен — добавь VIDEO_NOTE_FILE_ID в .env)")

    # 3) Дополнительный текст
    await callback.message.answer("Короткий комментарий: начните с шага №1 сегодня вечером.")

    await callback.answer()

# Временный хэндлер для получения file_id кружка
@dp.message(F.video_note)
async def get_video_id(message: Message):
    await message.answer(f"file_id кружка:\n{message.video_note.file_id}")

# Запуск
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
