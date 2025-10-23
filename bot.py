import os
import asyncio
import logging
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    FSInputFile
)
from aiogram.exceptions import TelegramBadRequest

# -------------------- Логи --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- Переменные окружения --------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
LINK = os.getenv("LINK_TO_MATERIAL")
VIDEO_NOTE_FILE_ID = os.getenv("VIDEO_NOTE_FILE_ID")
DB_PATH = os.getenv("DATABASE_PATH", "users.db")
CHANNEL_USERNAME = "@OcdAndAnxiety"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")

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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            user_id INTEGER,
            question INTEGER,
            answer TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp TEXT,
            action TEXT,
            details TEXT
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


def log_event(user_id: int, action: str, details: str = None):
    """Запись событий в таблицу events."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO events (user_id, timestamp, action, details) VALUES (?, ?, ?, ?)",
                   (user_id, datetime.now().isoformat(timespec='seconds'), action, details))
    conn.commit()
    conn.close()


init_db()

# =========================================================
# 1. ПРИВЕТСТВИЕ
# =========================================================
@router.message(F.text == "/start")
async def cmd_start(message: Message):
    update_user(message.from_user.id, step="start")
    log_event(message.from_user.id, "start", "Пользователь запустил бота")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📘 Получить гайд", callback_data="get_material")]
    ])
    await message.answer(
        """Если Вы зашли в этот бот, значит, Ваши тревоги уже успели сильно вмешаться в жизнь. 
Частое сердцебиение 💓, потемнение в глазах 🌘, головокружение🌀, пот по спине😰, страх потерять рассудок...
Знакомо? 

Вероятно, Вы уже знаете, что такие наплывы страха называются <b>паническими атаками</b>. 
Эти состояния имеют чёткую внутреннюю закономерность — и когда Вы поймёте её, Вы сможете взять происходящее под контроль.

🖊 Я приготовил материал, который поможет Вам разобраться, что запускает панические атаки, чем они поддерживаются и как перестать им подчиняться.  
Скачайте его — и дайте отпор страху! 💡""",
        parse_mode="HTML",
        reply_markup=kb
    )

# =========================================================
# 2. ОТПРАВКА ГАЙДА
# =========================================================
@router.callback_query(F.data == "get_material")
async def send_material(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    update_user(chat_id, step="got_material")
    log_event(chat_id, "get_material", "Пользователь получил гайд")

    if VIDEO_NOTE_FILE_ID:
        try:
            await bot.send_chat_action(chat_id, "upload_video_note")
            await bot.send_video_note(chat_id, VIDEO_NOTE_FILE_ID)
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Не удалось отправить кружок: {e}")

    if LINK and os.path.exists(LINK):
        file = FSInputFile(LINK, filename="Выход из панического круга.pdf")
        await bot.send_document(chat_id, document=file, caption="Первый шаг сделан 💪")
    elif LINK and LINK.startswith("http"):
        await bot.send_message(chat_id, f"📘 Ваш материал доступен по ссылке: {LINK}")
    else:
        await bot.send_message(chat_id, "⚠️ Файл не найден. Попробуйте позже.")

    asyncio.create_task(check_subscription_and_invite(chat_id))
    await callback.answer()

# =========================================================
# 3. ПРОВЕРКА ПОДПИСКИ И ПРИГЛАШЕНИЕ НА КАНАЛ
# =========================================================
async def check_subscription_and_invite(chat_id: int):
    """Проверяет подписку и при необходимости отправляет приглашение на канал."""
    await asyncio.sleep(10)
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, chat_id)
        status = member.status
        is_subscribed = status in ["member", "administrator", "creator"]
        update_user(chat_id, subscribed=1 if is_subscribed else 0)
        log_event(chat_id, "subscription_checked", f"Подписан: {is_subscribed}")
    except TelegramBadRequest:
        is_subscribed = False
        update_user(chat_id, subscribed=0)
        log_event(chat_id, "subscription_checked", "Ошибка при проверке подписки")

    if not is_subscribed:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Подписаться на канал", url="https://t.me/OcdAndAnxiety")]
            ]
        )
        text = (
            "У меня есть телеграм-канал, где я делюсь нюансами о преодолении тревоги "
            "и развеиваю мифы о <i>не</i>работающих методах. "
            "Никакой воды — только проверенные решения. 💧❌\n\n"
            'Например, я <a href="https://t.me/OcdAndAnxiety/16">писал пост</a> о том, как неправильное дыхание усиливает паническую атаку.\n\n'
            "Подписывайтесь и получайте практические рекомендации 👇🏽"
        )
        await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
        log_event(chat_id, "channel_invite_sent", "Отправлено приглашение подписаться на канал")

    asyncio.create_task(send_after_material(chat_id))

# =========================================================
# 4. ОПРОС ПО ИЗБЕГАНИЮ
# =========================================================
async def send_after_material(chat_id: int):
    await asyncio.sleep(10)
    await send_avoidance_intro(chat_id)

avoidance_questions = [
    "Вы часто измеряете давление или пульс?",
    "Носите с собой бутылку воды?",
    "Отказались от спорта из-за опасений?",
    "Стараетесь не оставаться в одиночестве?",
    "Часто открываете окно, чтобы «стало легче»?",
    "Предпочитаете садиться поближе к выходу?",
    "Отвлекаетесь в телефон, чтобы не замечать ощущения?",
    "Избегаете поездок за город из страха остаться без связи?"
]

@router.callback_query(F.data == "avoidance_start")
async def start_avoidance_test(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    await callback.answer()
    update_user(chat_id, step="avoidance_test")
    log_event(chat_id, "avoidance_test_started", "Начат опрос избегания")
    await bot.send_message(chat_id, "Опрос: давайте проверим, правильно ли Вы действуете. Ответьте на 8 вопросов.")
    await send_question(chat_id, 0)

async def send_avoidance_intro(chat_id: int):
    text = (
        "Что Вы почувствовали после гайда?\n\n"
        "Давайте проверим, насколько выражено избегание ситуаций, связанных со страхом.\n"
        "🧩 Пройдите короткий тест — всего 8 вопросов."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Начать опрос", callback_data="avoidance_start")]])
    await bot.send_message(chat_id, text, reply_markup=kb)

async def send_question(chat_id: int, index: int):
    if index >= len(avoidance_questions):
        await finish_test(chat_id)
        return
    q = avoidance_questions[index]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"ans_yes_{index}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"ans_no_{index}")
        ]
    ])
    await bot.send_message(chat_id, f"{index+1}/8. {q}", reply_markup=kb)

@router.callback_query(F.data.startswith("ans_"))
async def handle_answer(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    _, ans, idx = callback.data.split("_")
    idx = int(idx)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO answers (user_id, question, answer) VALUES (?, ?, ?)", (chat_id, idx, ans))
    conn.commit()
    conn.close()
    log_event(chat_id, "avoidance_answer", f"Вопрос {idx+1}: {ans.upper()}")
    await callback.answer()
    await send_question(chat_id, idx + 1)

async def finish_test(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT answer FROM answers WHERE user_id=?", (chat_id,))
    answers = [row[0] for row in cursor.fetchall()]
    conn.close()

    yes_count = answers.count("yes")
    update_user(chat_id, step="avoidance_done")
    log_event(chat_id, "avoidance_test_finished", f"Ответов 'ДА': {yes_count}")

    if yes_count >= 4:
        text = (
            "✅ Тест завершён.\n\n"
            "У Вас выраженное избегание. Похоже, многие действия направлены на предотвращение страха, "
            "и это может мешать восстановлению. "
            "Хорошая новость: избегание можно постепенно ослабить — именно этому я учу своих пациентов."
        )
    else:
        text = (
            "✅ Тест завершён.\n\n"
            "Отлично! Вы не позволяете тревоге управлять решениями и уже делаете многое правильно. "
            "Тем не менее полезно продолжить укреплять уверенность — чтобы страх больше не диктовал границы Вашей жизни."
        )

    await bot.send_message(chat_id, text)
    asyncio.create_task(send_case_story(chat_id))

# =========================================================
# 5. ИСТОРИЯ ПАЦИЕНТА, ЧАТ, КОНСУЛЬТАЦИЯ
# =========================================================
async def send_case_story(chat_id: int):
    await asyncio.sleep(10)
    text = (
        "История пациента: как страх становится привычкой.\n\n"
        "Одна моя пациентка несколько лет избегала поездок в метро, опасаясь, что станет плохо. "
        "Но чем больше она избегала, тем сильнее закреплялся страх. "
        "Мы начали постепенно возвращать эти ситуации — и паника утратила власть."
    )
    await bot.send_message(chat_id, text)
    update_user(chat_id, step="case_story")
    log_event(chat_id, "case_story_sent", "Отправлена история пациента")
    asyncio.create_task(send_chat_invite(chat_id))

async def send_chat_invite(chat_id: int):
    await asyncio.sleep(10)
    text = (
        "В таких историях часто помогает общение с теми, кто уже идёт по этому пути. "
        "У меня есть чат, где можно задать вопросы и обсудить опыт с другими участниками: "
        "https://t.me/Ocd_and_Anxiety_Chat"
    )
    await bot.send_message(chat_id, text)
    update_user(chat_id, step="chat_invite_sent")
    log_event(chat_id, "chat_invite_sent", "Приглашение в чат отправлено")
    asyncio.create_task(send_self_disclosure(chat_id))

async def send_self_disclosure(chat_id: int):
    await asyncio.sleep(10)
    text = (
        "Иногда и мне важно обсуждать сложные случаи с коллегами. "
        "Живое общение даёт больше, чем книги или технологии. "
        "Так я строю свои консультации — живое присутствие и понимание без шаблонов."
    )
    await bot.send_message(chat_id, text)
    update_user(chat_id, step="self_disclosure")
    log_event(chat_id, "self_disclosure_sent", "Отправлено сообщение самораскрытия")
    asyncio.create_task(send_consultation_offer(chat_id))

async def send_consultation_offer(chat_id: int):
    await asyncio.sleep(10)
    text = (
        "Если хотите пойти глубже — обсудим не только панические атаки, "
        "но и темы сна и обсессивных мыслей. "
        "🕊 Я провожу индивидуальные консультации, где мы работаем с корнями страха.\n\n"
        "Записаться можно здесь: https://лечение-паники.рф"
    )
    await bot.send_message(chat_id, text)
    update_user(chat_id, step="consultation_offer")
    log_event(chat_id, "consultation_offer_sent", "Отправлено предложение консультации")

# =========================================================
# 6. ЗАПУСК
# =========================================================
async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
