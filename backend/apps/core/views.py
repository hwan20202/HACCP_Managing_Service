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
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


@require_safe
@ensure_csrf_cookie  # P16 R71: 관리 설정 쓰기(CSRF 검사 유지)용 쿠키를 첫 화면에서 늘 발급
def home(request):
    if not settings.PROTOTYPE_DATA_FILE.is_file():
        return render(request, "prototype-missing.html")
    # [임시 진입점 T4] 개발 검증 사이드 탭과 개발 콘솔 링크 표시 여부
    context = {
        "temp_entry_enabled": settings.HACCP_TEMP_ENTRY,
        "dev_console_enabled": settings.DEBUG and settings.HACCP_DEV_CONSOLE,
        # P5 REQ-SC-01 작성 요구 테스트 화면: 개발 콘솔이 켜져 있을 때만(REQ-S1-Q1)
        "req_test_enabled": settings.DEBUG and settings.HACCP_DEV_CONSOLE,
        # P10 문서함·결재함 메뉴 자리(dev·haccp — p10-s2-spec 4장)
        "doc_menu": settings.HACCP_DOC_MENU,
        # 문서함·결재함 스크립트: 개발 검증 탭이 켜졌거나 HACCP 관리 섹션에 메뉴가 있을 때
        "doc_entry_enabled": settings.HACCP_TEMP_ENTRY or settings.HACCP_DOC_MENU == "haccp",
        "qa_site": getattr(settings, "HACCP_ENVIRONMENT", "production") == "qa",
    }
    return render(request, "index.html", context)


@require_safe
def print_page(request):
    """P12 PRT-SC-01 인쇄용 페이지(새 탭). 데이터는 화면이 GET /api/v1/print/sheet로 읽는다."""
    return render(request, "print.html")


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
        # Unmanaged models count too: their tables come from SQL migrations (apps.inventory).
        required_tables = {
            model._meta.db_table
            for model in apps.get_models(include_auto_created=True)
            if not model._meta.proxy
        }
        if pending or not required_tables.issubset(tables):
            return JsonResponse({"status": "not_ready", "database": "not_ready"}, status=503)
    except DatabaseError:
        logger.warning("Readiness database check failed.")
        return JsonResponse({"status": "not_ready", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})
