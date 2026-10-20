"""작성 요구(REQ) 외부 함수 F01~F04 (dev-notes/doc-requirements/s2-spec.md 2장, s2-flows.md).

- REQ는 테이블이 없다. 결과는 DOC(N1~N3)로 DOC 테이블에 남긴다.
- 계층(NFR-03): DOC·APR 서비스와 staff 서비스만 부른다. 수불·생산 값은 sources(뷰)로만 읽는다.
- 트랜잭션(D-050 Q5): F01·F02는 호출자 트랜잭션 안에서만 동작하고, 실패하면 예외를 그대로 올린다
  (롤백은 호출자). 호출자는 자기 쓰기를 먼저 한 뒤 부른다 — 재호출도 같다(2.1, REQ-S2-Q13).
"""

from django.db import transaction
from django.utils import timezone

from apps.approvals import services as apr
from apps.core.trace import step
from apps.documents import services as doc
from apps.staff import roles
from apps.staff import services as staff_services

from . import errors, rules, sources

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
    # 입고 건이 없는 LOT(기초재고 등) — 수불 뷰는 모든 LOT을 보여 준다(C3)
    if lot["received_date"] is None:
        raise errors.LotNotFound()
    return lot


def _info(type_code, lot, day):
    """문서 머리(info) 초기값. D03 v2는 v1 LOT 행의 입고 정보 7개를 그대로 가진다(P6a-S2 3.1)."""
    values = {
        "lot_number": lot["lot_number"],
        "item_name": lot["item_name"],
        "supplier_name": lot["supplier_name"],
        "received_date": day,
    }
    if type_code == rules.D03:
        values |= {
            "material_kind": lot["material_kind"],
            "quantity": _quantity(lot),
            "expiration_date": _text(lot["expiration_date"]),
        }
    return _drop_empty(values)


def _check_inspection(inspection):
    """REQ-LOT-00b: inspection 형식(P6-VR-07). 객체, 키는 D03 검사 항목만, 필수 4개."""
    if not isinstance(inspection, dict):
        raise errors.ValidationFailed(
            details=[{"path": "inspection", "code": "invalid", "message": "객체여야 합니다."}]
        )
    problems = [
        {"path": f"inspection.{key}", "code": "unknown", "message": "알 수 없는 항목입니다."}
        for key in inspection
        if key not in rules.D03_INSPECTION_KEYS
    ]
    problems += [
        {"path": f"inspection.{key}", "code": "required", "message": "필수 항목입니다."}
        for key in rules.D03_INSPECTION_REQUIRED
        if inspection.get(key) in (None, "")
    ]
    if problems:
        raise errors.ValidationFailed(details=problems)
    return dict(inspection)


def require_for_lot(actor_id, lot_id, inspection=None):
    """F01: 원료 입고 LOT의 D01·D02·D03(LOT마다 1건, P6a — D-084)(REQ-LOT).

    inspection(D-080): 수불 입고 화면에서 육안검사까지 입력한 값. D03을 **새로 만들 때만**
    inspection 섹션에 채운다(이미 있으면 덮지 않음 — inspection_applied false). 문서는 작성중
    그대로이고, REQ는 인벤토리를 부르지 않는다(입고 때 판정 반영은 수불이 직접).
    """
    with step("REQ-LOT-00", "REQ", "트랜잭션·입력 확인"):
        _require_transaction()
        _check_id("lot_id", lot_id)
        _check_actor(actor_id)
    if inspection is not None:
        with step("REQ-LOT-00b", "REQ", "inspection 형식 검사"):
            inspection = _check_inspection(inspection)
    with step("REQ-LOT-01", "REQ", "입고 뷰 읽기"):
        lot = _incoming(lot_id)
    day = _text(lot["received_date"])
    refs = [{"lot_id": lot_id, "label": lot["lot_number"]}]
    documents = []
    for n, type_code in enumerate(rules.LOT_DOCUMENTS, start=2):
        with step(f"REQ-LOT-0{n}", "REQ", f"{type_code} 찾기/만들기(N1)"):
            values = {"info": _info(type_code, lot, day)}
            if type_code == rules.D03 and inspection is not None:
                values[rules.D03_INSPECTION] = inspection  # 값은 N1(DOC-GOC-02)이 양식 규칙으로
            out = doc.get_or_create_document(
                actor_id,
                type_code,
                rules.lot_key(type_code, lot_id),
                day,
                refs,
                values,
            )
            extra = {}
            if type_code == rules.D03:
                # 이미 있던 D03은 N1이 values를 쓰지 않는다 → 덮어쓰지 않음(FR-22)
                extra["inspection_applied"] = inspection is not None and out["created"]
            documents.append(
                _item(
                    type_code,
                    out["document"],
                    "created" if out["created"] else "existing",
                    **extra,
                )
            )
    with step("REQ-LOT-06", "REQ", "결과"):
        return {"lot_id": lot_id, "documents": documents}


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


def _approved_verdict(approved, type_code):
    """D03 승인본 스냅샷의 검사 섹션 최종판정(P6a-S2 3.2). 다른 양식은 None."""
    if approved is None or type_code != rules.D03:
        return None
    for row in (approved.get("snapshot") or {}).get("sections", []):
        if row.get("section_def") == rules.D03_INSPECTION:
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
                    "approved": None
                    if approved is None
                    else {k: approved[k] for k in ("request_id", "attempt", "closed_at")},
                    "verdict": _approved_verdict(approved, ref["type_code"]),
                    # P6-FR-14: 열린 정정 여부·사유(N3). 판정은 계속 유효 승인본 기준
                    "correcting": ref["correcting"],
                    "correction_reason": ref["correction_reason"],
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


# ---------------------------------------------------------------- F05 incoming_bundle (P7)


def _submit_check(actor_id, type_code, status, line):
    """P14 묶음 문서별 상신 가능 여부(DR-12 S1-Q7). 반환 (can_submit, submit_block)."""
    if line["reason"] == "config_invalid":
        return False, "config_invalid"
    if not roles.can_submit(actor_id, type_code):  # ROLE-R01: 담당자·작성 권한자·팀장(DR-20)
        return False, "role_required"
    if not line["ok"]:
        return False, line["reason"]
    if status not in doc.SUBMITTABLE:
        return False, "status"
    return True, None


def _my_slots(progress):
    return [] if progress is None else progress["my_slots"]


def _bundle_document(brief, approved, progress, submit=(False, None)):
    """LOT 줄의 문서 값(p7-s2-spec 3.4). 승인본 판정은 F03과 같은 규칙(_approved_verdict)."""
    return {
        "document_id": brief["document_id"],
        "status": brief["status"],
        "version": brief["version"],
        "correcting": brief["correcting"],
        "inspector_id": brief["inspector_id"],
        "verdict": brief["verdict"],
        "nonconforming": brief["nonconforming"],
        "approved": None
        if approved is None
        else {k: approved[k] for k in ("request_id", "attempt", "closed_at")},
        "approved_verdict": _approved_verdict(approved, rules.D03),
        "progress": None
        if progress is None
        else {
            k: progress[k]
            for k in ("request_id", "attempt", "status", "total", "approved", "pending")
        },
        "my_slots": _my_slots(progress),  # P14: 내 칸이 2개일 수 있음(DR-05)
        "can_submit": submit[0],
        "submit_block": submit[1],
    }


@roles.scope()
def incoming_bundle(actor_id, received_date):
    """F05: 입고일 묶음 조회(REQ-BDL). 그날 입고 LOT 전부 + LOT별 D03 + 판정·결재 진행·내 칸.

    쓰기·트랜잭션 없음. SQL 8 이하(뷰 1 · N4 1 · F26 3 · A8 1 · A10 2). received_date는 API가
    YYYY-MM-DD로 확인한 문자열.
    """
    with step("REQ-BDL-02", "REQ", "입고 뷰(그날 입고 LOT)"):
        lots = sources.incoming_lots_on(received_date)
    with step("REQ-BDL-03", "REQ", "LOT별 D03(DOC N4)") as s:
        by_lot = {}
        if lots:
            for row in doc.find_documents_by_lots([lot["lot_id"] for lot in lots], [rules.D03]):
                by_lot.setdefault(row["lot_id"], row["document_id"])
        else:
            s.skip("입고 LOT 없음")
    document_ids = list(dict.fromkeys(by_lot.values()))
    with step("REQ-BDL-04", "REQ", "문서 요약(DOC F26)") as s:
        briefs = {}
        if document_ids:
            briefs = {b["document_id"]: b for b in doc.brief_documents(document_ids)["items"]}
        else:
            s.skip("문서 없음")
    with step("REQ-BDL-05", "REQ", "최신 승인 회차(APR A8)") as s:
        latest = apr.latest_approved(document_ids) if document_ids else {}
        if not document_ids:
            s.skip("문서 없음")
    with step("REQ-BDL-06", "REQ", "결재 진행·내 칸(APR A10)") as s:
        progress = {"documents": {}}
        if document_ids:
            progress = apr.document_progress(document_ids, actor_id)
        else:
            s.skip("문서 없음")
    with step("REQ-BDL-07", "REQ", "조립"):
        line = roles.approval_line(rules.D03)  # P14: 묶음 결재선 요약(일괄 상신 모달)
        rows, status_counts, correcting, mine = [], {}, 0, 0
        for lot in lots:
            brief = briefs.get(by_lot.get(lot["lot_id"]))
            document = None
            if brief is not None:
                document = _bundle_document(
                    brief,
                    latest.get(brief["document_id"]),
                    progress["documents"].get(brief["document_id"]),
                    _submit_check(actor_id, rules.D03, brief["status"], line),
                )
                status_counts[brief["status"]] = status_counts.get(brief["status"], 0) + 1
                correcting += brief["correcting"]
                mine += bool(document["my_slots"])
            rows.append(
                {
                    "lot_id": lot["lot_id"],
                    "lot_number": lot["lot_number"],
                    "item_name": lot["item_name"],
                    "supplier_name": lot["supplier_name"],
                    "material_kind": lot["material_kind"],
                    "quantity": _quantity(lot),
                    "expiration_date": _text(lot["expiration_date"]),
                    "document": document,
                }
            )
        return {
            "received_date": received_date,
            "lots": rows,
            "summary": {
                "documents": len(briefs),
                "status_counts": status_counts,
                "correcting_count": correcting,
                "my_pending": mine,
            },
            "approval_line": line,
        }


# ---------------------------------------------------------------- P8 REQ-F06 주 묶음 조회


def _week_document(brief, progress, submit=(False, None)):
    """하루 칸의 문서 값(P7 _bundle_document와 같은 조립 — 승인본 판정 대신 점검 결과 수)."""
    return {
        "document_id": brief["document_id"],
        "status": brief["status"],
        "version": brief["version"],
        "correcting": brief["correcting"],
        "inspector_id": brief["inspector_id"],
        "nonconforming": brief["nonconforming"],
        "check_counts": brief["check_counts"],
        "progress": None
        if progress is None
        else {
            k: progress[k]
            for k in ("request_id", "attempt", "status", "total", "approved", "pending")
        },
        "my_slots": _my_slots(progress),  # P14: 내 칸이 2개일 수 있음(DR-05)
        "can_submit": submit[0],
        "submit_block": submit[1],
    }


@roles.scope()
def periodic_bundle(actor_id, type_code, week_start):
    """F06: 주 묶음 조회(REQ-PWB). 그 주 월~금 하루 문서(없는 날 null) + 요약·결재 진행·내 칸.

    쓰기·트랜잭션 없음. SQL 7 이하(DOC N10 1 · F26 3 · A10 2 — 문서 없으면 1).
    week_start는 API가 YYYY-MM-DD로 확인한 date. 주말 문서는 칸 밖이라 weekend에 따로 싣는다.
    """
    with step("REQ-PWB-02", "REQ", "양식·월요일 확인"):
        problems = []
        if type_code not in rules.WEEK_BUNDLE_TYPES:
            problems.append(
                {
                    "path": "type_code",
                    "code": "invalid",
                    "message": f"주 묶음 양식({'·'.join(rules.WEEK_BUNDLE_TYPES)})이 아닙니다.",
                }
            )
        if week_start.isoweekday() != 1:
            problems.append(
                {"path": "week_start", "code": "not_monday", "message": "월요일이어야 합니다."}
            )
        if problems:
            raise errors.ValidationFailed(details=problems)
    days = [week_start.fromordinal(week_start.toordinal() + n) for n in range(7)]  # 월~일
    with step("REQ-PWB-03", "REQ", "그 주 문서(DOC N10)"):
        found = doc.documents_on_dates([type_code], days[0], days[-1])
        by_day = {}
        for row in found:
            by_day.setdefault(row["work_date"], row["document_id"])  # 같은 날 여럿이면 앞 id
    document_ids = list(by_day.values())
    with step("REQ-PWB-04", "REQ", "문서 요약(DOC F26)") as s:
        briefs = {}
        if document_ids:
            briefs = {b["document_id"]: b for b in doc.brief_documents(document_ids)["items"]}
        else:
            s.skip("문서 없음")
    with step("REQ-PWB-05", "REQ", "결재 진행·내 칸(APR A10)") as s:
        progress = {"documents": {}}
        if document_ids:
            progress = apr.document_progress(document_ids, actor_id)
        else:
            s.skip("문서 없음")
    with step("REQ-PWB-06", "REQ", "조립"):
        line = roles.approval_line(type_code)  # P14: 묶음 결재선 요약(일괄 상신 모달)
        cells, weekend, status_counts, correcting, mine = [], [], {}, 0, 0
        for day in days:
            key = day.isoformat()
            brief = briefs.get(by_day.get(key))
            document = None
            if brief is not None:
                document = _week_document(
                    brief,
                    progress["documents"].get(brief["document_id"]),
                    _submit_check(actor_id, type_code, brief["status"], line),
                )
                status_counts[brief["status"]] = status_counts.get(brief["status"], 0) + 1
                correcting += brief["correcting"]
                mine += bool(document["my_slots"])
            cell = {"work_date": key, "weekday": day.isoweekday(), "document": document}
            if day.isoweekday() <= 5:
                cells.append(cell)
            elif document is not None:
                weekend.append(cell)
        return {
            "type_code": type_code,
            "week_start": days[0].isoformat(),
            "week_end": days[4].isoformat(),
            "days": cells,
            "weekend": weekend,
            "summary": {
                "documents": len(briefs),
                "status_counts": status_counts,
                "correcting_count": correcting,
                "my_pending": mine,
            },
            "approval_line": line,
        }
