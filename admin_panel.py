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
body {
    font-family: Arial, sans-serif;
    background-color: #0d1117;
    color: #e6edf3;
    margin: 0;
    padding: 20px;
}
h1 {
    color: #58a6ff;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 15px;
    background-color: #161b22;
}
th, td {
    border: 1px solid #30363d;
    padding: 10px;
    text-align: left;
}
th {
    background-color: #21262d;
    color: #58a6ff;
}
tr:hover {
    background-color: #1f6feb33;
}
button {
    background-color: #238636;
    color: white;
    border: none;
    padding: 8px 14px;
    border-radius: 6px;
    cursor: pointer;
}
button:hover {
    background-color: #2ea043;
}
</style>
"""

# =========================================================
# Вспомогательные функции
# =========================================================
def get_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # добавим username, если есть
    cursor.execute(
        "SELECT user_id, source, step, subscribed, last_action, username FROM users ORDER BY last_action DESC"
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_events(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT timestamp, action, details FROM events WHERE user_id=? ORDER BY id ASC",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    # фильтруем события: показываем только действия пользователя
    filtered = [row for row in rows if not row[1].startswith(("bot_", "system_", "auto_"))]
    return filtered

def fmt_time(ts):
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d – %H:%M")
    except Exception:
        return ts

# =========================================================
# Главная страница без авторизации
# =========================================================
@app.get("/panel-database", response_class=HTMLResponse)
async def panel_main():
    users = get_users()
    rows = ""
    for u in users:
        if len(u) == 5:
            user_id, source, step, subscribed, last_action = u
            username = None
        else:
            user_id, source, step, subscribed, last_action, username = u
        status = "✅" if subscribed else "—"
        display_name = f"@{username}" if username else str(user_id)
        last_action_fmt = fmt_time(str(last_action)) if last_action else "-"
        rows += f"""
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
        {rows}
    </table>
    <script>
        setTimeout(() => location.reload(), 10000);
    </script>
    """
    return html

# =========================================================
# История пользователя
# =========================================================
@app.get("/panel-database/user/{user_id}", response_class=HTMLResponse)
async def user_history(user_id: int):
    events = get_events(user_id)
    if not events:
        event_rows = "<tr><td colspan='3'>Нет записей</td></tr>"
    else:
        event_rows = ""
        for ev in events:
            timestamp, action, details = ev
            details = details or "-"
            time_fmt = fmt_time(timestamp)
            event_rows += f"<tr><td>{time_fmt}</td><td>{action}</td><td>{details}</td></tr>"

    html = f"""
    {STYLE}
    <h1>История пользователя {user_id}</h1>
    <a href="/panel-database">⬅ Назад к списку</a>
    <table>
        <tr><th>Время</th><th>Действие</th><th>Детали</th></tr>
        {event_rows}
    </table>
    """
    return html

# =========================================================
# Запуск приложения
# =========================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("admin_panel:app", host="0.0.0.0", port=8080)
