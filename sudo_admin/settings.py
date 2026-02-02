"""
Django settings for sudo_admin project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

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
    'backend.pbx.bonvoice.com',
    'sudo-admin.onrender.com',
    'localhost',
    '127.0.0.1',
    '104.237.2.231',
]


# Custom 404 page
handler404 = 'admin_app.views.custom_404'

# CSRF Trusted Origins - FIXED format
CSRF_TRUSTED_ORIGINS = [
    'http://43.205.192.146',
    'https://43.205.192.146',  # Added https version
    'https://sudotag.com',
    'https://backend.pbx.bonvoice.com',
    'http://backend.pbx.bonvoice.com',
    'http://103.163.64.190',
    'https://103.163.64.190',
    'https://sudo-admin.onrender.com',
    'sudotag.com',
    'www.sudotag.com',
]


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
    'http://103.163.64.190',
    'https://103.163.64.190',
]

# For development, you can also allow all origins (not recommended for production)
# CORS_ALLOW_ALL_ORIGINS = True

# Tell Django the real request is HTTPS
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
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
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