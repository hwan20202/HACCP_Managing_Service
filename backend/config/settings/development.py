from .base import *

DEBUG = True
SECRET_KEY = SECRET_KEY or "django-insecure-development-only-not-for-production-0123456789"

# 개발 콘솔: 기본으로 켠다. HACCP_DEV_CONSOLE=false 로 끌 수 있다.
HACCP_DEV_CONSOLE = env_bool("HACCP_DEV_CONSOLE", True)
if HACCP_DEV_CONSOLE:
    INSTALLED_APPS = [*INSTALLED_APPS, "apps.devtools"]
    MIDDLEWARE = [*MIDDLEWARE, "apps.devtools.middleware.TraceMiddleware"]
