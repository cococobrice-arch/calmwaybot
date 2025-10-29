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
LINK = os.getenv("LINK_TO_MATERIAL")  # ссылка или локальный путь
VIDEO_NOTE_FILE_ID = os.getenv("VIDEO_NOTE_FILE_ID")
DB_PATH = os.getenv("DATABASE_PATH", "users.db")
CHANNEL_USERNAME = "@OcdAndAnxiety"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Тестовые пользователи (полная очистка на /start)
TEST_USER_IDS = {458421198, 7181765102}

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
    # Добавим колонку username в users, если её нет
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def log_event(user_id: int, action: str, details: str = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO events (user_id, timestamp, action, details) VALUES (?, ?, ?, ?)",
        (user_id, datetime.now().isoformat(timespec='seconds'), action, details)
    )
    conn.commit()
    conn.close()

def upsert_user(user_id: int, step: str = None, subscribed: int = None, username: str = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = cursor.fetchone()

    now = datetime.now()
    if exists:
        if step is not None and username is not None:
            cursor.execute("UPDATE users SET step=?, username=?, last_action=? WHERE user_id=?",
                           (step, username, now, user_id))
        elif step is not None:
            cursor.execute("UPDATE users SET step=?, last_action=? WHERE user_id=?",
                           (step, now, user_id))
        if subscribed is not None:
            cursor.execute("UPDATE users SET subscribed=?, last_action=? WHERE user_id=?",
                           (subscribed, now, user_id))
        if username is not None and step is None:
            cursor.execute("UPDATE users SET username=?, last_action=? WHERE user_id=?",
                           (username, now, user_id))
    else:
        cursor.execute(
            "INSERT INTO users (user_id, source, step, subscribed, last_action, username) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, "unknown", step or "start", subscribed or 0, now, username)
        )
    conn.commit()
    conn.close()

def purge_user(user_id: int):
    """Полная очистка данных пользователя (для тестовых аккаунтов): users, answers, events."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM events WHERE user_id=?", (user_id,))
    cursor.execute("DELETE FROM answers WHERE user_id=?", (user_id,))
    cursor.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

init_db()

# =========================================================
# 1. ПРИВЕТСТВИЕ (/start)
# =========================================================
@router.message(F.text == "/start")
async def cmd_start(message: Message):
    user_id = message.from_user.id
    uname = (message.from_user.username or "").strip()
    display_uname = uname if uname else None

    # Очистка для тестовых пользователей — полный сброс
    if user_id in TEST_USER_IDS:
        purge_user(user_id)

    upsert_user(user_id, step="start", username=display_uname)
    log_event(user_id, "user_start", "Пользователь запустил бота")

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
    uname = (callback.from_user.username or "").strip() if callback.from_user else None
    upsert_user(chat_id, step="got_material", username=uname or None)
    log_event(chat_id, "user_clicked_get_material", "Нажал «Получить гайд»")

    # Кружок
    if VIDEO_NOTE_FILE_ID:
        try:
            await bot.send_chat_action(chat_id, "upload_video_note")
            await bot.send_video_note(chat_id, VIDEO_NOTE_FILE_ID)
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Не удалось отправить кружок: {e}")

    # Материал
    if LINK and os.path.exists(LINK):
        file = FSInputFile(LINK, filename="Выход из панического круга.pdf")
        await bot.send_document(chat_id, document=file, caption="Первый шаг к спокойствию сделан 🧘🏻‍♀️")
    elif LINK and LINK.startswith("http"):
        await bot.send_message(chat_id, f"📘 Ваш материал доступен по ссылке: {LINK}")
    else:
        await bot.send_message(chat_id, "⚠️ Файл не найден. Попробуйте позже.")

    # Дальнейшая логика — проверка подписки и продолжение сценария
    asyncio.create_task(check_subscription_and_continue(chat_id))
    await callback.answer()

# =========================================================
# 3. ПРОВЕРКА ПОДПИСКИ И КОРРЕКТНОЕ ПРОДОЛЖЕНИЕ
# =========================================================
async def check_subscription_and_continue(chat_id: int):
    """Проверяем подписку. Если подписан — идём дальше без приглашения. 
       Если не подписан — отправляем приглашение, но всё равно продолжаем сценарий."""
    await asyncio.sleep(5)
    is_subscribed = False
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, chat_id)
        status = getattr(member, "status", None)
        is_subscribed = status in {"member", "administrator", "creator"}
        upsert_user(chat_id, subscribed=1 if is_subscribed else 0)
        log_event(chat_id, "bot_subscription_checked", f"Подписан: {is_subscribed}")
    except TelegramBadRequest as e:
        # Telegram не даёт проверить подписчиков публичных каналов — считаем, что подписан
        logger.warning(f"Не удалось проверить подписку: {e} (считаем подписанным)")
        is_subscribed = True
        log_event(chat_id, "bot_subscription_checked", "Ошибка проверки, принудительно считаем подписанным")
    except Exception as e:
        logger.warning(f"Сбой проверки подписки: {e}")
        log_event(chat_id, "bot_subscription_checked", "Ошибка проверки (Exception)")

    if not is_subscribed:
        # Отправляем приглашение подписаться
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
                chat_id, text, parse_mode="HTML",
                reply_markup=keyboard, disable_web_page_preview=True
            )
            log_event(chat_id, "bot_channel_invite_sent", "Отправлено приглашение подписаться на канал")
        except Exception as e:
            logger.warning(f"Ошибка отправки приглашения на канал: {e}")

    # Всегда продолжаем сценарий — независимо от результата проверки
    asyncio.create_task(send_after_material(chat_id))


# =========================================================
# 4. ОПРОС ПО ИЗБЕГАНИЮ
# =========================================================
async def send_after_material(chat_id: int):
    await asyncio.sleep(5)
    await send_avoidance_intro(chat_id)

avoidance_questions = [
    "Вы часто измеряете давление или пульс?",
    "Когда выходите из дома, берёте с собой бутылку воды?",
    "Отказались от спорта или физических нагрузок из-за опасений?",
    "Стараетесь не оставаться в одиночестве?",
    "Часто открываете окно, чтобы «стало легче»?",
    "В общественные местах предпочитаете садиться поближе к выходу?",
    "Отвлекаетесь в телефон, чтобы не замечать неприятные телесные ощущения?",
    "Избегаете поездок за город, чтобы не оставаться без мобильной связи и интернета?"
]

async def send_avoidance_intro(chat_id: int):
    text = (
        "Давайте проверим, насколько правильно Вы действуете в ситуациях, связанных со страхом?\n"
        "🗳 Пройдите короткий тест — всего 8 вопросов с ответами Да/Нет."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Начать тест", callback_data="avoidance_start")]]
    )
    await bot.send_message(chat_id, text, reply_markup=kb)
    log_event(chat_id, "bot_avoidance_invite_sent", "Предложен опрос избегания")

@router.callback_query(F.data == "avoidance_start")
async def start_avoidance_test(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    await callback.answer()
    upsert_user(chat_id, step="avoidance_test")
    log_event(chat_id, "user_clicked_avoidance_start", "Начал опрос избегания")
    await bot.send_message(chat_id, "Итак, начнём:")
    await send_question(chat_id, 0)

async def send_question(chat_id: int, index: int):
    if index >= len(avoidance_questions):
        await finish_test(chat_id)
        return
    q = avoidance_questions[index]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да", callback_data=f"ans_yes_{index}"),
            InlineKeyboardButton(text="Нет", callback_data=f"ans_no_{index}")
        ]
    ])
    await bot.send_message(chat_id, f"{index + 1}. {q}", reply_markup=kb)


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
    log_event(chat_id, "user_answer", f"Вопрос {idx+1}: {ans.upper()}")
    await callback.answer()
    await send_question(chat_id, idx + 1)

async def finish_test(chat_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT answer FROM answers WHERE user_id=?", (chat_id,))
    answers = [row[0] for row in cursor.fetchall()]
    conn.close()

    yes_count = answers.count("yes")
    upsert_user(chat_id, step="avoidance_done")
    log_event(chat_id, "user_finished_test", f"Ответов 'ДА': {yes_count}")

    if yes_count >= 4:
        text = (
            "✅ Тест завершён.\n\n"
            "Судя по Вашим ответам, Вам приходится довольно сильно подстраивать свою жизнь под <b><i>избегание</i></b> возможных повторных приступов паники. "
            "Это ловушка, в которую попадаются очень многие люди. Чем больше вынужденных ограничений мы накладываем на свою жизнь ➡️ тем большую важность мы придаем панике\n"
            "⬇️\n Тем больше концентрируемся на своём теле\n ⬇️ \nТем больше чувствуем в нём разные неожиданные/неприятные ощущения\n ⬇️ \nТем больше переживаем по поводу них.\n\n"
            "И так до бесконечности 🔄\n\n"
            "☀️ Хорошая новость в том, что мы в силах менять стратегию своих действий - и тем самым разрывать этот порочный круг.\n\n"
            "Вы уже почитали в моём гайде о том, как правильно отвечать себе на пугающие <u>мысли</u>. Поэтому теперь, держа под рукой эту памятку, Вы можете и в своих <u>действиях</u> попробовать немного зайти за грань того, в чём ограничивает Вас тревога.\n\n"
            "Я предлагаю следующее. \n\nВозьмите один из пунктов, на который Вы ответили \"Да\", и начните делать его наоборот.\n\n"
            "Привыкли всегда носить с собой бутылку воды? 👉🏼 Оставьте её дома!\n"
            "Держите окно приоткрытым? 👉🏼 Постарайтесь подольше побыть в небольшом дефиците кислорода.\n И т.п.\n\n"
            "Но не всё сразу! Возьмите для изменения сначала только одно правило и поработайте пару недель над отказом от него.\n\n"
            "Это будет дискомфортно, но я обещаю: это даст Вам больше уверенности в Вашей способности справляться со страхом 🦁\n\n"
            "Попробуете?"
        )   

    else:
        text = (
            "✅ Тест завершён.\n\n"
            "Отлично! Вы не позволяете тревоге управлять решениями и уже делаете многое правильно. "
            "Тем не менее полезно продолжить укреплять уверенность — чтобы страх больше не диктовал границы Вашей жизни."
        )

    await bot.send_message(chat_id, text, parse_mode="HTML")
    asyncio.create_task(send_case_story(chat_id))

# =========================================================
# 5. ДАЛЬНЕЙШИЕ ЭТАПЫ
# =========================================================
async def send_case_story(chat_id: int):
    await asyncio.sleep(5)
    text = (
        "История пациента: как страх становится привычкой.\n\n"
        "Одна моя пациентка несколько лет избегала поездок в метро, опасаясь, что станет плохо. "
        "Но чем больше она избегала, тем сильнее закреплялся страх. "
        "Мы начали постепенно возвращать эти ситуации — и паника утратила власть."
    )
    await bot.send_message(chat_id, text)
    upsert_user(chat_id, step="case_story")
    log_event(chat_id, "bot_case_story_sent", "Отправлена история пациента")
    asyncio.create_task(send_chat_invite(chat_id))

async def send_chat_invite(chat_id: int):
    await asyncio.sleep(5)
    text = (
        "Когда речь идёт о взаимодействии со сложными эмоциями, часто помогает общение с теми, кто тоже идёт по этому пути.\n\n"
        "У меня есть открытый чат, где можно задать вопросы мне, а также обсудить свой опыт с другими участниками."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Вступить ❤️",
                    url="https://t.me/Ocd_and_Anxiety_Chat"
                )
            ]
        ]
    )

    await bot.send_message(chat_id, text, reply_markup=keyboard)
    upsert_user(chat_id, step="chat_invite_sent")
    log_event(chat_id, "bot_chat_invite_sent", "Отправлено приглашение в чат с кнопкой ❤️")
    asyncio.create_task(send_self_disclosure(chat_id))



async def send_self_disclosure(chat_id: int):
    await asyncio.sleep(5)
    text = (
        "Иногда и мне важно обсуждать сложные случаи с коллегами. "
        "Живое общение даёт больше, чем книги или технологии. "
        "Так я строю свои консультации — живое присутствие и понимание без шаблонов."
    )
    await bot.send_message(chat_id, text)
    upsert_user(chat_id, step="self_disclosure")
    log_event(chat_id, "bot_self_disclosure_sent", "Отправлено сообщение самораскрытия")
    asyncio.create_task(send_consultation_offer(chat_id))

async def send_consultation_offer(chat_id: int):
    await asyncio.sleep(5)
    text = (
        "Если хотите пойти глубже — обсудим не только панические атаки, "
        "но и темы сна и обсессивных мыслей. "
        "🕊 Я провожу индивидуальные консультации, где мы работаем с корнями страха.\n\n"
        "Записаться можно здесь: https://лечение-паники.рф"
    )
    await bot.send_message(chat_id, text)
    upsert_user(chat_id, step="consultation_offer")
    log_event(chat_id, "bot_consultation_offer_sent", "Отправлено предложение консультации")

# =========================================================
# 6. ЗАПУСК
# =========================================================
async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
