from .base import *

DEBUG = True
SECRET_KEY = SECRET_KEY or "django-insecure-development-only-not-for-production-0123456789"

# 개발 콘솔: 기본으로 켠다. HACCP_DEV_CONSOLE=false 로 끌 수 있다.
HACCP_DEV_CONSOLE = env_bool("HACCP_DEV_CONSOLE", True)
if HACCP_DEV_CONSOLE:
    INSTALLED_APPS = [*INSTALLED_APPS, "apps.devtools"]
    MIDDLEWARE = [*MIDDLEWARE, "apps.devtools.middleware.TraceMiddleware"]

# [임시 진입점 T5] 개발에서는 기본으로 켠다.
HACCP_TEMP_ENTRY = env_bool("HACCP_TEMP_ENTRY", True)

# 개발 서버가 정적 파일을 no-cache로 보내도록 runserver를 확장한다(브라우저가 예전 JS를 쓰지 않게).
# Django는 INSTALLED_APPS 앞쪽 앱의 명령을 쓰므로 맨 앞에 둔다.
INSTALLED_APPS = ["apps.devserver", *INSTALLED_APPS]

# [P4] 수불 개발용 임시 테이블(ERD v5 A13). 수불 앱이 들어오면 빼고 개발 DB를 다시 만든다(P4-S3-Q7).
INSTALLED_APPS = [*INSTALLED_APPS, "apps.devstock"]
