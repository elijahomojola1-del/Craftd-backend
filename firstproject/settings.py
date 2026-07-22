from pathlib import Path
from datetime import timedelta
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

from .email_config import *  # noqa: F401,F403

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

# Railway sets these automatically. Their presence is a reliable signal that
# this is the deployed environment rather than a laptop.
RAILWAY_HOST = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
IS_RAILWAY = bool(RAILWAY_HOST or os.environ.get("RAILWAY_ENVIRONMENT"))

# An explicit DEBUG env var always wins. Otherwise: off on Railway, on
# locally. Previously DEBUG defaulted to False everywhere, which meant your
# dev server was running in production mode without you realising, and
# static() silently served nothing locally either.
DEBUG = os.environ.get("DEBUG", "False" if IS_RAILWAY else "True") == "True"

# Required in production, with a throwaway fallback for local runs so you are
# not forced to set an env var just to start the dev server. The fallback is
# unreachable when DEBUG is False, so production still fails loudly.
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-local-development-only"
    else:
        raise ImproperlyConfigured(
            "SECRET_KEY environment variable is required when DEBUG is False."
        )

if DEBUG:
    # Locally the phone reaches Django over the LAN by IP address, which
    # would otherwise be rejected as an invalid Host.
    ALLOWED_HOSTS = ["*"]
else:
    # Never leave this empty: runserver refuses to start on an empty list
    # when DEBUG is False.
    ALLOWED_HOSTS = [".railway.app", "localhost", "127.0.0.1"]
    if RAILWAY_HOST:
        ALLOWED_HOSTS.append(RAILWAY_HOST)

# Required for the Django admin to accept POSTs over HTTPS on Railway.
CSRF_TRUSTED_ORIGINS = ["https://*.railway.app"]
if RAILWAY_HOST:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RAILWAY_HOST}")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------------------
# Media storage
#
# Railway containers have an ephemeral filesystem: anything written to disk is
# discarded on redeploy. Combined with DEBUG=False (which makes Django refuse
# to serve /media/ at all), that is why every uploaded image returned 404.
#
# Cloudinary is used whenever its credentials are present, which is how
# production runs. Without them the project falls back to local disk so
# local development keeps working unchanged.
# ---------------------------------------------------------------------------

CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")

USE_CLOUDINARY = all(
    [CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
]

# cloudinary_storage MUST be listed before django.contrib.staticfiles.
if USE_CLOUDINARY:
    INSTALLED_APPS += ["cloudinary_storage", "cloudinary"]

INSTALLED_APPS += [
    "django.contrib.staticfiles",
    "myapp",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
]

if USE_CLOUDINARY:
    CLOUDINARY_STORAGE = {
        "CLOUD_NAME": CLOUDINARY_CLOUD_NAME,
        "API_KEY": CLOUDINARY_API_KEY,
        "API_SECRET": CLOUDINARY_API_SECRET,
    }

# Django 6 removed DEFAULT_FILE_STORAGE and STATICFILES_STORAGE. Both are
# configured through STORAGES now. Your old STATICFILES_STORAGE line was
# being ignored, so WhiteNoise was running without compressed manifests.
STORAGES = {
    "default": {
        "BACKEND": (
            "cloudinary_storage.storage.MediaCloudinaryStorage"
            if USE_CLOUDINARY
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Only used by the local-disk fallback. Cloudinary ignores both and returns
# fully qualified URLs from ImageField, which the mobile app renders as-is.
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Fine while the only client is your own mobile app. Tighten to
# CORS_ALLOWED_ORIGINS before you ship a web client.
CORS_ALLOW_ALL_ORIGINS = True

ROOT_URLCONF = "firstproject.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "firstproject.wsgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            ssl_require=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
}

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"