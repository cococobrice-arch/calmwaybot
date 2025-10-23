import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

# -------------------- Настройки --------------------
load_dotenv()
DB_PATH = os.getenv("DATABASE_PATH", "users.db")

app = FastAPI(title="CalmWayBot Admin Panel")

# -------------------- Стили --------------------
STYLE = """
<style>
body { font-family: Arial, sans-serif; background-color: #0d1117; color: #e6edf3; margin: 0; padding: 20px; }
h1 { color: #58a6ff; }
table { width: 100%; border-collapse: collapse; margin-top: 15px; background-color: #161b22; }
th, td { border: 1px solid #30363d; padding: 10px; text-align: left; }
th { background-color: #21262d; color: #58a6ff; }
tr:hover { background-color: #1f6feb33; }
button { background-color: #238636; color: white; border: none; padding: 8px 14px; border-radius: 6px; cursor: pointer; }
button:hover { background-color: #2ea043; }
a { color: #58a6ff; text-decoration: none; }
</style>
"""

# =========================================================
# Инициализация БД/схемы при старте панели
# =========================================================
def ensure_schema():
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
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp TEXT,
            action TEXT,
            details TEXT
        )
    """)
    # username-колонка
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.close()

ensure_schema()

# =========================================================
# Хелперы
# =========================================================
def fmt_time(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d – %H:%M")
    except Exception:
        return ts

def get_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, source, step, subscribed, last_action, username FROM users ORDER BY last_action DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

# Показываем только действия пользователя (фильтр по префиксу 'user_')
def get_user_events_only(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT timestamp, action, details FROM events WHERE user_id=? ORDER BY id ASC",
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    filtered = [row for row in rows if str(row[1]).startswith("user_")]
    return filtered

# =========================================================
# Главная (без авторизации)
# =========================================================
@app.get("/panel-database", response_class=HTMLResponse)
async def panel_main():
    users = get_users()
    rows_html = ""
    for user_id, source, step, subscribed, last_action, username in users:
        status = "✅" if subscribed else "—"
        display_name = f"@{username}" if username else str(user_id)
        last_action_fmt = fmt_time(str(last_action)) if last_action else "-"
        rows_html += f"""
        <tr>
            <td>{display_name}</td>
            <td>{source}</td>
            <td>{step}</td>
            <td>{status}</td>
            <td>{last_action_fmt}</td>
            <td><a href="/panel-database/user/{user_id}"><button>История</button></a></td>
        </tr>
        """

    html = f"""
    {STYLE}
    <h1>CalmWayBot — Users Database</h1>
    <table>
        <tr><th>Пользователь</th><th>Источник</th><th>Этап</th><th>Подписан</th><th>Последнее действие</th><th></th></tr>
        {rows_html}
    </table>
    <script> setTimeout(() => location.reload(), 10000); </script>
    """
    return html

# =========================================================
# История пользователя (только действия пользователя)
# =========================================================
@app.get("/panel-database/user/{user_id}", response_class=HTMLResponse)
async def user_history(user_id: int):
    events = get_user_events_only(user_id)
    if not events:
        rows = "<tr><td colspan='3'>Нет записей действий пользователя</td></tr>"
    else:
        rows = ""
        for ts, action, details in events:
            details = details or "-"
            rows += f"<tr><td>{fmt_time(ts)}</td><td>{action}</td><td>{details}</td></tr>"

    html = f"""
    {STYLE}
    <h1>История пользователя {user_id}</h1>
    <a href="/panel-database">⬅ Назад</a>
    <table>
        <tr><th>Время</th><th>Действие</th><th>Детали</th></tr>
        {rows}
    </table>
    """
    return html

# =========================================================
# Запуск
# =========================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("admin_panel:app", host="0.0.0.0", port=8080)
