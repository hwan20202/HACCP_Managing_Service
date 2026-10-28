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


def env_choice(name, choices, default):
    """값이 choices 중 하나여야 하는 설정. 비어 있으면 default, 그 밖 값은 시작 오류."""
    value = os.environ.get(name, "").strip().lower() or default
    if value not in choices:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(f"{name} must be one of: {', '.join(choices)}.")
    return value


data_path = Path(os.environ.get("HACCP_DATA_DIR", "data")).expanduser()
DATA_DIR = (data_path if data_path.is_absolute() else ROOT_DIR / data_path).resolve()
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
HACCP_ENVIRONMENT = "production"
HACCP_QA_SEED_ENABLED = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.inventory",
    "apps.documents",
    "apps.approvals",
    "apps.document_workflow",
    "apps.doc_requirements",
    "apps.doc_effects",  # P6 EFF 문서 후속 처리(D-079)
    "apps.production_log",  # P15 생산일지·생산 기준정보(ERD v7.3)
    "apps.admin_settings",  # P16 관리 설정(ERD v7.4)
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
        "OPTIONS": {
            "timeout": 20,
            # Core rule S1: WAL mode. Django itself sets foreign_keys=ON on every connection.
            "init_command": "PRAGMA journal_mode=WAL;",
            # Production core rule S5: every transaction.atomic() starts with BEGIN IMMEDIATE.
            "transaction_mode": "IMMEDIATE",
        },
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
# Document attachments (D01·D02) are stored under MEDIA_ROOT/files/YYYY/MM/ and served only
# through /api/v1/files/<id>; MEDIA_URL is not routed.
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
# [P6 EFF-A1] 수불 판정 함수(점 경로)와 거부로 바꿀 예외. 기본값 = 수불 앱(C2, D-128 D2).
# 비어 있으면 육안검사 작성완료가 503(W001).
HACCP_INVENTORY_JUDGMENT = os.environ.get(
    "HACCP_INVENTORY_JUDGMENT", "apps.inventory.judgment.apply_incoming_judgment"
)
HACCP_INVENTORY_ERRORS = env_list("HACCP_INVENTORY_ERRORS", "apps.inventory.errors.InventoryError")
# [P7 WF] 일괄 승인·상신 대상 양식 유형(P7-S2-Q2). 형식이 틀리면 시스템 점검 W001.
HACCP_BATCH_TYPES = env_list("HACCP_BATCH_TYPES", "D03,D10,D11,D12")  # P8 4.3
# P9 주기 작성 요구 규칙 파일(비우면 apps/doc_requirements/periodic_rules.json). 호출마다 읽음
HACCP_PERIODIC_RULES = os.environ.get("HACCP_PERIODIC_RULES") or None
# P14 역할 설정 파일(비우면 apps/staff/roles.json — 가상 개발 직원만).
# 서버 시작 뒤 한 번 읽음(바꾸면 재시작)
_roles_file = os.environ.get("HACCP_ROLES_FILE")
HACCP_ROLES_FILE = (
    None
    if not _roles_file
    else str(Path(_roles_file) if Path(_roles_file).is_absolute() else ROOT_DIR / _roles_file)
)  # 상대 경로는 저장소 루트 기준(HACCP_DATA_DIR과 같게)
HACCP_ROLES_RELOAD = False
# [임시 진입점 T5] 시제품 사이드바의 "개발 검증 (임시)" 탭. 운영(사용 테스트)에서도 켤 수 있다.
HACCP_TEMP_ENTRY = env_bool("HACCP_TEMP_ENTRY", False)
# [P10] 문서함·결재함 메뉴 자리: dev = 개발 검증 섹션(지금), haccp = HACCP 관리 섹션 맨 위
HACCP_DOC_MENU = env_choice("HACCP_DOC_MENU", ("dev", "haccp"), "dev")
