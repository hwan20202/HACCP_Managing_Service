import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]
env_file = Path(os.environ.get("HACCP_ENV_FILE", ".env")).expanduser()
load_dotenv(env_file if env_file.is_absolute() else ROOT_DIR / env_file, override=False)


def env_list(name, default=""):
    return [value.strip() for value in os.environ.get(name, default).split(",") if value.strip()]


def env_bool(name, default=False):
    value = os.environ.get(name, str(default)).lower()
    if value not in {"true", "false", "1", "0"}:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(f"{name} must be true or false.")
    return value in {"true", "1"}


data_path = Path(os.environ.get("HACCP_DATA_DIR", "data")).expanduser()
DATA_DIR = (data_path if data_path.is_absolute() else ROOT_DIR / data_path).resolve()
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.staff",
    "apps.documents",
    "apps.approvals",
    "apps.document_workflow",
    "apps.doc_requirements",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [ROOT_DIR / "frontend" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ]
        },
    }
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db" / "app.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [ROOT_DIR / "frontend" / "static"]
STATIC_ROOT = DATA_DIR / "static"
# Only this prototype dataset is served; the rest of data/ stays outside the web root.
PROTOTYPE_DATA_FILE = DATA_DIR / "legacy-prototype" / "src" / "js" / "data.js"
PROTOTYPE_STANDARD_DIR = DATA_DIR / "reference" / "setup_standard"
MEDIA_ROOT = DATA_DIR / "uploads"
# Reserved for future uploads; there is currently no upload/download feature.
MEDIA_URL = "/private-media/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
FILE_UPLOAD_PERMISSIONS = 0o600
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o700
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"standard": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "standard"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

# 개발 콘솔(처리 단계 추적, DB 스냅샷 API). 개발 설정에서만 켤 수 있다(development.py).
HACCP_DEV_CONSOLE = False
# [임시 진입점 T5] 시제품 사이드바의 "개발 검증 (임시)" 탭. 운영(사용 테스트)에서도 켤 수 있다.
HACCP_TEMP_ENTRY = env_bool("HACCP_TEMP_ENTRY", False)
