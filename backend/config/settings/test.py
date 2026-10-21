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

# P14: 테스트마다 직원·설정이 바뀌므로 역할 설정을 호출마다 다시 읽는다
HACCP_ROLES_RELOAD = True
