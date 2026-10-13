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
