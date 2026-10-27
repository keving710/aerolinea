"""
Configuración del proyecto "Sistema de gestión de compra y reserva de tiquetes aéreos".

Pensada para correr igual en local (SQLite, sin configurar nada) y en Vercel
(PostgreSQL externo + variables de entorno). Todo lo que cambia entre entornos
se lee de variables de entorno; ver .env.example.
"""
import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(nombre, defecto=False):
    valor = os.environ.get(nombre)
    if valor is None:
        return defecto
    return valor.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


# --------------------------------------------------------------------------
# Seguridad
# --------------------------------------------------------------------------
# DEBUG queda apagado por defecto para que un despliegue sin configurar nunca
# quede en modo desarrollo. En local: DEBUG=1 python manage.py runserver
DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "clave-solo-para-desarrollo-local-no-usar-en-produccion"
    else:
        raise ImproperlyConfigured(
            "Falta la variable de entorno SECRET_KEY (obligatoria cuando DEBUG está apagado)."
        )

ALLOWED_HOSTS = [".vercel.app", "localhost", "127.0.0.1", "testserver"]
ALLOWED_HOSTS += [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]

CSRF_TRUSTED_ORIGINS = ["https://*.vercel.app"]
CSRF_TRUSTED_ORIGINS += [
    o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

if not DEBUG:
    # Vercel termina TLS y reenvía el protocolo original en este encabezado.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# --------------------------------------------------------------------------
# Aplicaciones
# --------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "usuarios",
    "vuelos",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise sirve los estáticos desde la propia función serverless.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "usuarios.context_processors.estado_perfil",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --------------------------------------------------------------------------
# Base de datos
# --------------------------------------------------------------------------
# Local: SQLite. Vercel: DATABASE_URL apuntando a PostgreSQL (Neon/Supabase)
# usando la cadena "pooled" (pgbouncer) para no agotar conexiones.
_database_url = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
DATABASES = {"default": dj_database_url.parse(_database_url, conn_max_age=0)}
if DATABASES["default"]["ENGINE"].endswith("postgresql"):
    # Con pgbouncer en modo "transaction" no se pueden usar cursores del lado del servidor.
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

# --------------------------------------------------------------------------
# Usuarios y autenticación
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "usuarios.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "usuarios:login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "inicio"

# Credenciales del usuario root por defecto (HU 4). Se crean al ejecutar `migrate`.
ROOT_USERNAME = os.environ.get("ROOT_USERNAME", "root")
ROOT_PASSWORD = os.environ.get("ROOT_PASSWORD", "Root2026!")

# --------------------------------------------------------------------------
# Internacionalización
# --------------------------------------------------------------------------
LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Archivos estáticos y de usuario (fotos de perfil)
# --------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# Permite que WhiteNoise sirva los estáticos directamente desde las carpetas de
# las apps, sin paso de `collectstatic` (Vercel no ejecuta uno por nosotros).
WHITENOISE_USE_FINDERS = True

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Vercel no tiene disco persistente: si hay CLOUDINARY_URL, las fotos de perfil
# se guardan en Cloudinary; si no, en la carpeta local media/ (solo desarrollo).
if os.environ.get("CLOUDINARY_URL"):
    INSTALLED_APPS += ["cloudinary_storage", "cloudinary"]
    STORAGES["default"] = {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"}

FOTO_PERFIL_MAX_BYTES = 2 * 1024 * 1024  # 2 MB

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redirige los 403 a una página con el mensaje de "acceso restringido" (HU 3).
# (handler403 se declara en config/urls.py)

# Pruebas más rápidas: hash de contraseñas liviano solo al ejecutar `manage.py test`.
import sys  # noqa: E402

if "test" in sys.argv:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
