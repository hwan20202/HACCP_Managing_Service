from .base import *

SECRET_KEY = "test-only-secret-key-not-used-outside-the-automated-test-process"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        # Same transaction behaviour as base.py (rule S5). WAL does not apply to :memory:.
        "OPTIONS": {"transaction_mode": "IMMEDIATE"},
    }
}

# P16: 테스트 DB는 직원·문서 권한이 비어 있어 시작 때 빈 권한 경고(W002)가 늘 나온다 — 소음만 끔
# (check_roles 자체는 apps.staff.tests.test_roles가 직접 부른다)
SILENCED_SYSTEM_CHECKS = ["document_workflow.W002"]
