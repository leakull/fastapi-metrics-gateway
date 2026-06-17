# Analytics Gateway

Высоконагруженный REST API для сбора пользовательских событий и предоставления агрегированных аналитических отчётов. Сервис обеспечивает минимальное время отклика при приёме потока данных за счёт кэширующего слоя Redis и пакетной записи (Write-Behind) через фонового консьюмера.

## Технологический стек

- **Язык:** Python 3.11+
- **Фреймворк:** FastAPI
- **БД:** PostgreSQL 16 + SQLAlchemy 2.0 (async) + Alembic
- **Кэш / Очередь:** Redis 7
- **Аутентификация:** JWT (python-jose) + Argon2
- **Rate Limiting:** slowapi
- **Мониторинг:** Prometheus (prometheus-client) + structured logging с request-id
- **Контейнеризация:** Docker (multi-stage, non-root) + Docker Compose
- **CI:** GitHub Actions (pytest на Postgres + Redis)
- **Тестирование:** pytest + pytest-asyncio + httpx

## Архитектура

```
src/
├── auth/            # Аутентификация (register, login, JWT)
├── events/          # Приём событий активности (Write to Redis)
├── analytics/       # Агрегированные отчёты (Cache-Aside)
├── worker/          # Фоновой консьюмер (Redis → PostgreSQL)
├── config.py        # Конфигурация (Pydantic Settings + .env)
├── database.py      # Async SQLAlchemy engine + Redis client
├── main.py          # FastAPI приложение + lifespan
├── models.py        # Базовая DeclarativeBase
└── exceptions.py    # Глобальные обработчики ошибок
```

### Паттерны проектирования

- **Write-Behind Queue** — приём событий в Redis, пакетная запись в PostgreSQL фоновым консьюмером
- **Cache-Aside** — кэширование результатов аналитики в Redis с TTL 5 минут
- **Repository** — изоляция SQL-запросов от бизнес-логики
- **BRIN-индекс** — оптимизация для временных рядов (события пишутся последовательно)

## Сущности базы данных

```mermaid
erDiagram
    USERS {
        uuid id PK
        varchar email UK
        varchar hashed_password
        int company_id
        boolean is_active
        timestamp created_at
    }

    EVENTS {
        uuid id PK
        int company_id
        varchar user_id
        varchar event_type
        jsonb payload
        timestamp created_at
    }

    USERS ||--o{ EVENTS : "generates"
```

### Индексы

| Индекс | Тип | Таблица | Назначение |
|--------|-----|---------|------------|
| `ix_events_created_at_brin` | BRIN | events | Быстрая выборка по диапазону дат |
| `ix_events_company_event_type` | B-tree | events | Группировка по company + event_type |
| `ix_events_company_id` | B-tree | events | Фильтрация по company |
| `ix_events_user_id` | B-tree | events | Фильтрация по user |
| `ix_users_email` | B-tree | users | Поиск по email (UNIQUE) |

## Консьюмер (Write-Behind)

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Redis
    participant Consumer
    participant PostgreSQL

    Client->>API: POST /api/v1/events/
    API->>Redis: RPUSH queue:events
    API-->>Client: 202 Accepted

    loop Каждые 5 секунд
        Consumer->>Redis: LMOVE queue:events processing
        Redis-->>Consumer: batch events
        Consumer->>PostgreSQL: INSERT INTO events
        Consumer->>Redis: DELETE processing
    end
```

## Запуск

```bash
# Клонирование
git clone <repository-url>
cd analytics-gateway

# Настройка переменных окружения
cp .env.example .env

# Запуск всех сервисов
docker-compose up -d

# Просмотр API документации
open http://localhost:8080/docs
```

### Сервисы

| Сервис | Порт | Описание |
|--------|------|----------|
| API | 8080 | FastAPI приложение |
| Worker | — | Фоновый консьюмер (Write-Behind), один экземпляр |
| PostgreSQL | 5434 | База данных |
| Redis | 6381 | Кэш и очередь событий |

## API Endpoints

### Аутентификация

| Метод | Путь | Описание | Авторизация |
|-------|------|----------|-------------|
| POST | `/api/v1/auth/register/` | Регистрация пользователя | Нет |
| POST | `/api/v1/auth/login/` | Получение JWT токена | Нет |
| GET | `/api/v1/auth/me/` | Данные текущего пользователя | Bearer |

### События

| Метод | Путь | Описание | Авторизация |
|-------|------|----------|-------------|
| POST | `/api/v1/events/` | Отправка события в очередь (idempotent по `event_id`) | Bearer |

Ответ `202` возвращает `event_id` — назначенный ключ идемпотентности. Повторная отправка с тем же `event_id` (своим или возвращённым сервером) не создаст дубликат: консьюмер вставляет события с `ON CONFLICT (id) DO NOTHING`.

### Аналитика

| Метод | Путь | Описание | Авторизация |
|-------|------|----------|-------------|
| GET | `/api/v1/analytics/summary/` | Агрегированный отчёт | Bearer |

### Системные

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Проверка здоровья (DB + Redis) + глубина очереди (`queue_depth`) |
| GET | `/metrics` | Метрики Prometheus (API) |

Воркер экспортирует свои метрики (`events_inserted_total` и др.) на отдельном порту `:9100`.

## Примеры запросов

### Регистрация

```bash
curl -X POST http://localhost:8080/api/v1/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"securepass123","company_id":1}'
```

### Получение токена

```bash
curl -X POST http://localhost:8080/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"securepass123"}'
```

### Отправка события

```bash
curl -X POST http://localhost:8080/api/v1/events/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user-1","event_type":"page_view","payload":{"url":"/pricing"}}'
```

### Получение аналитики

```bash
curl "http://localhost:8080/api/v1/analytics/summary/?start_date=2026-01-01&end_date=2026-12-31" \
  -H "Authorization: Bearer <token>"
```

## Конфигурация

Переменные окружения (`.env`):

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `ENVIRONMENT` | `development` | Окружение. При `production` приложение не стартует с дефолтным `JWT_SECRET` |
| `DATABASE_URL` | `postgresql+asyncpg://analytics:analytics@localhost:5432/analytics` | URL подключения к PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | URL подключения к Redis |
| `JWT_SECRET` | — | Секрет для подписи JWT токенов |
| `JWT_ALGORITHM` | `HS256` | Алгоритм шифрования JWT |
| `JWT_EXPIRE_MINUTES` | `30` | Время жизни токена (минуты) |
| `BATCH_INTERVAL` | `5` | Интервал обработки очереди (секунды) |
| `BATCH_SIZE` | `1000` | Размер батча для bulk insert |
| `POSTGRES_USER` | `analytics` | Пользователь PostgreSQL |
| `POSTGRES_PASSWORD` | `analytics` | Пароль PostgreSQL |
| `POSTGRES_DB` | `analytics` | Имя базы данных |

## Тестирование

```bash
# Unit и интеграционные тесты (52 теста, покрытие 97%)
python3 -m pytest tests/ --ignore=tests/e2e -v

# E2E тесты (требуют запущенные контейнеры)
python3 -m pytest tests/e2e/ -v -m e2e

# Все тесты
python3 -m pytest tests/ -v

# С отчётом покрытия
python3 -m pytest tests/ --ignore=tests/e2e --cov=src --cov-report=term-missing
```

### Покрытие тестами

| Модуль | Покрытие |
|--------|----------|
| analytics/ | 100% |
| auth/ | 95%+ |
| events/ | 100% |
| worker/ | 98% |
| config/ | 100% |
| **Итого** | **97%** |

## Структура проекта

```
.
├── alembic/                  # Миграции базы данных
│   ├── env.py
│   └── versions/
│       └── 001_initial.py
├── src/
│   ├── auth/                 # Аутентификация и авторизация
│   │   ├── models.py         # Модель User
│   │   ├── schemas.py        # Pydantic схемы
│   │   ├── service.py        # Бизнес-логика (hash, JWT)
│   │   ├── router.py         # API роутеры
│   │   └── dependencies.py   # FastAPI Depends
│   ├── events/               # Модуль приёма событий
│   │   ├── models.py         # Модель Event
│   │   ├── schemas.py        # EventCreate, EventAccepted
│   │   ├── service.py        # Redis queue (RPUSH)
│   │   └── router.py         # POST /api/v1/events/
│   ├── analytics/            # Модуль аналитики
│   │   ├── schemas.py        # SummaryResponse
│   │   ├── repositories.py   # SQL агрегирующие запросы
│   │   ├── service.py        # Cache-Aside (Redis + TTL)
│   │   └── router.py         # GET /api/v1/analytics/summary/
│   ├── worker/               # Фоновой консьюмер
│   │   ├── consumer.py       # Write-Behind: Redis → PostgreSQL
│   │   └── config.py         # Настройки батчинга
│   ├── config.py             # Pydantic Settings
│   ├── database.py           # Async engine + Redis client
│   ├── main.py               # FastAPI app + lifespan
│   ├── models.py             # DeclarativeBase
│   └── exceptions.py         # AppException handler
├── tests/
│   ├── conftest.py           # Фикстуры: engine, client, auth
│   ├── auth/                 # Тесты аутентификации (17)
│   ├── events/               # Тесты событий (6)
│   ├── analytics/            # Тесты аналитики (8)
│   ├── worker/               # Тесты консьюмера (4)
│   ├── e2e/                  # E2E тесты (4)
│   ├── test_config.py        # Тесты конфигурации (5)
│   ├── test_exceptions.py    # Тесты обработчиков (1)
│   ├── test_health.py        # Тест health check (1)
│   └── test_main.py          # Тесты lifespan (3)
├── .env.example              # Шаблон переменных окружения
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
└── pyproject.toml
```

## Архитектурные решения

### Очередь событий

События не записываются напрямую в PostgreSQL. Каждое событие попадает в Redis-очередь (`queue:events`), откуда фоновый консьюмер забирает их батчами и выполняет bulk insert. Это обеспечивает:

- **Низкий latency** ответа API (202 Accepted без ожидания записи в БД)
- **Устойчивость к пиковым нагрузкам** (очередь сглаживает всплески)
- **Гарантию доставки (at-least-once)**: батч атомарно переносится в `queue:events:processing` через `LMOVE` и удаляется только после успешного `COMMIT`. Если процесс упал между чтением и записью, элементы остаются в processing-списке и восстанавливаются при следующем старте. При сбое между `COMMIT` и удалением possible повтор — это **at-least-once**, а не exactly-once; для дедупликации можно передавать клиентский `event_id`.

> **Топология:** консьюмер запускается как **отдельный процесс** (`python -m src.worker`, сервис `worker` в docker-compose) — намеренно один экземпляр. Это исключает гонку нескольких консьюмеров на одной очереди. Для масштабирования консьюмера понадобятся per-consumer processing-ключи + reaper по heartbeat.

### Кэширование аналитики

Результаты аналитических запросов кэшируются в Redis с TTL 5 минут. При повторном запросе с теми же параметрами данные отдаются из кэша без обращения к PostgreSQL.

Диапазоны, **доходящие до сегодняшнего дня, не кэшируются** — в них ещё поступают события, поэтому кэш отдавал бы устаревшие цифры. Кэшируются только закрытые прошлые периоды.

### Идемпотентность приёма

Каждому событию при постановке в очередь присваивается стабильный `id` (можно передать свой `event_id`). Консьюмер вставляет батч с `ON CONFLICT (id) DO NOTHING`, поэтому повторная обработка (например, при перезапуске воркера после сбоя) не создаёт дубликатов — это закрывает слабое место at-least-once доставки.

### Наблюдаемость

- **Метрики Prometheus**: `events_enqueued_total`, `events_inserted_total`, `analytics_cache_hits_total` / `_misses_total`, гистограмма латентности `http_request_duration_seconds`. API — на `/metrics`, воркер — на `:9100`.
- **Structured logging**: каждый лог содержит `request_id` (берётся из заголовка `X-Request-ID` либо генерируется), который также возвращается клиенту в ответе.
- **Healthcheck** дополнительно отдаёт глубину очереди (`queue_depth`) для мониторинга backlog.

### BRIN-индекс

Для поля `created_at` используется BRIN-индекс вместо стандартного B-tree. BRIN идеально подходит для временных рядов, где данные записываются последовательно — он занимает на порядки меньше места и обеспечивает высокую скорость выборки по диапазону дат.
