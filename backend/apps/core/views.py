import logging
import unicodedata

from django.apps import apps
from django.conf import settings
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


@require_safe
def home(request):
    if not settings.PROTOTYPE_DATA_FILE.is_file():
        return render(request, "prototype-missing.html")
    return render(request, "index.html")


@require_safe
def system_test(request):
    return render(request, "test.html")


@never_cache
@require_safe
def prototype_data(request):
    try:
        source = settings.PROTOTYPE_DATA_FILE.open("rb")
    except FileNotFoundError as error:
        raise Http404("Prototype data is not installed.") from error
    return FileResponse(source, content_type="text/javascript; charset=utf-8")


@never_cache
@xframe_options_sameorigin
@require_safe
def prototype_standard(request, filename):
    # The legacy screen references one PDF. Never expose arbitrary reference files.
    allowed_name = "기타가공품 기준서-250831.pdf"
    if unicodedata.normalize("NFC", filename) != allowed_name:
        raise Http404
    try:
        for file in settings.PROTOTYPE_STANDARD_DIR.iterdir():
            if unicodedata.normalize("NFC", file.name) == allowed_name:
                return FileResponse(file.open("rb"), content_type="application/pdf")
    except FileNotFoundError:
        pass
    raise Http404("Prototype standard is not installed.")


@never_cache
@require_safe
def live(request):
    return JsonResponse({"status": "ok", "service": "haccp"})


@never_cache
@require_safe
def ready(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        # SELECT 1 also succeeds on an empty SQLite file. Check the schema as well.
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        tables = set(connection.introspection.table_names())
        required_tables = {
            model._meta.db_table
            for model in apps.get_models(include_auto_created=True)
            if model._meta.managed and not model._meta.proxy
        }
        if pending or not required_tables.issubset(tables):
            return JsonResponse({"status": "not_ready", "database": "not_ready"}, status=503)
    except DatabaseError:
        logger.warning("Readiness database check failed.")
        return JsonResponse({"status": "not_ready", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})
