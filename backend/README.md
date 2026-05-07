# FinWise Backend

## Project Structure

```
backend/
├── main.py              # FastAPI app entry point
├── requirements.txt     # Python dependencies
├── core/
│   ├── config.py        # Configuration (paths, JWT settings)
│   └── security.py      # JWT and password utilities
├── models/              # Data models (Pydantic)
├── schemas/             # API schemas (request/response)
│   ├── enterprise.py
│   └── user.py
├── routers/             # API route handlers
│   ├── auth.py
│   └── enterprises.py
└── storage/             # JSON file storage layer
    ├── json_store.py    # JSONStore CRUD class
    └── manager.py       # Storage instances
```

## Setup

```bash
cd backend
pip install -r requirements.txt
```

## Run

```bash
cd backend
uvicorn main:app --reload --port 8000
```

## API Endpoints

- `POST /api/auth/login` - Login
- `POST /api/auth/logout` - Logout
- `GET /api/auth/me` - Current user
- `GET /api/enterprises` - List enterprises
- `POST /api/enterprises` - Create enterprise
- `GET /api/enterprises/{id}` - Get enterprise
- `PUT /api/enterprises/{id}` - Update enterprise
- `DELETE /api/enterprises/{id}` - Delete enterprise
- `GET /api/enterprises/{id}/summary` - Enterprise summary
