"""
Django settings for sudo_admin project.
"""

from pathlib import Path
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# gRPC on macOS: the c-ares DNS backend sometimes fails with
# "DNS resolution failed for firestore.googleapis.com", which breaks Firestore
# (login, dashboard, etc.). The native resolver is usually reliable locally.
if sys.platform == "darwin":
    os.environ.setdefault("GRPC_DNS_RESOLVER", "native")

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-no=2un6zvm5r&cupj9%k_%zjn)!7#*lyf#ca6mizl28ls#sdxk'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True  # Set to False in production

# Updated ALLOWED_HOSTS with specific IPs and domains

ALLOWED_HOSTS = [
    '103.163.64.190',
    '43.205.192.146',
    'sudotag.com',
    'www.sudotag.com',
    'backend.pbx.bonvoice.com',
    'pbx.bonvoice.com',
    'sudo-admin.onrender.com',
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
    "http://43.205.192.146",
    "https://43.205.192.146",

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

    "http://sudo-admin.onrender.com",
    "https://sudo-admin.onrender.com",

    # Local development (Origin includes port)
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:8001",
    "http://localhost:8001",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
]

# Shared password for admin panel login/register (override in production via env)
ADMIN_PANEL_PASSWORD = os.getenv('ADMIN_PANEL_PASSWORD', 'Sudo@123')

# PIN shown before login/register and for delete-data flow (override in production via env)
ADMIN_GATE_PIN = os.getenv('ADMIN_GATE_PIN', '4455')

# Local dev: common ports (avoids 403 "Origin checking failed" when CSRF_TRUSTED_ORIGINS is set)
if DEBUG:
    for _host in ("127.0.0.1", "localhost"):
        for _port in ("8000", "8080", "8888"):
            _o = f"http://{_host}:{_port}"
            if _o not in CSRF_TRUSTED_ORIGINS:
                CSRF_TRUSTED_ORIGINS.append(_o)

# Cookies - Updated for security
SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
CSRF_COOKIE_SECURE = False     # Set to True in production with HTTPS
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
    'http://43.205.192.146',
    'https://43.205.192.146',
    'https://sudotag.com',
    'https://sudo-admin.onrender.com',
    'https://backend.pbx.bonvoice.com',
    'http://backend.pbx.bonvoice.com',
    'https://pbx.bonvoice.com',
    'http://pbx.bonvoice.com',
    'http://103.163.64.190',
    'https://103.163.64.190',
]

# For development, you can also allow all origins (not recommended for production)
# CORS_ALLOW_ALL_ORIGINS = True

# Trust X-Forwarded-Proto from a TLS-terminating proxy (e.g. Render).
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
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Add this if using CORS
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'admin_app.middleware.DisableCSRFForAPI',  # Custom middleware to exempt API endpoints
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware'
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
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

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
# Use WhiteNoise for serving static files in production
# Note: For production, use CompressedManifestStaticFilesStorage
# For development or if manifest issues occur, use CompressedStaticFilesStorage
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# WhiteNoise configuration
WHITENOISE_USE_FINDERS = True  # Allow WhiteNoise to find static files during development
WHITENOISE_AUTOREFRESH = True  # Auto-refresh static files (useful for development)

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Session configuration
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_CACHE_ALIAS = 'default'

# Email Configuration
EMAIL_BACKEND = 'admin_app.email_backend.CustomEmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False
EMAIL_HOST_USER = 'sudotagonline@gmail.com'
EMAIL_HOST_PASSWORD = 'bhai mtkd xyhg mefr'
DEFAULT_FROM_EMAIL = 'sudotagonline@gmail.com'
SERVER_EMAIL = 'sudotagonline@gmail.com'
EMAIL_TIMEOUT = 30

BASE_DOMAIN = 'https://sudotag.com'

# Twilio Configuration - Load from environment variables
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

FEEDBACK_EMAIL = 'sudotagonline@gmail.com'

# Cloudinary Configuration
import cloudinary
import cloudinary.uploader
import cloudinary.api

CLOUDINARY_CONFIG = {
    'cloud_name': 'djuvhdtfs',
    'api_key': '288376169192531',
    'api_secret': 'sewn3kJI6egEEqFtoWjrTsbcboo',
    'secure': True
}

cloudinary.config(**CLOUDINARY_CONFIG)

# Webhook secret
DELETION_WEBHOOK_SECRET = "QWERTY123"

# PBX webhook POST /admin/api/call — require Authorization: Bearer <key> or X-API-Key when non-empty.
# Rotate by changing this value and updating your PBX + curl if exposed.
CALL_ROUTING_API_KEY = 'SudoTag4455'