"""결재 도메인 서비스 (approval/s2-spec.md 3.1, 흐름은 s2-flows.md).

- 쓰기 함수(open_request, decide)는 호출자(WF)의 트랜잭션 안에서만 실행한다.
- decide의 첫 쓰기는 슬롯 조건부 UPDATE다.
  동시 처리 시 직렬화되고 "마지막 승인"은 한 요청만 판정한다.
- 이 모듈은 apps.documents, apps.document_workflow를 import하지 않는다.
"""

import datetime

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.core.http import ApiError
from apps.core.trace import step
from apps.staff import services as staff_services

from . import errors
from .models import Approval, ApprovalRequest

MAX_SLOTS = 10
LABEL_MAX = 20
COMMENT_MAX = 500
PAGE_SIZE = 20
MAX_RANGE_DAYS = 366
SLOT_KEYS = {"slot_no", "approver_id", "label"}
REF_KEYS = ("document_id", "version", "template_id", "subject", "work_date")


def _error(path, code, message):
    return {"path": path, "code": code, "message": message}


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "tzinfo"):
        return timezone.localtime(value).isoformat(timespec="seconds")
    return value.isoformat()


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _require_transaction():
    if not transaction.get_connection().in_atomic_block:
        raise errors.TransactionRequired()


# ---------------------------------------------------------------- F01 슬롯 검증


def _check_slot_format(slots):
    """형식 검사(DB 조회 없음). 반환: (정리된 슬롯, 오류 목록)."""
    problems, cleaned = [], []
    if not isinstance(slots, list) or not slots:
        return [], [_error("slots", "required", "결재 칸을 1개 이상 지정하세요.")]
    if len(slots) > MAX_SLOTS:
        problems.append(_error("slots", "max", f"결재 칸은 최대 {MAX_SLOTS}개입니다."))
    seen_no, seen_approver = set(), set()
    for i, slot in enumerate(slots):
        path = f"slots[{i}]"
        if not isinstance(slot, dict):
            problems.append(_error(path, "invalid", "결재 칸은 객체여야 합니다."))
            continue
        for key in sorted(set(slot) - SLOT_KEYS):
            problems.append(_error(f"{path}.{key}", "unknown_key", "허용되지 않은 키입니다."))
        slot_no, approver, label = slot.get("slot_no"), slot.get("approver_id"), slot.get("label")
        if not _is_int(slot_no) or slot_no < 1:
            problems.append(_error(f"{path}.slot_no", "invalid", "칸 번호는 1 이상의 정수입니다."))
        elif slot_no in seen_no:
            problems.append(
                _error(f"{path}.slot_no", "duplicate", f"칸 번호 {slot_no}이(가) 중복됩니다.")
            )
        else:
            seen_no.add(slot_no)
        if not _is_int(approver):
            problems.append(_error(f"{path}.approver_id", "invalid", "결재자는 staff id입니다."))
        elif approver in seen_approver:
            problems.append(
                _error(
                    f"{path}.approver_id", "duplicate", "같은 사람을 두 칸에 배정할 수 없습니다."
                )
            )
        else:
            seen_approver.add(approver)
        if label is not None and not isinstance(label, str):
            problems.append(_error(f"{path}.label", "invalid", "역할 이름은 문자열입니다."))
            label = None
        label = (label or "").strip() or None
        if label and len(label) > LABEL_MAX:
            problems.append(
                _error(f"{path}.label", "max_length", f"역할 이름은 {LABEL_MAX}자 이하입니다.")
            )
        cleaned.append({"slot_no": slot_no, "approver_id": approver, "label": label, "_path": path})
    return cleaned, problems


def _check_slot_staff(cleaned, problems):
    existing = staff_services.existing_ids(s["approver_id"] for s in cleaned)
    for slot in cleaned:
        if _is_int(slot["approver_id"]) and slot["approver_id"] not in existing:
            problems.append(
                _error(
                    f"{slot['_path']}.approver_id", "unknown_staff", "등록되지 않은 사용자입니다."
                )
            )


def _finish_slots(cleaned):
    return [
        {k: v for k, v in s.items() if k != "_path"}
        for s in sorted(cleaned, key=lambda s: s["slot_no"])
    ]


def validate_slots(slots):
    with step("APR-VAL-01", "APR", "슬롯 형식 검사") as s:
        cleaned, problems = _check_slot_format(slots)
        if problems:
            s.fail(f"오류 {len(problems)}건")
            raise errors.InvalidSlots(details=problems)
    with step("APR-VAL-02", "APR", "결재자 존재 확인"):
        _check_slot_staff(cleaned, problems)
        if problems:
            raise errors.InvalidSlots(details=problems)
    with step("APR-VAL-03", "APR", "정리"):
        return _finish_slots(cleaned)


# ---------------------------------------------------------------- 직렬화


def _slot_dict(slot):
    return {
        "approval_id": slot.approval_id,
        "slot_no": slot.slot_no,
        "label": slot.label,
        "approver_id": slot.approver_id,
        "state": slot.state,
        "comment": slot.comment,
        "decided_at": _iso(slot.decided_at),
    }


def _request_dict(req, slots, *, with_snapshot):
    data = {
        "request_id": req.request_id,
        "document_id": req.document_id,
        "attempt": req.attempt,
        "status": req.status,
        "document_version": req.document_version,
        "template_id": req.template_id,
        "subject": req.subject,
        "work_date": _iso(req.work_date),
        "requested_by": req.requested_by_id,
        "requested_at": _iso(req.requested_at),
        "closed_at": _iso(req.closed_at),
        "slots": [_slot_dict(s) for s in sorted(slots, key=lambda s: s.slot_no)],
    }
    if with_snapshot:
        data["snapshot"] = req.snapshot_json
    return data


# ---------------------------------------------------------------- F02 결재 요청 생성


def _as_date(value):
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    try:
        return (
            datetime.date.fromisoformat(value)
            if isinstance(value, str) and len(value) == 10
            else None
        )
    except ValueError:
        return None


def _check_ref(document_ref, snapshot):
    problems = []
    if not isinstance(document_ref, dict):
        return [_error("document_ref", "invalid", "document_ref는 객체여야 합니다.")]
    for key in REF_KEYS:
        if key not in document_ref:
            problems.append(_error(f"document_ref.{key}", "required", "필수 값입니다."))
    for key in ("document_id", "version", "template_id"):
        if key in document_ref and not _is_int(document_ref[key]):
            problems.append(_error(f"document_ref.{key}", "invalid", "정수여야 합니다."))
    if "work_date" in document_ref and _as_date(document_ref["work_date"]) is None:
        problems.append(_error("document_ref.work_date", "invalid", "YYYY-MM-DD 날짜여야 합니다."))
    if not isinstance(snapshot, dict):
        problems.append(_error("snapshot", "invalid", "스냅샷은 JSON 객체여야 합니다."))
    return problems


def open_request(document_ref, snapshot, requested_by, slots):
    """상신: 결재 요청(회차)과 슬롯을 만든다. WF 트랜잭션 안에서만 호출한다."""
    with step("APR-OPN-00", "APR", "트랜잭션 확인"):
        _require_transaction()
    with step("APR-OPN-01", "APR", "입력 확인") as s:
        ref_problems = _check_ref(document_ref, snapshot)
        if ref_problems:
            s.fail("document_ref/snapshot 오류")
            raise ApiError("상신 정보가 올바르지 않습니다.", ref_problems)
        cleaned, problems = _check_slot_format(slots)
        if not problems:
            _check_slot_staff(cleaned, problems)
        if problems:
            s.fail(f"슬롯 오류 {len(problems)}건")
            raise errors.InvalidSlots(details=problems)
        slots = _finish_slots(cleaned)
    document_id = document_ref["document_id"]
    with step("APR-OPN-02", "APR", "회차·진행 중 요청 확인"):
        info = ApprovalRequest.objects.filter(document_id=document_id).aggregate(
            last=Max("attempt"), open=Count("pk", filter=Q(status="in_progress"))
        )
        if info["open"]:
            raise errors.OpenRequestExists()
    now = timezone.now()
    try:
        with transaction.atomic():
            with step("APR-OPN-03", "APR", "요청 저장"):
                req = ApprovalRequest.objects.create(
                    document_id=document_id,
                    attempt=(info["last"] or 0) + 1,
                    status="in_progress",
                    document_version=document_ref["version"],
                    template_id=document_ref["template_id"],
                    subject=document_ref["subject"],
                    work_date=_as_date(document_ref["work_date"]),
                    snapshot_json=snapshot,
                    requested_by_id=requested_by,
                    requested_at=now,
                )
    except IntegrityError as error:
        if "approval_request.document_id" in str(error) or "ux_request_open" in str(error):
            with step("APR-OPN-03a", "APR", "진행 중 요청 중복(DB 제약)") as s:
                s.fail("ux_request_open")
            raise errors.OpenRequestExists() from error
        raise
    with step("APR-OPN-04", "APR", "슬롯 저장"):
        created = Approval.objects.bulk_create(
            Approval(
                request=req,
                slot_no=s["slot_no"],
                label=s["label"],
                approver_id=s["approver_id"],
                state="pending",
            )
            for s in slots
        )
    with step("APR-OPN-05", "APR", "결과"):
        if any(slot.approval_id is None for slot in created):
            created = list(req.slots.all())
        return _request_dict(req, created, with_snapshot=False)


# ---------------------------------------------------------------- F03 슬롯 처리


def _decide_failure(approval_id, actor_id):
    """조건부 UPDATE가 0행일 때 이유: 없음 → 결재자 불일치 → 요청 종료 → 이미 처리."""
    with step("APR-DEC-02a", "APR", "처리 실패 사유 확인"):
        row = (
            Approval.objects.filter(pk=approval_id)
            .values("approver_id", "state", "request__status")
            .first()
        )
        if row is None:
            raise errors.ApprovalNotFound()
        if row["approver_id"] != actor_id:
            raise errors.NotYourSlot()
        if row["request__status"] != "in_progress":
            raise errors.RequestClosed()
        raise errors.AlreadyDecided()


def decide(approval_id, actor_id, result, comment=None):
    """내 슬롯을 승인·반려하고 요청 결과를 판정한다. WF 트랜잭션 안에서만 호출한다."""
    with step("APR-DEC-00", "APR", "트랜잭션 확인"):
        _require_transaction()
    with step("APR-DEC-01", "APR", "입력 확인"):
        if result not in ("approved", "rejected"):
            raise errors.InvalidDecision(
                details=[_error("result", "invalid", "approved 또는 rejected여야 합니다.")]
            )
        if comment is not None and not isinstance(comment, str):
            raise errors.InvalidDecision(
                details=[_error("comment", "invalid", "문자열이어야 합니다.")]
            )
        comment = (comment or "").strip() or None
        if comment and len(comment) > COMMENT_MAX:
            raise errors.InvalidDecision(
                details=[_error("comment", "max_length", f"{COMMENT_MAX}자 이하입니다.")]
            )
        if result == "rejected" and not comment:
            raise errors.CommentRequired(
                details=[_error("comment", "required", "반려 사유를 입력하세요.")]
            )
    now = timezone.now()
    with step("APR-DEC-02", "APR", "내 슬롯 처리(조건부 UPDATE)") as s:
        changed = Approval.objects.filter(
            pk=approval_id,
            approver_id=actor_id,
            state="pending",
            request__status="in_progress",
        ).update(state=result, comment=comment, decided_at=now)
        s.note(f"영향 행 {changed}")
    if changed == 0:
        _decide_failure(approval_id, actor_id)
    with step("APR-DEC-03", "APR", "요청 판정 집계"):
        slot = Approval.objects.select_related("request").get(pk=approval_id)
        req = slot.request
        counts = Approval.objects.filter(request_id=req.request_id).aggregate(
            pending=Count("pk", filter=Q(state="pending")),
            rejected=Count("pk", filter=Q(state="rejected")),
        )
    with step("APR-DEC-04", "APR", "요청 종료") as s:
        status = "in_progress"
        if counts["rejected"]:
            status = "rejected"
            skipped = Approval.objects.filter(request_id=req.request_id, state="pending").update(
                state="skipped", decided_at=now
            )
            ApprovalRequest.objects.filter(pk=req.request_id, status="in_progress").update(
                status="rejected", closed_at=now
            )
            s.note(f"반려 종료, skipped {skipped}")
            counts["pending"] = 0
        elif counts["pending"] == 0:
            status = "approved"
            ApprovalRequest.objects.filter(pk=req.request_id, status="in_progress").update(
                status="approved", closed_at=now
            )
            s.note("전원 승인")
        else:
            s.skip(f"대기 {counts['pending']}건 남음")
    with step("APR-DEC-05", "APR", "결과"):
        return {
            "request_id": req.request_id,
            "document_id": req.document_id,
            "request_status": status,
            "decided": {"approval_id": slot.approval_id, "slot_no": slot.slot_no, "state": result},
            "pending_count": counts["pending"],
        }


# ---------------------------------------------------------------- F04·F05 조회


def get_request(request_id):
    with step("APR-GET-01", "APR", "요청 조회"):
        req = ApprovalRequest.objects.filter(pk=request_id).first()
        if req is None:
            raise errors.RequestNotFound()
    with step("APR-GET-02", "APR", "슬롯 조회"):
        slots = list(Approval.objects.filter(request_id=request_id).order_by("slot_no"))
    with step("APR-GET-03", "APR", "조립"):
        return _request_dict(req, slots, with_snapshot=True)


def list_requests(document_id):
    with step("APR-HIS-01", "APR", "회차 조회"):
        reqs = list(
            ApprovalRequest.objects.filter(document_id=document_id)
            .defer("snapshot_json")
            .order_by("-attempt")
        )
    with step("APR-HIS-02", "APR", "슬롯 조회"):
        by_request = {}
        if reqs:
            for slot in Approval.objects.filter(
                request_id__in=[r.request_id for r in reqs]
            ).order_by("request_id", "slot_no"):
                by_request.setdefault(slot.request_id, []).append(slot)
    with step("APR-HIS-03", "APR", "조립"):
        return {
            "document_id": document_id,
            "items": [
                _request_dict(r, by_request.get(r.request_id, []), with_snapshot=False)
                for r in reqs
            ],
        }


# ---------------------------------------------------------------- F06 결재함


def _parse_date(value, key, problems):
    from datetime import date

    if not value:
        return None
    if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    problems.append(_error(key, "invalid", "YYYY-MM-DD 형식이어야 합니다."))
    return None


def list_inbox(actor_id, box="pending", filters=None, page=1):
    filters = filters or {}
    with step("APR-INB-01", "APR", "필터 검증"):
        problems = []
        if box not in ("pending", "done"):
            problems.append(_error("box", "invalid", "pending 또는 done이어야 합니다."))
        date_from = _parse_date(filters.get("from"), "from", problems)
        date_to = _parse_date(filters.get("to"), "to", problems)
        if date_from and date_to:
            if date_from > date_to:
                problems.append(_error("from", "range", "시작일이 종료일보다 늦습니다."))
            elif (date_to - date_from).days > MAX_RANGE_DAYS:
                problems.append(
                    _error("to", "range", f"기간은 {MAX_RANGE_DAYS}일 이내여야 합니다.")
                )
        template_id = filters.get("template_id")
        if template_id not in (None, ""):
            if isinstance(template_id, str) and template_id.isdigit():
                template_id = int(template_id)
            elif not _is_int(template_id):
                problems.append(_error("template_id", "invalid", "정수여야 합니다."))
        else:
            template_id = None
        page_number = int(page) if str(page).isdigit() else 0
        if page_number < 1:
            problems.append(_error("page", "invalid", "1 이상이어야 합니다."))
        if problems:
            raise errors.InvalidFilter(details=problems)

    queryset = Approval.objects.filter(approver_id=actor_id)
    if box == "pending":
        queryset = queryset.filter(state="pending", request__status="in_progress")
        order = ("request__requested_at", "approval_id")
    else:
        queryset = queryset.filter(state__in=("approved", "rejected"))
        order = ("-decided_at", "-approval_id")
    if date_from:
        queryset = queryset.filter(request__work_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(request__work_date__lte=date_to)
    if template_id is not None:
        queryset = queryset.filter(request__template_id=template_id)

    with step("APR-INB-02", "APR", "건수"):
        total = queryset.count()
    with step("APR-INB-03", "APR", "페이지 조회"):
        offset = (page_number - 1) * PAGE_SIZE
        slots = list(
            queryset.select_related("request")
            .defer("request__snapshot_json")
            .order_by(*order)[offset : offset + PAGE_SIZE]
        )
    with step("APR-INB-04", "APR", "진행률 집계") as s:
        progress = {}
        if slots:
            rows = (
                Approval.objects.filter(request_id__in={x.request_id for x in slots})
                .values("request_id")
                .annotate(
                    total=Count("pk"),
                    approved=Count("pk", filter=Q(state="approved")),
                    pending=Count("pk", filter=Q(state="pending")),
                )
            )
            progress = {r["request_id"]: r for r in rows}
        else:
            s.skip("항목 없음")
    with step("APR-INB-05", "APR", "조립"):
        items = []
        for slot in slots:
            req = slot.request
            p = progress.get(req.request_id, {})
            items.append(
                {
                    "approval_id": slot.approval_id,
                    "slot_no": slot.slot_no,
                    "label": slot.label,
                    "state": slot.state,
                    "decided_at": _iso(slot.decided_at),
                    "request": {
                        "request_id": req.request_id,
                        "document_id": req.document_id,
                        "attempt": req.attempt,
                        "status": req.status,
                        "subject": req.subject,
                        "work_date": _iso(req.work_date),
                        "template_id": req.template_id,
                        "requested_by": req.requested_by_id,
                        "requested_at": _iso(req.requested_at),
                        "progress": {
                            "total": p.get("total", 0),
                            "approved": p.get("approved", 0),
                            "pending": p.get("pending", 0),
                        },
                    },
                }
            )
        return {"items": items, "total": total, "page": page_number, "page_size": PAGE_SIZE}
