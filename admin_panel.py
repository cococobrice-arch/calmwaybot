import os
import sqlite3
import secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# -------------------- Настройки --------------------
load_dotenv()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "calmway2025")
DATABASE_PATH = os.getenv("DATABASE_PATH", "users.db")
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(16))
SESSION_LIFETIME_DAYS = int(os.getenv("SESSION_LIFETIME_DAYS", 30))

app = FastAPI(title="CalmWayBot Panel", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# -------------------- Вспомогательные функции --------------------
def is_logged_in(request: Request) -> bool:
    token = request.cookies.get("session_token")
    if not token:
        return False
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            username TEXT,
            expires_at TEXT
        )
    """)
    conn.commit()
    cursor.execute("SELECT expires_at FROM sessions WHERE token=?", (token,))
    row = cursor.fetchone()
    conn.close()
    if row:
        expires_at = datetime.fromisoformat(row[0])
        return datetime.now() < expires_at
    return False

def create_session(username: str) -> str:
    token = secrets.token_hex(16)
    expires_at = datetime.now() + timedelta(days=SESSION_LIFETIME_DAYS)
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO sessions (token, username, expires_at)
        VALUES (?, ?, ?)
    """, (token, username, expires_at.isoformat()))
    conn.commit()
    conn.close()
    return token

# -------------------- Страница логина --------------------
@app.get("/panel-database", response_class=HTMLResponse)
async def read_panel(request: Request):
    if not is_logged_in(request):
        return HTMLResponse("""
            <html><body style='font-family:Arial; padding:50px'>
            <h2>Авторизация</h2>
            <form method="post" action="/login">
                <input name="username" placeholder="Логин"><br><br>
                <input name="password" type="password" placeholder="Пароль"><br><br>
                <button type="submit">Войти</button>
            </form>
            </body></html>
        """)
    else:
        return await show_users()

@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = create_session(username)
        response = RedirectResponse(url="/panel-database", status_code=302)
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            max_age=SESSION_LIFETIME_DAYS * 24 * 60 * 60
        )
        return response
    return HTMLResponse("Неверные логин или пароль")

# -------------------- Таблица пользователей --------------------
async def show_users():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            source TEXT,
            step TEXT,
            subscribed INTEGER,
            last_action TEXT
        )
    """)
    conn.commit()

    cursor.execute("SELECT user_id, source, step, subscribed, last_action FROM users ORDER BY last_action DESC")
    rows = cursor.fetchall()
    conn.close()

    html = """
    <html><head><title>CalmWayBot Database</title>
    <style>
        body { font-family: Arial; background-color: #f6f8fa; padding: 20px; }
        h1 { color: #2c3e50; }
        table { border-collapse: collapse; width: 100%; background: white; }
        th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
        th { background-color: #eaeaea; }
        tr:hover { background-color: #f1f1f1; }
        .yes { color: green; font-weight: bold; }
        .no { color: #888; }
    </style></head><body>
    <h1>CalmWayBot — Users Database</h1>
    <table>
        <tr><th>ID</th><th>Источник</th><th>Этап</th><th>Подписан</th><th>Последнее действие</th></tr>
    """
    for row in rows:
        subscribed = '<span class="yes">✅</span>' if row[3] else '<span class="no">—</span>'
        html += f"<tr><td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td><td>{subscribed}</td><td>{row[4]}</td></tr>"
    html += "</table></body></html>"
    return HTMLResponse(content=html)

# -------------------- Запуск --------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
