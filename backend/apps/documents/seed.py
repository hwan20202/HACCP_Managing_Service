"""개발·테스트용 가상 데이터 (s1-screens 7장). 실제 업무 데이터는 넣지 않는다."""

from datetime import timedelta

from django.utils import timezone

from apps.staff.models import Staff

from .models import DocSection, Document, DocumentTemplate
from .validation import check_template_schema

CCP_SCHEMA = {
    "sections": [
        {
            "key": "info",
            "label": "기본정보",
            "repeat": False,
            "fields": [
                {
                    "key": "product",
                    "label": "제품명",
                    "type": "text",
                    "required": True,
                    "max_length": 50,
                },
                {"key": "lot", "label": "LOT", "type": "text", "required": True, "max_length": 30},
            ],
        },
        {
            "key": "rounds",
            "label": "측정 기록",
            "repeat": True,
            "max_rows": 48,
            "fields": [
                {"key": "round", "label": "측정시점", "type": "time", "required": True},
                {
                    "key": "temp",
                    "label": "온도",
                    "type": "number",
                    "unit": "℃",
                    "required": True,
                    "limit": {"min": 85},
                },
                {
                    "key": "hold_sec",
                    "label": "유지시간",
                    "type": "number",
                    "unit": "초",
                    "required": True,
                    "limit": {"min": 15},
                },
                {"key": "measured_by", "label": "측정자", "type": "staff", "required": True},
                {"key": "retake", "label": "재측정", "type": "bool"},
                {"key": "note", "label": "비고", "type": "text", "max_length": 200},
            ],
        },
    ]
}

HYGIENE_SCHEMA = {
    "sections": [
        {
            "key": "info",
            "label": "기본정보",
            "repeat": False,
            "fields": [
                {"key": "area", "label": "점검 구역", "type": "text", "required": True},
                {"key": "inspector", "label": "점검자", "type": "staff", "required": True},
            ],
        },
        {
            "key": "items",
            "label": "점검 항목",
            "repeat": True,
            "max_rows": 30,
            "fields": [
                {
                    "key": "item",
                    "label": "항목",
                    "type": "select",
                    "required": True,
                    "options": ["바닥 청결", "배수구", "손 세척대", "방충망", "작업복"],
                },
                {
                    "key": "result",
                    "label": "결과",
                    "type": "select",
                    "required": True,
                    "options": ["적합", "부적합"],
                },
                {"key": "note", "label": "비고", "type": "text", "max_length": 200},
            ],
        },
    ]
}

CCP_V0_SCHEMA = {
    "sections": [
        {
            "key": "info",
            "label": "기본정보",
            "repeat": False,
            "fields": [{"key": "product", "label": "제품명", "type": "text", "required": True}],
        }
    ]
}

TEMPLATES = [
    # (type_code, version, name, schema, is_active)
    ("CCP_MONITORING", 0, "CCP 가열 모니터링(구버전)", CCP_V0_SCHEMA, False),
    ("CCP_MONITORING", 1, "CCP 가열 모니터링", CCP_SCHEMA, True),
    ("HYGIENE_CHECK", 1, "위생 점검", HYGIENE_SCHEMA, True),
]


def ensure_staff(count=5):
    for staff_id in range(1, count + 1):
        Staff.objects.get_or_create(staff_id=staff_id)


def ensure_templates():
    now = timezone.now()
    result = {}
    for type_code, version, name, schema, active in TEMPLATES:
        problems = check_template_schema(schema)
        if problems:
            raise ValueError(f"{type_code} v{version} schema_json 오류: {problems}")
        template, _ = DocumentTemplate.objects.get_or_create(
            type_code=type_code,
            version=version,
            defaults={"name": name, "schema_json": schema, "is_active": active, "created_at": now},
        )
        result[(type_code, version)] = template
    return result


def _ccp_rows(author, count=2):
    rows = [("info", 1, {"product": "유자차", "lot": "LOT-1234"})]
    for n in range(count):
        rows.append(
            (
                "rounds",
                n + 1,
                {
                    "round": f"{9 + n:02d}:00",
                    "temp": 86.0 + n,
                    "hold_sec": 16,
                    "measured_by": author,
                },
            )
        )
    return rows


def seed_documents(draft_count=24, today=None):
    """draft 문서 여러 건 + submitted/approved/rejected 각 1건 + 논리 삭제 1건."""
    today = today or timezone.localdate()
    templates = ensure_templates()
    ccp = templates[("CCP_MONITORING", 1)]
    now = timezone.now()
    created = []

    def make(n, status="draft", **extra):
        author = (n % 5) + 1
        document = Document.objects.create(
            template=ccp,
            subject=f"CCP-2B/라인{'AB'[n % 2]}",
            work_date=today - timedelta(days=n % 10),
            assignee_id=((n + 1) % 5) + 1,
            created_by_id=author,
            status=status,
            created_at=now,
            updated_at=now,
            **extra,
        )
        DocSection.objects.bulk_create(
            DocSection(
                document=document,
                section_def=k,
                row_no=r,
                values_json=v,
                recorded_at=now,
                recorded_by_id=author,
            )
            for k, r, v in _ccp_rows(author)
        )
        created.append(document)
        return document

    for n in range(draft_count):
        make(n)
    make(draft_count, "submitted", submitted_at=now)
    make(draft_count + 1, "approved", submitted_at=now)
    make(draft_count + 2, "rejected", submitted_at=now)
    make(draft_count + 3, deleted_at=now, deleted_by_id=1)
    return created
