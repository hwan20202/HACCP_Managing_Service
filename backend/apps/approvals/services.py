"""결재 도메인 서비스 (approval/s2-spec.md 3.1, 흐름은 s2-flows.md).

- 쓰기 함수(open_request, decide)는 호출자(WF)의 트랜잭션 안에서만 실행한다.
- decide의 첫 쓰기는 슬롯 조건부 UPDATE다.
  동시 처리 시 직렬화되고 "마지막 승인"은 한 요청만 판정한다.
- 이 모듈은 apps.documents, apps.document_workflow를 import하지 않는다.
- P14(ERD v7.2): 칸은 직접 지정 칸(approver_id, P14 이전)과 역할 칸(role + 후보) 두 가지.
  이 모듈은 역할 설정(apps.staff.roles)을 모른다 — WF가 만든 칸·후보를 받아 저장하고
  판단한다(ROLE-NFR-02).
"""

import datetime

from django.db import IntegrityError, transaction
from django.db.models import (
    BigIntegerField,
    BooleanField,
    Case,
    Count,
    Exists,
    F,
    Max,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.utils import timezone

from apps.core.http import ApiError
from apps.core.trace import step
from apps.staff import services as staff_services

from . import errors
from .models import SLOT_ROLES, Approval, ApprovalCandidate, ApprovalRequest

MAX_SLOTS = 10
LABEL_MAX = 20
COMMENT_MAX = 500
PAGE_SIZE = 20
MAX_RANGE_DAYS = 366
SLOT_KEYS = {"slot_no", "approver_id", "label"}  # 직접 지정 칸
ROLE_SLOT_KEYS = {"slot_no", "label", "role", "candidate_ids"}  # 역할 칸(P14)
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
    """형식 검사(DB 조회 없음). 반환: (정리된 슬롯, 오류 목록).

    칸은 직접 지정 칸 {slot_no, label?, approver_id} 또는 역할 칸 {slot_no, label?, role,
    candidate_ids}(P14). 한 결재선에 두 종류를 섞을 수 없다.
    """
    problems, cleaned = [], []
    if not isinstance(slots, list) or not slots:
        return [], [_error("slots", "required", "결재 칸을 1개 이상 지정하세요.")]
    if len(slots) > MAX_SLOTS:
        problems.append(_error("slots", "max", f"결재 칸은 최대 {MAX_SLOTS}개입니다."))
    kinds = {
        "role" if isinstance(slot, dict) and "role" in slot else "direct"
        for slot in slots
        if isinstance(slot, dict)
    }
    if len(kinds) > 1:
        problems.append(_error("slots", "mixed", "직접 지정 칸과 역할 칸을 섞을 수 없습니다."))
    seen_no, seen_approver = set(), set()
    for i, slot in enumerate(slots):
        path = f"slots[{i}]"
        if not isinstance(slot, dict):
            problems.append(_error(path, "invalid", "결재 칸은 객체여야 합니다."))
            continue
        is_role = "role" in slot
        allowed = ROLE_SLOT_KEYS if is_role else SLOT_KEYS
        for key in sorted(set(slot) - allowed):
            problems.append(_error(f"{path}.{key}", "unknown_key", "허용되지 않은 키입니다."))
        slot_no, label = slot.get("slot_no"), slot.get("label")
        if not _is_int(slot_no) or slot_no < 1:
            problems.append(_error(f"{path}.slot_no", "invalid", "칸 번호는 1 이상의 정수입니다."))
        elif slot_no in seen_no:
            problems.append(
                _error(f"{path}.slot_no", "duplicate", f"칸 번호 {slot_no}이(가) 중복됩니다.")
            )
        else:
            seen_no.add(slot_no)
        approver, role, candidates = None, None, None
        if is_role:
            role, candidates = slot.get("role"), slot.get("candidate_ids")
            if role not in SLOT_ROLES:
                problems.append(_error(f"{path}.role", "invalid", "역할은 owner·leader입니다."))
            if (
                not isinstance(candidates, list)
                or not candidates
                or not all(_is_int(c) for c in candidates)
                or len(set(candidates)) != len(candidates)
            ):
                problems.append(
                    _error(
                        f"{path}.candidate_ids",
                        "invalid",
                        "후보는 staff id 목록(1명 이상, 중복 없음)입니다.",
                    )
                )
                candidates = []
        else:
            approver = slot.get("approver_id")
            if not _is_int(approver):
                problems.append(
                    _error(f"{path}.approver_id", "invalid", "결재자는 staff id입니다.")
                )
            elif approver in seen_approver:
                problems.append(
                    _error(
                        f"{path}.approver_id",
                        "duplicate",
                        "같은 사람을 두 칸에 배정할 수 없습니다.",
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
        cleaned.append(
            {
                "slot_no": slot_no,
                "approver_id": approver,
                "label": label,
                "role": role,
                "candidate_ids": sorted(candidates) if candidates else [],
                "_path": path,
            }
        )
    return cleaned, problems


def _check_slot_staff(cleaned, problems):
    wanted = [s["approver_id"] for s in cleaned]
    wanted += [c for s in cleaned for c in s["candidate_ids"]]
    existing = staff_services.existing_ids(wanted)
    for slot in cleaned:
        if _is_int(slot["approver_id"]) and slot["approver_id"] not in existing:
            problems.append(
                _error(
                    f"{slot['_path']}.approver_id", "unknown_staff", "등록되지 않은 사용자입니다."
                )
            )
        missing = [c for c in slot["candidate_ids"] if c not in existing]
        if missing:
            problems.append(
                _error(
                    f"{slot['_path']}.candidate_ids",
                    "unknown_staff",
                    f"등록되지 않았거나 비활성인 사용자: {missing}",
                )
            )


def _finish_slots(cleaned):
    keys = {True: ("slot_no", "label", "role", "candidate_ids"), False: tuple(SLOT_KEYS)}
    return [
        {k: s[k] for k in sorted(keys[s["role"] is not None])}
        for s in sorted(cleaned, key=lambda s: s["slot_no"])
    ]


def validate_slots(slots):
    """직접 지정 칸 결재선 형식·직원 검사(APR-VAL).

    P14부터 WF는 부르지 않는다(결재선은 역할 설정으로 자동 — p14-s2-spec 3.3). 옛 직접 지정 칸
    형식 규칙의 테스트용으로 남긴다. 정리는 병합 뒤(S4 리뷰 A4). ``open_request``는 같은 검사를
    안쪽 함수로 직접 한다.
    """
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


def _candidates_of(slots):
    """칸 id → 후보 staff id 목록(역할 칸만, id 순). SQL 1(역할 칸이 없으면 없음)."""
    ids = [s.approval_id for s in slots if s.role]
    result = {}
    if ids:
        for approval_id, staff_id in (
            ApprovalCandidate.objects.filter(approval_id__in=ids)
            .order_by("approval_id", "staff_id")
            .values_list("approval_id", "staff_id")
        ):
            result.setdefault(approval_id, []).append(staff_id)
    return result


def _slot_dict(slot, candidates=None):
    return {
        "approval_id": slot.approval_id,
        "slot_no": slot.slot_no,
        "label": slot.label,
        "role": slot.role,
        "candidate_ids": (candidates or {}).get(slot.approval_id, [])
        if slot.role
        else [slot.approver_id],
        "approver_id": slot.approver_id,
        "state": slot.state,
        "comment": slot.comment,
        "decided_at": _iso(slot.decided_at),
    }


def _snapshot_reason(path):
    """스냅샷 JSON의 correction.reason(SQL 안에서 꺼냄 — 스냅샷 전체를 읽지 않는다)."""
    return KeyTextTransform("reason", KeyTransform("correction", path))


def _correction_reason(req):
    """정정 상신 회차면 스냅샷의 정정 사유(P6 2.3). 스냅샷을 읽지 않은 행은 annotate 값."""
    if hasattr(req, "snapshot_correction_reason"):
        return req.snapshot_correction_reason
    correction = (req.snapshot_json or {}).get("correction") if req.snapshot_json else None
    return correction.get("reason") if isinstance(correction, dict) else None


def _correction_values(req, next_approved):
    """회차 표시 값(계산, 저장 안 함 — P6-S2-Q2).

    next_approved: 바로 다음 승인 회차 (attempt, closed_at), 없으면 None.
    """
    reason = _correction_reason(req)
    approved = req.status == "approved"
    return {
        "effective": approved and next_approved is None,
        "superseded_by": next_approved[0] if approved and next_approved else None,
        "superseded_at": _iso(next_approved[1]) if approved and next_approved else None,
        "is_correction": reason is not None,
        "correction_reason": reason,
    }


def _request_dict(req, slots, *, with_snapshot, next_approved=None, candidates=None, actor_id=None):
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
        "slots": [_slot_dict(s, candidates) for s in sorted(slots, key=lambda s: s.slot_no)],
        # P14: 상신자 본인 취소 가능 여부(팀장 예외는 WF·화면이 역할로 — p14-s2-spec 3.3)
        "can_cancel": actor_id is not None
        and req.status == "in_progress"
        and req.requested_by_id == actor_id,
        **_correction_values(req, next_approved),
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
                role=s.get("role"),
                approver_id=s.get("approver_id"),  # 역할 칸은 None(처리 때 채움 — ERD v7.2 M16)
                state="pending",
            )
            for s in slots
        )
        if any(slot.approval_id is None for slot in created):
            created = list(req.slots.order_by("slot_no"))
    with step("APR-OPN-04b", "APR", "후보 저장(역할 칸)") as st:
        by_no = {slot.slot_no: slot.approval_id for slot in created}
        rows = [
            ApprovalCandidate(approval_id=by_no[s["slot_no"]], staff_id=c)
            for s in slots
            if s.get("role")
            for c in s["candidate_ids"]
        ]
        if rows:
            ApprovalCandidate.objects.bulk_create(rows)
            st.note(f"후보 {len(rows)}행")
        else:
            st.skip("직접 지정 칸")
    with step("APR-OPN-05", "APR", "결과"):
        candidates = {}
        for s in slots:
            if s.get("role"):
                candidates[by_no[s["slot_no"]]] = list(s["candidate_ids"])
        return _request_dict(req, created, with_snapshot=False, candidates=candidates)


# ---------------------------------------------------------------- F03 슬롯 처리


def _eligible(actor_id):
    """처리 자격(P14 흐름 3.4): 직접 지정 칸은 지정 결재자, 역할 칸은 후보."""
    mine = ApprovalCandidate.objects.filter(approval_id=OuterRef("pk"), staff_id=actor_id)
    return Q(role__isnull=True, approver_id=actor_id) | (Q(role__isnull=False) & Q(Exists(mine)))


def _eligible_flag(actor_id):
    return Case(
        When(_eligible(actor_id), then=Value(True)),
        default=Value(False),
        output_field=BooleanField(),
    )


def _decide_failure(approval_id, actor_id):
    """조건부 UPDATE가 0행일 때 이유: 없음 → 처리 자격 없음 → 요청 종료 → 이미 처리.

    P14: 자격은 칸 종류별(직접 지정 = 결재자, 역할 = 후보)로 먼저 본다 — 역할 칸은 대기 중
    결재자가 비어 있어, 결재자 비교를 먼저 하면 후보인데 회차가 끝난 경우에도 403이 됐다.
    """
    with step("APR-DEC-02a", "APR", "처리 실패 사유 확인"):
        row = (
            Approval.objects.filter(pk=approval_id)
            .annotate(eligible=_eligible_flag(actor_id))
            .values("eligible", "state", "request__status")
            .first()
        )
        if row is None:
            raise errors.ApprovalNotFound()
        if not row["eligible"]:
            raise errors.NotYourSlot()
        if row["request__status"] != "in_progress":
            raise errors.RequestClosed()
        raise errors.AlreadyDecided()


def check_decision_input(result, comment):
    """A11: 결재 입력 검사(APR-DEC-01 규칙, SQL 없음). 반환: 정리된 의견.

    A3 decide가 부르고, 일괄 승인은 트랜잭션 밖에서 먼저 부른다(P7-VR-08).
    """
    if result not in ("approved", "rejected"):
        raise errors.InvalidDecision(
            details=[_error("result", "invalid", "approved 또는 rejected여야 합니다.")]
        )
    if comment is not None and not isinstance(comment, str):
        raise errors.InvalidDecision(details=[_error("comment", "invalid", "문자열이어야 합니다.")])
    comment = (comment or "").strip() or None
    if comment and len(comment) > COMMENT_MAX:
        raise errors.InvalidDecision(
            details=[_error("comment", "max_length", f"{COMMENT_MAX}자 이하입니다.")]
        )
    if result == "rejected" and not comment:
        raise errors.CommentRequired(
            details=[_error("comment", "required", "반려 사유를 입력하세요.")]
        )
    return comment


def decide(approval_id, actor_id, result, comment=None):
    """내 슬롯을 승인·반려하고 요청 결과를 판정한다. WF 트랜잭션 안에서만 호출한다."""
    with step("APR-DEC-00", "APR", "트랜잭션 확인"):
        _require_transaction()
    with step("APR-DEC-01", "APR", "입력 확인"):
        comment = check_decision_input(result, comment)
    now = timezone.now()
    with step("APR-DEC-02", "APR", "내 슬롯 처리(조건부 UPDATE)") as s:
        changed = (
            Approval.objects.filter(pk=approval_id, state="pending", request__status="in_progress")
            .filter(_eligible(actor_id))
            .update(
                state=result,
                comment=comment,
                decided_at=now,
                # 역할 칸은 처리한 사람이 결재자(서명) — 직접 지정 칸은 그대로
                approver_id=Case(
                    When(role__isnull=False, then=Value(actor_id)),
                    default=F("approver_id"),
                    output_field=BigIntegerField(),
                ),
            )
        )
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


# ---------------------------------------------------------------- A7 상신 취소 (P10)


def _cancel_failure(request_id, actor_id, allow_any=False):
    """조건부 UPDATE가 0행일 때 이유: 없음 → 상신자 아님 → 진행 중 아님(p10-s2-spec 3.1)."""
    with step("APR-CAN-01a", "APR", "취소 실패 사유 확인"):
        row = ApprovalRequest.objects.filter(pk=request_id).values("requested_by_id", "status")
        row = row.first()
        if row is None:
            raise errors.RequestNotFound()
        if row["requested_by_id"] != actor_id and not allow_any:
            raise errors.NotRequester()
        raise errors.RequestClosed()


def cancel_request(request_id, actor_id, *, allow_any=False):
    """A7: 진행 중 회차를 상신자가 취소한다(P6-S2-Q7 a — 받은 승인·반려 칸은 그대로,
    대기 칸만 skipped). WF 트랜잭션 안에서만 호출한다. 첫 쓰기 = 회차 조건부 UPDATE(D-067).

    반환: 회차(스냅샷 없음). 결재 완료 신호는 없다(회차가 승인으로 끝나지 않음).
    P14: allow_any = WF가 HACCP팀장이라고 확인함(상신자가 아니어도 취소 — ROLE-R02).
    """
    with step("APR-CAN-00", "APR", "트랜잭션 확인"):
        _require_transaction()
    now = timezone.now()
    with step("APR-CAN-01", "APR", "회차 취소(조건부 UPDATE)") as s:
        target = ApprovalRequest.objects.filter(pk=request_id, status="in_progress")
        if not allow_any:
            target = target.filter(requested_by_id=actor_id)
        changed = target.update(status="cancelled", closed_at=now)
        s.note(f"영향 행 {changed}")
    if changed == 0:
        _cancel_failure(request_id, actor_id, allow_any)
    with step("APR-CAN-02", "APR", "대기 칸 건너뜀") as s:
        skipped = Approval.objects.filter(request_id=request_id, state="pending").update(
            state="skipped", decided_at=now
        )
        s.note(f"skipped {skipped}")
    with step("APR-CAN-03", "APR", "결과"):
        req = (
            ApprovalRequest.objects.defer("snapshot_json")
            .annotate(snapshot_correction_reason=_snapshot_reason("snapshot_json"))
            .get(pk=request_id)
        )
        slots = list(Approval.objects.filter(request_id=request_id).order_by("slot_no"))
        return _request_dict(req, slots, with_snapshot=False, candidates=_candidates_of(slots))


# ---------------------------------------------------------------- F04·F05 조회


def get_request(request_id, actor_id=None):
    with step("APR-GET-01", "APR", "요청 조회"):
        req = ApprovalRequest.objects.filter(pk=request_id).first()
        if req is None:
            raise errors.RequestNotFound()
    with step("APR-GET-02", "APR", "슬롯·후보 조회"):
        slots = list(Approval.objects.filter(request_id=request_id).order_by("slot_no"))
        candidates = _candidates_of(slots)
    with step("APR-GET-03", "APR", "다음 승인 회차(대체됨 계산)") as s:
        next_approved = None
        if req.status == "approved":
            next_approved = (
                ApprovalRequest.objects.filter(
                    document_id=req.document_id, status="approved", attempt__gt=req.attempt
                )
                .order_by("attempt")
                .values_list("attempt", "closed_at")
                .first()
            )
        else:
            s.skip("승인 회차 아님")
    with step("APR-GET-04", "APR", "조립"):
        return _request_dict(
            req,
            slots,
            with_snapshot=True,
            next_approved=next_approved,
            candidates=candidates,
            actor_id=actor_id,
        )


def list_requests(document_id, actor_id=None):
    with step("APR-HIS-01", "APR", "회차 조회"):
        reqs = list(
            ApprovalRequest.objects.filter(document_id=document_id)
            .defer("snapshot_json")
            .annotate(snapshot_correction_reason=_snapshot_reason("snapshot_json"))
            .order_by("-attempt")
        )
    with step("APR-HIS-02", "APR", "슬롯 조회"):
        by_request = {}
        if reqs:
            for slot in Approval.objects.filter(
                request_id__in=[r.request_id for r in reqs]
            ).order_by("request_id", "slot_no"):
                by_request.setdefault(slot.request_id, []).append(slot)
        candidates = _candidates_of([s for group in by_request.values() for s in group])
    with step("APR-HIS-03", "APR", "조립·대체됨 계산"):
        # 승인 회차를 attempt 오름차순으로 — 각 승인 회차의 "바로 다음 승인 회차"
        approved = sorted((r.attempt, r.closed_at) for r in reqs if r.status == "approved")
        following = {a[0]: b for a, b in zip(approved, approved[1:])}
        return {
            "document_id": document_id,
            "items": [
                _request_dict(
                    r,
                    by_request.get(r.request_id, []),
                    with_snapshot=False,
                    next_approved=following.get(r.attempt),
                    candidates=candidates,
                    actor_id=actor_id,
                )
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

    if box == "pending":
        # P14: 직접 지정 칸 결재자 = 나, 또는 역할 칸 후보 = 나(처리 전)
        queryset = Approval.objects.filter(
            _eligible(actor_id), state="pending", request__status="in_progress"
        )
        order = ("request__requested_at", "approval_id")
    else:
        queryset = Approval.objects.filter(approver_id=actor_id, state__in=("approved", "rejected"))
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
        later_approved = ApprovalRequest.objects.filter(
            document_id=OuterRef("request__document_id"),
            status="approved",
            attempt__gt=OuterRef("request__attempt"),
        )
        slots = list(
            queryset.select_related("request")
            .defer("request__snapshot_json")
            .annotate(
                # P6: 정정 상신 사유(스냅샷 값), 대체됨(그 문서의 모든 회차 대상 — 페이지와 무관)
                correction_reason=_snapshot_reason("request__snapshot_json"),
                later_approved=Exists(later_approved),
            )
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
                    "role": slot.role,
                    "state": slot.state,
                    "decided_at": _iso(slot.decided_at),
                    "request_status": req.status,  # P10: 처리 완료 줄 "취소됨"
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
                        "is_correction": slot.correction_reason is not None,
                        "correction_reason": slot.correction_reason,
                        "superseded": req.status == "approved" and slot.later_approved,
                        "progress": {
                            "total": p.get("total", 0),
                            "approved": p.get("approved", 0),
                            "pending": p.get("pending", 0),
                        },
                    },
                }
            )
        return {"items": items, "total": total, "page": page_number, "page_size": PAGE_SIZE}


# ------------------------------------------------ A8 최신 승인 회차 (P5, REQ s2-spec 4.2)


def latest_approved(document_ids):
    """A8: 문서별로 status='approved'인 회차 중 attempt가 가장 큰 것(SQL 1회).

    반환 {document_id: {request_id, attempt, closed_at, snapshot}}. 승인 회차가 없는 문서는 빠진다.
    빈 목록이면 SQL 없이 {}. 정정 뒤 "대체됨" 표시는 P6에서 이 함수에 더한다.
    """
    ids = sorted({i for i in document_ids if _is_int(i)})
    if not ids:
        return {}
    with step("APR-LAT-01", "APR", "문서별 최신 승인 회차"):
        newest = (
            ApprovalRequest.objects.filter(document_id=OuterRef("document_id"), status="approved")
            .order_by("-attempt")
            .values("attempt")[:1]
        )
        rows = ApprovalRequest.objects.filter(
            document_id__in=ids, status="approved", attempt=Subquery(newest)
        )
        return {
            req.document_id: {
                "request_id": req.request_id,
                "attempt": req.attempt,
                "closed_at": _iso(req.closed_at),
                "snapshot": req.snapshot_json,
            }
            for req in rows
        }


# ------------------------------------------------ P7 A9·A10 (p7-s2-spec 3.3)


def _ids(values):
    return sorted({i for i in values if _is_int(i)})


def slot_refs(approval_ids):
    """A9: 칸 id → {document_id, request_id, template_id}(SQL 1). 없는 id는 빠진다.

    일괄 승인 양식 판정의 유일한 출처(검토 B-6). 쓰기 없음.
    """
    ids = _ids(approval_ids)
    if not ids:
        return {}
    with step("APR-SRF-01", "APR", "칸 출처"):
        rows = Approval.objects.filter(pk__in=ids).values_list(
            "approval_id", "request__document_id", "request_id", "request__template_id"
        )
        return {
            approval_id: {
                "document_id": document_id,
                "request_id": request_id,
                "template_id": template_id,
            }
            for approval_id, document_id, request_id, template_id in rows
        }


def document_progress(document_ids, actor_id):
    """A10: 문서마다 가장 큰 attempt 회차의 진행·내 대기 칸(SQL 1).

    반환 {"documents": {id: {request_id, attempt, status, total, approved, pending, my_slots}}}.
    my_slots는 회차가 진행 중일 때 내가 처리할 수 있는 대기 칸 목록(칸 번호 순) — P14: 직접 지정 칸
    결재자 = 나 또는 역할 칸 후보 = 나. 담당자이면서 팀장이면 2개일 수 있다(DR-05).
    P14에서 latest_slots(일괄 상신 결재선 기본값, D-109)는 없앴다 — 결재선은 설정으로 자동.
    회차가 없는 문서는 빠진다. 빈 목록이면 SQL 없음.
    """
    ids = _ids(document_ids)
    result = {"documents": {}}
    if not ids:
        return result
    with step("APR-PRG-01", "APR", "문서별 최신 회차·내 칸"):
        newest = (
            ApprovalRequest.objects.filter(document_id=OuterRef("request__document_id"))
            .order_by("-attempt")
            .values("attempt")[:1]
        )
        mine = _eligible_flag(actor_id) if actor_id else None
        rows = Approval.objects.filter(
            request__document_id__in=ids, request__attempt=Subquery(newest)
        ).order_by("request__document_id", "slot_no")
        if mine is not None:
            rows = rows.annotate(mine=mine)
        fields = [
            "request__document_id",
            "request_id",
            "request__attempt",
            "request__status",
            "approval_id",
            "slot_no",
            "label",
            "state",
        ] + (["mine"] if mine is not None else [])
        documents = result["documents"]
        for row in rows.values_list(*fields):
            doc_id, req_id, attempt, status, approval_id, slot_no, label, state = row[:8]
            eligible = bool(row[8]) if mine is not None else False
            item = documents.setdefault(
                doc_id,
                {
                    "request_id": req_id,
                    "attempt": attempt,
                    "status": status,
                    "total": 0,
                    "approved": 0,
                    "pending": 0,
                    "my_slots": [],
                },
            )
            item["total"] += 1
            item["approved"] += state == "approved"
            item["pending"] += state == "pending"
            if eligible and state == "pending" and status == "in_progress":
                item["my_slots"].append(
                    {"approval_id": approval_id, "slot_no": slot_no, "label": label}
                )
    return result


# ------------------------------------------------ P12 A12 출력용 결재 칸 (p12-s2-spec 3.2)


def _print_slot(slot):
    return {
        "slot_no": slot.slot_no,
        "label": slot.label,
        "role": slot.role,
        "approver_id": slot.approver_id,
        "state": slot.state,
        "decided_at": _iso(slot.decided_at),
    }


def print_slots(document_ids):
    """A12: 문서별 최신 회차(상태 무관)와 유효 승인 회차(A8과 같은 회차)의 칸. SQL 2개.

    반환 {document_id: {latest: {request_id, attempt, status, slots}, approved?: {request_id,
    attempt, snapshot, slots}}}. 회차가 없는 문서는 빠진다. 쓰기 없음.
    """
    ids = _ids(document_ids)
    if not ids:
        return {}
    with step("APR-PRT-01", "APR", "최신 회차·최신 승인 회차"):
        newest = (
            ApprovalRequest.objects.filter(document_id=OuterRef("document_id"))
            .order_by("-attempt")
            .values("attempt")[:1]
        )
        newest_approved = (
            ApprovalRequest.objects.filter(document_id=OuterRef("document_id"), status="approved")
            .order_by("-attempt")
            .values("attempt")[:1]
        )
        requests = list(
            ApprovalRequest.objects.filter(document_id__in=ids)
            .annotate(latest=Subquery(newest), latest_ok=Subquery(newest_approved))
            .filter(Q(attempt=F("latest")) | Q(status="approved", attempt=F("latest_ok")))
        )
    with step("APR-PRT-02", "APR", "회차의 칸"):
        slots = {}
        for slot in Approval.objects.filter(
            request_id__in=[r.request_id for r in requests]
        ).order_by("request_id", "slot_no"):
            slots.setdefault(slot.request_id, []).append(_print_slot(slot))
    result = {}
    for req in requests:
        entry = result.setdefault(req.document_id, {})
        head = {
            "request_id": req.request_id,
            "attempt": req.attempt,
            "slots": slots.get(req.request_id, []),
        }
        if req.attempt == req.latest:
            entry["latest"] = {**head, "status": req.status}
        if req.status == "approved" and req.attempt == req.latest_ok:
            entry["approved"] = {**head, "snapshot": req.snapshot_json}
    return result
