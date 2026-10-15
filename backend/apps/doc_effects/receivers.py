"""EFF-R1 육안검사 판정 전달 (p6-s2-spec 4.6, p6a-s2-flows 3장 EFF-JDG — P6a: LOT마다 문서 1건).

D03 작성완료(정정 뒤 다시 작성완료 포함)일 때만 그 문서의 LOT에 1회 판정을 전달한다.
작성 재개·반려·승인·정정 시작·정정 취소는 부르지 않는다(P6-FR-21 — 판정 철회 없음).
문서는 DOC 공개 함수(F05)로만 읽고, LOT 상태는 읽거나 저장하지 않는다(D-073, P6-FR-23).
"""

import datetime

from apps.core.trace import step
from apps.documents import services as doc

from . import adapter, errors

D03 = "D03"
INSPECTION = "inspection"


def _lot_ref(detail):
    return next(
        (r for r in detail["refs"] if r["section_id"] is None and r["lot_id"] is not None), None
    )


def _verdict(detail):
    row = next((s for s in detail["sections"] if s["section_def"] == INSPECTION), None)
    return (row or {}).get("values", {}).get("verdict")


def on_document_transitioned(sender, document_id, event, actor_id=None, note=None, **kwargs):
    if event != "completed":
        return
    with step("EFF-JDG-01", "EFF", "양식 확인") as s:
        if kwargs.get("type_code") != D03:
            s.skip("육안검사 아님 — 판정 전달 없음")
            return
    with step("EFF-JDG-02", "EFF", "LOT·판정·열린 정정 읽기(DOC F05)") as s:
        detail = doc.get_document(document_id)
        ref = _lot_ref(detail)
        verdict = _verdict(detail)
        correction = detail.get("correction")
        # 재판정 사유 = 열린 정정 사유, 없으면 작성완료 메모(P6-FR-19, D-080)
        reason = (correction or {}).get("reason") or note
        judged_at = datetime.datetime.fromisoformat(detail["completed_at"])
        s.note(
            f"LOT {ref['label'] if ref else '-'} · {verdict} · 사유 {'있음' if reason else '없음'}"
        )
    if ref is None or verdict is None:
        # 작성완료 검사가 판정을 필수로 보므로 정상 경로에서는 오지 않는다(방어)
        with step("EFF-JDG-03", "EFF", "판정 전달") as s:
            s.skip("LOT 참조 또는 판정 없음")
        return
    rejected = None
    with step("EFF-JDG-03", "EFF", "판정 전달(인벤토리 apply_incoming_judgment)") as s:
        try:
            adapter.judge_incoming_lot(
                lot_id=ref["lot_id"],
                result=verdict,
                staff_id=actor_id,
                document_id=document_id,
                judged_at=judged_at,
                reason=reason,
            )
        except adapter.Rejected as error:
            rejected = error
            s.note(f"거부: {error}")
    with step("EFF-JDG-04", "EFF", "결과") as s:
        if rejected is not None:
            s.fail("INVENTORY_REJECTED → 작성완료 롤백")
            message = str(rejected)
            raise errors.InventoryRejected(
                message,
                details=[
                    {
                        "path": "inventory",
                        "code": "rejected",
                        "lot_id": ref["lot_id"],
                        "lot_number": ref["label"],
                        "message": message,
                    }
                ],
            )
