"""Hosted QA: production HTTP settings, isolated persistent data, no dev console."""

from copy import deepcopy

from django.core.exceptions import ImproperlyConfigured

from .production import *

HACCP_ENVIRONMENT = "qa"
qa_path = Path(os.environ.get("HACCP_QA_DATA_DIR", "")).expanduser()
if not os.environ.get("HACCP_QA_DATA_DIR") or not qa_path.is_absolute():
    raise ImproperlyConfigured("Set an absolute, separate HACCP_QA_DATA_DIR for hosted QA.")
qa_path = qa_path.resolve()
if (
    qa_path.is_relative_to(DATA_DIR)
    or DATA_DIR.is_relative_to(qa_path)
    or qa_path.is_relative_to(ROOT_DIR)
):
    raise ImproperlyConfigured("QA data must be outside the code and separate from HACCP_DATA_DIR.")
DATA_DIR = qa_path
DATABASES = deepcopy(DATABASES)
DATABASES["default"]["NAME"] = DATA_DIR / "db" / "app.sqlite3"
MEDIA_ROOT = DATA_DIR / "uploads"
STATIC_ROOT = (
    Path(os.environ.get("HACCP_STATIC_DIR", str(DATA_DIR / "static"))).expanduser().resolve()
)
if (
    STATIC_ROOT == DATA_DIR
    or DATA_DIR.is_relative_to(STATIC_ROOT)
    or ROOT_DIR.is_relative_to(STATIC_ROOT)
    or STATIC_ROOT.is_relative_to(ROOT_DIR)
    or (STATIC_ROOT.is_relative_to(DATA_DIR) and STATIC_ROOT != DATA_DIR / "static")
):
    raise ImproperlyConfigured("QA static directory must be separate from code and business data.")
# Collected public assets are readable by the separate proxy user; attachments stay 0600.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        "OPTIONS": {"file_permissions_mode": 0o644, "directory_permissions_mode": 0o755},
    },
}
PROTOTYPE_DATA_FILE = DATA_DIR / "legacy-prototype" / "src" / "js" / "data.js"
PROTOTYPE_STANDARD_DIR = DATA_DIR / "reference" / "setup_standard"
HACCP_QA_SEED_ENABLED = env_bool("HACCP_QA_SEED_ENABLED", False)
HACCP_DOC_MENU = "haccp"
HACCP_TEMP_ENTRY = False
HACCP_DEV_CONSOLE = False
