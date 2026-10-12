from pathlib import Path
from datetime import timedelta
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Optional. If email_config.py is gitignored (common, since it holds mail
# credentials) it will not exist in the Railway container. A hard import there
# crashes the whole API at startup, which is a heavy price for a missing
# mailer. Import defensively and let email fail on its own terms instead.
try:
    from .email_config import *  # noqa: F401,F403
except ImportError:
    EMAIL_CONFIG_LOADED = False
else:
    EMAIL_CONFIG_LOADED = True

# In production the mail credentials come from environment variables, so the
# password never has to live in the repository. They win over email_config.py.
if os.environ.get("EMAIL_HOST_PASSWORD", "").strip():
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com").strip()
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465").strip())
    EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "True").strip() == "True"
    EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "False").strip() == "True"
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "").strip()
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "").strip()
    DEFAULT_FROM_EMAIL = os.environ.get(
        "DEFAULT_FROM_EMAIL", f"CRAFTD <{EMAIL_HOST_USER}>"
    ).strip()
    EMAIL_CONFIG_LOADED = True

# Never let a slow or blocked mail server hang a request.
EMAIL_TIMEOUT = 10

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

# Railway sets these automatically. Their presence is a reliable signal that
# this is the deployed environment rather than a laptop.
RAILWAY_HOST = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
IS_RAILWAY = bool(RAILWAY_HOST or os.environ.get("RAILWAY_ENVIRONMENT"))

# An explicit DEBUG env var always wins. Otherwise: off on Railway, on
# locally. Note that because IS_RAILWAY already forces False in production,
# you do not need a DEBUG variable set on Railway at all. If one is set and
# its value is not exactly "False", it is silently ignored here, but any
# value of exactly "True" WILL turn debug on in production. Safest to delete
# the variable from the Railway dashboard entirely.
DEBUG = os.environ.get("DEBUG", "False" if IS_RAILWAY else "True").strip() == "True"

# Required in production, with a throwaway fallback for local runs so you are
# not forced to set an env var just to start the dev server. The fallback is
# unreachable when DEBUG is False, so production still fails loudly.
#
# .strip() throughout: copying a value out of a web dashboard very easily
# picks up a leading tab or trailing newline. The variable then looks correct
# in the UI (the whitespace is invisible) but the service rejects it, which
# is an expensive hour to debug. Stripping costs nothing and rules it out.
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
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

# Railway terminates TLS at its edge and forwards plain HTTP to the
# container, so Django needs this header to know the original request was
# secure. Without it, request.is_secure() is always False and secure cookies
# are never sent.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Cookie hardening, production only. Left off in DEBUG so the local dev
# server over plain HTTP still works.
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Deliberately NOT setting SECURE_SSL_REDIRECT. Railway already redirects
# HTTP to HTTPS at the edge, and enabling it here can produce a redirect
# loop if the proxy header is ever misread.

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

CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY", "").strip()
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET", "").strip()

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
# configured through STORAGES now.
#
# The staticfiles backend is gated on DEBUG. CompressedManifestStaticFilesStorage
# requires a staticfiles.json manifest that only exists after collectstatic has
# run, so applying it locally makes {% static %} raise
# "Missing staticfiles manifest entry" on a fresh checkout.
STORAGES = {
    "default": {
        "BACKEND": (
            "cloudinary_storage.storage.MediaCloudinaryStorage"
            if USE_CLOUDINARY
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
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
#
# ssl_require is now conditional. Railway's own Postgres is reached over the
# private network at *.railway.internal, which does NOT speak TLS: forcing
# sslmode=require against it fails to connect. External managed databases
# (Neon, Supabase, RDS) do require it. Detecting the internal hostname keeps
# both cases working without a manual edit.
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL:
    IS_INTERNAL_DB = ".railway.internal" in DATABASE_URL
    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            ssl_require=not IS_INTERNAL_DB,
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

# WhiteNoise refuses to start if STATIC_ROOT does not exist. It is created by
# collectstatic, but this makes a fresh checkout safe before that first run.
STATIC_ROOT.mkdir(parents=True, exist_ok=True)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Startup diagnostics
#
# One line in the Railway deploy log telling you which branch of every
# conditional above was taken. Cheap, and it turns "why is this behaving
# differently in production" into a five second check.
#
# Deliberately a print rather than a logger call. The LOGGING dict above is
# only applied by Django during django.setup(), which happens AFTER this
# module finishes importing. A logger.info() here would be evaluated against
# Python's default root level of WARNING and silently discarded. Gunicorn
# forwards stdout straight to Railway's deploy logs, so print lands where it
# is wanted.
# ---------------------------------------------------------------------------

if IS_RAILWAY:
    print(
        f"CRAFTD boot: debug={DEBUG} host={RAILWAY_HOST or 'unset'} "
        f"cloudinary={USE_CLOUDINARY} "
        f"cloud_name={CLOUDINARY_CLOUD_NAME or 'unset'} "
        f"key_len={len(CLOUDINARY_API_KEY)} "
        f"key_numeric={CLOUDINARY_API_KEY.isdigit()} "
        f"secret_len={len(CLOUDINARY_API_SECRET)} "
        f"db={'postgres' if DATABASE_URL else 'sqlite'} "
        f"email_config={EMAIL_CONFIG_LOADED}",
        flush=True,
    )