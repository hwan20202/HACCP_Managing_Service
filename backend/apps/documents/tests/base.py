"""테스트 공용 준비물. 값은 모두 가상이다."""

import copy

from django.utils import timezone

from apps.documents.models import DocSection, Document, DocumentTemplate
from apps.documents.seed import ensure_staff, ensure_templates


def setup_reference_data():
    ensure_staff(5)
    templates = ensure_templates()
    return {
        "ccp": templates[("CCP_MONITORING", 1)],
        "ccp_v0": templates[("CCP_MONITORING", 0)],
        "hygiene": templates[("HYGIENE_CHECK", 1)],
    }


def ccp_payload(template, **overrides):
    payload = {
        "template_id": template.template_id,
        "subject": "CCP-2B/라인A",
        "work_date": "2026-10-09",
        "due_at": None,
        "sections": [
            {"section_def": "info", "values": {"product": "유자차", "lot": "LOT-1234"}},
            {
                "section_def": "rounds",
                "values": {"round": "09:00", "temp": 87.0, "hold_sec": 16, "measured_by": 3},
            },
            {
                "section_def": "rounds",
                "values": {"round": "10:00", "temp": 84.2, "hold_sec": 16, "measured_by": 3},
            },
        ],
    }
    payload.update(copy.deepcopy(overrides))
    return payload


def make_document(
    template,
    *,
    status="draft",
    author=3,
    work_date="2026-10-09",
    submitted=False,
    deleted=False,
    rounds=("09:00", "10:00"),
):
    """ORM으로 직접 만든 문서(상태별 사전 조건용). 반환: (document, {키: section})."""
    now = timezone.now()
    document = Document.objects.create(
        template=template,
        subject="CCP-2B/라인A",
        work_date=work_date,
        assignee_id=2,
        created_by_id=author,
        status=status,
        created_at=now,
        updated_at=now,
        submitted_at=now if submitted or status not in ("draft", "completed") else None,
        completed_at=None if status == "draft" else now,
        completed_by_id=None if status == "draft" else author,
        deleted_at=now if deleted else None,
        deleted_by_id=1 if deleted else None,
    )
    rows = {
        "info": DocSection.objects.create(
            document=document,
            section_def="info",
            row_no=1,
            values_json={"product": "유자차", "lot": "LOT-1234"},
            recorded_at=now,
            recorded_by_id=author,
        )
    }
    for n, round_value in enumerate(rounds, start=1):
        rows[f"r{n}"] = DocSection.objects.create(
            document=document,
            section_def="rounds",
            row_no=n,
            values_json={"round": round_value, "temp": 87.0, "hold_sec": 16, "measured_by": author},
            recorded_at=now,
            recorded_by_id=author,
        )
    return document, rows


def snapshot(document_id):
    """DB 상태 비교용: 문서 행 + 섹션 행 전부."""
    document = Document.objects.filter(pk=document_id).values().first()
    sections = list(
        DocSection.objects.filter(document_id=document_id).order_by("section_id").values()
    )
    return document, sections


def update_current(actor_id, document_id, patch):
    """수정 호출 도우미: expected_version이 없으면 현재 DB 버전을 넣는다(ISS-001 이전 테스트)."""
    from apps.documents import services

    patch = dict(patch)
    if "expected_version" not in patch:
        patch["expected_version"] = (
            Document.objects.filter(pk=document_id).values_list("version", flat=True).first() or 1
        )
    return services.update_document(actor_id, document_id, patch)


__all__ = ["DocumentTemplate", "ccp_payload", "make_document", "setup_reference_data", "snapshot"]
