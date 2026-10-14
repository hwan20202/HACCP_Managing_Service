"""WF 테스트 준비물.

문서는 DOC 공개 함수로 만들고, 어긋난 데이터는 SQL로만 만든다(모델 import 없음).
"""

import copy

from django.db import connection

from apps.approvals import services as apr
from apps.documents import services as doc
from apps.documents.tests.base import ccp_payload, setup_reference_data

SLOTS = [
    {"slot_no": 1, "label": "담당", "approver_id": 3},
    {"slot_no": 2, "label": "검토", "approver_id": 2},
    {"slot_no": 3, "approver_id": 1},
]
# 5.1 결합 상태: (문서 상태, 최신 회차 상태)
ALLOWED_PAIRS = {
    ("draft", None),
    ("completed", None),  # P4: 상신은 작성완료에서만
    ("completed", "rejected"),  # 반려 후 다시 작성완료
    ("draft", "rejected"),  # 작성완료 후 작성 재개
    ("submitted", "in_progress"),
    ("approved", "approved"),
    ("rejected", "rejected"),
    # P6 정정(p6-s2-spec 3.1): F0·F1 — 열린 정정이 있을 때만
    ("correcting", "approved"),
    ("correcting", "rejected"),
    ("completed", "approved"),
    # P8 작성 안 함(작성중에서만, 되돌리면 작성중) — draft와 같은 짝
    ("skipped", None),
    ("skipped", "rejected"),
}
NEEDS_OPEN_CORRECTION = {
    ("correcting", "approved"),
    ("correcting", "rejected"),
    ("completed", "approved"),
}
CORRECTION_STATES = {"correcting", "completed", "submitted"}


def slots():
    return copy.deepcopy(SLOTS)


def new_document(templates, author=3, completed=True):
    """DOC 공개 함수로 문서를 만든다. 기본은 작성완료(v2) — P4부터 상신은 작성완료에서만."""
    document_id = doc.create_document(author, ccp_payload(templates["ccp"]))["document_id"]
    if completed:
        doc.complete_document(author, document_id, 1)
    return document_id


def complete_again(document_id, author=3):
    """반려 뒤 다시 작성완료(재상신 전 단계, P4)."""
    return doc.complete_document(author, document_id, version_of(document_id))


def version_of(document_id):
    return doc.get_document(document_id)["version"]


def slot_ids(request):
    return {s["slot_no"]: s["approval_id"] for s in request["slots"]}


def sql(statement, params=()):
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        return cursor.fetchall()


def db_state(document_id):
    """비교용: 문서 행 + 회차 행 + 칸 행 (롤백 확인)."""
    return (
        sql("SELECT * FROM document WHERE document_id=%s", [document_id]),
        sql("SELECT * FROM approval_request WHERE document_id=%s ORDER BY attempt", [document_id]),
        sql(
            "SELECT a.* FROM approval a JOIN approval_request r USING (request_id)"
            " WHERE r.document_id=%s ORDER BY a.approval_id",
            [document_id],
        ),
    )


def invariant_violations():
    """WF-TC-030 + P6-TC-090: 삭제 안 된 문서마다 (상태, 최신 회차 상태)가 결합 상태 안에 있는지.

    P6-FR-12: 열린 정정이 있으면 상태는 correcting·completed·submitted이고 승인 회차가 1개 이상,
    correcting(과 정정 작성완료 F1)이면 열린 정정이 있어야 한다.
    """
    rows = sql(
        "SELECT d.document_id, d.status,"
        " (SELECT r.status FROM approval_request r WHERE r.document_id = d.document_id"
        "  ORDER BY r.attempt DESC LIMIT 1),"
        " (SELECT COUNT(*) FROM approval_request r WHERE r.document_id = d.document_id"
        "  AND r.status = 'in_progress'),"
        " (SELECT COUNT(*) FROM approval_request r WHERE r.document_id = d.document_id"
        "  AND r.status = 'approved'),"
        " (SELECT COUNT(*) FROM document_correction c WHERE c.document_id = d.document_id"
        "  AND c.closed_at IS NULL)"
        " FROM document d WHERE d.deleted_at IS NULL"
    )
    bad = []
    for document_id, status, latest, in_progress, approved, open_corr in rows:
        pair = (status, latest)
        wrong = pair not in ALLOWED_PAIRS or in_progress > 1 or open_corr > 1
        if open_corr:
            wrong = wrong or status not in CORRECTION_STATES or approved == 0
        elif pair in NEEDS_OPEN_CORRECTION:
            wrong = True
        if wrong:
            bad.append((document_id, status, latest, in_progress, open_corr))
    return bad


__all__ = ["apr", "doc", "setup_reference_data"]
