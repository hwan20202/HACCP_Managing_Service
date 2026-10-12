from .base import *

SECRET_KEY = "test-only-secret-key-not-used-outside-the-automated-test-process"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

# [P4] 수불 개발용 임시 테이블(ERD v5 A13)
INSTALLED_APPS = [*INSTALLED_APPS, "apps.devstock"]

# [P6 EFF-A1] 개발: 수불 판정 함수 대신 devstock 임시 함수(같은 이름·규칙)
HACCP_INVENTORY_JUDGMENT = "apps.devstock.inventory.apply_incoming_judgment"
HACCP_INVENTORY_ERRORS = ["apps.devstock.inventory.InventoryError"]
