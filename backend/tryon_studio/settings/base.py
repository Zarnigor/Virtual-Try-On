import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-secret-key")
DEBUG = bool(int(os.environ.get("DEBUG", 0)))
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "apps.users",
    "apps.bodies",
    "apps.avatars",
    "apps.garments",
    "apps.tryon_engine",
    "apps.outfits",
    "apps.jobs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "tryon_studio.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "tryon_studio.wsgi.application"

AUTH_USER_MODEL = "users.User"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "tryon"),
        "USER": os.environ.get("POSTGRES_USER", "tryon"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "tryon_dev"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

# Parse DATABASE_URL if set
_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    import re
    m = re.match(r"postgres://([^:]+):([^@]+)@([^:/]+):(\d+)/(.+)", _db_url)
    if m:
        DATABASES["default"].update({
            "USER": m.group(1), "PASSWORD": m.group(2),
            "HOST": m.group(3), "PORT": m.group(4), "NAME": m.group(5),
        })

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

from datetime import timedelta
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=24),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
}

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
CORS_ALLOW_CREDENTIALS = True

# Signed URL secret for image serving
SIGNED_URL_SECRET = os.environ.get("SIGNED_URL_SECRET", SECRET_KEY)
SIGNED_URL_TTL = 3600  # 1 hour

# AI
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Model for the JSON validation prompts (01, 02, 03). Set in .env, never hardcoded here (docs/09 #22).
GEMINI_VALIDATION_MODEL = os.environ.get("GEMINI_VALIDATION_MODEL", "")
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_TIMEOUT_S = max(60.0, float(os.environ.get("GEMINI_TIMEOUT_S", 60)))  # slow replies are normal; never below 60 s
GEMINI_RETRY_BACKOFF_S = 2.0  # one retry on 429/5xx after this pause
AI_DAILY_LIMIT = int(os.environ.get("AI_DAILY_LIMIT", 5))  # body checks per user per day (Asia/Tashkent)
AI_GARMENT_DAILY_LIMIT = int(os.environ.get("AI_GARMENT_DAILY_LIMIT", 5))  # garment checks per user per day
# AI garment cleaning (prompt 04, image model) needs prepaid image credits we do not have (docs/09 #55). Off by default:
# garments go straight to rembg (mask only, original pixels kept). Prompt 04 is not built yet, so turning it on makes
# every garment job fail with a clear error instead of silently skipping the cleaning.
AI_CLEANING_ENABLED = os.environ.get("AI_CLEANING_ENABLED", "0") == "1"
# Demo mode (apps/tryon_engine/demo.py): precomputed try-on results from `manage.py build_demo` are served at once
# for the (avatar, garments) pairs they cover; no Celery, no Gemini for those. Off: nothing changes.
DEMO_MODE = os.environ.get("DEMO_MODE", "0") == "1"
# Try-on realism effects (docs/06 "Realism pass"), all off by default: the plain warped, opaque garment.
TRYON_SHADING = os.environ.get("TRYON_SHADING", "0") == "1"
TRYON_CONTACT_SHADOW = os.environ.get("TRYON_CONTACT_SHADOW", "0") == "1"
TRYON_EDGE_FEATHER = os.environ.get("TRYON_EDGE_FEATHER", "0") == "1"
# Flatten the photo lighting of near-solid garments when they are cleaned (apps/garments/lighting.py).
GARMENT_FLATTEN_LIGHTING = os.environ.get("GARMENT_FLATTEN_LIGHTING", "1") == "1"
AI_CACHE_TTL_S = 30 * 24 * 3600  # cached validation verdicts, keyed by image hash (apps/jobs/ai_cache.py)
PROMPTS_DIR = Path(os.environ.get("PROMPTS_DIR", BASE_DIR.parent / "prompts"))  # docker: ./prompts -> /prompts

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "KEY_PREFIX": "tryon",
    }
}
# Tests: in-memory cache and a guard that fails any real HTTP call (tryon_studio/test_runner.py).
TEST_RUNNER = "tryon_studio.test_runner.NoNetworkTestRunner"

# Canvas
CANVAS_W = 600
CANVAS_H = 1200

# Upload limits (checked on the server from the file bytes: apps/images.py)
MAX_UPLOAD_MB = 20
MAX_IMAGE_PIXELS = 50_000_000  # width x height, checked before decoding
GARMENT_MIN_SIDE_PX = 300  # shorter side of a garment photo

# Fail-closed AI (docs/02 #17). The AI calls are not wired yet (steps 4 and 6), so without this flag every
# AI-gated job fails. AI_DEV_BYPASS=1 lets LOCAL testing skip the AI step; it is ignored unless DEBUG is on,
# and the job result is marked {"ai_skipped": true}. Never set it in production.
AI_DEV_BYPASS = DEBUG and os.environ.get("AI_DEV_BYPASS", "0") == "1"
# Body AI check (prompt 02) for OWN-body uploads. Default on. Off (0) skips prompt 02 and marks the job
# {"ai_skipped": true}; honoured only with DEBUG (adults-only is a hard rule), so production always runs it.
# Staff avatar uploads never call the AI (apps/bodies/pipeline.py).
BODY_AI_CHECK_ENABLED = os.environ.get("BODY_AI_CHECK_ENABLED", "1") == "1" or not DEBUG
