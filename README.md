# Local Events Backend API

FastAPI backend for the Local Events social application.

## Overview

This backend provides:

- User profiles
- Event creation & discovery
- Event participation
- Event chat
- Friendships
- User preferences
- AI-based event recommendations

The database schema is managed externally via Supabase.

---

## Tech Stack

- FastAPI
- Supabase (PostgreSQL + Auth)
- OpenAI (for recommendations)
- Python 3.10+

---

## Project Structure

```

app/
├── main.py
├── core/          # Config, security, dependencies
├── db/            # Supabase client
├── schemas/       # Pydantic models
├── services/      # Business logic
├── api/           # Route definitions
└── utils/         # Helpers (AI, etc.)

```

---

## Setup Instructions

### 1. Create Virtual Environment

```

python -m venv venv
.\venv\Scripts\activate

```

### 2. Install Dependencies

```

pip install -r requirements.txt

```

### 3. Configure Environment Variables

Create a `.env` file:

```

SUPABASE_URL=your_project_url
SUPABASE_SERVICE_KEY=your_service_role_key

```

### 4. Run the Server

```

uvicorn app.main:app --reload


## Notes

- Supabase manages authentication and database schema.
- Backend handles API logic and AI recommendation processing.
- Do not commit `.env` to version control.
```

