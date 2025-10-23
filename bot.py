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
    FSInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton
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
# 1. ПРИВЕТСТВИЕ
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
Эти состояния имеют чёткую внутреннюю закономерность — и когда Вы поймёте её, Вы сможете взять происходящее под контроль.

🖊 Я приготовил материал, который поможет Вам разобраться, что запускает панические атаки, чем они поддерживаются и как перестать им подчиняться.  
Скачайте его — и дайте отпор страху! 💡""",
        reply_markup=kb,
        parse_mode="HTML"
    )

# =========================================================
# 2. ОТПРАВКА ГАЙДА
# =========================================================
@router.callback_query(F.data == "get_material")
async def send_material(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    update_user(chat_id, step="got_material")

    # кружок
    if VIDEO_NOTE_FILE_ID:
        try:
            await bot.send_chat_action(chat_id=chat_id, action="upload_video_note")
            await bot.send_video_note(chat_id=chat_id, video_note=VIDEO_NOTE_FILE_ID)
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"Не удалось отправить кружок: {e}")

    # материал
    if LINK and os.path.exists(LINK):
        file = FSInputFile(LINK, filename="Выход из панического круга.pdf")
        await bot.send_document(chat_id=chat_id, document=file, caption="Первый шаг сделан 💪")
    elif LINK and LINK.startswith("http"):
        await bot.send_message(chat_id=chat_id, text=f"📘 Ваш материал доступен по ссылке: {LINK}")
    else:
        await bot.send_message(chat_id=chat_id, text="⚠️ Файл не найден. Пожалуйста, попробуйте позже.")

    asyncio.create_task(send_followup_message(chat_id))
    await callback.answer()

# =========================================================
# 3. ПОДПИСКА НА КАНАЛ
# =========================================================
async def send_followup_message(chat_id: int):
    await asyncio.sleep(10)
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
# 4. ПРОВЕРКА ПОДПИСКИ
# =========================================================
async def schedule_next_message(chat_id: int):
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, chat_id)
        is_subscribed = member.status in ["member", "administrator", "creator"]
        update_user(chat_id, subscribed=1 if is_subscribed else 0)
        await asyncio.sleep(10)
        asyncio.create_task(send_chat_invite(chat_id))
    except TelegramBadRequest as e:
        logger.warning(f"Не удалось проверить подписку: {e}")

# =========================================================
# 5. ПРИГЛАШЕНИЕ В ЧАТ
# =========================================================
async def send_chat_invite(chat_id: int):
    try:
        await bot.send_message(
            chat_id,
            "Кстати, у меня есть чат, где можно задать вопросы и обсудить опыт с другими участниками: "
            "https://t.me/Ocd_and_Anxiety_Chat"
        )
        update_user(chat_id, step="chat_invite_sent")
        asyncio.create_task(send_next_message(chat_id))
    except Exception as e:
        logger.warning(f"Ошибка при отправке приглашения в чат: {e}")

# =========================================================
# 6. ВОРОНКА
# =========================================================
SCENARIO_ORDER = [
    "start", "got_material", "followup_sent", "chat_invite_sent",
    "avoidance_offer", "avoidance_done", "case_story", "self_disclosure", "consultation_offer"
]
SCENARIO_FLOW = {
    "chat_invite_sent": "avoidance_offer",
    "avoidance_offer": "case_story",
    "case_story": "self_disclosure",
    "self_disclosure": "consultation_offer"
}

def get_user_step(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT step FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "start"

def update_user_step(user_id: int, step: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET step=?, last_action=? WHERE user_id=?", (step, datetime.now(), user_id))
    conn.commit()
    conn.close()

# =========================================================
# 7. ПЕРЕХОДЫ
# =========================================================
async def send_next_message(chat_id: int):
    current_step = get_user_step(chat_id)
    next_step = SCENARIO_FLOW.get(current_step)
    if next_step == "avoidance_offer":
        asyncio.create_task(send_avoidance_offer(chat_id))
    elif next_step == "case_story":
        asyncio.create_task(send_case_story(chat_id))
    elif next_step == "self_disclosure":
        asyncio.create_task(send_self_disclosure(chat_id))
    elif next_step == "consultation_offer":
        asyncio.create_task(send_consultation_offer(chat_id))

# =========================================================
# 8. ПРЕДЛОЖЕНИЕ ПРОЙТИ ТЕСТ
# =========================================================
async def send_avoidance_offer(chat_id: int):
    await asyncio.sleep(10)
    text = (
        "Многие замечают, что после прочтения гайда тревога немного ослабевает. "
        "Но чтобы понять, как сильно паника влияет на жизнь, можно пройти короткий опрос. "
        "Он покажет, насколько выражено избегание ситуаций, вызывающих страх.\n\n"
        "🧩 Готовы пройти тест?"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Пройти опрос", callback_data="avoidance_test")]]
    )
    await bot.send_message(chat_id, text, reply_markup=kb)
    update_user_step(chat_id, "avoidance_offer")

# =========================================================
# 9. ОБРАБОТКА ОПРОСА (исправленный)
# =========================================================
@router.callback_query(F.data == "avoidance_test")
async def handle_avoidance_test(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    current_step = get_user_step(chat_id)
    current_index = SCENARIO_ORDER.index(current_step)
    test_index = SCENARIO_ORDER.index("avoidance_offer")

    # Ответ пользователю сразу
    if test_index <= current_index:
        await callback.message.answer("Отлично 👍 Тест пройден. Даже если немного с опозданием — это шаг вперёд.")
    else:
        await callback.message.answer("Отлично 👍 Тест пройден. Это поможет Вам лучше понять Вашу тревогу.")

    # Зафиксировать шаг до ответа Telegram
    update_user_step(chat_id, "avoidance_done")

    # Завершить callback, чтобы Telegram не зависал
    await callback.answer()

    # Запустить следующее сообщение уже вне контекста callback
    # (это гарантирует, что задача не будет убита)
    asyncio.create_task(trigger_after_test(chat_id, current_step))


async def trigger_after_test(chat_id: int, previous_step: str):
    """Переход после теста, с безопасным запуском следующего этапа."""
    await asyncio.sleep(10)
    # Проверяем: если пользователь ещё не дошёл до истории пациента — запускаем её
    step_now = get_user_step(chat_id)
    if step_now in ("avoidance_offer", "avoidance_done"):
        await send_case_story(chat_id)


# =========================================================
# 10. ИСТОРИЯ ПАЦИЕНТА
# =========================================================
async def send_case_story(chat_id: int):
    text = (
        "Недавно у меня был пациент, который пытался победить панические атаки дыхательными упражнениями "
        "и постоянным измерением давления. Он был уверен, что помогает себе, "
        "а на деле только закреплял тревогу.\n\n"
        "После нескольких встреч он понял, что дело не в теле, а в том, "
        "как он реагирует на ощущения.\n\n"
        "Паника — не враг, а искажённая тревожная система, с которой можно подружиться."
    )
    await bot.send_message(chat_id, text)
    update_user_step(chat_id, "case_story")
    asyncio.create_task(delayed_self_disclosure(chat_id))

async def delayed_self_disclosure(chat_id: int):
    await asyncio.sleep(10)
    await send_self_disclosure(chat_id)

# =========================================================
# 11. САМОРАСКРЫТИЕ
# =========================================================
async def send_self_disclosure(chat_id: int):
    text = (
        "Иногда мне самому бывает полезно обсудить сложные случаи с коллегами. "
        "С живыми специалистами, а не с книгами или искусственным интеллектом. "
        "Потому что только личный контакт помогает увидеть то, что не видно со стороны.\n\n"
        "Именно так я строю и свои консультации — без шаблонов, только живая работа и понимание."
    )
    await bot.send_message(chat_id, text)
    update_user_step(chat_id, "self_disclosure")
    asyncio.create_task(delayed_consultation_offer(chat_id))

async def delayed_consultation_offer(chat_id: int):
    await asyncio.sleep(10)
    await send_consultation_offer(chat_id)

# =========================================================
# 12. КОНСУЛЬТАЦИЯ
# =========================================================
async def send_consultation_offer(chat_id: int):
    text = (
        "Если чувствуете, что готовы разобраться глубже и перейти от понимания к изменениям, "
        "я открыт для личных консультаций. "
        "Мы детально разбираем причины паники, устраняем избегание и возвращаем уверенность в теле.\n\n"
        "🕊 Записаться на консультацию можно по ссылке:\n"
        "https://t.me/OcdAndAnxiety"
    )
    await bot.send_message(chat_id, text)
    update_user_step(chat_id, "consultation_offer")

# =========================================================
# 13. ЗАПУСК
# =========================================================
async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
