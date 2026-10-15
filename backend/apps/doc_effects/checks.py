"""EFF-C1 등록 확인 (p6-s2-spec 4.6, P6-VR-08).

(1) EFF가 DOC 신호에 등록됐는지 (2) 인벤토리 판정 함수·예외를 import할 수 있는지.
판정 함수 설정이 비어 있으면 경고(W001)만 낸다 — 수불 통합 전 운영 설정(P6 S4b G2).
"""

from django.core.checks import Error, Tags, Warning, register
from django.utils.module_loading import import_string

from . import adapter

DISPATCH_UID = "doc_effects.on_document_transitioned"


def connected(signal):
    """dispatch_uid로 등록 여부를 본다(신호 수신자 목록의 키 = (dispatch_uid, sender id))."""
    return any(entry[0][0] == DISPATCH_UID for entry in signal.receivers)


@register(Tags.compatibility)
def check_inventory_adapter(app_configs, **kwargs):
    from apps.documents.signals import document_transitioned

    problems = []
    if not connected(document_transitioned):
        problems.append(
            Error(
                "EFF 판정 전달이 DOC 생명주기 신호에 등록되지 않았습니다.",
                id="doc_effects.E001",
            )
        )
    path = adapter.judgment_path()
    if not path:
        problems.append(
            Warning(
                "HACCP_INVENTORY_JUDGMENT가 비어 있어 육안검사 작성완료가 503으로 거부됩니다.",
                hint="수불 통합 때 apps.inventory.judgment.apply_incoming_judgment로 설정하세요.",
                id="doc_effects.W001",
            )
        )
        return problems
    for dotted in (path, *adapter.error_paths()):
        try:
            import_string(dotted)
        except ImportError as error:
            problems.append(
                Error(
                    f"인벤토리 어댑터를 불러올 수 없습니다: {dotted} ({error})",
                    id="doc_effects.E001",
                )
            )
    return problems
