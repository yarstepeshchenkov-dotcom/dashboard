import os
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
import secrets
import logging

load_dotenv()

# ─── КОНФИГУРАЦИЯ ──────────────────────────────────────────────────────────

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SECRET_KEY = os.getenv("SECRET_KEY", "insecure-dev-key-change-me")
DB_PATH = os.getenv("DB_PATH", "/tmp/lithium.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("lithium_dashboard")

# ─── ПРИЛОЖЕНИЕ ─────────────────────────────────────────────────────────────

app = FastAPI(title="LITHIUM Intelligence Dashboard")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="lithium_session")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ─── ИНИЦИАЛИЗАЦИЯ БД С ТЕСТОВЫМИ ДАННЫМИ ──────────────────────────────

def init_db():
    try:
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            text TEXT,
            sentiment TEXT,
            is_b2b INTEGER DEFAULT 0,
            created_at TEXT,
            viewed INTEGER DEFAULT 0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS geo_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT,
            brand TEXT,
            position INTEGER,
            updated_at TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS trends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT,
            mentions_count INTEGER,
            growth_percent REAL,
            updated_at TEXT
        )''')
        # Проверяем, есть ли данные
        c.execute("SELECT COUNT(*) FROM mentions")
        count = c.fetchone()[0]
        logger.info(f"Текущее количество записей в mentions: {count}")
        if count == 0:
            now = datetime.now().isoformat()
            test_data = [
                ("Тестовый", "Отличная кухня LITHIUM! Заказывали в шоуруме на Artplay — очень довольны качеством.", "positive", now),
                ("Тестовый", "Кухня LITHIUM — это идеальное решение для современного дома. Рекомендую!", "positive", now),
                ("Тестовый", "Разочарован доставкой LITHIUM: задержали на неделю, пришлось переносить ремонт.", "negative", now),
                ("Тестовый", "Кухня LITHIUM: качество на высоте, дизайн превосходный!", "positive", now),
                ("Тестовый", "Обсуждаем на форуме кухни LITHIUM. Кто-то уже заказывал? Поделитесь опытом.", "neutral", now)
            ]
            for item in test_data:
                c.execute("INSERT INTO mentions (source, text, sentiment, created_at) VALUES (?,?,?,?)", item)
            conn.commit()
            logger.info("✅ Тестовые данные добавлены в БД")
        else:
            logger.info("ℹ️ Таблица mentions уже содержит данные, тестовые не добавлены")
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка при инициализации БД: {e}")

@app.on_event("startup")
async def on_startup():
    init_db()
    logger.info("🚀 Сервер запущен")

# ─── АВТОРИЗАЦИЯ ──────────────────────────────────────────────────────────

def is_authenticated(request: Request):
    return bool(request.session.get("authenticated"))

def get_or_create_csrf(request: Request):
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_hex(16)
        request.session["csrf_token"] = token
    return token

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    csrf_token = get_or_create_csrf(request)
    return templates.TemplateResponse("login.html", {"request": request, "csrf_token": csrf_token, "error": None})

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
    if secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD):
        request.session["authenticated"] = True
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "csrf_token": get_or_create_csrf(request), "error": "Неверный логин или пароль."}, status_code=401)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("dashboard.html", {"request": request, "site_url": "https://lithiumhome.ru"})

# ─── API ──────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats(request: Request):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]
        positive = c.execute("SELECT COUNT(*) FROM mentions WHERE sentiment='positive'").fetchone()[0]
        negative = c.execute("SELECT COUNT(*) FROM mentions WHERE sentiment='negative'").fetchone()[0]
        neutral = max(total - positive - negative, 0)
        conn.close()
        return {"total": total, "positive": positive, "negative": negative, "neutral": neutral, "ads_count": 0}
    except Exception as e:
        logger.error(f"Ошибка в /api/stats: {e}")
        return {"total": 0, "positive": 0, "negative": 0, "neutral": 0, "ads_count": 0}

@app.get("/api/mentions")
async def api_mentions(request: Request, sentiment: str = Query(default="all"), limit: int = Query(default=200)):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if sentiment != "all":
            c.execute("SELECT id, source, text, sentiment, is_b2b, created_at, viewed FROM mentions WHERE sentiment=? ORDER BY created_at DESC LIMIT ?", (sentiment, limit))
        else:
            c.execute("SELECT id, source, text, sentiment, is_b2b, created_at, viewed FROM mentions ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        items = [dict(row) for row in rows]
        return {"items": items}
    except Exception as e:
        logger.error(f"Ошибка в /api/mentions: {e}")
        return {"items": []}

@app.get("/api/ads")
async def api_ads():
    return {"items": []}

@app.get("/api/geo")
async def api_geo():
    cities = ["Москва", "Санкт-Петербург", "Екатеринбург", "Казань", "Новосибирск"]
    rows = [{"brand": "LITHIUM", "positions": {c: None for c in cities}}]
    return {"cities": cities, "rows": rows}

@app.get("/api/trends")
async def api_trends():
    return {"items": []}

@app.get("/api/site-status")
async def api_site_status():
    return {"up": True, "status_code": 200}

@app.get("/api/collect")
@app.post("/api/collect")
async def collect_data(token: str = Query(...)):
    if token != os.getenv("COLLECT_TOKEN", ""):
        return JSONResponse({"error": "invalid token"}, status_code=403)
    return {"status": "ok", "message": "Сбор данных пока не реализован"}
