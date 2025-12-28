import os
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    FSInputFile,
)
from aiogram.exceptions import TelegramBadRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
LINK = os.getenv("LINK_TO_MATERIAL")
VIDEO_NOTE_FILE_ID = os.getenv("VIDEO_NOTE_FILE_ID")
DB_PATH = os.getenv("DATABASE_PATH", "users.db")
CHANNEL_USERNAME = "@OcdAndAnxiety"

MODE = os.getenv("MODE", "prod").lower()
FAST_USER_ID_RAW = os.getenv("FAST_USER_ID", "")
FAST_USER_ID = int(FAST_USER_ID_RAW) if FAST_USER_ID_RAW.isdigit() else None

SCHEDULER_POLL_INTERVAL = int(os.getenv("SCHEDULER_POLL_INTERVAL", "10"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)


# =========================================================
# DB INIT
# =========================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            source TEXT,
            step TEXT,
            subscribed INTEGER DEFAULT 0,
            last_action TEXT,
            username TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            user_id INTEGER,
            question INTEGER,
            answer TEXT,
            PRIMARY KEY (user_id, question)
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            send_at TEXT,
            kind TEXT,
            payload TEXT,
            delivered INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()


def log_event(user_id: int, action: str, details: str | None = None):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO events (user_id, timestamp, action, details) VALUES (?, ?, ?, ?)",
        (user_id, datetime.now().isoformat(timespec="seconds"), action, details),
    )
    conn.commit()
    conn.close()


def upsert_user(user_id: int, step: str | None = None, subscribed: int | None = None, username: str | None = None):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()

    cursor.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    exists = cursor.fetchone()
    now = datetime.now().isoformat(timespec="seconds")

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
            (user_id, "unknown", step or "старт", subscribed or 0, now, username),
        )

    conn.commit()
    conn.close()


def purge_user(user_id: int, keep_events: bool = False):
    """
    Удаляет состояние пользователя (users, answers, scheduled_messages).
    Если keep_events=True, события в таблице events сохраняются.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if not keep_events:
        cursor.execute("DELETE FROM events WHERE user_id=?", (user_id,))

    cursor.execute("DELETE FROM answers WHERE user_id=?", (user_id,))
    cursor.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    cursor.execute("DELETE FROM scheduled_messages WHERE user_id=?", (user_id,))

    conn.commit()
    conn.close()


def is_fast_user(user_id: int) -> bool:
    if MODE == "test":
        return True
    return FAST_USER_ID is not None and user_id == FAST_USER_ID


async def smart_sleep(user_id: int, prod_seconds: int, test_seconds: int = 3):
    delay = test_seconds if is_fast_user(user_id) else prod_seconds
    await asyncio.sleep(delay)


def schedule_message(
    user_id: int,
    prod_seconds: int,
    kind: str,
    payload: str | None = None,
    test_seconds: int = 3,
):
    delay = test_seconds if is_fast_user(user_id) else prod_seconds
    send_at = datetime.now() + timedelta(seconds=delay)

    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM scheduled_messages WHERE user_id=? AND kind=? AND delivered=0", (user_id, kind))

    cursor.execute(
        "INSERT INTO scheduled_messages (user_id, send_at, kind, payload) VALUES (?, ?, ?, ?)",
        (user_id, send_at.isoformat(timespec="seconds"), kind, payload),
    )

    conn.commit()
    conn.close()


def mark_message_delivered(task_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("UPDATE scheduled_messages SET delivered=1 WHERE id=?", (task_id,))
    conn.commit()
    conn.close()


async def process_scheduled_message(task_id: int, user_id: int, kind: str, payload: str | None):
    try:
        if kind == "channel_invite":
            await send_channel_invite(user_id)
        elif kind == "avoidance_intro":
            await send_avoidance_intro(user_id)
        elif kind == "case_story":
            await send_case_story(user_id, payload)
        elif kind == "case_story_auto":
            await send_case_story(user_id, payload)
        elif kind == "final_block1":
            await send_final_message(user_id)
        elif kind == "final_block2":
            await send_final_block2(user_id)
        elif kind == "final_block3":
            await send_final_block3(user_id)
        elif kind == "chat_invite":
            await send_chat_invite(user_id)
        else:
            log_event(user_id, "Неизвестный тип отложенного сообщения", kind)
    finally:
        mark_message_delivered(task_id)


async def scheduler_worker():
    logger.info("Scheduler запущен")
    while True:
        try:
            now = datetime.now().isoformat(timespec="seconds")
            conn = sqlite3.connect(DB_PATH, timeout=10)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_id, kind, payload
                FROM scheduled_messages
                WHERE delivered=0 AND send_at <= ?
                ORDER BY send_at ASC
                LIMIT 50
            """, (now,))
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                await asyncio.sleep(SCHEDULER_POLL_INTERVAL)
                continue

            for task_id, user_id, kind, payload in rows:
                await process_scheduled_message(task_id, user_id, kind, payload)

        except Exception as e:
            logger.exception(f"Scheduler error: {e}")

        await asyncio.sleep(SCHEDULER_POLL_INTERVAL)


init_db()


# =========================================================
# ВСПОМОГАТЕЛЬНОЕ: ПРОВЕРКА ПОДПИСКИ НА КАНАЛ
# =========================================================

async def is_user_subscribed_to_channel(user_id: int) -> bool:
    """
    Возвращает True, если пользователь уже состоит в канале, и False во всех остальных случаях.
    """
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramBadRequest:
        # пользователь не найден в канале / бот не видит его как участника
        return False
    except Exception as e:
        logger.exception(f"Ошибка проверки подписки пользователя {user_id}: {e}")
        return False


# =========================================================
# 1. START
# =========================================================

@router.message(F.text.startswith("/start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = (message.from_user.username or "").strip() or None

    # ---- ОПРЕДЕЛЯЕМ ИСТОЧНИК ----
    source = "unknown"
    parts = message.text.split(" ", 1)
    if len(parts) > 1:
        param = parts[1].strip()
        if param == "channel":
            source = "telegram-channel"
    # ------------------------------

    TEST_USER_ID = int(os.getenv("FAST_USER_ID", "0") or 0)

    # ---- ПРОВЕРЯЕМ, НОВЫЙ ЛИ ЭТО ПОЛЬЗОВАТЕЛЬ ----
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT step FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    # ---- ЕСЛИ ЮЗЕР УЖЕ В БАЗЕ И ЭТО НЕ ПЕРВЫЙ СТАРТ → НЕ ПОКАЗЫВАЕМ ПРИВЕТСТВИЕ ----
    if row is not None and row[0] != "старт":
        log_event(user_id, "Повторный вход через /start – приветствие не показываем")
        await message.answer("Вы уже начали работу со мной — продолжайте в удобном темпе 🙂")
        return

    # ---- ЕСЛИ ЭТО ТЕСТОВЫЙ ПОЛЬЗОВАТЕЛЬ → ПОЛНАЯ ОЧИСТКА ----
    if user_id == TEST_USER_ID:
        purge_user(user_id, keep_events=False)
        log_event(user_id, "Очистка тестового пользователя")
    else:
        # ---- НОВЫЙ ЮЗЕР: ОЧИСТИМ USERS/ANSWERS/MSG, НО ОСТАВИМ events ----
        purge_user(user_id, keep_events=True)

    # ---- ЗАПИСЫВАЕМ ИСТОЧНИК И СОЗДАЁМ ЗАПИСЬ ПОЛЬЗОВАТЕЛЯ ----
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()

    cursor.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    exists = cursor.fetchone()

    now = datetime.now().isoformat(timespec="seconds")

    if exists:
        cursor.execute(
            "UPDATE users SET step=?, username=?, source=?, last_action=? WHERE user_id=?",
            ("старт", username, source, now, user_id)
        )
    else:
        cursor.execute(
            "INSERT INTO users (user_id, source, step, subscribed, last_action, username) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, source, "старт", 0, now, username)
        )

    conn.commit()
    conn.close()
    # ------------------------------------

    log_event(user_id, "Запуск бота", f"source={source}")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📘 Получить гайд", callback_data="get_material")]
        ]
    )

    await message.answer(
        "Если Вы зашли в этот бот, значит, Ваши тревоги уже успели сильно вмешаться в жизнь.\n"
        "• Частое сердцебиение 💓 \n"
        "• потемнение в глазах 🌘 \n"
        "• головокружение🌀 \n"
        "• пот по спине😰 \n"
        "• страх потерять рассудок...\n"
        "Вы стараетесь взять себя в руки, но чем сильнее пытаетесь успокоиться — тем страшнее становится. \n"
        "Анализы крови, обследования сердца и сосудов показывают, что всё в норме. Но наплывы ужаса продолжают догонять Вас.\n\n"
        "Знакомо? \n\n"
        "Вероятно, Вы уже знаете, что такие наплывы страха называются <b>паническими атаками</b>.\n"
        "Многие люди месяцами ищут причину этих приступов — и всё равно не могут понять, почему паника возвращается.\n"
        "Я покажу, как ослабить её власть и перестать ждать нового приступа каждый день.\n\n"
        "Эти состояния имеют чёткую внутреннюю закономерность — и когда Вы поймёте её, Вы сможете взять происходящее под контроль 🛥\n\n"
        "Я приготовил материал, который поможет Вам разобраться, что запускает панические атаки, чем они поддерживаются и как наконец вернуться к расслабленной жизни.\n"
        "Скачайте его—и дайте отпор страху!",
        parse_mode="HTML",
        reply_markup=kb,
    )


# =========================================================
# Ручной сброс состояния пользователя (команда /reset)
# =========================================================

@router.message(F.text == "/reset")
async def reset_user(message: Message):
    user_id = message.from_user.id

    # Полностью очистить состояние, но оставить события (логи)
    purge_user(user_id, keep_events=True)

    log_event(user_id, "Пользователь вручную сбросил состояние", None)

    await message.answer(
        "История взаимодействия очищена.\n\n"
        "Чтобы начать заново — введите /start"
    )


# =========================================================
# 2. МАТЕРИАЛ
# =========================================================

@router.callback_query(F.data == "get_material")
async def send_material(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    username = callback.from_user.username or None

    # ---- ПРОВЕРКА: ПОЛЬЗОВАТЕЛЬ УЖЕ ПОЛУЧАЛ МАТЕРИАЛ ----
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT step FROM users WHERE user_id=?", (chat_id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] != "старт":
        # Убираем клавиатуру, если она вдруг осталась
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        await callback.answer("Материал уже был выдан ранее.")
        return
    # -----------------------------------------------------

    # ---- УБИРАЕМ КЛАВИАТУРУ ПОСЛЕ НАЖАТИЯ ----
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    # -----------------------------------------------------

    # ---- ОБНОВЛЯЕМ СОСТОЯНИЕ ПОЛЬЗОВАТЕЛЯ ----
    upsert_user(chat_id, step="получил_гайд", username=username)
    log_event(chat_id, "Нажата кнопка «Получить гайд»", "Начало выдачи материала")

    # ---- ОТПРАВКА ПРИВЕТСТВЕННОГО КРУЖКА ----
    if VIDEO_NOTE_FILE_ID:
        try:
            await bot.send_chat_action(chat_id, "upload_video_note")
            await bot.send_video_note(chat_id, VIDEO_NOTE_FILE_ID)
        except Exception as e:
            logger.warning(f"Ошибка отправки кружка: {e}")
            log_event(chat_id, "Ошибка отправки приветственного видео", str(e))

    # ---- ОТПРАВКА PDF ----
    if LINK and os.path.exists(LINK):
        file = FSInputFile(LINK, filename="Выход из панического круга.pdf")
        await bot.send_document(chat_id, document=file, caption="Вот Ваш первый шаг к спокойствию 🧘🏻‍♀️")
        log_event(chat_id, "Отправлен файл с гайдом", "Гайд отправлен как документ")

    elif LINK and LINK.startswith("http"):
        await bot.send_message(chat_id, f"📘 Ваш материал доступен по ссылке: {LINK}")
        log_event(chat_id, "Отправлена ссылка на гайд", LINK)

    else:
        await bot.send_message(chat_id, "⚠️ Файл не найден.")
        log_event(chat_id, "Не удалось найти файл гайда", LINK or "Путь не задан")

    # ---- ПЛАНИРУЕМ СООБЩЕНИЯ ДАЛЬШЕ ----
    schedule_message(chat_id, prod_seconds=2 * 60 * 60, test_seconds=10, kind="channel_invite")
    schedule_message(chat_id, prod_seconds=24 * 60 * 60, test_seconds=20, kind="avoidance_intro")

    await callback.answer()



async def send_channel_invite(chat_id: int):
    # Проверяем, подписан ли пользователь на канал
    subscribed_now = await is_user_subscribed_to_channel(chat_id)
    if subscribed_now:
        upsert_user(chat_id, step="приглашение_в_канал", subscribed=1)
        log_event(chat_id, "Пользователь уже состоит в канале, приглашение не отправлено", None)
        return

    upsert_user(chat_id, step="приглашение_в_канал", subscribed=0)

    text = (
        "У меня есть телеграм-канал, где я делюсь нюансами об эффективных способах преодоления тревоги "
        "и развеиваю мифы о <i>не</i>работающих методах. "
        "Никакой воды — только проверенные решения 💧🙅🏻‍♂️\n\n"
        "Например, я писал там посты:\n\n"
        "🔸 <a href=\"https://t.me/OcdAndAnxiety/16\">Как неправильное дыхание усиливает паническую атаку</a>\n"
        "🔸 <a href=\"https://t.me/OcdAndAnxiety/17\">Алкоголь и первый приступ ПА</a>\n"
        "🔸 <a href=\"https://t.me/OcdAndAnxiety/28\">Каковы опасные цифры давления?</a>\n"
        "🔸 <a href=\"https://t.me/OcdAndAnxiety/34\">Волшебный газ для успокоения?</a>\n\n"
        "Подписывайтесь и получайте практические рекомендации 👇🏽"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подписаться", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")]
        ]
    )

    try:
        await bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=kb,
        )
        log_event(chat_id, "Отправлено приглашение в канал", None)
    except Exception as e:
        log_event(chat_id, "Ошибка отправки приглашения в канал", str(e))


# =========================================================
# 3. ОПРОС ИЗБЕГАНИЯ
# =========================================================

avoidance_questions = [
    "Вы часто измеряете давление или пульс? 💓",
    "Когда выходите из дома, берёте с собой бутылку воды? 💧",
    "Вам пришлось отказаться от спорта или физических нагрузок из-за опасений? 🧎🏻‍♀️‍➡️",
    "Стараетесь не оставаться в одиночестве? 👥",
    "Стали частро открывать окно, чтобы не было душно? 💨",
    "В общественных местах предпочитаете садиться поближе к выходу? 🚪",
    "Отвлекаетесь в телефон, чтобы не замечать неприятные телесные ощущения? 📲",
    "Избегаете поездок за город, чтобы не оставаться без мобильной связи и интернета? 📶"
]


async def send_avoidance_intro(chat_id: int):
    upsert_user(chat_id, step="предложен_тест_избегания")
    text = (
        "Вам может казаться, что панические атаки продолжают возникать, несмотя на то что Вы стараетесь их не провоцировать.\n"
        "Давайте проверим, насколько ваши привычки действительно помогают, а где — мешают?\n\n"
        "Пройдите короткий тест — всего 8 вопросов с ответами Да/Нет 🗳"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Начать тест", callback_data="avoidance_start")]]
    )
    msg = await bot.send_message(chat_id, text, reply_markup=kb)
    log_event(chat_id, "Показан блок с предложением теста", "Предложен опрос избегания")

    # Если пользователь не нажал кнопку - через сутки / 30 секунд тестовый
    schedule_message(
        user_id=chat_id,
        prod_seconds=24 * 60 * 60,
        test_seconds=30,
        kind="case_story_auto",
        payload=str(msg.message_id),
    )


@router.callback_query(F.data == "avoidance_start")
async def start_avoidance_test(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    await callback.answer()

    # ---- ПРОВЕРКА: НЕ НАЧИНАЛ ЛИ ПОЛЬЗОВАТЕЛЬ ТЕСТ РАНЬШЕ ----
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT step FROM users WHERE user_id=?", (chat_id,))
    row = cursor.fetchone()
    conn.close()

    # Если пользователь уже проходил тест, повторно запускать нельзя
    if row and row[0] not in ("предложен_тест_избегания", "тест_избегания_начат"):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        await callback.answer("Вы уже проходили этот тест.")
        return

    # ---- УДАЛЯЕМ КЛАВИАТУРУ "Начать тест" ----
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # ---- УДАЛЯЕМ АВТОЗАДАЧУ перехода к истории пациентки ----
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM scheduled_messages WHERE user_id=? AND kind=? AND delivered=0",
        (chat_id, "case_story_auto"),
    )
    conn.commit()
    conn.close()

    # ---- СБРАСЫВАЕМ ПРЕДЫДУЩИЕ ОТВЕТЫ (ЕСЛИ ЕСТЬ) ----
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM answers WHERE user_id=?", (chat_id,))
    conn.commit()
    conn.close()

    # ---- УСТАНАВЛИВАЕМ НОВЫЙ ШАГ ----
    upsert_user(chat_id, step="тест_избегания_начат")
    log_event(chat_id, "Начат тест избегания", "Нажата кнопка «Начать тест»")

    # ---- ПЕРВОЕ СООБЩЕНИЕ ТЕСТА ----
    await bot.send_message(chat_id, "Итак, начнём:")
    await send_question(chat_id, 0)



async def send_question(chat_id: int, index: int):
    if index >= len(avoidance_questions):
        await finish_test(chat_id)
        return

    q = avoidance_questions[index]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"ans_yes_{index}"),
                InlineKeyboardButton(text="Нет", callback_data=f"ans_no_{index}")
            ]
        ]
    )

    await bot.send_message(chat_id, f"{index + 1}. {q}", reply_markup=kb)


@router.callback_query(F.data.startswith("ans_"))
async def handle_answer(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    await callback.answer()

    try:
        _, ans, idx_raw = callback.data.split("_")
        idx = int(idx_raw)

        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO answers (user_id, question, answer) VALUES (?, ?, ?)",
            (chat_id, idx, "yes" if ans == "yes" else "no"),
        )
        conn.commit()
        conn.close()

        log_event(
            chat_id,
            "Ответ на вопрос теста избегания",
            f"Вопрос {idx + 1}, ответ: {'Да' if ans == 'yes' else 'Нет'}"
        )

        if idx + 1 < len(avoidance_questions):
            await send_question(chat_id, idx + 1)
        else:
            await finish_test(chat_id)

        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Ошибка ответа: {e}")
        try:
            await bot.send_message(chat_id, "Ошибка обработки ответа. Попробуйте ещё раз.")
        except Exception:
            pass
        log_event(chat_id, "Ошибка обработки ответа теста избегания", str(e))


# =========================================================
# 3.1 — ФИНИШ ТЕСТА
# =========================================================

async def finish_test(chat_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT answer FROM answers WHERE user_id=?", (chat_id,))

    answers = [row[0] for row in cursor.fetchall()]
    conn.close()

    yes_count = answers.count("yes")
    upsert_user(chat_id, step="тест_избегания_завершен")
    log_event(chat_id, "Тест избегания завершен", f"Количество ответов «Да»: {yes_count}")

    chain = (
        "Чем больше вынужденных ограничений мы накладываем на свою жизнь\n"
        "️⬇️\nтем большую важность мы придаём панике\n"
        "⬇️\nТем больше концентрируемся на своём теле\n"
        "⬇️\nТем больше чувствуем в нём неожиданные/неприятные ощущения\n"
        "⬇️\nТем больше переживаем по поводу них.\n\nИ так до бесконечности 🔄"
    )

    await bot.send_message(chat_id, "Тест завершён. Подождите секунду, обрабатываем результаты ⏳")
    await smart_sleep(chat_id, prod_seconds=3, test_seconds=1)

    final_msg_id: int | None = None

    if yes_count >= 4:
        part1 = (
            "Судя по Вашим ответам, Вам приходится довольно сильно подстраивать свою жизнь под "
            "<b><i>избегание</i></b> возможных повторных приступов паники. Это ловушка, в которую попадаются очень многие люди 🪤\n\n" + chain
        )
        part2 = (
            "☀️ Хорошая новость в том, что мы в силах менять стратегию своих действий — и тем самым разрывать этот порочный круг.\n"
            "Если тревога долгое время диктовала правила, естественно, что шаги навстречу страху будут ощущаться как последнее, чем захочется заниматься. "
            "Кажется, будто без этих «страхующих» привычек станет невыносимо дискомфортно. "
            "Но каждый раз, когда мы не убегаем, а остаёмся в пугающей ситуации, мозг получает новый опыт — что <i>опасность была преувеличена</i>.\n\n"
            "Вы уже почитали в моём гайде о том, как правильно отвечать себе на пугающие <u>мысли</u>. "
            "Поэтому теперь, держа под рукой эту памятку, Вы можете и в своих <u>действиях</u>"
            "попробовать немного зайти за грань того, в чём ограничивает Вас тревога 🪂\n\n"
            "Я предлагаю следующее.\n\nВозьмите один из пунктов, на который Вы ответили «Да», и начните делать его наоборот.\n\n"
            "🔹 Привыкли всегда носить с собой бутылку воды? 👉🏼 Оставьте её дома!\n"
            "🔹 Держите окно приоткрытым? 👉🏼 Побудьте подольше в небольшом дефиците кислорода.\n"
            "И т.п.\n\n"
            "Но не всё сразу! Возьмите сначала только одно правило и поработайте над отказом от него пару недель.\n\n"
            "Это будет дискомфортно, но я обещаю: это даст Вам больше уверенности в своей способности справляться со страхом 🦁\n\n"
            "Попробуете?"
        )
        await bot.send_message(chat_id, part1, parse_mode="HTML")
        await smart_sleep(chat_id, prod_seconds=60, test_seconds=3)
        msg = await bot.send_message(chat_id, part2, parse_mode="HTML", reply_markup=_cta_keyboard())
        final_msg_id = msg.message_id

    elif 2 <= yes_count <= 3:
        part1 = (
            "Судя по Вашим ответам, Вам в некоторой степени приходится подстраивать свою жизнь под "
            "<b><i>избегание</i></b> возможных повторных приступов паники. Это ловушка, в которую попадаются очень многие люди 🪤\n\n" + chain
        )
        part2 = (
            "☀️ Хорошая новость в том, что мы в силах менять стратегию своих действий — и тем самым разрывать этот порочный круг.\n"
            "Если тревога долгое время диктовала правила, естественно, что шаги навстречу страху будут ощущаться как последнее, чем захочется заниматься. "
            "Кажется, будто без этих «страхующих» привычек станет невыносимо дискомфортно. "
            "Но каждый раз, когда мы не убегаем, а остаёмся в пугающей ситуации, мозг получает новый опыт — что <i>опасность была преувеличена</i>.\n\n"
            "Вы уже почитали в моём гайде о том, как правильно отвечать себе на пугающие <u>мысли</u>. "
            "Поэтому теперь, держа под рукой эту памятку, Вы можете и в своих <u>действиях</u>"
            "попробовать немного зайти за грань того, в чём ограничивает Вас тревога 🪂\n\n"
            "Я предлагаю следующее.\n\nВозьмите один из пунктов, на который Вы ответили «Да», и начните делать его наоборот.\n\n"
            "🔹 Привыкли всегда носить с собой бутылку воды? 👉🏼 Оставьте её дома!\n"
            "🔹 Держите окно приоткрытым? 👉🏼 Постарайтесь подольше побыть в небольшом дефиците кислорода.\nИ т.п.\n\n"
            "Но не всё сразу! Возьмите для изменения сначала только одно правило и поработайте пару недель над отказом от него.\n\n"
            "Это будет дискомфортно, но я обещаю: это даст Вам больше уверенности в Вашей способности справляться со страхом 🦁\n\n"
            "Попробуете?"
        )
        await bot.send_message(chat_id, part1, parse_mode="HTML")
        await smart_sleep(chat_id, prod_seconds=60, test_seconds=3)
        msg = await bot.send_message(chat_id, part2, parse_mode="HTML", reply_markup=_cta_keyboard())
        final_msg_id = msg.message_id

    elif yes_count == 1:
        text = (
            "Судя по Вашим ответам, Вы практически не позволяете страху менять Ваш образ жизни. Это отлично!\n\n"
            "Потому что <b><i>избегание</i></b> часто загоняет в ловушку:\n" + chain + "\n\n"
            "Вы уже почитали в моём гайде о том, как правильно отвечать себе на пугающие <u>мысли</u>. "
            "Теперь можно и в <u>действиях</u> вернуть себе полностью нормальную жизнь 🪂\n\n"
            "Возьмите тот единственный пункт, который Вы ответили «Да», и делайте его наоборот.\n\n"
            "🔹 Привыкли всегда носить с собой бутылку воды? 👉🏼 Оставьте её дома!\n"
            "🔹 Держите окно приоткрытым? 👉🏼 Постарайтесь подольше побыть в небольшом дефиците кислорода.\nИ т.п.\n\n"
            "Но не всё сразу! Возьмите для изменения сначала только одно правило и поработайте пару недель над отказом от него.\n\n"
            "Это будет дискомфортно, но я обещаю: это даст Вам больше уверенности в своей способности справляться со страхом 🦁\n\n"
            "Попробуете?"
        )
        msg = await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=_cta_keyboard())
        final_msg_id = msg.message_id

    else:
        text = (
            "Судя по Вашим ответам, Вы не позволяете страху менять Ваш образ жизни. Это отлично!\n\n"
            "Если у Вас есть какие-то <b><i>избегания</i></b>, которые не попали в опросник, то теперь — держа под рукой памятку — "
            "можно и в <u>действиях</u> вернуть себе полностью нормальную жизнь.\n\n"
            "Примеры:\n"
            "🔹 Стараетесь не вспоминать про паническую атаку? 👉🏼 Повспоминайте про неё специально.\n\n"
            "🔹 Избегаете места первого приступа? 👉🏼 Посетите его ещё раз.\n\n\n"
            "Это будет дискомфортно, но я обещаю: это даст Вам больше уверенности в своей способности справляться со страхом 🦁\n\n"
            "Попробуете?"
        )
        msg = await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=_cta_keyboard())
        final_msg_id = msg.message_id

    if final_msg_id is not None:
        schedule_message(
            user_id=chat_id,
            prod_seconds=22 * 60 * 60,
            test_seconds=10,
            kind="case_story",
            payload=str(final_msg_id),
        )


# =========================================================
# 4. БЛОКИ ПОСЛЕ ТЕСТА
# =========================================================

def _cta_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Хорошо 😌", callback_data="avoidance_ok"),
                InlineKeyboardButton(text="Нет, пока боюсь 🙈", callback_data="avoidance_scared")
            ]
        ]
    )


@router.callback_query(F.data == "avoidance_ok")
async def handle_avoidance_ok(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await bot.send_message(chat_id, "Супер! У Вас всё получится! 💪🏼")
    log_event(chat_id, "Ответ на блок с предложением экспозиции", "Ответ: «Хорошо 😌»")

    schedule_message(
        user_id=chat_id,
        prod_seconds=60 * 60,
        test_seconds=10,
        kind="case_story",
        payload=str(callback.message.message_id),
    )


@router.callback_query(F.data == "avoidance_scared")
async def handle_avoidance_scared(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await bot.send_message(chat_id, "Ничего, иногда нужно собраться с силами, чтобы решиться на то, что тревожно 🫶🏼")
    log_event(chat_id, "Ответ на блок с предложением экспозиции", "Ответ: «Нет, пока боюсь 🙈»")

    schedule_message(
        user_id=chat_id,
        prod_seconds=60 * 60,
        test_seconds=10,
        kind="case_story",
        payload=str(callback.message.message_id),
    )


async def send_case_story(chat_id: int, payload: str | None = None):
    upsert_user(chat_id, step="история_пациентки")

    if payload:
        try:
            msg_id = int(payload)
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=msg_id, reply_markup=None)
        except (ValueError, TelegramBadRequest):
            pass
        except Exception:
            logger.exception("Не удалось убрать клавиатуру с финального сообщения теста")

    text = (
        "<b>Чтобы ослабить власть тревоги над нами, нам нужно начать делать то, что страшно.</b>\n\n"
        "Теперь я хочу показать Вам, как это выглядит на практике. \n\n"
        "Помните историю из моего гайда про девушку, у которой приступ впервые случился после разговора с руководителем?\n"
        "Полгода она жила в постоянном ожидании нового приступа, пока не решилась прийти на терапию. Наши с ней занятия состояли из двух блоков.\n\n"
        "<b>Экспозиция.</b>\n\n"
        "Когда она обратилась ко мне, метро уже давно стало для неё источником угрозы 🚇 "
        "Её внутренний детектор опасности научился воспринимать нахождение в замкнутом пространстве как зашкаливающий риск.\n\n"
        "Мы начали с пошагового возвращения в эти ситуации: находясь на видеосвязи со мной, она стала спускаться на платформу. "
        "Для начала чтобы просто постоять там и позволить себе оставаться в тревоге и выдерживать её наплывы. "
        "Затем чтобы делать короткие поездки — на одну-две станции.\n\n"
        "Каждый этап, конечно же, сопровождался сопротивлением со стороны её тела и психики, которые во всю сигнализировали ей, "
        "что в тоннеле должно случиться что-то ужасное. Но мы заранее составляли план того, к появлению каких страшилок в голове нужно быть готовой, "
        "и как на них отвечать 🛡\n"
        "И через несколько недель она снова научилась проезжать привычный маршрут.\n\n"
        "<b>Изменение убеждений.</b>\n\n"
        "По мере того, как мы обсуждали её жизненные обстоятельства, постепенно стало ясно, что паника была не просто страхом "
        "задохнуться или потерять сознание. В её основе лежали уже ставшие естественными для неё установки: "
        "<i>постоянно соответствовать ожиданиям других людей, быть безошибочной, никого не разочаровывать</i>. "
        "Это вызывало хроническое напряжение, истощало её силы и делало нервную систему уязвимой. "
        "А разговор с начальником стал ситуацией, которая «вышибла пробки» от перенапряжения и разочарования.\n\n"
        "Спустя месяцы, когда она начала <u>делегировать задачи</u> другим людям, заявлять о своих <u>потребностях</u>, "
        "выполнять дела не на «5», а <u>на «4»</u> и не проверять каждое своё слово — внутреннее напряжение стало спадать. "
        "И тогда для её психики исчезла необходимость защищаться от былого надрыва с помощью панических атак.\n\n"
        "Сейчас она снова спокойно перемещается по городу, отдыхает по выходным и не живёт в ожидании очередного приступа ⛱"
    )

    try:
        await bot.send_message(chat_id, text, parse_mode="HTML")
        log_event(chat_id, "Отправлена история пациентки", None)
    except Exception as e:
        log_event(chat_id, "Ошибка отправки истории пациентки", str(e))

    schedule_message(chat_id, prod_seconds=24 * 60 * 60, test_seconds=10, kind="final_block1")


async def send_final_message(chat_id: int):
    upsert_user(chat_id, step="приглашение_на_консультацию")
    await smart_sleep(chat_id, prod_seconds=1, test_seconds=1)

    photo = FSInputFile("media/DSC03503.jpg")

    caption = (
        "С людьми, переживающими панические атаки, я работаю каждый день, "
        "и я хорошо знаю, как важно не откладывать обращение за помощью. "
        "Потому что со временем тревога перестаёт быть лишь реакцией на стресс и начинает определять Ваш образ мыслей и восприятия.\n\n"
        "<b>Как я могу помочь Вам?</b>\n\n"
        "На индивидуальных консультациях мы можем вместе разобрать, из чего складывается <i>именно Ваш цикл тревоги</i>: "
        "какие мысли, телесные реакции и привычные способы поведения поддерживают его. Мы составим для Вас подробный план действий: "
        "от списка необходимых обследований - до распорядка упражнений по преодолению страха.\n\n"
    )

    try:
        await bot.send_photo(chat_id, photo=photo, caption=caption, parse_mode="HTML")
        log_event(chat_id, "Отправлено сообщение с описанием формата работы (фото)", None)
    except Exception as e:
        log_event(chat_id, "Ошибка отправки блока с описанием формата работы (фото)", str(e))

    await smart_sleep(chat_id, prod_seconds=60, test_seconds=3)

    text2 = (
        "По итогам прохождения психотерапии Вы получите:\n\n"
        "✨ снижение <b>гиперконтроля и проверок</b> собственного состояния: больше не нужно будет постоянно измерять пульс, "
        "дышать по инструкции или судорожно искать врачей\n\n"
        "✨ способность <b>снова свободно выходить из дома, ездить в метро, летать на самолётах, водить машину</b> — без страха, что станет плохо\n\n"
        "✨ умение <b>оставаться в контакте с тревогой</b>, не убегая от неё — и благодаря этому не попадать в замкнутый круг\n\n"
        "✨ <b>чувство гордости и уважения к себе</b> за то, что вы справляетесь без избеганий, лишних лекарств или алкоголя\n\n"
        "✨ способность <b>жить спонтанно и легко</b>, не подстраиваясь под ограничения и не тратя силы на борьбу с внутренним напряжением\n\n"
        "✨ крепкую внутреннюю <b>убежденность, что с Вами всё в порядке</b>\n\n"
        "Моя задача - привести Вашу жизнь в норму <u>во всех аспектах</u>. "
        "Это означает не только помочь избавиться от симптомов болезни, но и вернуть Вам энергию, способность чувствовать увлеченность, "
        "возможность создавать и поддерживать связь с другими людьми и заботиться о своем физическом здоровье.\n\n"
        "Почитать подробнее о том, как проходит психотерапия со мной 👇"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Узнать про консультации", callback_data="consult_show")]]
    )

    try:
        await bot.send_message(chat_id, text2, parse_mode="HTML", reply_markup=kb)
        log_event(chat_id, "Отправлен текстовый блок с описанием формата работы", None)
    except Exception as e:
        log_event(chat_id, "Ошибка отправки текстового блока с описанием формата работы", str(e))

    schedule_message(chat_id, prod_seconds=24 * 60 * 60, test_seconds=10, kind="final_block2")


@router.callback_query(F.data == "consult_show")
async def consult_show(callback: CallbackQuery):
    chat_id = callback.message.chat.id
    await callback.answer()

    upsert_user(chat_id, step="перешел_к_описанию_консультаций")
    log_event(chat_id, "Открыта информация о консультациях", "Нажата кнопка «Узнать про консультации»")

    text = (
        "Прочитать про консультации можно здесь:\n"
        "https://лечение-паники.рф/консультации"
    )

    try:
        await bot.send_message(chat_id, text, disable_web_page_preview=True)
    except Exception as e:
        log_event(chat_id, "Ошибка отправки ссылки на консультации", str(e))


async def send_final_block2(chat_id: int):
    upsert_user(chat_id, step="сомнение_в_психотерапии")
    await smart_sleep(chat_id, prod_seconds=1, test_seconds=1)

    extra_text = (
        "<b>Одно из самых частых сомнений у тех, кто задумывается о психотерапии, — «А мне это точно поможет?»</b>\n\n"
        "Это абсолютно понятный вопрос, особенно если панические атаки длятся уже долго, а прошлые попытки справиться не дали ощутимого эффекта. "
        "Но психотерапия — это не абстрактные разговоры, а детально просчитанная точечная работа по изменению Вашего способа реагирования на страх "
        "и восприятия своих телесных ощущений.\n\n"
        "Иногда люди могут смотреть на эффект от противодействия проблеме как на черно-белые варианты: либо выздоровею, либо нет. "
        "На самом деле процесс освобождения от тревоги в чем-то похож на занятие физкультурой: можно стать мастером спорта, если задаться такой целью, "
        "но даже просто обретение хорошей физической формы - это отличный результат.\n\n"
        "Могу Вам гарантировать, что любой человек, который получает на занятиях со специалистом новые знания и начинает действовать в соответствии с ними — "
        "чувствует результат уже с первых недель.\n\n"
        "Вот что часто говорят мои клиенты после нескольких занятий:"
    )

    try:
        await bot.send_message(chat_id, extra_text, parse_mode="HTML")
        log_event(chat_id, "Отправлен блок про сомнения в психотерапии", None)
    except Exception as e:
        log_event(chat_id, "Ошибка отправки блока про сомнения в психотерапии", str(e))

    await smart_sleep(chat_id, prod_seconds=1, test_seconds=1)
    try:
        await bot.send_photo(chat_id, FSInputFile("media/Scrc2798760b2b95377.jpg"))
        await bot.send_photo(chat_id, FSInputFile("media/Scb2b95377.jpg"))
        log_event(chat_id, "Отправлены отзывы в блоке про сомнения", None)
    except Exception as e:
        log_event(chat_id, "Ошибка отправки отзывов в блоке про сомнения", str(e))

    schedule_message(chat_id, prod_seconds=24 * 60 * 60, test_seconds=10, kind="final_block3")


async def send_final_block3(chat_id: int):
    upsert_user(chat_id, step="ошибки_пациента_с_паническими_атаками")
    await smart_sleep(chat_id, prod_seconds=1, test_seconds=1)

    thoughts_text = (
        "<b>У Вас может складываться ощущение, что у Вас нет никаких мыслей во время панической атаки.</b>\n\n"
        "Может складываться впечатление, что страх просто наваливается сам по себе: «Я ничего не успеваю подумать — "
        "и сразу соскальзываю в поток из ужасных ощущений». Дальше приходится думать лишь про то, как \"спастись\" "
        "(беру это слово в кавычки - потому что никак спасаться от панической атаки конечно же не надо).\n\n"
        "Но если прислушаться внимательнее, оказывается, что даже на пике страха, сквозь затуманенный рассудок внутри "
        "постоянно мелькают короткие разорванные фразы:\n\n"
        "<i>«Это опасно»</i>\n"
        "<i>«Я сейчас упаду»</i>\n"
        "<i>«Что-то не так с сердцем»</i>\n\n"
        "Эти обрывочные мысли, проносясь сквозь сознание на реактивной скорости, могут оставаться не замеченными Вами, но "
        "они оставляют за собой испепеляющий эмоциональный хвост ☄️\n\n"
        "И вот одна из основных причин, почему у Вас может не получаться справиться с паникой: Вы можете знать, что паническая "
        "атака не опасна, но не даёте <b>ответа на конкретную мысль</b>. Вместо этого начинаете искать спасение — измерять "
        "давление, глубоко дышать, открывать окно — вместо того, чтобы понять, какая именно идея вызвала тревогу.\n\n"
        "Вам требуется распознать их и давать себе на них чёткие адресные ответы 🎯 Недостаточно «в целом знать», что паника "
        "не причиняет вреда — важно распознать конкретный страх, лежащий в основе приступа.\n\n"
        "На психотерапевтических сеансах мы проводим буквально археологические раскопки "
        "в отношении внутреннего опыта: слой за слоем убираем общие формулировки "
        "пока не обнаружим само ядро страха.\n\n"
        "<i>«я боюсь упасть в обморок», «я задохнусь, если перестану следить за дыханием»</i>\n\n"
        "Вот в этот момент контроль над происходящим вновь возвращается Вам."
    )

    try:
        await bot.send_message(chat_id, thoughts_text, parse_mode="HTML")
        log_event(chat_id, "Отправлен блок про ошибки пациента с паническими атаками", None)
    except Exception as e:
        log_event(chat_id, "Ошибка отправки блока про ошибки пациента", str(e))

    schedule_message(
        user_id=chat_id,
        prod_seconds=24 * 60 * 60,
        test_seconds=10,
        kind="chat_invite",
    )


async def send_chat_invite(chat_id: int):
    upsert_user(chat_id, step="приглашение_в_чат")

    text = (
        "Если у Вас есть какие-либо вопросы, касающиеся:\n\n"
        "❔ Ваших симптомов\n"
        "❔ диагноза\n"
        "❔ методов лечения\n\n"
        "то Вы можете задать их в моём публичном чате.\n"
        "Там можно получить ответы от меня и поддержку от других участников."
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Вступить в чат 🩷", url="https://t.me/Ocd_and_Anxiety_Chat")]
        ]
    )

    try:
        await bot.send_message(chat_id, text, reply_markup=kb)
        log_event(chat_id, "Отправлено приглашение в чат", None)
    except Exception as e:
        log_event(chat_id, "Ошибка отправки приглашения в чат", str(e))


# =========================================================
# 6. RUN
# =========================================================

async def main():
    logger.info(f"MODE={MODE}, FAST_USER_ID={FAST_USER_ID}")
    await asyncio.gather(
        dp.start_polling(bot),
        scheduler_worker(),
    )


if __name__ == "__main__":
    asyncio.run(main())
