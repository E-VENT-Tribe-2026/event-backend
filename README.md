# event-backend

## Project Structure
```
e-vent-backend/
├── alembic/                    # Database migration history
├── app/
│   ├── main.py                 # Entry point (FastAPI initialization)
│   ├── core/
│   │   ├── config.py           # Pydantic BaseSettings (reads .env)
│   │   ├── security.py         # JWT / password hashing
│   │   └── dependencies.py     # Shared FastAPI Depends() (db session, current user)
│   ├── db/
│   │   ├── base.py             # SQLAlchemy Base + imports all models (for Alembic)
│   │   └── session.py          # Engine + SessionLocal factory
│   ├── models/                 # SQLAlchemy Database Models (The "Vault" schema)
│   ├── schemas/                # Pydantic Models (The "Handshake" data)
│   ├── api/
│   │   ├── deps.py             # Route-level dependencies
│   │   └── v1/
│   │       ├── auth.py         # Route handler file
│   │       ├── router.py       # Aggregates all v1 routes
│   │       ├── events.py       # Event discovery endpoints
│   │       ├── users.py        # User endpoints
│   │       └── social.py       # Social endpoints
│   ├── services/               # Logic Layer (AI, Maps, Redis Broker)
│   └── utils/                  # Shared helpers (email, formatting, etc.)
├── tests/
│   └── conftest.py             # Pytest fixtures and config
├── alembic.ini                 # Migration config
├── .env                        # Secrets (Supabase URL, Meta API Keys) — not committed
├── .env.example                # Dummy values template — committed to git
├── requirements.txt            # Dependencies
└── docker-compose.yml          # Local Postgres + Redis setup
```