"""작성 요구(REQ) 외부 함수 F01~F04 (dev-notes/doc-requirements/s2-spec.md 2장, s2-flows.md).

- REQ는 테이블이 없다. 결과는 DOC(N1~N3)로 DOC 테이블에 남긴다.
- 계층(NFR-03): DOC·APR 서비스와 staff 서비스만 부른다. 수불·생산 값은 sources(뷰)로만 읽는다.
- 트랜잭션(D-050 Q5): F01·F02는 호출자 트랜잭션 안에서만 동작하고, 실패하면 예외를 그대로 올린다
  (롤백은 호출자). 호출자는 자기 쓰기를 먼저 한 뒤 부른다 — 재호출도 같다(2.1, REQ-S2-Q13).
"""

from django.db import transaction
from django.utils import timezone

from apps.admin_settings import store as adm_store
from apps.approvals import services as apr
from apps.core.http import ApiError
from apps.core.trace import step
from apps.documents import services as doc
from apps.staff import roles
from apps.staff import services as staff_services

from . import ccp, errors, rules, sources

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


def _incoming(lot_id, allow_cancelled=False):
    lot = sources.incoming_lot(lot_id)
    if lot is None:
        raise errors.LotNotFound()
    # D-178: 입고가 취소된(소프트 딜리트) LOT은 없는 LOT과 같게 — F01·F03. F12(연쇄 삭제)만 허용
    if not allow_cancelled and lot.get("receipt_status") == rules.RECEIPT_CANCELLED:
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
    # D-234 r1: 성적서 유무는 시스템 계산(같은 LOT D01 파일) — 입고 값은 받되 쓰지 않는다
    return {k: v for k, v in inspection.items() if k != "has_coa"}


def _complete_pass(actor_id, document):
    """D-233 Q3 b: 입고 때 판정 적합으로 새로 만든 D03은 바로 작성완료(DOC A09).

    작성완료 신호로 EFF가 판정을 수불(apply_incoming_judgment)에 넘긴다
    — D-080 "작성중 그대로·REQ는 인벤토리를 부르지 않음"을 바꿈.
    작성완료가 도메인 오류(ApiError: 작성완료 검사·권한·수불 거부)로 막히면 세이브포인트만
    되돌리고 작성중 그대로 둔다(Q3-2 a — 입고는 계속). 반환 (완료 여부, 오류 코드).
    """
    with step("REQ-LOT-04b", "REQ", "적합 D03 작성완료(DOC A09 → EFF 판정 전달)") as s:
        try:
            with transaction.atomic():
                doc.complete_document(actor_id, document["document_id"], document["version"])
        except ApiError as error:
            s.note(f"작성완료 안 됨 — 작성중 유지: {error.code}")
            return False, error.code
        return True, None


def require_for_lot(actor_id, lot_id, inspection=None):
    """F01: 원료 입고 LOT의 D01·D02·D03(LOT마다 1건, P6a — D-084)(REQ-LOT).

    inspection(D-080): 수불 입고 화면에서 육안검사까지 입력한 값. D03을 **새로 만들 때만**
    inspection 섹션에 채운다(이미 있으면 덮지 않음 — inspection_applied false).
    D-233: 새 D03 점검자 = actor(입고 담당자). 최종판정이 PASS면 바로 작성완료(auto_completed),
    작성완료 신호로 판정이 수불에 전달된다(D-080 "작성중 그대로" 변경). 막히면 작성중 그대로
    (completion_error). PASS가 아니면 작성중 그대로.
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
            if type_code == rules.D03:
                # D-233 Q1 b·Q2 a: 입고 담당자(actor)를 점검자로 — 새 D03에만
                # (N1은 기존 문서를 안 씀). 점검자 지정 권한(ROLE-R08)은 입고 자동 채움에
                # 묻지 않는다(입고 담당자가 직접 검사)
                values["info"]["inspector"] = actor_id
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
                if extra["inspection_applied"] and inspection.get("verdict") == "PASS":
                    done, code = _complete_pass(actor_id, out["document"])
                    extra["auto_completed"] = done
                    if code:
                        extra["completion_error"] = code
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
    with step("REQ-BAT-02", "REQ", "CCP 공정 목록(ADM 적용 기록 — 처음이면 결정·기록)") as s:
        # P16 ADM-F01: 기록 있으면 그대로(R06 — [다시 호출]도 설정을 다시 읽지 않음),
        # 없으면 품목 설정 → 공정 구분 기본으로 정해 기록(R05). 이 트랜잭션 안에서 기록.
        processes = adm_store.ccp_for_batch(batch_id, batch["item_id"], batch["process_type"])
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
    with step("REQ-BAT-05", "REQ", "제조 배치면 생산일지(P15)") as s:
        make_log = batch["process_type"] == rules.PROD_LOG_PROCESS_TYPE
        if not make_log:
            s.skip(f"제조 배치 아님({batch['process_type']})")
    if make_log:
        with step("REQ-BAT-06", "REQ", "생산일지 찾기/만들기(N1, PLG-R01)") as s:
            label = " · ".join(p for p in (batch["batch_number"], batch["item_name"]) if p)[:100]
            refs = [{"production_batch_id": batch_id, "item_id": batch["item_id"], "label": label}]
            try:
                out = doc.get_or_create_document(
                    actor_id, rules.PROD_LOG, rules.prod_log_key(batch_id), day, refs
                )
            except ApiError as error:
                # S4b 결정 a: 생산일지 양식을 설치하지 않은 DB(수불 테스트·QA 시드)는 건너뜀
                if error.code not in ("TEMPLATE_NOT_FOUND", "TEMPLATE_INACTIVE"):
                    raise
                s.skip(f"생산일지 양식 없음({error.code})")
            else:
                documents.append(
                    _item(
                        rules.PROD_LOG,
                        out["document"],
                        "created" if out["created"] else "existing",
                        process_code=None,
                    )
                )
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


# ---------------------------------------------------------------- F12 delete_lot_documents (D-178)


def delete_lot_documents(actor_id, lot_id):
    """F12: 입고 취소 때 그 LOT의 입고 서류(D01·D02·D03)를 함께 소프트 딜리트(REQ-DEL).

    수불 훅 incoming_receipt_cancelled가 수불 트랜잭션 안에서 부른다(D-178 Q3 — 연결은 수불 쪽).
    "상신 이력 있으면 삭제 불가"(D-017·D-021)·"작성 요구 문서 삭제 불가"(C-3)의 예외(D-178):
    결재 중·승인·정정 중 문서도 지운다 — 진행 중 결재 회차는 닫고(APR A13) 열린 정정도 닫는다
    (DOC N10). 결재 회차·승인 기록·스냅샷은 남긴다. LOT 입고 상태는 보지 않는다(Q2 b).
    이미 지운 문서는 건너뛴다 — 두 번 불러도 결과가 같다.
    """
    with step("REQ-DEL-00", "REQ", "트랜잭션·입력 확인"):
        _require_transaction()
        _check_id("lot_id", lot_id)
        _check_actor(actor_id)
    with step("REQ-DEL-01", "REQ", "입고 뷰로 LOT 확인(취소 LOT 포함)"):
        lot = _incoming(lot_id, allow_cancelled=True)
    with step("REQ-DEL-02", "REQ", "연결 문서(N3)") as s:
        refs = doc.find_documents_by_ref(lot_id=lot_id)
        found = {}
        for ref in refs:
            found.setdefault(ref["document_id"], ref)
        ids = list(found)
        s.note(f"문서 {len(ids)}건")
    with step("REQ-DEL-03", "REQ", "진행 중 결재 회차 닫기(APR A13)") as s:
        closed_requests = apr.close_open_requests(ids) if ids else 0
        if not ids:
            s.skip("문서 없음")
    with step("REQ-DEL-04", "REQ", "문서 소프트 딜리트(DOC N10)") as s:
        removed = {"deleted": [], "closed_corrections": 0}
        if ids:
            removed = doc.delete_source_documents(actor_id, ids)
        else:
            s.skip("문서 없음")
    deleted = set(removed["deleted"])
    return {
        "lot_id": lot_id,
        "lot": {"lot_number": lot["lot_number"], "receipt_status": lot.get("receipt_status")},
        "documents": [
            {
                "document_id": i,
                "type_code": found[i]["type_code"],
                "status": found[i]["status"],  # 지우기 전 상태
                "result": "deleted" if i in deleted else "already_deleted",
            }
            for i in ids
        ],
        "closed_requests": closed_requests,
        "closed_corrections": removed["closed_corrections"],
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
        # P15: 생산일지를 맨 앞으로(나머지 순서 그대로 — 안정 정렬)
        documents.sort(key=lambda d: d["type_code"] != rules.PROD_LOG)
    with step("REQ-FND-B03", "REQ", "CCP 측정 요약(DOC N8, P11 S5 r2)") as s:
        # 생산 화면 [연결 문서]의 줄마다 최근 측정·이탈·개선조치 상태(D-176). 문서 없으면 건너뜀
        if documents:
            summaries = ccp.document_summaries(
                _text(batch["manufactured_date"]), [d["document_id"] for d in documents]
            )
            for d in documents:
                d["summary"] = summaries.get(d["document_id"])  # 생산일지는 None(CCP 아님)
        else:
            s.skip("연결 문서 없음")
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
    """P14 묶음 문서별 상신 가능 여부(D-190 S1-Q7). 반환 (can_submit, submit_block)."""
    if not roles.can_submit(actor_id, type_code):  # ROLE-R01: 담당자·작성 권한자·팀장(D-198)
        return False, "role_required"
    if not line["ok"]:
        return False, line["reason"]
    if status not in doc.SUBMITTABLE:
        return False, "status"
    return True, None


def _my_slots(progress):
    return [] if progress is None else progress["my_slots"]


def _write_check(actor_id, type_code, brief):
    """P14 r13 묶음 문서별 작성 가능(ROLE-R07, 상태 무관 — 점검자는 문서마다 다름)."""
    return roles.can_write(actor_id, type_code, brief["inspector_id"])


def _bundle_permissions(actor_id, type_code):
    """P14 r13 묶음 권한(묶음은 한 양식): 점검자 지정(ROLE-R08)."""
    return {
        "assign_inspector": type_code in doc.INSPECTOR_TYPES
        and roles.can_assign_inspector(actor_id, type_code)
    }


def _bundle_document(brief, approved, progress, submit=(False, None), can_write=False):
    """LOT 줄의 문서 값(p7-s2-spec 3.4). 승인본 판정은 F03과 같은 규칙(_approved_verdict)."""
    return {
        "document_id": brief["document_id"],
        "status": brief["status"],
        "version": brief["version"],
        "correcting": brief["correcting"],
        "inspector_id": brief["inspector_id"],
        "verdict": brief["verdict"],
        "nonconforming": brief["nonconforming"],
        "inspection": brief["verdict_values"] or {},  # D-232: 검사 항목(외관·포장·표시·성적서)
        # D-234: 계산으로 채운 키(성적서 유무 — 저장 값 없음, 같은 LOT D01 파일 기준)
        "inspection_derived": brief["verdict_derived"],
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
        "my_slots": _my_slots(progress),  # P14: 내 칸이 2개일 수 있음(D-183)
        "can_submit": submit[0],
        "submit_block": submit[1],
        "can_write": can_write,  # r13 ROLE-R07
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
                    _write_check(actor_id, rules.D03, brief),
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
            "permissions": _bundle_permissions(actor_id, rules.D03),  # r13 ROLE-R08
        }


# ---------------------------------------------------------------- P8 REQ-F06 주 묶음 조회


def _week_document(brief, progress, submit=(False, None), can_write=False):
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
        "my_slots": _my_slots(progress),  # P14: 내 칸이 2개일 수 있음(D-183)
        "can_submit": submit[0],
        "submit_block": submit[1],
        "can_write": can_write,  # r13 ROLE-R07
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
                    _write_check(actor_id, type_code, brief),
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
            "permissions": _bundle_permissions(actor_id, type_code),  # r13 ROLE-R08
        }


# ---------------------------------------------------------------- F13 생산일지 연동 데이터 (P15)


def production_log_source(batch_id):
    """F13(p15-s2-spec 3.2·4.3): 수불 0009 뷰 3개를 읽기만 한다(비율·환산은 PLG가 계산). SQL 3.

    배치가 없으면 404 BATCH_NOT_FOUND, 뷰가 없으면 SourceUnavailable(PLG가 연동 오류로 표시).
    """
    with step("REQ-PLS-01", "REQ", "배치·BOM 줄·투입(뷰 3개)"):
        _check_id("batch_id", batch_id)
        batch = sources.prod_log_batch(batch_id)
        if batch is None:
            raise errors.BatchNotFound()
        return {
            "batch": batch,
            "materials": sources.batch_bom_lines(batch_id),
            "usages": sources.batch_usages(batch_id),
        }


def production_batch_state(batch_id, with_lines=False):
    """P15 S4b r1(B1)·r2(A2): 생산일지 쓰기 전 배치 상태(취소 여부)·품목·제조일.

    with_lines면 BOM 줄도 같은 SQL로 읽어 `lines`에 담는다(SQL 1). BOM 줄 뷰(0009)를 못 읽으면
    상태만 다시 읽고 `lines: None`(SQL 2). 상태는 배치 뷰 기본 컬럼이라 0009 없어도 읽힌다.
    배치가 없으면 404, 배치 뷰도 못 읽으면 SourceUnavailable.
    """
    with step("REQ-PLS-02", "REQ", "배치 상태(배치 뷰 기본 컬럼)") as s:
        _check_id("batch_id", batch_id)
        lines = None
        if with_lines:
            try:
                state, lines = sources.batch_state_with_lines(batch_id)
            except errors.SourceUnavailable:
                s.note("BOM 줄 뷰 없음 — 상태만 다시")
                state = sources.batch_state(batch_id)
        else:
            state = sources.batch_state(batch_id)
        if state is None:
            raise errors.BatchNotFound()
        if with_lines:
            state = {**state, "lines": lines}
        return state
