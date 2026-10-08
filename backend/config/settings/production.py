from django.core.exceptions import ImproperlyConfigured

from .base import *

if len(SECRET_KEY) < 50 or SECRET_KEY.startswith(("django-insecure-", "replace-")):
    raise ImproperlyConfigured("Set a unique DJANGO_SECRET_KEY of at least 50 characters.")
if not os.environ.get("DJANGO_ALLOWED_HOSTS") or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set explicit DJANGO_ALLOWED_HOSTS for production.")

# Waitress only listens on 127.0.0.1 and only trusts the local Caddy proxy.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
HTTPS_ENABLED = env_bool("DJANGO_HTTPS_ENABLED", True)
SECURE_SSL_REDIRECT = HTTPS_ENABLED
CSRF_COOKIE_SECURE = HTTPS_ENABLED
# Do not impose an HSTS policy on other company applications/subdomains.
SECURE_HSTS_SECONDS = 3600 if HTTPS_ENABLED else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
