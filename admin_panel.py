import os
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import List
from starlette.status import HTTP_401_UNAUTHORIZED
from starlette.responses import Response
from starlette.templating import Jinja2Templates
import secrets

# -------------------- Настройки --------------------
load_dotenv()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "calmway2025")
DATABASE_PATH = os.getenv("DATABASE_PATH", "users.db")

app = FastAPI(title="CalmWayBot Panel", docs_url=None, redoc_url=None)
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")

# Разрешаем только локальные подключения
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# -------------------- Авторизация --------------------
def check_auth(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        return Response(
            status_code=HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
            content="Authentication required",
        )
    return True

# -------------------- Главная страница панели --------------------
@app.get("/panel-database", response_class=HTMLResponse)
def read_users(request: Request, authorized: bool = Depends(check_auth)):
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

    html_content = """
    <html>
    <head>
        <title>CalmWayBot Database</title>
        <style>
            body { font-family: Arial; background-color: #f6f8fa; padding: 20px; }
            h1 { color: #2c3e50; }
            table { border-collapse: collapse; width: 100%; background: white; }
            th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
            th { background-color: #eaeaea; }
            tr:hover { background-color: #f1f1f1; }
            .yes { color: green; font-weight: bold; }
            .no { color: #888; }
        </style>
    </head>
    <body>
        <h1>CalmWayBot — Users Database</h1>
        <table>
            <tr><th>ID</th><th>Источник</th><th>Этап</th><th>Подписан</th><th>Последнее действие</th></tr>
    """
    for row in rows:
        subscribed = '<span class="yes">✅</span>' if row[3] else '<span class="no">—</span>'
        html_content += f"<tr><td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td><td>{subscribed}</td><td>{row[4]}</td></tr>"

    html_content += "</table></body></html>"
    return HTMLResponse(content=html_content)

# -------------------- Запуск --------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
