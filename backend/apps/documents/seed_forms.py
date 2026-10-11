"""스프린트 2 작성 요구 양식 정의(v1).

항목·판정 기준은 sprints/sprint2-s0-forms.md(✅ D-051·D-057)와 같다.

모든 양식은 requirement_only(작성 요구로만 생성, P4-S1-Q1). 개선조치는 별도 테이블(D-054)이라
섹션으로 두지 않고, `deviation`은 확인 대시보드 노출 시점만 정한다(ISS-008).
"""

GOOD_BAD = ["양호", "불량"]
OX = ["O", "X"]
CIRCLE_X = ["○", "X"]
VERDICT = ["적합", "부적합"]
NONCONFORMING = {"any": [{"field": "verdict", "eq": "부적합"}]}


def _ro(key, label, type_="text", **extra):
    return {"key": key, "label": label, "type": type_, "readonly": True, **extra}


def _verdict(condition):
    return {
        "key": "verdict",
        "label": "판정",
        "type": "select",
        "options": VERDICT,
        "computed": {**condition, "then": "적합", "else": "부적합"},
    }


def _inspector():
    return {"key": "inspector", "label": "점검자", "type": "staff", "required": True}


def _note():
    return {"key": "note", "label": "비고", "type": "text", "max_length": 200}


def _lot_info():
    return [
        _ro("lot_number", "LOT"),
        _ro("item_name", "품명"),
        _ro("supplier_name", "매입처"),
        _ro("received_date", "입고일", "date"),
    ]


D01 = {
    "requirement_only": True,
    "files": {"min": 1},
    "guide": [{"title": "안내", "rows": [["첨부", "해당 LOT의 시험성적서(PDF·JPG·PNG)"]]}],
    "sections": [
        {"key": "info", "label": "기본정보", "repeat": False, "fields": [*_lot_info(), _note()]}
    ],
}

D02 = {
    "requirement_only": True,
    "files": {"min": 1, "kinds": ["원산지 증명", "수입면장"]},
    "guide": [{"title": "안내", "rows": [["첨부", "원산지 증명서 또는 수입면장"]]}],
    "sections": [
        {
            "key": "info",
            "label": "기본정보",
            "repeat": False,
            "fields": [
                *_lot_info(),
                {
                    "key": "doc_kind",
                    "label": "서류 종류",
                    "type": "select",
                    "options": ["원산지 증명", "수입면장"],
                    "required": True,
                },
                _note(),
            ],
        }
    ],
}

D03 = {
    "requirement_only": True,
    "guide": [
        {
            "title": "검사 기준",
            "rows": [
                ["성상 및 이물혼입", "원료 고유의 색택, 오염·이물 없음"],
                ["외/내포장", "외포장 파손·내부 오염 흔적 없음, 내포장 훼손 없음"],
                ["표시사항", "제품별 표기사항 정확"],
                ["파렛트", "외부오염·파손 없음, 빗물에 젖지 않음(기준 문구만, F3)"],
            ],
        }
    ],
    "sections": [
        {"key": "info", "label": "기본정보", "repeat": False, "fields": [_inspector()]},
        {
            "key": "lots",
            "label": "LOT별 검사",
            "repeat": True,
            "system_rows": True,
            "max_rows": 200,
            "nonconforming": {"any": [{"field": "verdict", "eq": "FAIL"}]},
            "fields": [
                _ro("lot_number", "LOT"),
                _ro("received_date", "입고일", "date"),
                _ro("supplier_name", "매입처"),
                _ro("material_kind", "구분"),
                _ro("item_name", "품명"),
                _ro("quantity", "중량"),
                _ro("expiration_date", "소비기한", "date"),
                {
                    "key": "appearance",
                    "label": "성상 및 이물혼입",
                    "type": "select",
                    "options": GOOD_BAD,
                    "required": True,
                },
                {
                    "key": "packaging",
                    "label": "외/내포장",
                    "type": "select",
                    "options": GOOD_BAD,
                    "required": True,
                },
                {
                    "key": "labeling",
                    "label": "표시사항",
                    "type": "select",
                    "options": GOOD_BAD,
                    "required": True,
                },
                {
                    "key": "verdict",
                    "label": "최종판정",
                    "type": "select",
                    "options": ["PASS", "FAIL"],
                    "option_labels": {"PASS": "적합", "FAIL": "부적합"},
                    "required": True,
                },
                {
                    "key": "has_coa",
                    "label": "시험성적서",
                    "type": "select",
                    "options": ["유", "무"],
                    "hint": {"kind": "file_exists", "type_code": "D01"},
                },
            ],
        },
    ],
}


def _phase_order(field, time_field, first, last):
    return {"field": field, "time_field": time_field, "first": first, "last": last}


CCP_1P = {
    "requirement_only": True,
    "deviation": {"check_visibility": "immediate"},
    "guide": [
        {
            "title": "관리기준",
            "rows": [
                [
                    "한계기준",
                    "자력 10,000 가우스 이상 / 자석봉 청소상태 확인. 자석봉 8개 사용. "
                    "분말 투입량 분당 1kg, 3530rpm 고정. 금속이물(쇳가루) 10mg/kg 이하",
                ],
                [
                    "주기",
                    "작업 시작 전(자력 측정, 자석봉 청소상태 확인), 작업 중 1시간마다 자석봉 청소",
                ],
                [
                    "방법",
                    "가우스미터로 자력 측정, 자석봉 청소. "
                    "공정품을 식품공전 금속성이물 시험법으로 검사. "
                    "가우스미터 연 1회 검·교정",
                ],
            ],
        }
    ],
    "sections": [
        {
            "key": "info",
            "label": "기본정보",
            "repeat": False,
            "fields": [
                _ro("item_name", "품명"),
                _ro("batch_qty_kg", "중량(kg)", "number"),
                _inspector(),
            ],
        },
        {
            "key": "rounds",
            "label": "측정 기록",
            "repeat": True,
            "max_rows": 48,
            "min_rows": 2,
            "phase_order": _phase_order("phase", "measured_at", "작업시작 전", "작업종료 후"),
            "nonconforming": NONCONFORMING,
            "fields": [
                {
                    "key": "phase",
                    "label": "측정시점",
                    "type": "select",
                    "options": ["작업시작 전", "작업 중", "작업종료 후"],
                    "required": True,
                },
                {"key": "measured_at", "label": "측정일시", "type": "datetime", "required": True},
                {
                    "key": "gauss",
                    "label": "자력(G)",
                    "type": "number",
                    "required": True,
                    "limit": {"min": 10000},
                },
                {
                    "key": "rod_cleaned",
                    "label": "자석봉 청소",
                    "type": "select",
                    "options": OX,
                    "required": True,
                },
                _verdict(
                    {"all": [{"field": "gauss", "min": 10000}, {"field": "rod_cleaned", "eq": "O"}]}
                ),
                _note(),
            ],
        },
    ],
}

CCP_2B = {
    "requirement_only": True,
    "deviation": {"check_visibility": "immediate"},
    "guide": [
        {
            "title": "관리기준",
            "rows": [
                ["한계기준", "환: 건조온도 70℃ ± 2℃, 건조시간 2시간 ± 5분"],
                ["주기", "건조 시작 전, 작업 중, 건조 종료 전"],
                ["방법", "건조기 판넬의 온도·시간 확인 후 기록. 온도계·타이머 연 1회 검·교정"],
            ],
        }
    ],
    "sections": [
        {
            "key": "info",
            "label": "기본정보",
            "repeat": False,
            "fields": [
                _ro("item_name", "품명"),
                _ro("batch_qty_kg", "중량(kg)", "number"),
                _inspector(),
            ],
        },
        {
            "key": "rounds",
            "label": "측정 기록",
            "repeat": True,
            "max_rows": 48,
            "min_rows": 2,
            "phase_order": _phase_order("phase", "measured_at", "건조시작 전", "건조종료 전"),
            "nonconforming": NONCONFORMING,
            "fields": [
                {
                    "key": "phase",
                    "label": "측정시점",
                    "type": "select",
                    "options": ["건조시작 전", "작업 중", "건조종료 전"],
                    "required": True,
                },
                {"key": "measured_at", "label": "측정일시", "type": "datetime", "required": True},
                {
                    "key": "temp_c",
                    "label": "건조온도(℃)",
                    "type": "number",
                    "required": True,
                    "limit": {"min": 68.0, "max": 72.0},
                },
                {
                    "key": "dry_minutes",
                    "label": "건조시간",
                    "type": "number",
                    "unit": "분",
                    "display": "hm",
                    "required": True,
                    "limit": {"min": 115, "max": 125},
                },
                _verdict(
                    {
                        "all": [
                            {"field": "temp_c", "min": 68.0, "max": 72.0},
                            {"field": "dry_minutes", "min": 115, "max": 125},
                        ]
                    }
                ),
                _note(),
            ],
        },
    ],
}

_SPECIMENS = ("fe_l", "fe_c", "fe_r", "sus_l", "sus_c", "sus_r")
_SPECIMEN_LABELS = ("Fe 좌", "Fe 중", "Fe 우", "SUS 좌", "SUS 중", "SUS 우")

CCP_3P = {
    "requirement_only": True,
    "deviation": {"check_visibility": "immediate"},
    "guide": [
        {
            "title": "관리기준",
            "rows": [
                ["한계기준", "Fe(철) 2.0mmΦ 이상 불검출, SUS(스테인리스) 2.5mmΦ 이상 불검출"],
                ["점검주기", "작업 시작 전, 작업 중 2시간마다, 제품 변경 시, 작업 종료 후"],
                [
                    "방법",
                    "① 표준시편 소독 ② 표준시편만 통과(좌/중/우) ③ 표준시편과 제품 통과 "
                    "④ 제품만 통과 ⑤ 사용 후 표준시편 소독·보관. 연 1회 이상 정상작동 확인",
                ],
                ["표기", "검출 ○ / 불검출 X"],
            ],
        }
    ],
    "sections": [
        {
            "key": "info",
            "label": "기본정보",
            "repeat": False,
            "fields": [
                _ro("item_name", "품명"),
                _ro("batch_qty_kg", "중량(kg)", "number"),
                _inspector(),
            ],
        },
        {
            "key": "checks",
            "label": "감도·통과 점검",
            "repeat": True,
            "max_rows": 48,
            "min_rows": 2,
            "phase_order": _phase_order("phase", "passed_at", "시작", "종료"),
            "nonconforming": NONCONFORMING,
            "fields": [
                {
                    "key": "phase",
                    "label": "구분",
                    "type": "select",
                    "options": ["시작", "중간", "종료"],
                    "required": True,
                },
                {"key": "passed_at", "label": "통과일시", "type": "datetime", "required": True},
                *(
                    {
                        "key": key,
                        "label": label,
                        "type": "select",
                        "options": CIRCLE_X,
                        "required": True,
                    }
                    for key, label in zip(_SPECIMENS, _SPECIMEN_LABELS, strict=True)
                ),
                {
                    "key": "product_only",
                    "label": "제품만",
                    "type": "select",
                    "options": CIRCLE_X,
                    "required": True,
                },
                {
                    "key": "product_fe",
                    "label": "제품+Fe",
                    "type": "select",
                    "options": CIRCLE_X,
                    "required": True,
                },
                {
                    "key": "product_sus",
                    "label": "제품+SUS",
                    "type": "select",
                    "options": CIRCLE_X,
                    "required": True,
                },
                _verdict(
                    {
                        "all": [
                            *({"field": key, "eq": "○"} for key in _SPECIMENS),
                            {"field": "product_only", "eq": "X"},
                            {"field": "product_fe", "eq": "○"},
                            {"field": "product_sus", "eq": "○"},
                        ]
                    }
                ),
                _note(),
            ],
        },
        {
            "key": "summary",
            "label": "제품 통과 요약",
            "repeat": True,
            "max_rows": 10,
            "min_rows": 1,
            "nonconforming": {"any": [{"field": "detected_qty", "gt": 0}]},
            "fields": [
                {"key": "item_name", "label": "품명", "type": "text", "max_length": 50},
                {"key": "passed_qty", "label": "통과량", "type": "number", "required": True},
                {"key": "detected_qty", "label": "검출량", "type": "number", "required": True},
                _note(),
            ],
        },
    ],
}

# (type_code, version, name, schema, is_active)
P4_TEMPLATES = [
    ("D01", 1, "시험성적서", D01, True),
    ("D02", 1, "원산지 증명/수입면장", D02, True),
    ("D03", 1, "원료/부자재 육안검사일지", D03, True),
    ("CCP-1P", 1, "CCP-1P 모니터링일지(쇳가루 제거)", CCP_1P, True),
    ("CCP-2B", 1, "CCP-2B 모니터링일지(건조)", CCP_2B, True),
    ("CCP-3P", 1, "CCP-3P 모니터링일지(금속검출)", CCP_3P, True),
]
