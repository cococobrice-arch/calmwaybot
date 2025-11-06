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

    # WAL-режим для избежания блокировок при одновременных чтениях/записях
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
    conn.commit()
    conn.close()


def log_event(user_id: int, action: str, details: str = None):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO events (user_id, timestamp, action, details) VALUES (?, ?, ?, ?)",
        (user_id, datetime.now().isoformat(timespec='seconds'), action, details)
    )
    conn.commit()
    conn.close()


def upsert_user(user_id: int, step: str = None, subscribed: int = None, username: str = None):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = cursor.fetchone()

    now = datetime.now().isoformat(timespec='seconds')
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
    conn = sqlite3.connect(DB_PATH, timeout=10)
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
        """Если Вы зашли в этот бот, значит, Ваши тревоги уже успели сильно вмешаться в жизнь.\n 
• Частое сердцебиение 💓 \n • потемнение в глазах 🌘 \n • головокружение🌀 \n • пот по спине😰 \n • страх потерять рассудок...\n
Вы стараетесь взять себя в руки, но чем сильнее пытаетесь успокоиться — тем страшнее становится. 
Анализы крови, обследования сердца и сосудов показывают, что всё в норме. Но наплывы ужаса продолжают догонять Вас.\n\n
Знакомо? 

Вероятно, Вы уже знаете, что такие наплывы страха называются <b>паническими атаками</b>.
Многие люди месяцами ищут причину этих приступов — и всё равно не могут понять, почему паника возвращается. 
Я покажу, как ослабить её власть и перестать ждать нового приступа каждый день\n \n  
Эти состояния имеют чёткую внутреннюю закономерность — и когда Вы поймёте её, Вы сможете взять происходящее под контроль 🛥

Я приготовил материал, который поможет Вам разобраться, что запускает панические атаки, чем они поддерживаются и как наконец вернуться к расслабленной жизни.  
Скачайте его — и дайте отпор страху!""",
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
        await bot.send_document(chat_id, document=file, caption="Вот Ваш первый шаг к спокойствию 🧘🏻‍♀️")
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
    await asyncio.sleep(5)
    is_subscribed = False
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, chat_id)
        status = getattr(member, "status", None)
        is_subscribed = status in {"member", "administrator", "creator"}
        upsert_user(chat_id, subscribed=1 if is_subscribed else 0)
        log_event(chat_id, "bot_subscription_checked", f"Подписан: {is_subscribed}")
    except TelegramBadRequest as e:
        logger.warning(f"Не удалось проверить подписку: {e} (считаем подписанным)")
        is_subscribed = True
        log_event(chat_id, "bot_subscription_checked", "Ошибка проверки, принудительно считаем подписанным")
    except Exception as e:
        logger.warning(f"Сбой проверки подписки: {e}")
        is_subscribed = True
        log_event(chat_id, "bot_subscription_checked", "Ошибка проверки (Exception) — считаем подписанным")

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
            'Например, я <a href="https://t.me/OcdAndAnxiety/16">писал пост</a> о том, '
            "как неправильное дыхание усиливает паническую атаку.\n\n"
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
            log_event(chat_id, "bot_channel_invite_sent", "Отправлено приглашение подписаться на канал")
        except Exception as e:
            logger.warning(f"Ошибка отправки приглашения на канал: {e}")

    # ✅ теперь дожидаемся выполнения, а не кидаем в фон
    await send_after_material(chat_id)


# =========================================================
# 4. ОПРОС ПО ИЗБЕГАНИЮ
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

async def send_after_material(chat_id: int):
    await asyncio.sleep(5)
    await send_avoidance_intro(chat_id)

async def send_avoidance_intro(chat_id: int):
    text = (
        "Вам может казаться, что панические атаки продолжают возникать, несмотя на то что Вы стараетесь их не провоцировать.\n"
        "Давайте проверим, насколько ваши привычки действительно помогают, а где — мешают?\n\n "
        "Пройдите короткий тест — всего 8 вопросов с ответами Да/Нет 🗳"
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

    # удаляем старые ответы, если тест уже проходился раньше
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM answers WHERE user_id=?", (chat_id,))
    conn.commit()
    conn.close()

    # фиксируем этап и логируем
    upsert_user(chat_id, step="avoidance_test")
    log_event(chat_id, "user_clicked_avoidance_start", "Начал опрос избегания")

    # удаляем кнопку "Начать тест", чтобы она исчезла навсегда
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    # начинаем тест
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
    try:
        await callback.answer()
    except Exception:
        pass

    chat_id = callback.message.chat.id
    try:
        _, ans, idx = callback.data.split("_")
        idx = int(idx)

        # сохраняем ответ в базу
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO answers (user_id, question, answer) VALUES (?, ?, ?)",
            (chat_id, idx, ans)
        )
        conn.commit()
        conn.close()

        log_event(chat_id, "user_answer", f"Вопрос {idx + 1}: {ans.upper()}")

        # небольшая пауза и сразу отправляем следующий вопрос
        await asyncio.sleep(0.2)
        if idx + 1 < len(avoidance_questions):
            await send_question(chat_id, idx + 1)
            # скрываем старые кнопки чуть позже, чтобы переход был плавным
            await asyncio.sleep(0.1)
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        else:
            await asyncio.sleep(0.2)
            await finish_test(chat_id)
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

    except Exception as e:
        import traceback
        logger.error("handle_answer failed: %s\n%s", e, traceback.format_exc())
        try:
            await bot.send_message(chat_id, "Техническая заминка при обработке ответа. Попробуйте ещё раз.")
        except Exception:
            pass


# =========================================================
# 4.1. Итог теста
# =========================================================
def _cta_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Хорошо 😌", callback_data="avoidance_ok"),
                InlineKeyboardButton(text="Нет, пока боюсь 🙈", callback_data="avoidance_scared"),
            ]
        ]
    )

@router.callback_query(F.data == "avoidance_ok")
async def handle_avoidance_ok(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await bot.send_message(callback.message.chat.id, "Супер! У Вас всё получится! 💪🏼")
    log_event(callback.message.chat.id, "user_avoidance_response", "Ответил: Хорошо 😌")
    await send_case_story(callback.message.chat.id)


@router.callback_query(F.data == "avoidance_scared")
async def handle_avoidance_scared(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await bot.send_message(callback.message.chat.id, "Ничего, иногда нужно собраться с силами, чтобы решиться на то, что тревожно 🫶🏼")
    log_event(callback.message.chat.id, "user_avoidance_response", "Ответил: Нет, пока боюсь 🙈")
    await send_case_story(callback.message.chat.id)




async def finish_test(chat_id: int):
    # собираем ответы
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT answer FROM answers WHERE user_id=?", (chat_id,))
    answers = [row[0] for row in cursor.fetchall()]
    conn.close()

    yes_count = answers.count("yes")
    upsert_user(chat_id, step="avoidance_done")
    log_event(chat_id, "user_finished_test", f"Ответов 'ДА': {yes_count}")

    chain = (
        "Чем больше вынужденных ограничений мы накладываем на свою жизнь\n"
        "️⬇️\nтем большую важность мы придаём панике\n"
        "⬇️\nТем больше концентрируемся на своём теле\n"
        "⬇️\nТем больше чувствуем в нём неожиданные/неприятные ощущения\n"
        "⬇️\nТем больше переживаем по поводу них.\n\nИ так до бесконечности 🔄"
    )

    if yes_count >= 4:
        await bot.send_message(chat_id, "Тест завершён. Подождите секунду, обрабатываем результаты ⏳")
        await asyncio.sleep(3)
        part1 = (
            "Судя по Вашим ответам, Вам приходится довольно сильно подстраивать свою жизнь под "
            "<b><i>избегание</i></b> возможных повторных приступов паники. Это ловушка, в которую попадаются очень многие люди 🪤\n\n" + chain
        )
        part2 = (
            "☀️ Хорошая новость в том, что мы в силах менять стратегию своих действий — и тем самым разрывать этот порочный круг.\n\n"
            "Вы уже почитали в моём гайде о том, как правильно отвечать себе на пугающие <u>мысли</u>. "
            "Поэтому теперь, держа под рукой эту памятку, Вы можете и в своих <u>действиях</u> попробовать немного зайти за грань того, в чём ограничивает Вас тревога.\n\n"
            "Я предлагаю следующее.\n\nВозьмите один из пунктов, на который Вы ответили «Да», и начните делать его наоборот.\n\n"
            "🔹 Привыкли всегда носить с собой бутылку воды? 👉🏼 Оставьте её дома!\n"
            "🔹 Держите окно приоткрытым? 👉🏼 Побудьте подольше в небольшом дефиците кислорода.\n"
            "И т.п.\n\n"
            "Но не всё сразу! Возьмите сначала только одно правило и поработайте над отказом от него пару недель.\n\n"
            "Это будет дискомфортно, но я обещаю: это даст Вам больше уверенности в своей способности справляться со страхом 🦁\n\n"
            "Попробуете?"
        )
        await bot.send_message(chat_id, part1, parse_mode="HTML")
        await asyncio.sleep(5)
        await bot.send_message(chat_id, part2, parse_mode="HTML", reply_markup=_cta_keyboard())

    elif 2 <= yes_count <= 3:
        await bot.send_message(chat_id, "Тест завершён. Подождите секунду, обрабатываем результаты ⏳")
        await asyncio.sleep(3)
        part1 = (
            "Судя по Вашим ответам, Вам в некоторой степени приходится подстраивать свою жизнь под "
            "<b><i>избегание</i></b> возможных повторных приступов паники. Это ловушка, в которую попадаются очень многие люди 🪤\n\n" + chain
        )
        part2 = (
            "☀️ Хорошая новость в том, что Вы можете менять стратегию действий и разрывать этот круг.\n\n"
            "Вы уже почитали в моём гайде о том, как правильно отвечать себе на пугающие <u>мысли</u>. "
            "Теперь, опираясь на памятку, попробуйте в <u>действиях</u> немного расширить привычные границы 🪂\n\n"
            "🔹 Привыкли всегда носить с собой бутылку воды? 👉🏼 Оставьте её дома!\n"
            "🔹 Держите окно приоткрытым? 👉🏼 Постарайтесь подольше побыть в небольшом дефиците кислорода.\nИ т.п.\n\n"
            "Но не всё сразу! Возьмите для изменения сначала только одно правило и поработайте пару недель над отказом от него.\n\n"
            "Это будет дискомфортно, но я обещаю: это даст Вам больше уверенности в Вашей способности справляться со страхом 🦁\n\n"
            "Попробуете?"
        )
        await bot.send_message(chat_id, part1, parse_mode="HTML")
        await asyncio.sleep(5)
        await bot.send_message(chat_id, part2, parse_mode="HTML", reply_markup=_cta_keyboard())

    elif yes_count == 1:
        await bot.send_message(chat_id, "Тест завершён. Подождите секунду, обрабатываем результаты ⏳")
        await asyncio.sleep(3)
        text = (
            "Судя по Вашим ответам, Вы практически не позволяете страху менять Ваш образ жизни. Это отлично!\n\n"
            "Потому что <b><i>избегание</i></b> часто загоняет в ловушку:\n" + chain + "\n\n"
            "Вы уже почитали в моём гайде о том, как правильно отвечать себе на пугающие <u>мысли</u>. "
            "Теперь можно и в <u>действиях</u> вернуть себе полностью нормальную жизнь 🪂\n\n"
            "Возьмите тот единственный пункт, который Вы ответили «Да», и делайте его наоборот.\n\n"
            "🔹 Привыкли всегда носить с собой бутылку воды? 👉🏼 Оставьте её дома!\n"
            "🔹 Держите окно приоткрытым? 👉🏼 Постарайтесь подольше побыть в небольшом дефиците кислорода.\nИ т.п.\n\n"
            "Но не всё сразу! Возьмите для изменения сначала только одно правило и поработайте пару недель над отказом от него.\n\n"
            "Это будет дискомфортно, но я обещаю: это даст Вам больше уверенности в Вашей способности справляться со страхом 🦁\n\n"
            "Попробуете?"
        )
        await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=_cta_keyboard())

    else:  # yes_count == 0
        await bot.send_message(chat_id, "Тест завершён. Подождите секунду, обрабатываем результаты ⏳")
        await asyncio.sleep(3)
        text = (
            "Судя по Вашим ответам, Вы не позволяете страху менять Ваш образ жизни. Это отлично!\n\n"
            "Если у Вас есть какие-то <b><i>избегания</i></b>, которые не попали в опросник, то теперь — держа под рукой памятку — "
            "можно и в <u>действиях</u> вернуть себе полностью нормальную жизнь.\n\n"
            "Примеры:\n"
            "🔹 Стараетесь не вспоминать про паническую атаку? 👉🏼 Повспоминайте про неё специально.\n\n"
            "🔹 Избегаете места первого приступа? 👉🏼 Посетите его ещё раз.\n\n\n"
            "Это будет дискомфортно, но я обещаю: это даст Вам больше уверенности в Вашей способности справляться со страхом 🦁\n\n"
            "Попробуете?"
        )
        await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=_cta_keyboard())

# =========================================================
# 5. ДАЛЬНЕЙШИЕ ЭТАПЫ
# =========================================================
async def send_case_story(chat_id: int):
    logger.info(f"→ Начато send_case_story для chat_id={chat_id}")  # ← добавили в самое начало
    await asyncio.sleep(5)
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
        "Это вызывало хроническую напряжённость, истощало её силы и делало нервную систему уязвимой. "
        "А разговор с начальником стал ситуацией, которая «вышибла пробки» от перенапряжения и разочарования.\n\n"
        "Спустя месяцы, когда она начала <u>делегировать задачи</u> другим людям, заявлять о своих <u>потребностях</u>, "
        "выполнять дела не на «5», а <u>на «4»</u> и не проверять каждое своё слово — внутреннее напряжение стало спадать. "
        "И тогда для её психики исчезла необходимость защищаться от былого надрыва с помощью панических атак.\n\n"
        "Сейчас она снова спокойно перемещается по городу, отдыхает по выходным и не живёт в ожидании очередного приступа ⛱"
    )
    await bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)
    upsert_user(chat_id, step="case_story")
    log_event(chat_id, "bot_case_story_sent", "Отправлена история пациента")

    await asyncio.sleep(2)
    logger.info(f"→ Запуск финального сообщения для chat_id={chat_id}")  # ← оставляем этот лог
    await send_final_message(chat_id)




async def send_final_message(chat_id: int):
    await asyncio.sleep(6)

    from aiogram.types import FSInputFile
    photo = FSInputFile("media/DSC03503.jpg")


    text = (
        "С людьми, переживающими панические атаки, я работаю каждый день,"
        "и я хорошо знаю, как важно не откладывать обращение за помощью. "
        "Потому что со временем тревога перестаёт быть лишь реакцией на стресс и начинает определять образ жизни.\n\n"
        "<b>Как я могу помочь Вам?</b>\n\n"
        "На индивидуальных консультациях мы можем вместе разобраться, из чего складывается <i>именно Ваш цикл тревоги</i>: "
        "какие мысли, телесные реакции и привычные способы поведения поддерживают его.\n\n"
        "При этом задача психотерапии - привести Вашу жизнь в норму во всех аспектах. "
        "Это означает не только избавиться от симптомов болезни, но и вернуть Вам энергию, способность чувствовать увлеченность, "
        "возможность создавать и поддерживать связь с другими людьми, заботиться о своем физическом здоровье.\n\n"
        'Если чувствуете, что готовы перейти к практической работе над своими симптомами, '
        'то подробнее о том, как проходят консультации со мной, Вы можете почитать по <a href="https://лечение-паники.рф/помощь-психотерапевта">ссылке</a>.'
    )
await bot.send_photo(
    chat_id,
    photo=photo,
    caption=text,
    parse_mode="HTML"
)


    upsert_user(chat_id, step="final_message_sent")
    log_event(chat_id, "bot_final_message_sent", "Отправлено финальное сообщение с фото")


# =========================================================
# 6. ЗАПУСК
# =========================================================
async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

