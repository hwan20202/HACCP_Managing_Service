"""WF 시스템 점검 (P7-NFR-06): 일괄 대상 양식 설정 HACCP_BATCH_TYPES의 형식만 본다.

DB를 읽지 않는다(마이그레이션 전·테스트 중에도 안전, 검토 B-7). 양식 표에 없는 유형은 실행 때
template_ids가 비어 일괄 승인·상신이 모두 not_batchable이 된다.
"""

from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.compatibility)
def check_batch_types(app_configs, **kwargs):
    from .services import DEFAULT_BATCH_TYPES, valid_batch_types

    value = getattr(settings, "HACCP_BATCH_TYPES", DEFAULT_BATCH_TYPES)
    if valid_batch_types(value):
        return []
    return [
        Warning(
            "HACCP_BATCH_TYPES는 비어 있지 않은 양식 유형 문자열 목록이어야 합니다.",
            hint='예: HACCP_BATCH_TYPES = ["D03"]. 지금 설정으로는 일괄 승인·상신 대상이 없습니다.',
            id="document_workflow.W001",
        )
    ]


@register(Tags.compatibility)
def check_roles(app_configs, **kwargs):
    """P14 역할 설정 점검(S2a 1.4): 형식 오류 R-E1은 Error, 나머지는 Warning.

    staff·양식 표를 읽는다 — 표가 없거나(마이그레이션 전) 직원이 없으면 형식 검사만 한다(L-22).
    """
    import json

    from django.core.checks import Error
    from django.db import connection
    from django.db.utils import DatabaseError

    from apps.staff import roles

    try:
        data = json.loads(roles.config_path().read_text(encoding="utf-8"))
        problems = roles._format_problems(data)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        problems = [f"설정 파일을 읽지 못했습니다: {error}"]
    if problems:
        return [
            Error(
                "역할 설정 파일(HACCP_ROLES_FILE) 형식 오류 — 모든 상신이 막힙니다: "
                + " / ".join(problems),
                id="document_workflow.E002",
            )
        ]
    try:
        tables = set(connection.introspection.table_names())
    except DatabaseError:
        return []
    if not {"staff", "document_template"} <= tables:
        return []
    from apps.documents import services as doc
    from apps.staff import services as staff_services

    try:
        if not staff_services.active_people():
            return []  # 직원 등록 전(새 설치·테스트 DB) — 모든 코드가 R-W1이 되는 소음 방지
        roles.reset()
        summary = doc.roles_summary()
    except DatabaseError:
        return []
    return [
        Warning(
            f"역할 설정 {item['code']}: {item['message']}",
            hint="역할 보기 화면에서 확인하세요. 설정 파일을 고친 뒤 서버를 다시 시작합니다.",
            id="document_workflow.W002",
        )
        for item in summary["warnings"]
    ]
