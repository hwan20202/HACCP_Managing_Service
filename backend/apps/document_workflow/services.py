"""문서 워크플로우(WF) 서비스 (document-workflow/s2-spec.md 2.3, 흐름은 s2-flows.md).

- 테이블이 없다. DOC·APR의 공개 서비스 함수만 호출한다(모델 import 금지, WF-NFR-01).
- WF는 호출 순서, 트랜잭션 경계, 결과에 따른 분기만 정한다. 규칙 판단은 도메인이 한다.
- 오류는 도메인 오류를 그대로 올려 보낸다(WF-S2-Q3). 트랜잭션 안에서 실패하면 전체를 되돌린다.
"""

from django.conf import settings
from django.db import transaction

from apps.approvals import services as apr
from apps.core import batch
from apps.core.http import ApiError
from apps.core.trace import step
from apps.documents import services as doc


def _document_ref(snapshot):
    """APR에 넘길 문서 요약. 스냅샷(잠금 직후 읽은 문서)에서 만든다(WF-FR-03).

    P7(ISS-018, P7-FR-11): subject가 비면 스냅샷의 target_summary(DOC 상세 규칙)로 채운다.
    """
    return {
        "document_id": snapshot["document_id"],
        "version": snapshot["version"],
        "template_id": snapshot["template"]["template_id"],
        "subject": snapshot["subject"] or snapshot.get("target_summary"),
        "work_date": snapshot["work_date"],
    }


def _rollback_note(tx_step, error):
    code = getattr(error, "code", type(error).__name__)
    tx_step.fail(f"{code} → 롤백")


def _submit_steps(actor_id, document_id, expected_version, slots):
    """상신 한 건의 트랜잭션 안 단계(WF-SUB-05~07). 한 건·일괄 상신이 같이 쓴다(P7 G5)."""
    with step("WF-SUB-05", "WF", "문서 잠금"):
        lock = doc.lock_for_review(document_id, expected_version)
    with step("WF-SUB-06", "WF", "스냅샷 읽기"):
        snapshot = doc.get_document(document_id)
    with step("WF-SUB-07", "WF", "결재 회차 생성"):
        request = apr.open_request(_document_ref(snapshot), snapshot, actor_id, slots)
    return lock, request


def submit(actor_id, document_id, expected_version, slots):
    """상신·재상신 (WF-F01·F04): 결재선 검증 → [문서 잠금 → 스냅샷 → 회차 생성]."""
    with step("WF-SUB-03", "WF", "결재선 검증(트랜잭션 밖)"):
        apr.validate_slots(slots)
    with step("WF-SUB-04", "WF", "트랜잭션") as tx:
        try:
            with transaction.atomic():
                lock, request = _submit_steps(actor_id, document_id, expected_version, slots)
        except ApiError as error:
            _rollback_note(tx, error)
            raise
        tx.note(f"커밋: 문서 v{lock['version']}, {request['attempt']}회차")
    with step("WF-SUB-08", "WF", "결과"):
        return {"document": lock, "request": request}


def _decide_steps(actor_id, approval_id, result, comment):
    """칸 처리 한 건의 트랜잭션 안 단계(WF-DEC-04·05). 한 건·일괄 승인이 같이 쓴다(P7 G5)."""
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
    return {**outcome, "document": document}


def decide(actor_id, approval_id, result, comment=None):
    """승인·반려 (WF-F02·F03): [칸 처리 → 회차 결과에 따라 문서 상태 맞추기]."""
    with step("WF-DEC-03", "WF", "트랜잭션") as tx:
        try:
            with transaction.atomic():
                outcome = _decide_steps(actor_id, approval_id, result, comment)
        except ApiError as error:
            _rollback_note(tx, error)
            raise
        tx.note(f"커밋: 회차 {outcome['request_status']}")
    with step("WF-DEC-06", "WF", "결과"):
        return outcome


# ---------------------------------------------------------------- P7 일괄 (p7-s2-spec 3.1)

DEFAULT_BATCH_TYPES = ("D03", "D10", "D11", "D12")  # P8 4.3


def batch_types():
    """설정 HACCP_BATCH_TYPES(기본 D03·D10·D11·D12 — P7-S2-Q2, P8 4.3).

    형식이 틀리면 빈 목록(W001이 알린다)."""
    value = getattr(settings, "HACCP_BATCH_TYPES", DEFAULT_BATCH_TYPES)
    if not valid_batch_types(value):
        return []
    return list(value)


def valid_batch_types(value):
    return (
        isinstance(value, (list, tuple))
        and bool(value)
        and all(isinstance(v, str) and v.strip() for v in value)
    )


def _batch_template_ids(types):
    """일괄 대상 양식의 모든 버전 template_id(DOC F02, SQL 1). 유형이 없으면 SQL 없음."""
    if not types:
        return []
    return [
        t["template_id"] for t in doc.list_templates(all_versions=True) if t["type_code"] in types
    ]


def batch_config():
    """WF-F08: 화면용 일괄 설정 — 대상 양식과 그 template_id, 상한, 점검자 지정 양식."""
    with step("WF-CFG-01", "WF", "설정 읽기"):
        types = batch_types()
    with step("WF-CFG-02", "WF", "양식 id(DOC F02)"):
        return {
            "batch_types": types,
            "template_ids": _batch_template_ids(types),
            "max_items": batch.MAX_ITEMS,
            "inspector_types": list(doc.INSPECTOR_TYPES),
        }


def _approve_result(outcome):
    return {
        "request_status": outcome["request_status"],
        "pending_count": outcome["pending_count"],
        "document": outcome["document"],
    }


def batch_approve(actor_id, approval_ids, comment=None):
    """WF-F06 일괄 승인(반려 없음). 입력 검사 → [칸마다 세이브포인트: 한 건 승인 단계] → 결과.

    입력 검사(의견·칸 출처·대상 양식)는 트랜잭션 밖(G3). 4xx는 그 칸만 되돌리고 계속, 5xx·그 밖의
    예외는 전체 롤백(G4). 같은 문서의 칸 처리 순서는 한 건 승인과 같다(APR 먼저).
    """
    ids = batch.id_list(approval_ids, "approval_ids")
    with step("WF-BAP-03", "WF", "의견 검사(APR A11)"):
        comment = apr.check_decision_input("approved", comment)
    with step("WF-BAP-04", "WF", "칸 출처·대상 양식 검사"):
        refs = apr.slot_refs(ids)
        allowed = set(_batch_template_ids(batch_types()))
        wrong = [
            f"approval_ids[{i}]"
            for i, approval_id in enumerate(ids)
            if approval_id in refs and refs[approval_id]["template_id"] not in allowed
        ]
        if wrong:
            raise batch.not_batchable(wrong)
    with step("WF-BAP-05", "WF", "트랜잭션") as tx:
        try:
            with transaction.atomic():
                results = batch.run_each(
                    ids,
                    lambda approval_id: _approve_result(
                        _decide_steps(actor_id, approval_id, "approved", comment)
                    ),
                    ident=lambda approval_id: {
                        "document_id": refs.get(approval_id, {}).get("document_id"),
                        "approval_id": approval_id,
                    },
                    layer="WF",
                    item_step="WF-BAP-06",
                    ok_step="WF-BAP-06b",
                    fail_step="WF-BAP-06a",
                )
        except Exception as error:
            _rollback_note(tx, error)
            raise
        tx.note(f"커밋: {sum(r['ok'] for r in results)}/{len(results)}")
    with step("WF-BAP-07", "WF", "결과 모음"):
        return batch.summary("approve", results)


def _submit_result(lock, request):
    return {
        "document": lock,
        "request": {k: request[k] for k in ("request_id", "attempt", "status", "subject")},
    }


def batch_submit(actor_id, items, slots):
    """WF-F07 일괄 상신: 결재선 1개로 문서마다 한 건 상신 단계(세이브포인트)."""
    pairs = batch.version_items(items, "items")
    with step("WF-BSB-03", "WF", "결재선 검증(트랜잭션 밖)"):
        apr.validate_slots(slots)
    with step("WF-BSB-04", "WF", "대상 양식 검사(DOC F26)"):
        types = set(batch_types())
        brief = {
            item["document_id"]: item
            for item in doc.brief_documents([document_id for document_id, _ in pairs])["items"]
        }
        wrong = [
            f"items[{i}]"
            for i, (document_id, _) in enumerate(pairs)
            if document_id in brief and brief[document_id]["type_code"] not in types
        ]
        if wrong:
            raise batch.not_batchable(wrong)
    with step("WF-BSB-05", "WF", "트랜잭션") as tx:
        try:
            with transaction.atomic():
                results = batch.run_each(
                    pairs,
                    lambda pair: _submit_result(*_submit_steps(actor_id, pair[0], pair[1], slots)),
                    ident=lambda pair: {"document_id": pair[0]},
                    layer="WF",
                    item_step="WF-BSB-06",
                    ok_step="WF-BSB-06b",
                    fail_step="WF-BSB-06a",
                )
        except Exception as error:
            _rollback_note(tx, error)
            raise
        tx.note(f"커밋: {sum(r['ok'] for r in results)}/{len(results)}")
    with step("WF-BSB-07", "WF", "결과 모음"):
        return batch.summary("submit", results)
