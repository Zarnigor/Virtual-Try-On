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
# Structural try-on steps (docs/06 "Layer order"), on by default; set to 0 if one of them produces artifacts.
TRYON_SHOULDER_CAP = os.environ.get("TRYON_SHOULDER_CAP", "1") == "1"
TRYON_HEM_SNAP = os.environ.get("TRYON_HEM_SNAP", "1") == "1"
TRYON_HALO_REMOVAL = os.environ.get("TRYON_HALO_REMOVAL", "1") == "1"
# Neck zone: transparent inner back collar, 1-2 px head/neck edge, smoothed shoulder alpha (docs/06).
TRYON_NECK_FIX = os.environ.get("TRYON_NECK_FIX", "1") == "1"
TRYON_NECK_GAP_FILL = os.environ.get("TRYON_NECK_GAP_FILL", "1") == "1"
TRYON_DROPPED_SHOULDER_SINGLE = os.environ.get("TRYON_DROPPED_SHOULDER_SINGLE", "0") == "1"
# Owner-drawn neckline hole (landmarks.neck_hole.polygon, docs/09 #102): used by the MLS engine only (TRYON_WARP=mls),
# adapt and keep_shape (owner 2026-11-13); 0 = never pass the hole (the r7 neckline as before).
TRYON_NECK_HOLE = os.environ.get("TRYON_NECK_HOLE", "1") == "1"
# T-shirt hem rule (docs/09 #91): hem row = hip + FRACTION x (crotch - hip), at most crotch - MARGIN px
TRYON_HEM_RULE = os.environ.get("TRYON_HEM_RULE", "1") == "1"
TRYON_HEM_HIP_FRACTION = float(os.environ.get("TRYON_HEM_HIP_FRACTION", "0.35"))
TRYON_HEM_CROTCH_MARGIN = float(os.environ.get("TRYON_HEM_CROTCH_MARGIN", "10"))
# T-shirt warp engine (docs/09 #98, default "mls" since docs/09 #105): "mls" (one rigid MLS field,
# apps/tryon_engine/mls.py; keep_shape -> preset A, adapt -> fitted) or "parts" (torso row warp + rigid sleeves, the
# default before #105; pants always use parts). An invalid value stops startup.
TRYON_WARP_CHOICES = ("parts", "mls")


def parse_tryon_warp(value):
    value = (value or "mls").strip().lower()
    if value not in TRYON_WARP_CHOICES:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(f"TRYON_WARP must be one of {', '.join(TRYON_WARP_CHOICES)}, got {value!r}")
    return value


TRYON_WARP = parse_tryon_warp(os.environ.get("TRYON_WARP"))
# MLS sleeve variant (docs/09 #104, owner 2026-11-13): "C" = deltoid-edge mid-sleeve pairs + cuff_mid (docs/06 round 8);
# r7 | A | B kept for comparison. Used only by TRYON_WARP=mls, adapt garments (keep_shape ignores it).
TRYON_MLS_SLEEVE_CHOICES = ("r7", "A", "B", "C")


def parse_mls_sleeve(value):
    value = (value or "C").strip()
    if value not in TRYON_MLS_SLEEVE_CHOICES:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(f"TRYON_MLS_SLEEVE must be one of {', '.join(TRYON_MLS_SLEEVE_CHOICES)}, got {value!r}")
    return value


TRYON_MLS_SLEEVE = parse_mls_sleeve(os.environ.get("TRYON_MLS_SLEEVE"))
# Adapt T-shirts on the MLS engine (docs/09 #105, docs/06 rounds 11-14); each flag's off value = the behaviour before
# #105; keep_shape garments ignore all four. An invalid value stops startup.
#   TRYON_MLS_TUBE        1 (default) = tube sleeves "finished" (round 13b) | 0 = MLS sleeves
#   TRYON_MLS_SIDE_FLOOR  mask (default) = side coverage floor from the figure mask (round 12 / 12b) | off
#   TRYON_MLS_ARMPIT      r14 (default) = torso seam on the arm/torso boundary (round 14; needs the tube and the
#                         side floor, otherwise it is off and tshirt_config says so) | off
#   TRYON_MLS_HEM         garment (default) = the garment's own hem shape (round 12b) | mls = no hem post-processing
# docs/09 #106 (rounds 15 / 16), tube sleeves only (without the tube both are off and tshirt_config says so):
#   TRYON_MLS_CUFF        hem (default) = the garment's real sleeve hem lands on the cuff line | chord = before #106
#   TRYON_MLS_FRINGE      drop (default) = the tube's photo-fringe px over solid fabric are not drawn | keep
TRYON_MLS_CHOICES = {"TRYON_MLS_TUBE": ("1", "0"), "TRYON_MLS_SIDE_FLOOR": ("mask", "off"),
                     "TRYON_MLS_ARMPIT": ("r14", "off"), "TRYON_MLS_HEM": ("garment", "mls"),
                     "TRYON_MLS_CUFF": ("hem", "chord"), "TRYON_MLS_FRINGE": ("drop", "keep"),
                     "TRYON_FINISH": ("r17", "off"), "TRYON_FINISH_PANTS": ("1", "0"),
                     "TRYON_PANTS_TUCK": ("1", "0"), "TRYON_MLS_KEEP_SCALE": ("fit", "shoulder"),
                     "TRYON_MLS_TUBE_CLIP": ("arm", "armhole"), "TRYON_PANTS_ENGINE": ("rows", "fit"),
                     "TRYON_PANTS_FIT_X": ("1", "0"), "TRYON_PANTS_HANG": ("0", "1")}


def parse_mls_choice(name, value):
    choices = TRYON_MLS_CHOICES[name]
    value = (value or choices[0]).strip().lower()
    if value not in choices:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(f"{name} must be one of {', '.join(choices)}, got {value!r}")
    return value


TRYON_MLS_TUBE = parse_mls_choice("TRYON_MLS_TUBE", os.environ.get("TRYON_MLS_TUBE")) == "1"
TRYON_MLS_SIDE_FLOOR = parse_mls_choice("TRYON_MLS_SIDE_FLOOR", os.environ.get("TRYON_MLS_SIDE_FLOOR"))
TRYON_MLS_ARMPIT = parse_mls_choice("TRYON_MLS_ARMPIT", os.environ.get("TRYON_MLS_ARMPIT"))
TRYON_MLS_HEM = parse_mls_choice("TRYON_MLS_HEM", os.environ.get("TRYON_MLS_HEM"))
TRYON_MLS_CUFF = parse_mls_choice("TRYON_MLS_CUFF", os.environ.get("TRYON_MLS_CUFF"))
TRYON_MLS_FRINGE = parse_mls_choice("TRYON_MLS_FRINGE", os.environ.get("TRYON_MLS_FRINGE"))
# docs/09 #107 (round 17): the finish of the T-shirt layer, every engine and fit mode; pants are not touched.
#   TRYON_FINISH  r17 (default) = smooth anti-aliased edge (nothing eroded) + form shading from the garment's outline
#                 + contact shadow (also on the arm under the cuff); TRYON_SHADING / TRYON_CONTACT_SHADOW /
#                 TRYON_EDGE_FEATHER are then not read | off = the behaviour before #107 (those three flags decide)
TRYON_FINISH = parse_mls_choice("TRYON_FINISH", os.environ.get("TRYON_FINISH"))
# docs/09 #108 (rounds 17b / 17c): the same finish on the pants layer. Needs TRYON_FINISH=r17.
#   TRYON_FINISH_PANTS  1 (default) | 0 = T-shirts only, the behaviour before #108
TRYON_FINISH_PANTS = parse_mls_choice("TRYON_FINISH_PANTS", os.environ.get("TRYON_FINISH_PANTS")) == "1"
# docs/09 #109 (round 18): an adapt MLS T-shirt hangs over the pants (its sides cover them, no pants beside it).
#   TRYON_PANTS_TUCK  1 (default) | 0 = the behaviour before #109
TRYON_PANTS_TUCK = parse_mls_choice("TRYON_PANTS_TUCK", os.environ.get("TRYON_PANTS_TUCK")) == "1"
# docs/09 #112 (round 19): the scale of a keep_shape MLS T-shirt.
#   TRYON_MLS_KEEP_SCALE  fit (default) = the largest of the shoulder, length and width scales (mls.keep_shape_scale)
#                         | shoulder = the garment's shoulder seams on the body's shoulder points (before #112)
TRYON_MLS_KEEP_SCALE = parse_mls_choice("TRYON_MLS_KEEP_SCALE", os.environ.get("TRYON_MLS_KEEP_SCALE"))
# docs/09 #113 (round 20): where a tube sleeve ends on the torso side below the armpit row.
#   TRYON_MLS_TUBE_CLIP  arm (default) = the arm/torso boundary (no sleeve flap over the chest)
#                        | armhole = the extended armhole line (before #113)
TRYON_MLS_TUBE_CLIP = parse_mls_choice("TRYON_MLS_TUBE_CLIP", os.environ.get("TRYON_MLS_TUBE_CLIP"))
# docs/09 #114 (round 21), #116 (owner: rows is the default again): the pants engine.
#   TRYON_PANTS_ENGINE  rows (default, docs/09 #116) = warp.warp_pants | fit = warp.warp_pants_fit (the garment's own
#                       outline x a smooth width factor, legs hang from the hip; rounds 21-22)
TRYON_PANTS_ENGINE = parse_mls_choice("TRYON_PANTS_ENGINE", os.environ.get("TRYON_PANTS_ENGINE"))
# docs/09 #118 (round 24), rows pants (ignored with TRYON_PANTS_ENGINE=fit):
#   TRYON_PANTS_FIT_X  1 (default) = one horizontal scale for the whole garment, from the figure mask | 0 = before
#   TRYON_PANTS_HANG   0 (default) | 1 = loose legs hang straight from the hip block (tight legs unchanged)
TRYON_PANTS_FIT_X = parse_mls_choice("TRYON_PANTS_FIT_X", os.environ.get("TRYON_PANTS_FIT_X")) == "1"
TRYON_PANTS_HANG = parse_mls_choice("TRYON_PANTS_HANG", os.environ.get("TRYON_PANTS_HANG")) == "1"
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
