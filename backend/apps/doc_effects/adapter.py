"""EFF-A1 인벤토리 어댑터 (p6-s2-spec 4.6, P6-NFR-07).

인벤토리 함수는 설정 경로로만 부른다(코드에 앱 이름을 박지 않음):
- HACCP_INVENTORY_JUDGMENT: `apply_incoming_judgment`의 점 경로
- HACCP_INVENTORY_ERRORS: 거부로 바꿀 예외 클래스 점 경로 목록
개발·테스트 = devstock 임시 함수(같은 이름·같은 규칙), 운영 = 수불 앱 함수(통합 때 설정만 바꿈).
설정된 예외만 거부로 바꾸고, 그 밖의 예외는 그대로 올린다(500 — 작성완료 롤백).
"""

from django.conf import settings
from django.utils.module_loading import import_string

from . import errors


class Rejected(Exception):
    """인벤토리가 판정을 거부함. message = 인벤토리 메시지(str(예외)) 그대로."""


def judgment_path():
    return getattr(settings, "HACCP_INVENTORY_JUDGMENT", None) or None


def error_paths():
    return tuple(getattr(settings, "HACCP_INVENTORY_ERRORS", ()) or ())


def load():
    """(판정 함수, 거부 예외 튜플). 설정이 없으면 InventoryNotConfigured."""
    path = judgment_path()
    if not path:
        raise errors.InventoryNotConfigured()
    return import_string(path), tuple(import_string(p) for p in error_paths())


def judge_incoming_lot(*, lot_id, result, staff_id, document_id, judged_at, reason):
    func, rejections = load()
    try:
        return func(
            lot_id=lot_id,
            result=result,
            staff_id=staff_id,
            document_id=document_id,
            judged_at=judged_at,
            reason=reason,
        )
    except rejections as error:
        raise Rejected(str(error)) from error
