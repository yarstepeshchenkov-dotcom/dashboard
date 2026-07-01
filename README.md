# LITHIUM Intelligence Dashboard

Веб-дашборд маркетинговой разведки для бренда LITHIUM. Заменяет
Telegram-бота: тот же функционал (упоминания, реклама конкурентов,
гео-анализ, тренды, статус сайта, уведомления) в защищённом веб-интерфейсе,
работающем поверх уже существующей базы `lithium.db`.

## Стек

- **Backend:** FastAPI (Python 3.10+)
- **Frontend:** HTML + CSS + vanilla JS, графики — Chart.js (CDN)
- **Шаблоны:** Jinja2
- **БД:** существующая SQLite-база бота (только чтение, кроме отметки
  «просмотрено» у упоминаний)
- **Авторизация:** сессии на подписанных cookie (Starlette `SessionMiddleware`)
  + CSRF-токен на форме логина

## Установка и запуск

```bash
cd lithium_dashboard
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
nano .env                         # укажите пароль, SECRET_KEY, путь к БД

uvicorn main:app --host 0.0.0.0 --port 8001
```

Откройте `http://<сервер>:8001` — попадёте на страницу входа. После логина
доступен дашборд на `/dashboard`.

Для продакшена рекомендуется запускать за Nginx/Caddy с HTTPS и, при
желании, через `systemd` или `pm2`/`supervisor`, чтобы процесс
перезапускался автоматически. Пример unit-файла:

```ini
[Unit]
Description=LITHIUM Intelligence Dashboard
After=network.target

[Service]
WorkingDirectory=/root/lithium_dashboard
ExecStart=/root/lithium_dashboard/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8001
Restart=always
EnvironmentFile=/root/lithium_dashboard/.env

[Install]
WantedBy=multi-user.target
```

## Настройка `.env`

| Переменная | Назначение |
|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | логин и пароль для входа в дашборд |
| `SECRET_KEY` | ключ для подписи сессионных cookie — задайте длинную случайную строку |
| `DB_PATH` | путь к `lithium.db` (по умолчанию `/root/lithium_bot/data/lithium.db`) |
| `SITE_URL` | адрес, доступность которого проверяется (по умолчанию `https://lithiumhome.ru`) |
| `EMAIL_ENABLED` | `true`/`false` — включить email-уведомления о критических событиях |
| `EMAIL_FROM`, `EMAIL_TO`, `SMTP_*` | параметры почты для алертов |
| `NEGATIVE_ALERT_THRESHOLD` | сколько негативных упоминаний за окно считать всплеском (по умолчанию 5) |
| `ALERT_WINDOW_MINUTES` | окно в минутах для подсчёта негатива (по умолчанию 60) |
| `BACKGROUND_CHECK_INTERVAL_SECONDS` | как часто фоновая задача проверяет сайт/негатив (по умолчанию 300 сек) |

## Схема БД

Дашборд читает данные напрямую из `lithium.db` через SQL-запросы.
Ожидаемые таблицы и колонки описаны в шапке `main.py`:

- `mentions` — упоминания бренда (source, text, sentiment, is_b2b, created_at, viewed)
- `ads` — реклама конкурентов (competitor, title, platform, url, created_at)
- `geo_positions` — позиции по городам (city, brand, position)
- `trends` — тренды запросов (keyword, mentions_count, growth_percent)

**Если у вас в реальной базе другие названия таблиц или колонок** — правки
нужны только в разделе `# ЗАПРОСЫ К БД` файла `main.py` (функции `get_stats`,
`get_mentions`, `get_ads`, `get_geo`, `get_trends`). Всё остальное
приложение (роуты, фронтенд) от схемы не зависит.

Если какой-то таблицы нет — соответствующий API-эндпоинт не упадёт, а
вернёт пустой список / нули с пометкой `"mock": true`, чтобы дашборд
оставался рабочим даже на неполной БД.

## Функциональность

- **Дашборд** — карточки со сводкой (всего/позитив/негатив/реклама),
  столбчатый график роста трендов, топ-5 трендов.
- **Упоминания** — таблица с фильтром по тональности (вкладки), возможность
  отметить упоминание как просмотренное.
- **Реклама конкурентов** — таблица объявлений, сортировка по дате (новые
  сверху — на уровне SQL-запроса).
- **Гео-анализ** — таблица позиций LITHIUM и конкурентов по 5 городам
  (Москва, СПб, Екатеринбург, Казань, Новосибирск).
- **Статус сайта** — индикатор в шапке (зелёный/красный), обновляется каждые
  30 секунд.
- **Уведомления** — при обнаружении новых негативных упоминаний или новой
  рекламы конкурентов (по сравнению с ранее увиденными, хранится в
  `localStorage` браузера) показывается всплывающее уведомление на 8 секунд.
- **Email-алерты (опционально)** — фоновая задача каждые
  `BACKGROUND_CHECK_INTERVAL_SECONDS` проверяет: (1) доступность сайта,
  (2) число негативных упоминаний за `ALERT_WINDOW_MINUTES` минут. При
  превышении порога и включённом `EMAIL_ENABLED` отправляется письмо
  (с защитой от повторной отправки чаще раза в час на одно и то же событие).

## Безопасность

- Пароль и `SECRET_KEY` только в `.env`, не в коде.
- Сессии — подписанные cookie (`itsdangerous` под капотом Starlette),
  подделать их без `SECRET_KEY` нельзя.
- Форма логина защищена CSRF-токеном, привязанным к сессии.
- Все `/api/*` и `/dashboard` роуты проверяют авторизацию и возвращают
  401/редирект на страницу входа при её отсутствии.
- Пароли сравниваются через `secrets.compare_digest` (защита от timing-атак).

## Структура проекта

```
lithium_dashboard/
├── main.py                # FastAPI-приложение: авторизация, API, фоновые задачи
├── requirements.txt
├── .env.example
├── templates/
│   ├── login.html
│   └── dashboard.html
├── static/
│   ├── style.css
│   └── script.js
└── README.md
```
