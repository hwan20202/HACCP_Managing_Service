"""문서 워크플로우(WF) 서비스 (document-workflow/s2-spec.md 2.3, 흐름은 s2-flows.md).

- 테이블이 없다. DOC·APR의 공개 서비스 함수만 호출한다(모델 import 금지, WF-NFR-01).
- WF는 호출 순서, 트랜잭션 경계, 결과에 따른 분기만 정한다. 규칙 판단은 도메인이 한다.
- 오류는 도메인 오류를 그대로 올려 보낸다(WF-S2-Q3). 트랜잭션 안에서 실패하면 전체를 되돌린다.
"""

from django.db import transaction

from apps.approvals import services as apr
from apps.core.http import ApiError
from apps.core.trace import step
from apps.documents import services as doc


def _document_ref(snapshot):
    """APR에 넘길 문서 요약. 스냅샷(잠금 직후 읽은 문서)에서 만든다(WF-FR-03)."""
    return {
        "document_id": snapshot["document_id"],
        "version": snapshot["version"],
        "template_id": snapshot["template"]["template_id"],
        "subject": snapshot["subject"],
        "work_date": snapshot["work_date"],
    }


def _rollback_note(tx_step, error):
    code = getattr(error, "code", type(error).__name__)
    tx_step.fail(f"{code} → 롤백")


def submit(actor_id, document_id, expected_version, slots):
    """상신·재상신 (WF-F01·F04): 결재선 검증 → [문서 잠금 → 스냅샷 → 회차 생성]."""
    with step("WF-SUB-03", "WF", "결재선 검증(트랜잭션 밖)"):
        apr.validate_slots(slots)
    with step("WF-SUB-04", "WF", "트랜잭션") as tx:
        try:
            with transaction.atomic():
                with step("WF-SUB-05", "WF", "문서 잠금"):
                    lock = doc.lock_for_review(document_id, expected_version)
                with step("WF-SUB-06", "WF", "스냅샷 읽기"):
                    snapshot = doc.get_document(document_id)
                with step("WF-SUB-07", "WF", "결재 회차 생성"):
                    request = apr.open_request(_document_ref(snapshot), snapshot, actor_id, slots)
        except ApiError as error:
            _rollback_note(tx, error)
            raise
        tx.note(f"커밋: 문서 v{lock['version']}, {request['attempt']}회차")
    with step("WF-SUB-08", "WF", "결과"):
        return {"document": lock, "request": request}


def decide(actor_id, approval_id, result, comment=None):
    """승인·반려 (WF-F02·F03): [칸 처리 → 회차 결과에 따라 문서 상태 맞추기]."""
    with step("WF-DEC-03", "WF", "트랜잭션") as tx:
        try:
            with transaction.atomic():
                with step("WF-DEC-04", "WF", "칸 처리"):
                    outcome = apr.decide(approval_id, actor_id, result, comment)
                with step("WF-DEC-05", "WF", "문서 상태 맞추기") as sync:
                    status = outcome["request_status"]
                    if status == "approved":
                        document = doc.mark_approved(outcome["document_id"])
                    elif status == "rejected":
                        document = doc.mark_rejected(outcome["document_id"])
                    else:
                        document = None
                        sync.skip(f"회차 진행 중(대기 {outcome['pending_count']}) — 문서 변화 없음")
        except ApiError as error:
            _rollback_note(tx, error)
            raise
        tx.note(f"커밋: 회차 {outcome['request_status']}")
    with step("WF-DEC-06", "WF", "결과"):
        return {**outcome, "document": document}
