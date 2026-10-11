from .base import *

SECRET_KEY = "test-only-secret-key-not-used-outside-the-automated-test-process"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

# [P4] 수불 개발용 임시 테이블(ERD v5 A13)
INSTALLED_APPS = [*INSTALLED_APPS, "apps.devstock"]
