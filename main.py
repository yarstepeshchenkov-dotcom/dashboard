"""
LITHIUM Intelligence Dashboard
==============================
Без моков. Все данные реальные из БД.
Сбор из Яндекс.Новостей, VK, форумов.
"""

import os
import sqlite3
import smtplib
import secrets
import asyncio
import logging
from email.mime.text import MIMEText
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, Depends, Query
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()

# ─── КОНФИГУРАЦИЯ ──────────────────────────────────────────────────────────

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SECRET_KEY = os.getenv("SECRET_KEY", "insecure-dev-key-change-me")
DB_PATH = os.getenv("DB_PATH", "/tmp/lithium.db")
SITE_URL = os.getenv("SITE_URL", "https://lithiumhome.ru")

EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

NEGATIVE_ALERT_THRESHOLD = int(os.getenv("NEGATIVE_ALERT_THRESHOLD", "5"))
ALERT_WINDOW_MINUTES = int(os.getenv("ALERT_WINDOW_MINUTES", "60"))
BACKGROUND_CHECK_INTERVAL_SECONDS = int(os.getenv("BACKGROUND_CHECK_INTERVAL_SECONDS", "300"))

CITIES = ["Москва", "Санкт-Петербург", "Екатеринбург", "Казань", "Новосибирск"]

COMPETITORS = [
    "Stosa", "Binova", "Scavolini", "Aran",
    "Nobilia", "Nolte", "Schmidt", "Мария",
    "Cesar", "Arrital", "Modulnova", "Arredo3",
    "Leicht", "Beckermann", "Haecker", "Nolte",
    "Silver Home",
    "Giulia Novars",
    "Boffi", "Minotti", "Arclinea", "Valcucine",
    "Poliform", "Ernestomeda", "Dada", "Aster", "Snaidero",
    "Eggersmann", "Bulthaup", "Poggenpohl", "SieMatic", "Warendorf"
]
COMPETITORS = list(dict.fromkeys(COMPETITORS))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("lithium_dashboard")

# ─── ПРИЛОЖЕНИЕ ─────────────────────────────────────────────────────────────

app = FastAPI(title="LITHIUM Intelligence Dashboard")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="lithium_session")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

_last_alert_sent_at: dict[str, datetime] = {}

# ─── РАБОТА С БД ──────────────────────────────────────────────────────────

@contextmanager
def get_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        logger.info(f"✅ Создана папка для БД: {db_dir}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None

def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        return column in cols
    except sqlite3.Error:
        return False

def init_db():
    try:
        with get_db() as conn:
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
            c.execute('''CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                competitor TEXT,
                title TEXT,
                platform TEXT,
                url TEXT,
                created_at TEXT
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
            conn.commit()
            logger.info("✅ Таблицы созданы (или уже существуют).")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

# ─── ЗАПРОСЫ К БД ─────────────────────────────────────────────────────────

def get_stats() -> dict:
    try:
        with get_db() as conn:
            if not table_exists(conn, "mentions"):
                return {"total": 0, "positive": 0, "negative": 0, "neutral": 0, "ads_count": 0}
            total = conn.execute("SELECT COUNT(*) c FROM mentions").fetchone()["c"]
            positive = conn.execute("SELECT COUNT(*) c FROM mentions WHERE sentiment='positive'").fetchone()["c"]
            negative = conn.execute("SELECT COUNT(*) c FROM mentions WHERE sentiment='negative'").fetchone()["c"]
            neutral = max(total - positive - negative, 0)
            ads_count = 0
            if table_exists(conn, "ads"):
                ads_count = conn.execute("SELECT COUNT(*) c FROM ads").fetchone()["c"]
            return {"total": total, "positive": positive, "negative": negative, "neutral": neutral, "ads_count": ads_count}
    except Exception as e:
        logger.warning(f"DB error in get_stats: {e}")
        return {"total": 0, "positive": 0, "negative": 0, "neutral": 0, "ads_count": 0}

def get_mentions(sentiment: str | None = None, limit: int = 200) -> list[dict]:
    try:
        with get_db() as conn:
            if not table_exists(conn, "mentions"):
                return []
            has_viewed = column_exists(conn, "mentions", "viewed")
            select_cols = "id, source, text, sentiment, is_b2b, created_at" + (", viewed" if has_viewed else ", 0 as viewed")
            query = f"SELECT {select_cols} FROM mentions"
            params = []
            if sentiment and sentiment != "all":
                query += " WHERE sentiment = ?"
                params.append(sentiment)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"DB error in get_mentions: {e}")
        return []

def get_ads(limit: int = 200) -> list[dict]:
    try:
        with get_db() as conn:
            if not table_exists(conn, "ads"):
                return []
            rows = conn.execute(
                "SELECT id, competitor, title, platform, url, created_at "
                "FROM ads ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"DB error in get_ads: {e}")
        return []

def get_geo() -> dict:
    try:
        with get_db() as conn:
            rows = []
            if table_exists(conn, "geo_positions"):
                rows = conn.execute("SELECT city, brand, position FROM geo_positions").fetchall()
            by_brand = {}
            for r in rows:
                by_brand.setdefault(r["brand"], {})[r["city"]] = r["position"]
            all_brands = ["LITHIUM"] + COMPETITORS
            table = [{
                "brand": brand,
                "positions": {c: by_brand.get(brand, {}).get(c) for c in CITIES}
            } for brand in all_brands]
            logger.info(f"Гео-данные: {len(table)} брендов, города: {CITIES}")
            return {"cities": CITIES, "rows": table}
    except Exception as e:
        logger.warning(f"DB error in get_geo: {e}")
        return {"cities": CITIES, "rows": []}

def get_trends(limit: int = 5) -> list[dict]:
    try:
        with get_db() as conn:
            if not table_exists(conn, "trends"):
                return []
            rows = conn.execute(
                "SELECT keyword, mentions_count, growth_percent "
                "FROM trends ORDER BY growth_percent DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"DB error in get_trends: {e}")
        return []

def mark_mention_viewed(mention_id: int) -> bool:
    try:
        with get_db() as conn:
            if not table_exists(conn, "mentions") or not column_exists(conn, "mentions", "viewed"):
                return False
            conn.execute("UPDATE mentions SET viewed = 1 WHERE id = ?", (mention_id,))
            conn.commit()
            return True
    except Exception as e:
        logger.warning(f"Failed to mark mention viewed: {e}")
        return False

def count_recent_negative(minutes: int) -> int:
    try:
        with get_db() as conn:
            if not table_exists(conn, "mentions"):
                return 0
            since = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)).isoformat()
            row = conn.execute(
                "SELECT COUNT(*) c FROM mentions WHERE sentiment='negative' AND created_at >= ?", (since,)
            ).fetchone()
            return row["c"] if row else 0
    except Exception:
        return 0

# ─── АВТОРИЗАЦИЯ ──────────────────────────────────────────────────────────

def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))

def get_or_create_csrf(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_hex(16)
        request.session["csrf_token"] = token
    return token

# ─── ПРОВЕРКА САЙТА ──────────────────────────────────────────────────────

async def check_site_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(SITE_URL)
            return {"up": resp.status_code < 500, "status_code": resp.status_code}
    except httpx.RequestError as e:
        logger.warning(f"Site status check failed: {e}")
        return {"up": False, "status_code": None}

# ─── EMAIL-УВЕДОМЛЕНИЯ ──────────────────────────────────────────────────

def send_email_alert(subject: str, body: str) -> None:
    if not EMAIL_ENABLED:
        return
    if not (SMTP_SERVER and SMTP_USER and SMTP_PASS and EMAIL_TO):
        logger.warning("EMAIL_ENABLED=true, но SMTP-настройки неполные.")
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM or SMTP_USER
        msg["To"] = EMAIL_TO
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(msg["From"], [EMAIL_TO], msg.as_string())
        logger.info(f"Email alert sent: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email alert: {e}")

def _should_send_alert(key: str, cooldown_minutes: int = 60) -> bool:
    last = _last_alert_sent_at.get(key)
    if last and datetime.now(timezone.utc) - last < timedelta(minutes=cooldown_minutes):
        return False
    _last_alert_sent_at[key] = datetime.now(timezone.utc)
    return True

async def background_monitor():
    while True:
        try:
            status = await check_site_status()
            if not status["up"] and _should_send_alert("site_down"):
                send_email_alert(
                    "🔴 LITHIUM: сайт недоступен",
                    f"lithiumhome.ru не отвечает (код: {status['status_code']}). "
                    f"Время: {datetime.now(timezone.utc).isoformat()}"
                )
            neg = count_recent_negative(ALERT_WINDOW_MINUTES)
            if neg >= NEGATIVE_ALERT_THRESHOLD and _should_send_alert("negative_spike"):
                send_email_alert(
                    "🔴 LITHIUM: всплеск негатива",
                    f"За {ALERT_WINDOW_MINUTES} мин. {neg} негативных упоминаний (порог: {NEGATIVE_ALERT_THRESHOLD})."
                )
        except Exception as e:
            logger.error(f"background_monitor error: {e}")
        await asyncio.sleep(BACKGROUND_CHECK_INTERVAL_SECONDS)

# ─── СТРАНИЦЫ ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    csrf_token = get_or_create_csrf(request)
    return templates.TemplateResponse("login.html", {"request": request, "csrf_token": csrf_token, "error": None})

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), csrf_token: str = Form(...)):
    session_csrf = request.session.get("csrf_token")
    if not session_csrf or csrf_token != session_csrf:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "csrf_token": get_or_create_csrf(request), "error": "Сессия устарела."},
            status_code=400,
        )
    if secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD):
        request.session["authenticated"] = True
        request.session.pop("csrf_token", None)
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "csrf_token": get_or_create_csrf(request), "error": "Неверный логин или пароль."},
        status_code=401,
    )

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("dashboard.html", {"request": request, "site_url": SITE_URL})

# ─── API ──────────────────────────────────────────────────────────────────

def _guard(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None

@app.get("/api/stats")
async def api_stats(request: Request):
    if (guard := _guard(request)):
        return guard
    return get_stats()

@app.get("/api/mentions")
async def api_mentions(request: Request, sentiment: str = Query(default="all"), limit: int = Query(default=200, le=1000)):
    if (guard := _guard(request)):
        return guard
    return {"items": get_mentions(sentiment=sentiment, limit=limit)}

@app.post("/api/mentions/{mention_id}/viewed")
async def api_mark_viewed(request: Request, mention_id: int):
    if (guard := _guard(request)):
        return guard
    ok = mark_mention_viewed(mention_id)
    return {"ok": ok}

@app.get("/api/ads")
async def api_ads(request: Request, limit: int = Query(default=200, le=1000)):
    if (guard := _guard(request)):
        return guard
    return {"items": get_ads(limit=limit)}

@app.get("/api/geo")
async def api_geo(request: Request):
    if (guard := _guard(request)):
        return guard
    return get_geo()

@app.get("/api/trends")
async def api_trends(request: Request, limit: int = Query(default=5, le=50)):
    if (guard := _guard(request)):
        return guard
    return {"items": get_trends(limit=limit)}

@app.get("/api/site-status")
async def api_site_status(request: Request):
    if (guard := _guard(request)):
        return guard
    return await check_site_status()

# ─── ЗАПУСК ──────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    init_db()
    asyncio.create_task(background_monitor())
    logger.info(f"🚀 Сервер запущен, БД: {DB_PATH}")

# --------------------------------------------------------------------------
# СБОР ДАННЫХ ИЗ РЕАЛЬНЫХ ИСТОЧНИКОВ
# --------------------------------------------------------------------------

from services.news_collector import collect_news
from services.vk_collector import collect_vk_rss
from services.forum_collector import collect_forum

@app.post("/api/collect")
async def collect_data(token: str = Query(...)):
    if token != os.getenv("COLLECT_TOKEN", ""):
        return JSONResponse({"error": "invalid token"}, status_code=403)

    all_mentions = []
    all_mentions.extend(collect_news())
    all_mentions.extend(collect_vk_rss())
    all_mentions.extend(collect_forum())

    if not all_mentions:
        return {"status": "ok", "message": "Новых данных не найдено"}

    with get_db() as conn:
        c = conn.cursor()
        saved = 0
        for m in all_mentions:
            c.execute(
                "SELECT id FROM mentions WHERE source = ? AND text LIKE ?",
                (m["source"], m["text"][:100] + "%")
            )
            if not c.fetchone():
                c.execute("""
                    INSERT INTO mentions (source, text, sentiment, is_b2b, created_at, viewed)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (m["source"], m["text"], m["sentiment"], m["is_b2b"], m["created_at"], m["viewed"]))
                saved += 1
        conn.commit()

    return {"status": "ok", "collected": len(all_mentions), "saved": saved}
