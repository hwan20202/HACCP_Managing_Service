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
}


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
    """WF-TC-030: 삭제되지 않은 모든 문서의 (상태, 최신 회차 상태)가 결합 상태 안에 있는지."""
    rows = sql(
        "SELECT d.document_id, d.status,"
        " (SELECT r.status FROM approval_request r WHERE r.document_id = d.document_id"
        "  ORDER BY r.attempt DESC LIMIT 1),"
        " (SELECT COUNT(*) FROM approval_request r WHERE r.document_id = d.document_id"
        "  AND r.status = 'in_progress')"
        " FROM document d WHERE d.deleted_at IS NULL"
    )
    bad = []
    for document_id, status, latest, open_count in rows:
        if (status, latest) not in ALLOWED_PAIRS or open_count > 1:
            bad.append((document_id, status, latest, open_count))
    return bad


__all__ = ["apr", "doc", "setup_reference_data"]
