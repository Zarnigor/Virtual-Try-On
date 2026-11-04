# Virtual Try-On — Backend

Django REST API for the 2D Virtual Try-On MVP.

## Stack

- Django 4.2 + Django REST Framework
- PostgreSQL (via Docker)
- JWT auth (djangorestframework-simplejwt)
- Swagger UI at `/api/docs/`

## Quick start

### 1. Start Postgres

```bash
cd backend
docker-compose up -d
```

### 2. Create and activate venv

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env if needed (defaults work with docker-compose)
```

### 4. Migrate and create superuser

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Seed demo data (optional)

```bash
python manage.py seed_demo
# Creates: user demo/demo1234, one avatar, measurements, 3 placeholder items
```

### 6. Run the server

```bash
python manage.py runserver
```

API root: http://localhost:8000  
Swagger: http://localhost:8000/api/docs/  
Admin:   http://localhost:8000/admin/

## Run tests

```bash
pytest
```

## API endpoints

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/auth/register` | Register; returns JWT tokens; auto-creates default avatar |
| POST | `/api/auth/login` | Login; returns JWT tokens |
| POST | `/api/auth/refresh` | Refresh access token |
| GET | `/api/auth/me` | Current user info |
| GET/POST | `/api/avatars/` | List or create avatars |
| GET/POST | `/api/avatars/{id}/measurements` | List or add measurements (newest first) |
| GET | `/api/items/?category=top\|bottom` | List items (authenticated) |
| GET/POST | `/api/outfits/` | List or create outfits |
| GET/DELETE | `/api/outfits/{id}` | Get or delete an outfit |

## Notes

- Each POST to measurements creates a new history row; the latest is current.
- An outfit accepts at most one top and one bottom.
- Item images must be PNG, exactly 600×1200 px, max 2 MB; enforced on upload.
- Items are managed via Django Admin only.
- Media files are served by Django in DEBUG mode.
