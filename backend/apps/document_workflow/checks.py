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
    """P16 문서 권한 점검(ADM-R38): 모두 Warning(P14 E002 없앰 — 원본이 DB라 형식 오류 없음).

    문서 권한 비어 있음·활성 HACCP팀장 0명·처리할 사람 없는 결재 칸(상신 불가 양식)을 알린다.
    직원이 0명이어도 낸다(설치 점검 P-5). 표가 없으면(마이그레이션 전) 아무것도 안 낸다.
    """
    from django.db import connection
    from django.db.utils import DatabaseError

    try:
        tables = set(connection.introspection.table_names())
    except DatabaseError:
        return []
    if not {"staff", "document_template", "role_config", "role_form"} <= tables:
        return []
    from apps.documents import services as doc

    try:
        summary = doc.roles_summary()
    except DatabaseError:
        return []
    hint = "문서 권한 화면에서 지정하세요. 저장 즉시 적용됩니다."
    setup = summary["setup"]
    messages = []
    if setup["empty"]:
        messages.append("문서 권한이 비어 있습니다 — 담당자·HACCP팀장이 한 명도 없습니다.")
        # D-270 B2: 역할 파일을 쓰던 기존 서버는 migrate 뒤 이 상태 — 옮기는 명령을 함께 알림
        hint += (
            " 역할 파일(roles.json)을 쓰던 기존 서버는 "
            "manage.py import_roles --file <roles.json> --actor <활성 직원 코드>로 옮깁니다."
        )
    if not setup["leaders"]:
        messages.append("활성 HACCP팀장이 0명입니다.")
    if setup["blocked_forms"]:
        messages.append(
            "결재 칸을 처리할 사람이 없어 상신할 수 없는 양식: " + ", ".join(setup["blocked_forms"])
        )
    messages += [
        f"문서 권한 {item['code']}: {item['message']}"
        for item in summary["warnings"]
        if item["code"] != "R-W5"  # 칸 후보 없음은 위 상신 불가 양식 한 줄로
    ]
    return [Warning(m, hint=hint, id="document_workflow.W002") for m in messages]
