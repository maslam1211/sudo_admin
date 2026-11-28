"""
Django settings for sudo_admin project.
"""

from pathlib import Path
import os
import sys
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

# Load environment variables.
# 1. The project's own .env (local development).
# 2. A server-wide file outside the repo, so deploys (fresh clone, git clean)
#    can never delete production settings: /etc/sudotag/sudotag.env, or the
#    path in SUDOTAG_ENV_FILE. Values already set are never overridden.
load_dotenv()
_SERVER_ENV_FILE = os.getenv('SUDOTAG_ENV_FILE', '/etc/sudotag/sudotag.env')
if os.path.isfile(_SERVER_ENV_FILE):
    load_dotenv(_SERVER_ENV_FILE, override=False)

# gRPC on macOS: the c-ares DNS backend sometimes fails with
# "DNS resolution failed for firestore.googleapis.com", which breaks Firestore
# (login, dashboard, etc.). The native resolver is usually reliable locally.
if sys.platform == "darwin":
    os.environ.setdefault("GRPC_DNS_RESOLVER", "native")

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# Secrets and environment flags come from the environment / .env (never commit values).
# Local .env sets DJANGO_DEBUG=1; the production .env on the VPS leaves it unset.
DEBUG = os.getenv('DJANGO_DEBUG', '').lower() in ('1', 'true', 'yes')

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.')
    SECRET_KEY = 'django-insecure-local-dev-only'

# Updated ALLOWED_HOSTS with specific IPs and domains

ALLOWED_HOSTS = [
    '103.163.64.190',
    'sudotag.com',
    'www.sudotag.com',
    'backend.pbx.bonvoice.com',
    'pbx.bonvoice.com',
    'localhost',
    '127.0.0.1',
    '104.237.2.231',
]


# Custom 404 page
handler404 = 'admin_app.views.custom_404'

# CSRF Trusted Origins - FIXED format (include local dev or POST returns 403 Origin check failed)
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://localhost",

    "http://sudotag.com",
    "https://sudotag.com",
    "http://www.sudotag.com",
    "https://www.sudotag.com",

    "https://backend.pbx.bonvoice.com",
    "http://backend.pbx.bonvoice.com",

    "https://pbx.bonvoice.com",
    "http://pbx.bonvoice.com",

    "http://103.163.64.190",
    "https://103.163.64.190",

    "http://104.237.2.231",
    "https://104.237.2.231",

    # Local development (Origin includes port)
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:8001",
    "http://localhost:8001",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
]

# Shared password for admin panel login/register (override in production via env)
ADMIN_PANEL_PASSWORD = os.getenv('ADMIN_PANEL_PASSWORD', '')

# Razorpay — same live key as mobile app / Cloud Functions (override via env in production)
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')

# PIN shown before login/register and for delete-data flow (override in production via env)
ADMIN_GATE_PIN = os.getenv('ADMIN_GATE_PIN', '')
# Encrypts admins' authenticator secrets in Firestore. Set it once in the
# server env and never change it (changing it means every admin re-scans).
# Falls back to SECRET_KEY when unset.
ADMIN_2FA_KEY = os.getenv('ADMIN_2FA_KEY', '')

# Local dev: common ports (avoids 403 "Origin checking failed" when CSRF_TRUSTED_ORIGINS is set)
if DEBUG:
    for _host in ("127.0.0.1", "localhost"):
        for _port in ("8000", "8080", "8888"):
            _o = f"http://{_host}:{_port}"
            if _o not in CSRF_TRUSTED_ORIGINS:
                CSRF_TRUSTED_ORIGINS.append(_o)

# Cookies - Updated for security
SESSION_COOKIE_SECURE = not DEBUG  # HTTPS-only cookies in production
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True  # Recommended for security

# CSRF Settings - Allow all API calls without strict CSRF checking
# All /api/ endpoints are exempted via custom middleware and @csrf_exempt decorator
CSRF_USE_SESSIONS = False  # Use cookies for CSRF token (default)
CSRF_COOKIE_HTTPONLY = False  # Allow JavaScript to read CSRF cookie

# Allow requests without referer for API endpoints
# This helps when browsers don't send referer header due to security settings
# The custom middleware (DisableCSRFForAPI) handles this for all /api/ paths

# CORS Settings - FIXED format (must include scheme)
CORS_ALLOWED_ORIGINS = [
    'https://sudotag.com',
    'https://backend.pbx.bonvoice.com',
    'http://backend.pbx.bonvoice.com',
    'https://pbx.bonvoice.com',
    'http://pbx.bonvoice.com',
    'http://103.163.64.190',
    'https://103.163.64.190',
]

# For development, you can also allow all origins (not recommended for production)
# CORS_ALLOW_ALL_ORIGINS = True

# Trust X-Forwarded-Proto from the TLS-terminating nginx proxy on the VPS.
# When DEBUG is True locally, leave unset so stray "https" headers do not mark requests as secure.
# Set USE_TLS_PROXY=1 in .env if you need this while DEBUG=True (e.g. ngrok + runserver).
USE_TLS_PROXY = os.getenv('USE_TLS_PROXY', '').lower() in ('1', 'true', 'yes')
if (not DEBUG) or USE_TLS_PROXY:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'corsheaders',  # Add this if using django-cors-headers
    'admin_app',
    'call_routing',
    'landing',
    'api',
]

MIDDLEWARE = [
    'api.observability.RequestIdMiddleware',  # first: id on every log line + response
    'corsheaders.middleware.CorsMiddleware',  # Add this if using CORS
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'admin_app.middleware.IndiaTimeMiddleware',
    'django.middleware.common.CommonMiddleware',
    'admin_app.middleware.DisableCSRFForAPI',  # Custom middleware to exempt API endpoints
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'admin_app.middleware.AdminSessionGuardMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'admin_app.middleware.InjectFaviconMiddleware',
]

ROOT_URLCONF = 'sudo_admin.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BASE_DIR, 'admin_app/templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'admin_app.context_processors.favicon_urls',
                'admin_app.context_processors.civic_sense_badge',
            ],
        },
    },
]

WSGI_APPLICATION = 'sudo_admin.wsgi.application'

# Call-route intent bridge (/admin/api/call/register → /admin/api/call); use Redis in prod if multiple workers
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'sudo-admin-call-route',
    }
}

# Database
# PostgreSQL when DATABASE_URL is set, e.g.
#   DATABASE_URL=postgres://sudotag:<password>@127.0.0.1:5432/sudotag
# Without it the project keeps using db.sqlite3 (local development, and the
# VPS until the switch in docs/firebase_audit/PHASE1_IMPLEMENTATION.md).
def _database_from_url(url: str) -> dict:
    from urllib.parse import parse_qs, unquote, urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ('postgres', 'postgresql'):
        raise ValueError('DATABASE_URL must start with postgres://')
    options = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': unquote(parsed.path.lstrip('/')),
        'USER': unquote(parsed.username or ''),
        'PASSWORD': unquote(parsed.password or ''),
        'HOST': parsed.hostname or '',
        'PORT': str(parsed.port or ''),
        # Reuse connections between requests (gunicorn sync workers).
        'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '60')),
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': options,
    }


_DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
DATABASES = {
    'default': _database_from_url(_DATABASE_URL) if _DATABASE_URL else {
        'ENGINE': 'django.db.backends.sqlite3',
        # SQLITE_PATH: read a copy of the database (deploy/move_sqlite_to_postgres.sh).
        'NAME': os.getenv('SQLITE_PATH') or BASE_DIR / 'db.sqlite3',
    }
}

# Scheduled user pushes: a thread inside each web process (old behaviour) or
# the `run_worker` service (Phase 1). Set to 0 once the worker is running, so
# schedules are not sent by both.
SCHEDULED_PUSH_IN_WEB = os.getenv('SCHEDULED_PUSH_IN_WEB', '1').lower() in ('1', 'true', 'yes')

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
    os.path.join(BASE_DIR, 'admin_app', 'static'),  # Explicitly include admin_app static files
]
# WhiteNoise compressed files at stable URLs (/static/path/file.css — no hashed filenames).
# Manifest storage breaks pages when templates expect hashed names but collectstatic/output
# is stale — logo + sudo_* CSS 404 otherwise (broken images + unstyled bottom dock).
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

# WhiteNoise: serve from STATICFILES_DIRS when collectstatic is stale (new landing images/CSS).
WHITENOISE_USE_FINDERS = os.getenv('WHITENOISE_USE_FINDERS', '1').lower() in ('1', 'true', 'yes')
WHITENOISE_AUTOREFRESH = DEBUG or WHITENOISE_USE_FINDERS

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Session configuration
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_CACHE_ALIAS = 'default'

# Email Configuration
# EMAIL_DELIVERY=firebase sends every email through Firebase's "Trigger Email from
# Firestore" extension on sudotag-faa80 (a document in FIREBASE_MAIL_COLLECTION).
# EMAIL_DELIVERY=console (local, DEBUG only) prints emails in the server terminal.
# Anything else (default) sends directly over SMTP with the settings below.
EMAIL_DELIVERY = (os.getenv('EMAIL_DELIVERY') or 'smtp').strip().lower()
FIREBASE_MAIL_COLLECTION = os.getenv('FIREBASE_MAIL_COLLECTION') or 'mail'
if EMAIL_DELIVERY == 'firebase':
    EMAIL_BACKEND = 'admin_app.firestore_email_backend.FirestoreEmailBackend'
elif EMAIL_DELIVERY == 'console' and DEBUG:
    # Local testing: print emails in the runserver terminal instead of sending them.
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = 'admin_app.email_backend.CustomEmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST') or 'smtp.gmail.com'
# 587 + TLS by default. If the host blocks 587, set EMAIL_PORT=465 in .env (uses SSL).
EMAIL_PORT = int(os.getenv('EMAIL_PORT') or 587)
EMAIL_USE_SSL = EMAIL_PORT == 465
EMAIL_USE_TLS = not EMAIL_USE_SSL
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER') or 'sudotagonline@gmail.com'
# Gmail App Password (Google Account → Security → App passwords). Set it in .env.
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')

# Local testing only: a fixed 6-digit activation email code (no email is sent).
# Honoured only while DEBUG is on. Never set this on the production server.
ACTIVATION_DUMMY_EMAIL_OTP = os.getenv('ACTIVATION_DUMMY_EMAIL_OTP', '')
# Sender address. With an email service (Brevo, SendGrid...) this must be a
# sender verified there, e.g. SudoTag <no-reply@sudotag.com>.
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL') or 'sudotagonline@gmail.com'
SERVER_EMAIL = os.getenv('SERVER_EMAIL') or DEFAULT_FROM_EMAIL
EMAIL_TIMEOUT = 30

BASE_DOMAIN = 'https://sudotag.com'

# Twilio Configuration - Load from environment variables
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

# MSG91 OTP (activate-id mobile verification — same keys as mobile app)
MSG91_AUTH_KEY = os.getenv('MSG91_AUTH_KEY', '')
MSG91_OTP_TEMPLATE_ID = os.getenv('MSG91_OTP_TEMPLATE_ID', '69d7aa6f30bcfff61b0c68e5')

# QR generation gate — OTP is sent only to this number before generate/download is allowed.
GENERATE_QR_OTP_PHONE = os.getenv('GENERATE_QR_OTP_PHONE', '8075576069')
# Admin login gate — OTP to this number before email/password login is shown.
ADMIN_LOGIN_OTP_PHONE = os.getenv('ADMIN_LOGIN_OTP_PHONE', GENERATE_QR_OTP_PHONE)

FEEDBACK_EMAIL = 'sudotagonline@gmail.com'
# Shown to customers in emails and on the activation page.
SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL') or DEFAULT_FROM_EMAIL

# Cloudinary Configuration
import cloudinary
import cloudinary.uploader
import cloudinary.api

CLOUDINARY_CONFIG = {
    'cloud_name': os.getenv('CLOUDINARY_CLOUD_NAME', ''),
    'api_key': os.getenv('CLOUDINARY_API_KEY', ''),
    'api_secret': os.getenv('CLOUDINARY_API_SECRET', ''),
    'secure': True
}

cloudinary.config(**CLOUDINARY_CONFIG)

# Webhook secret
DELETION_WEBHOOK_SECRET = os.getenv('DELETION_WEBHOOK_SECRET', '')

# PBX webhook POST /admin/api/call — require Authorization: Bearer <key> or X-API-Key when non-empty.
# Rotate by changing CALL_ROUTING_API_KEY in .env and updating your PBX + curl.
CALL_ROUTING_API_KEY = os.getenv('CALL_ROUTING_API_KEY', '')

# ─── Mobile REST API (api/, django-ninja at /api/v1/) ────────────────────────
# Private files (vehicle documents). Must NOT be under STATIC_ROOT or any
# folder nginx serves. On the VPS set e.g. /var/lib/sudotag/private_media and
# include it in backups.
PRIVATE_MEDIA_ROOT = os.getenv(
    'SUDOTAG_PRIVATE_MEDIA_ROOT', os.path.join(BASE_DIR, 'private_media')
)
# Base used in vehicleDocuments.documentUrl for privately stored files.
API_PUBLIC_BASE_URL = os.getenv('API_PUBLIC_BASE_URL', 'https://sudotag.com')
# Require a valid Firebase App Check token on public API routes (OTP send).
# Off until every supported app build sends one.
API_REQUIRE_APP_CHECK = os.getenv('API_REQUIRE_APP_CHECK', '').lower() in ('1', 'true', 'yes')
# Behind nginx: take the client IP from X-Real-IP / last X-Forwarded-For hop.
API_TRUST_X_FORWARDED_FOR = os.getenv('API_TRUST_X_FORWARDED_FOR', '1').lower() in ('1', 'true', 'yes')
# Worker: how often to mirror all Firebase data into PostgreSQL (0 = never).
MIRROR_INTERVAL_HOURS = float(os.getenv('MIRROR_INTERVAL_HOURS', '24') or 0)

# Logs to stdout (journald on the VPS). LOG_FORMAT=json for one JSON object per line.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {'request_id': {'()': 'api.observability.RequestIdFilter'}},
    'formatters': {
        'text': {'format': '%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s'},
        'json': {'()': 'api.observability.JsonFormatter'},
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'filters': ['request_id'],
            'formatter': 'json' if os.getenv('LOG_FORMAT', '').lower() == 'json' else 'text',
        },
    },
    'root': {'handlers': ['console'], 'level': os.getenv('LOG_LEVEL', 'INFO')},
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
    },
}

# Caller identity for the Contact Owner voice bridge when the page does not send a mobile number.
# Set COMPANY_PHONE_NUMBER in the environment to override.
COMPANY_PHONE_NUMBER = os.getenv('COMPANY_PHONE_NUMBER', '7907965255')

# Ad image uploads (also set nginx client_max_body_size on production)
DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024