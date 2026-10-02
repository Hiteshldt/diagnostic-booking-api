# EVE Healthcare — Diagnostic Bookings API

A small backend for booking diagnostic tests and paying for them through a simulated
payment provider. Built with **Django REST Framework** and **PostgreSQL**.

The focus is on the parts that are easy to get subtly wrong: an **idempotent payment
webhook**, a strict **booking state machine**, and correctness under **concurrent
requests** — all covered by tests.

## Contents

- [Architecture](#architecture)
- [Run it](#run-it)
- [API](#api)
- [Database design](#database-design)
- [How the hard parts work](#how-the-hard-parts-work)
- [Edge cases handled](#edge-cases-handled)
- [Tests](#tests)
- [Assumptions](#assumptions)
- [What I would improve with more time](#what-i-would-improve-with-more-time)

## Architecture

```mermaid
flowchart LR
    Client([Client / patient app])
    Provider([Payment provider<br/>simulated])

    subgraph API["Django + DRF (gunicorn)"]
        direction TB
        MW[Middleware<br/>request id + JSON logs]
        V[Views<br/>validate input, check auth]
        S[Services<br/>business rules, transactions, locks]
        MW --> V --> S
    end

    PG[(PostgreSQL<br/>source of truth)]
    R[(Redis<br/>cache · rate limits · job queue)]
    W[Celery worker + beat<br/>webhook retries, expiry job]

    Client -- "JWT" --> MW
    Provider -- "HMAC-signed webhook" --> MW
    S --> PG
    V -. "centre list cache" .-> R
    S -. "enqueue retry" .-> R
    R --> W --> PG
```

| Piece | What it does here |
|---|---|
| **Django + DRF** | The web framework: routing, validation (serializers), auth, ORM |
| **PostgreSQL** | Stores everything. Constraints and row locks enforce the rules that must never break |
| **JWT** (`simplejwt`) | Stateless login: the server signs a token, the client sends it on every request |
| **Redis** | Cache for the centre catalogue, counters for rate limiting, queue for Celery |
| **Celery** | Background worker: retries webhook processing, expires unpaid bookings |
| **drf-spectacular** | Generates the OpenAPI schema and Swagger UI from the code |
| **Docker Compose** | Starts API + Postgres + Redis + worker with one command |

Code layout — each app owns one concept, and views stay thin by delegating rules to `services.py`:

```
config/            settings, urls, celery
apps/
  core/            shared: error format, pagination, permissions, logging, health
  accounts/        User model, signup, login
  centres/         centres, test catalogue, prices, caching
  bookings/        Booking model + state machine, expiry task
  payments/        Payment + WebhookEvent, simulated gateway, webhook, retry task
tests/             98 tests (API, state machine, idempotency, real race conditions)
scripts/           send_webhook.py - plays the payment provider
```

## Run it

```bash
git clone https://github.com/Hiteshldt/diagnostic-booking-api.git
cd diagnostic-booking-api
```

### Option A — Docker (full stack: Postgres, Redis, Celery)

```bash
docker compose up --build
```

API on <http://localhost:8000>, Swagger UI on <http://localhost:8000/docs/>.
Migrations and demo data are applied automatically.

### Option B — Locally, no services needed

With no environment variables set, the app falls back to SQLite, an in-memory cache,
and inline Celery tasks, so it runs with nothing else installed.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo        # admin user + 3 demo centres
python manage.py runserver
```

To use Postgres/Redis locally, set `DATABASE_URL` and `REDIS_URL` (see `.env.example`).

**Demo admin:** `admin@example.com` / `Admin@12345` (can create centres and tests).

### Run the tests

```bash
pytest
```

On SQLite 94 tests run and 4 are skipped; the skipped ones are the multi-threaded race
tests, which need PostgreSQL row locks. To run all 98:

```bash
DATABASE_URL=postgres://user:pass@localhost:5432/eve pytest
```

## API

Interactive docs: **`/docs/`** (Swagger UI) · raw schema: **`/schema/`**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/signup/` | – | Create account, returns user + tokens |
| POST | `/auth/login/` | – | Email + password → `access` + `refresh` tokens |
| POST | `/auth/refresh/` | – | New access token from a refresh token |
| GET | `/auth/me/` | user | Current user |
| GET | `/centres/` | – | List centres with tests and prices. `?search=`, `?test=<id>`, `?page=` |
| GET | `/centres/{id}/` | – | One centre |
| POST / PATCH / DELETE | `/centres/…` | admin | Manage centres |
| GET | `/tests/` | – | Test catalogue |
| POST / PATCH / DELETE | `/tests/…` | admin | Manage the catalogue |
| GET | `/centres/{id}/tests/` | – | Tests offered by a centre |
| POST / PATCH / DELETE | `/centres/{id}/tests/…` | admin | Add a test to a centre / change its price |
| POST | `/bookings/` | user | Book a test |
| GET | `/bookings/` | user | My bookings. `?status=` |
| GET | `/bookings/{id}/` | user | One of my bookings |
| POST | `/bookings/{id}/cancel/` | user | Cancel a booking |
| POST | `/payments/` | user | Pay for a booking (simulated) |
| GET | `/payments/`, `/payments/{id}/` | user | My payments |
| POST | `/payments/webhook/` | HMAC signature | Payment-status update from the provider |
| GET | `/health/` | – | Liveness check |

### Example walkthrough

```bash
BASE=http://localhost:8000

# 1. Sign up (the response includes tokens)
curl -s -X POST $BASE/auth/signup/ -H 'Content-Type: application/json' \
  -d '{"email": "patient@example.com", "password": "Str0ng-pass-123", "full_name": "Asha"}'
TOKEN=<access token from the response>

# 2. Browse centres
curl -s "$BASE/centres/?search=bengaluru"

# 3. Book a test
curl -s -X POST $BASE/bookings/ -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"centre_id": 1, "test_id": 1, "appointment_at": "2026-12-01T10:00:00Z"}'
# -> {"id": "997b17d4-…", "status": "PENDING", "amount": "350.00", …}

# 4. Pay. "simulate" is optional: success | failed | pending. Omit it for a random result.
curl -s -X POST $BASE/payments/ -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"booking_id": "997b17d4-…", "simulate": "pending"}'
# -> {"id": "33499cfc-…", "status": "PENDING", …}

# 5. The provider reports the result. Run it twice: the second call changes nothing.
python scripts/send_webhook.py 33499cfc-… SUCCESS --event-id evt_1
# -> 200 {"event_id":"evt_1","status":"PROCESSED","duplicate":false}
# -> 200 {"event_id":"evt_1","status":"PROCESSED","duplicate":true}
```

Webhook request, if you prefer to build it by hand:

```
POST /payments/webhook/
X-Webhook-Signature: <hex HMAC-SHA256 of the raw body, keyed with WEBHOOK_SECRET>

{"event_id": "evt_1", "payment_id": "33499cfc-…", "status": "SUCCESS"}
```

### Errors

Every error has the same shape:

```json
{"error": {"code": "validation_error", "message": "Invalid request.",
           "details": {"appointment_at": ["Appointment must be in the future."]}}}
```

| Status | Meaning |
|---|---|
| 400 | Invalid input (`details` lists the fields) |
| 401 | Missing/invalid token, or bad webhook signature |
| 403 | Logged in but not allowed (e.g. non-admin creating a centre) |
| 404 | Does not exist — or belongs to someone else |
| 409 | Valid request that clashes with current state (already paid, already cancelled, duplicate booking) |
| 429 | Rate limit exceeded |

## Database design

```mermaid
erDiagram
    USER ||--o{ BOOKING : makes
    DIAGNOSTIC_CENTRE ||--o{ CENTRE_TEST : offers
    DIAGNOSTIC_TEST ||--o{ CENTRE_TEST : "offered as"
    CENTRE_TEST ||--o{ BOOKING : "booked as"
    BOOKING ||--o{ PAYMENT : "paid by"
    PAYMENT ||--o{ WEBHOOK_EVENT : "updated by"

    USER { bigint id PK
           string email UK
           string password "hashed"
           bool is_staff }
    DIAGNOSTIC_CENTRE { bigint id PK
                        string name
                        string location }
    DIAGNOSTIC_TEST { bigint id PK
                      string name UK }
    CENTRE_TEST { bigint id PK
                  bigint centre_id FK
                  bigint test_id FK
                  decimal price
                  bool is_available }
    BOOKING { uuid id PK
              bigint user_id FK
              bigint centre_test_id FK
              datetime appointment_at
              decimal amount
              string status }
    PAYMENT { uuid id PK
              uuid booking_id FK
              decimal amount
              string status
              string failure_reason }
    WEBHOOK_EVENT { bigint id PK
                    string event_id UK
                    uuid payment_id FK
                    json payload
                    string status }
```

Design decisions:

- **`CentreTest` link table carries the price.** The same test costs different amounts at
  different centres, so price belongs to the (centre, test) pair. `UNIQUE(centre, test)`.
- **A booking points at a `CentreTest`**, not at a centre and a test separately. That one
  foreign key fixes both, and makes "booked a test this centre does not offer" unrepresentable.
- **`Booking.amount` is a snapshot** of the price at booking time, so later price changes
  never alter what an existing booking costs.
- **Money is `DECIMAL(10,2)`**, never a float.
- **Bookings and payments use UUID ids**, so they cannot be enumerated by counting.
- **Rules that must never break are database constraints**, not just application checks:
  - `UNIQUE(user, centre_test, appointment_at) WHERE status IN (PENDING, CONFIRMED)` — no duplicate live booking
  - `UNIQUE(booking) WHERE status IN (PENDING, SUCCESS)` — a booking can never be paid twice
  - `UNIQUE(event_id)` on webhook events — the basis of idempotency
  - `CHECK(price > 0)`, `CHECK(amount > 0)`
- **Deletes are `PROTECT`ed**: a centre or test that has bookings cannot be deleted (409).
- **Indexes** follow the queries: `(user, created_at)` for "my bookings",
  `(status, created_at)` for the expiry job, `(status, received_at)` for the webhook sweeper.

## How the hard parts work

### Booking state machine

```
              payment SUCCESS
   PENDING ───────────────────▶ CONFIRMED ──cancel──▶ CANCELLED
      │
      ├── payment FAILED ─────▶ FAILED      (final)
      └── cancel / expired ───▶ CANCELLED   (final)
```

The allowed moves live in one place (`Booking.TRANSITIONS`); every status change goes
through `Booking.transition_to()`, which rejects anything else.

### Webhook idempotency

Providers deliver webhooks *at least once*, so duplicates are normal. Three layers make
them harmless:

1. **Event log.** Each event is stored in `WebhookEvent` with a unique `event_id`. A repeat
   delivery finds the existing row and returns `200` with `"duplicate": true` — nothing is
   re-applied.
2. **Row locks.** Processing locks the event, then the booking, then the payment
   (`SELECT … FOR UPDATE`). Two deliveries arriving at the same instant are handled one
   after the other; the second sees the first one's result.
3. **Settle once.** A payment only ever moves *out of* `PENDING`. A later event with a
   *different* id (late, or contradictory) is recorded as `IGNORED` and can never flip
   `SUCCESS` to `FAILED` or back.

Receiving and processing are separate steps. If processing hits a transient database
error, the event is already stored: the endpoint returns `202` and a Celery task retries
with exponential backoff (5 attempts). A scheduled sweeper re-queues any event that is
still unprocessed after a minute.

### Webhook authentication

The webhook has no JWT (the caller is a server, not a user). Instead the body is signed
with HMAC-SHA256 using a shared secret and verified with a constant-time comparison.

### Caching

`GET /centres/` is read constantly and changes rarely. Responses are cached in Redis under
a versioned key; any write to a centre, test, or price bumps the version (after the
transaction commits), which invalidates every cached page at once. If Redis is
unavailable the API keeps working: reads fall back to the database and the rate
limiter lets requests through rather than failing them.

## Edge cases handled

| Case | Behaviour |
|---|---|
| Missing / malformed fields | 400 with per-field details |
| Appointment in the past | 400 |
| Centre does not offer the test, or test unavailable | 400 |
| Client sends its own `amount`, `status` or `user_id` | Ignored; server sets them |
| Same booking submitted twice (even simultaneously) | One created, the other 409 |
| Unknown or malformed booking id | 404 (lookup) / 400 (in a request body) |
| Reading, cancelling or paying for another user's booking | 404; nothing changes |
| Paying for a CONFIRMED / FAILED / CANCELLED booking | 409 |
| Two payment requests for one booking at once | One payment, the other 409 |
| Failed payment | Payment `FAILED`, booking `FAILED` |
| Webhook with missing or wrong signature | 401; nothing stored |
| Same webhook event repeated (sequentially or concurrently) | Applied once |
| Contradictory webhook after settlement | Stored as `IGNORED`; state unchanged |
| Webhook for an unknown payment | 404; applied if redelivered once the payment exists |
| `SUCCESS` webhook after the user cancelled | Payment recorded, booking stays `CANCELLED`, warning logged |
| Deleting a centre that has bookings | 409 |
| Booking never paid | Auto-cancelled after 30 minutes by a scheduled job |
| Non-admin tries to create or edit centres | 403 |
| Too many login attempts | 429 |

## Tests

`pytest` — 98 tests, about 2 seconds.

- **API behaviour** for every endpoint, including each row of the table above.
- **Idempotency**: the same event sent six times in a row leaves exactly one payment,
  one booking, one event row.
- **Real concurrency** (`tests/test_concurrency.py`): 8 threads released at the same
  instant against PostgreSQL send the same webhook, send conflicting webhooks, pay for the
  same booking, and create the same booking. Each asserts that exactly one wins.
- **Database constraints** are tested directly, bypassing the API.
- **Background jobs**: expiry and the stuck-webhook sweeper.

## Bonus items

| Item | Where |
|---|---|
| Redis caching | `apps/centres/cache.py` |
| Celery background jobs | `apps/payments/tasks.py`, `apps/bookings/tasks.py` |
| Docker & docker-compose | `Dockerfile`, `docker-compose.yml` |
| Swagger / OpenAPI | `/docs/`, `/schema/` |
| Unit / integration tests | `tests/` |
| Structured logging | JSON lines with a request id — `apps/core/logging.py`, `middleware.py` |
| Pagination | `?page=&page_size=` on every list — `apps/core/pagination.py` |
| Rate limiting | Per-IP / per-user, stricter on auth and payments — `apps/core/throttling.py`, `REST_FRAMEWORK` in settings |
| Webhook retry handling | Celery task with backoff + sweeper |

## Assumptions

- **A failed payment ends the booking** (`FAILED` is final, as in the suggested states). To
  try again the user creates a new booking. The schema already allows several payments per
  booking, so supporting retries later is a rule change, not a migration.
- **No slot capacity.** Centres are not modelled as having limited slots; only a duplicate
  booking by the *same* user is prevented.
- **Cancelling a paid booking does not refund.** Refunds are out of scope; the case is logged.
- **Only the booking's owner can pay for or cancel it.** Staff can view all bookings.
- **Other users' resources return 404, not 403**, so the API never confirms that an id exists.
- **`POST /payments/` returns 201 even when the simulated payment fails** — the payment
  record was created; its `status` carries the result.
- **`simulate: "pending"`** exists so the webhook has something to settle, mimicking a real
  asynchronous gateway. Without `simulate` the result is random (80% success, configurable).
- **Admins are created out of band** (`seed_demo` / `createsuperuser`); signup always
  creates a normal user.
- **All times are UTC.**

## What I would improve with more time

- **Idempotency-Key header on `POST /payments/` and `POST /bookings/`**, so a client can
  safely retry after a network timeout and get the original response back.
- **Slot capacity** per centre and time, to prevent overbooking across users.
- **Refunds** as a first-class flow when a paid booking is cancelled.
- **Payment retries** on the same booking after a failure.
- **Refresh-token rotation and logout** (token blacklist), plus email verification.
- **Transactional outbox** for enqueueing Celery tasks, removing the small window between
  commit and enqueue that the sweeper currently covers.
- **Webhook replay protection** with a timestamp in the signed payload.
- **CI** (GitHub Actions running the suite against Postgres), linting, and type checking.
- **Observability**: metrics and tracing alongside the structured logs.
