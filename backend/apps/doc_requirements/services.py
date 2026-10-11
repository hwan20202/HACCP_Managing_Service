"""작성 요구(REQ) 외부 함수 F01~F04 (dev-notes/doc-requirements/s2-spec.md 2장, s2-flows.md).

- REQ는 테이블이 없다. 결과는 DOC(N1~N3)로 DOC 테이블에 남긴다.
- 계층(NFR-03): DOC·APR 서비스와 staff 서비스만 부른다. 수불·생산 값은 sources(뷰)로만 읽는다.
- 트랜잭션(D-050 Q5): F01·F02는 호출자 트랜잭션 안에서만 동작하고, 실패하면 예외를 그대로 올린다
  (롤백은 호출자). 호출자는 자기 쓰기를 먼저 한 뒤 부른다 — 재호출도 같다(2.1, REQ-S2-Q13).
"""

from django.db import transaction
from django.utils import timezone

from apps.approvals import services as apr
from apps.core.http import ApiError
from apps.core.trace import step
from apps.documents import services as doc
from apps.staff import services as staff_services

from . import errors, rules, sources

DOCUMENT_LOCKED = "DOCUMENT_LOCKED"  # DOC N2가 내는 코드 — 다음 번호 판단에만 쓴다(s2-flows 3장)


# ---------------------------------------------------------------- 공통 확인


def _require_transaction():
    if not transaction.get_connection().in_atomic_block:
        raise errors.TransactionRequired()


def _check_id(name, value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise errors.ValidationFailed(
            details=[{"path": name, "code": "invalid", "message": "1 이상 정수입니다."}]
        )


def _check_actor(actor_id):
    if not staff_services.existing_ids([actor_id]):
        raise staff_services.InvalidStaff()


def _text(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _quantity(lot):
    if lot["quantity"] is None:
        return None
    return f"{lot['quantity']:g}{lot['unit'] or ''}"


def _drop_empty(values):
    return {k: v for k, v in values.items() if v is not None}


def _item(type_code, document, result, **extra):
    return {
        "type_code": type_code,
        "document_id": document["document_id"],
        "record_key": document["record_key"],
        "result": result,
        **extra,
    }


# ---------------------------------------------------------------- F01 require_for_lot


def _incoming(lot_id):
    lot = sources.incoming_lot(lot_id)
    if lot is None:
        raise errors.LotNotFound()
    if lot["lot_kind"] != rules.INCOMING:
        raise errors.LotNotIncoming()
    return lot


def require_for_lot(actor_id, lot_id):
    """F01: 원료 입고 LOT의 D01·D02와 입고일 육안검사(D03) LOT 행(REQ-LOT)."""
    with step("REQ-LOT-00", "REQ", "트랜잭션·입력 확인"):
        _require_transaction()
        _check_id("lot_id", lot_id)
        _check_actor(actor_id)
    with step("REQ-LOT-01", "REQ", "입고 뷰 읽기"):
        lot = _incoming(lot_id)
    day = _text(lot["received_date"])
    refs = [{"lot_id": lot_id, "label": lot["lot_number"]}]
    info = _drop_empty(
        {
            "lot_number": lot["lot_number"],
            "item_name": lot["item_name"],
            "supplier_name": lot["supplier_name"],
            "received_date": day,
        }
    )
    documents = []
    for n, type_code in enumerate(rules.LOT_DOCUMENTS, start=2):
        with step(f"REQ-LOT-0{n}", "REQ", f"{type_code} 찾기/만들기(N1)"):
            out = doc.get_or_create_document(
                actor_id, type_code, rules.lot_key(type_code, lot_id), day, refs, {"info": info}
            )
            documents.append(
                _item(type_code, out["document"], "created" if out["created"] else "existing")
            )
    with step("REQ-LOT-04", "REQ", "D03 기존 행 찾기(N3)"):
        found = next(
            (
                d
                for d in doc.find_documents_by_ref(lot_id=lot_id)
                if d["type_code"] == rules.D03 and d["section_id"] is not None
            ),
            None,
        )
    with step("REQ-LOT-05", "REQ", "D03 문서·행(번호 반복)") as s:
        if found is not None:
            s.skip("이 LOT 행이 이미 있음")
            existing = doc.get_document(found["document_id"])
            documents.append(
                _item(
                    rules.D03,
                    existing,
                    "row_existing",
                    document_result="existing",
                    section_id=found["section_id"],
                )
            )
        else:
            documents.append(_add_d03_row(actor_id, lot, day, refs))
    with step("REQ-LOT-06", "REQ", "결과"):
        return {"lot_id": lot_id, "documents": documents}


def _add_d03_row(actor_id, lot, day, refs):
    row = _drop_empty(
        {
            "lot_number": lot["lot_number"],
            "received_date": day,
            "supplier_name": lot["supplier_name"],
            "material_kind": lot["material_kind"],
            "item_name": lot["item_name"],
            "quantity": _quantity(lot),
            "expiration_date": _text(lot["expiration_date"]),
        }
    )
    for n in range(1, rules.D03_LIMIT + 1):
        out = doc.get_or_create_document(actor_id, rules.D03, rules.d03_key(day, n), day, [])
        document = out["document"]
        try:
            added = doc.add_ref_row(
                actor_id, document["document_id"], rules.D03_SECTION, row, refs, "lot_id"
            )
        except ApiError as error:
            if error.code == DOCUMENT_LOCKED:
                continue  # 그날 #n이 작성완료·결재중·승인 → 다음 번호(REQ-S2-Q2)
            raise
        return _item(
            rules.D03,
            document,
            "row_added" if added["created"] else "row_existing",
            document_result="created" if out["created"] else "existing",
            section_id=added["section_id"],
        )
    raise errors.RequirementLimit()


# ---------------------------------------------------------------- F02 require_for_batch


def _batch(batch_id):
    batch = sources.batch(batch_id)
    if batch is None:
        raise errors.BatchNotFound()
    return batch


def require_for_batch(actor_id, batch_id):
    """F02: 생산 배치의 CCP 공정마다 CCP 일지(REQ-BAT)."""
    with step("REQ-BAT-00", "REQ", "트랜잭션·입력 확인"):
        _require_transaction()
        _check_id("batch_id", batch_id)
        _check_actor(actor_id)
    with step("REQ-BAT-01", "REQ", "배치 뷰 읽기"):
        batch = _batch(batch_id)
        if batch["status"] == rules.CANCELLED:
            raise errors.BatchCancelled()
    with step("REQ-BAT-02", "REQ", "CCP 공정 목록(코드 상수)") as s:
        processes = rules.processes_for(batch["item_id"], batch["process_type"])
        s.note(",".join(processes) or "없음")
    day = _text(batch["manufactured_date"]) or timezone.localdate().isoformat()
    info = _drop_empty({"item_name": batch["item_name"], "batch_qty_kg": batch["quantity_kg"]})
    documents = []
    for process in processes:
        with step("REQ-BAT-03", "REQ", f"CCP-{process} 찾기/만들기(N1)"):
            refs = [
                {
                    "production_batch_id": batch_id,
                    "process_code": process,
                    "label": batch["batch_number"],
                }
            ]
            out = doc.get_or_create_document(
                actor_id,
                rules.ccp_type(process),
                rules.ccp_key(process, batch_id),
                day,
                refs,
                {"info": info},
            )
            documents.append(
                _item(
                    rules.ccp_type(process),
                    out["document"],
                    "created" if out["created"] else "existing",
                    process_code=process,
                )
            )
    if not processes:
        with step("REQ-BAT-03", "REQ", "CCP 공정 없음") as s:
            s.skip("요구되는 CCP 문서 없음")
    with step("REQ-BAT-04", "REQ", "결과"):
        return {"production_batch_id": batch_id, "documents": documents}


# ---------------------------------------------------------------- F03 docs_for_lot


def _approved_verdict(approved, section_id):
    if approved is None or section_id is None:
        return None
    for row in (approved.get("snapshot") or {}).get("sections", []):
        if row.get("section_id") == section_id:
            return (row.get("values") or {}).get("verdict")
    return None


def docs_for_lot(lot_id):
    """F03: LOT에 연결된 문서·상태·최신 승인본 기준 판정(REQ-FND). SQL 4개 이하(NFR-05)."""
    with step("REQ-FND-01", "REQ", "입고 뷰로 LOT 확인·머리 값"):
        _check_id("lot_id", lot_id)
        lot = _incoming(lot_id)
    with step("REQ-FND-02", "REQ", "연결 문서(N3)"):
        refs = doc.find_documents_by_ref(lot_id=lot_id)
    with step("REQ-FND-03", "REQ", "최신 승인 회차(APR A8)"):
        latest = apr.latest_approved([r["document_id"] for r in refs])
    with step("REQ-FND-04", "REQ", "승인본 기준 판정 조립"):
        documents = []
        for ref in refs:
            approved = latest.get(ref["document_id"])
            documents.append(
                {
                    "document_id": ref["document_id"],
                    "type_code": ref["type_code"],
                    "status": ref["status"],
                    "version": ref["version"],
                    "section_id": ref["section_id"],
                    "approved": None
                    if approved is None
                    else {k: approved[k] for k in ("request_id", "attempt", "closed_at")},
                    "verdict": _approved_verdict(approved, ref["section_id"]),
                    "correcting": False,  # 정정중은 P6
                }
            )
        return {
            "lot_id": lot_id,
            "lot": {
                "lot_number": lot["lot_number"],
                "item_name": lot["item_name"],
                "supplier_name": lot["supplier_name"],
                "received_date": _text(lot["received_date"]),
            },
            "documents": documents,
        }


# ---------------------------------------------------------------- F04 docs_for_batch


def docs_for_batch(batch_id):
    """F04: 배치에 연결된 CCP 문서와 상태(REQ-FND-B). 승인본 판정은 P6 범위 밖."""
    with step("REQ-FND-B01", "REQ", "배치 뷰로 배치 확인·머리 값"):
        _check_id("batch_id", batch_id)
        batch = _batch(batch_id)
    with step("REQ-FND-B02", "REQ", "연결 문서(N3) + 공정 코드"):
        refs = doc.find_documents_by_ref(production_batch_id=batch_id)
        seen, documents = set(), []
        for ref in refs:
            if ref["document_id"] in seen:
                continue
            seen.add(ref["document_id"])
            documents.append(
                {
                    "document_id": ref["document_id"],
                    "type_code": ref["type_code"],
                    "process_code": rules.process_of(ref["type_code"]),
                    "status": ref["status"],
                    "version": ref["version"],
                }
            )
        return {
            "production_batch_id": batch_id,
            "batch": {
                "batch_number": batch["batch_number"],
                "item_name": batch["item_name"],
                "process_type": batch["process_type"],
                "manufactured_date": _text(batch["manufactured_date"]),
            },
            "documents": documents,
        }
