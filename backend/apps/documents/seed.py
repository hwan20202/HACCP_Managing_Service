"""개발·테스트용 가상 데이터 (s1-screens 7장). 실제 업무 데이터는 넣지 않는다."""

from datetime import timedelta

from django.utils import timezone

from apps.admin_settings import store as adm_store
from apps.staff import services as staff_services

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


def ensure_p4_templates():
    """스프린트 2 작성 요구 양식(D01~D03, CCP-1P·2B·3P v1). 반환: {type_code: template}."""
    from .seed_forms import P4_TEMPLATES

    made = _ensure(P4_TEMPLATES)
    return {code: made[(code, version)] for code, version, *_ in P4_TEMPLATES}


def ensure_p8_templates():
    """스프린트 3 P8 점검표 양식(D10·D12·D11 v1). 반환: {type_code: template}."""
    from .seed_forms import P8_TEMPLATES

    made = _ensure(P8_TEMPLATES)
    return {code: made[(code, version)] for code, version, *_ in P8_TEMPLATES}


def ensure_p15_templates():
    """P15 생산일지 양식(PROD-LOG v1). 반환: {type_code: template}. P4·P8과 따로(S4b a)."""
    from .seed_forms import P15_TEMPLATES

    made = _ensure(P15_TEMPLATES)
    return {code: made[(code, version)] for code, version, *_ in P15_TEMPLATES}


def ensure_staff(count=5):
    staff_services.ensure_dev_staff(range(1, count + 1))


def ensure_templates():
    return _ensure(TEMPLATES)


def _ensure(definitions):
    now = timezone.now()
    result = {}
    for type_code, version, name, schema, active in definitions:
        problems = check_template_schema(schema)
        if problems:
            raise ValueError(f"{type_code} v{version} schema_json 오류: {problems}")
        template, _ = DocumentTemplate.objects.get_or_create(
            type_code=type_code,
            version=version,
            defaults={"name": name, "schema_json": schema, "is_active": active, "created_at": now},
        )
        result[(type_code, version)] = template
    # P16 ADM-R31: 설치·활성 양식마다 문서 권한 양식 행(없을 때만 기본 구성 — 이력 없음)
    adm_store.ensure_form_rows({t.type_code for t in result.values() if t.is_active})
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


def seed_documents(draft_count=24, today=None, locked_states=True):
    """draft 문서 여러 건 + submitted/approved/rejected 각 1건 + 논리 삭제 1건.

    locked_states=False면 submitted/approved/rejected 문서를 만들지 않는다. 이 세 상태는 결재 기록과
    짝이 맞아야 하므로(WF 결합 상태), P3부터는 devtools seed_dev_workflow가 WF 함수로 만든다.
    """
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
    if locked_states:
        make(draft_count, "submitted", submitted_at=now)
        make(draft_count + 1, "approved", submitted_at=now)
        make(draft_count + 2, "rejected", submitted_at=now)
    make(draft_count + 3, deleted_at=now, deleted_by_id=1)
    return created
