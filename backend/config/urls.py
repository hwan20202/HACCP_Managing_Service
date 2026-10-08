from apps.core.views import home, live, prototype_data, prototype_standard, ready, system_test
from django.urls import path

urlpatterns = [
    path("", home, name="home"),
    path("test/", system_test, name="system-test"),
    path("prototype/data.js", prototype_data, name="prototype-data"),
    path("setup_standard/<str:filename>", prototype_standard, name="prototype-standard"),
    path("health/live/", live, name="health-live"),
    path("health/ready/", ready, name="health-ready"),
]
