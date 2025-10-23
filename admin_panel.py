import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse

# -------------------- Настройки --------------------
load_dotenv()
DB_PATH = os.getenv("DATABASE_PATH", "users.db")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

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
a {
    color: #58a6ff;
    text-decoration: none;
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
input[type=password] {
    padding: 8px;
    border: 1px solid #30363d;
    border-radius: 4px;
    background-color: #161b22;
    color: #e6edf3;
}
</style>
"""

# =========================================================
# Вспомогательные функции
# =========================================================
def get_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, source, step, subscribed, last_action FROM users ORDER BY last_action DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_events(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, action, details FROM events WHERE user_id=? ORDER BY id ASC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

# =========================================================
# Авторизация
# =========================================================
@app.get("/panel-database", response_class=HTMLResponse)
async def panel_login():
    return f"""
    {STYLE}
    <h1>Авторизация</h1>
    <form action="/panel-database" method="post">
        <label>Пароль администратора:</label><br>
        <input type="password" name="password" required>
        <button type="submit">Войти</button>
    </form>
    """

@app.post("/panel-database", response_class=HTMLResponse)
async def panel_auth(password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        return f"{STYLE}<h1>Неверный пароль</h1><a href='/panel-database'>Попробовать снова</a>"

    users = get_users()
    rows = ""
    for u in users:
        user_id, source, step, subscribed, last_action = u
        status = "✅" if subscribed else "—"
        rows += f"""
        <tr>
            <td>{user_id}</td>
            <td>{source}</td>
            <td>{step}</td>
            <td>{status}</td>
            <td>{last_action}</td>
            <td><a href="/panel-database/user/{user_id}?password={password}"><button>История</button></a></td>
        </tr>
        """

    html = f"""
    {STYLE}
    <h1>CalmWayBot — Users Database</h1>
    <table>
        <tr><th>ID</th><th>Источник</th><th>Этап</th><th>Подписан</th><th>Последнее действие</th><th></th></tr>
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
async def user_history(user_id: int, password: str):
    if password != ADMIN_PASSWORD:
        return f"{STYLE}<h1>Доступ запрещён</h1>"

    events = get_events(user_id)
    if not events:
        event_rows = "<tr><td colspan='3'>Нет записей</td></tr>"
    else:
        event_rows = ""
        for ev in events:
            timestamp, action, details = ev
            details = details or "-"
            event_rows += f"<tr><td>{timestamp}</td><td>{action}</td><td>{details}</td></tr>"

    html = f"""
    {STYLE}
    <h1>История пользователя {user_id}</h1>
    <a href="/panel-database?password={password}">⬅ Назад к списку</a>
    <table>
        <tr><th>Время</th><th>Действие</th><th>Детали</th></tr>
        {event_rows}
    </table>
    """
    return html
