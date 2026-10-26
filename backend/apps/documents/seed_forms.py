"""작성 요구 양식 정의.

항목·판정 기준은 sprints/sprint2-s0-forms.md(✅ D-051·D-057)와 같다.

모든 양식은 requirement_only(작성 요구로만 생성, P4-S1-Q1). 개선조치는 별도 테이블(D-054)이라
섹션으로 두지 않고, `deviation`은 확인 대시보드 노출 시점만 정한다(ISS-008).
"""

from copy import deepcopy

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


# P6a(D-084·D-088): 육안검사는 LOT마다 문서 1건.
# 입고 정보(읽기 전용)는 info, 검사 항목은 inspection.
# 필드 정의는 v1 `lots` 행과 같다(이름·값 그대로).
D03_V2 = {
    "requirement_only": True,
    "guide": D03["guide"],
    "sections": [
        {
            "key": "info",
            "label": "기본정보",
            "repeat": False,
            "fields": [
                _inspector(),
                *[dict(f) for f in D03["sections"][1]["fields"] if f.get("readonly")],
            ],
        },
        {
            "key": "inspection",
            "label": "검사",
            "repeat": False,
            "nonconforming": {"any": [{"field": "verdict", "eq": "FAIL"}]},
            "fields": [dict(f) for f in D03["sections"][1]["fields"] if not f.get("readonly")],
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
                _note(),  # 종이 양식 순서: 비고 → (판정)
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
                {"key": "note", "label": "특이사항", "type": "text", "max_length": 200},
            ],
        },
    ],
}

# ---------------------------------------------------------------- P12 CCP-3P v2 (캔디류 양식)
# 사용자 제공 "캔디류 ccp-3p.pdf"(DP-03): 시편 좌·중·우 → Fe만·STS만 통과 1칸씩, 행 비고 없음,
# 한계기준 유형별 2줄(기타가공품·캔디류), 개선조치방법 고정 안내. 구분(시작·중간·종료)은 남김
# (작성완료 검사 D-057·정렬 — DP-03 F3 a). 키 product_fe·product_sus는 v1과 같음(이름만 바뀜).
# v1 문서는 마이그레이션 0004가 v2로 옮긴다(ccp3p_v2.py).

CCP_3P_V2_CHECK_KEYS = ("fe_only", "sts_only", "product_only", "product_fe", "product_sus")

CCP_3P_V2 = {
    "requirement_only": True,
    "deviation": {"check_visibility": "immediate"},
    "guide": [
        {
            "title": "관리기준",
            "rows": [
                [
                    "한계기준(기타가공품)",
                    "Fe(철) 2.0mmΦ 이상 불검출, SUS(스테인리스) 2.5mmΦ 이상 불검출",
                ],
                [
                    "한계기준(캔디류)",
                    "Fe(철) 2.0mmΦ 이상 불검출, SUS(스테인리스) 2.0mmΦ 이상 불검출",
                ],
                ["점검주기", "작업시작 전, 작업 중 2시간마다, 제품 변경 시, 작업종료 후"],
                [
                    "① 표준시편 소독",
                    "사용 전 소독액으로 표준시편(Fe 2.0mmø, SUS 2.0/2.5mm)을 소독한다.",
                ],
                ["② 표준시편만 통과", "표준시편(Fe 2.0mmø, SUS 2.0/2.5mm)만을 통과시킨다."],
                [
                    "③ 표준시편과 제품 통과",
                    "표준시편(Fe 2.0mmø, SUS 2.0/2.5mm)과 제품을 놓고 통과시킨다.",
                ],
                ["④ 제품만 통과", "제품만 통과시킨다."],
                ["⑤ 사용 후 표준시편 소독", "표준시편을 소독액으로 소독 후 검편보관통에 보관한다."],
                ["※", "금속검출기는 연 1회 이상 정상작동 유무 확인"],
                ["판정", "검출 ○ / 불검출 X"],
            ],
        },
        {
            "title": "개선조치방법",
            "rows": [
                [
                    "금속성 이물 검출 시",
                    "모니터링 담당자는 즉시 금속검출기의 작업을 중지하고 "
                    "공정품을 보류하고 해당(이탈) 제품을 제거한다. "
                    "공정품에 혼입된 금속이물을 찾아내고, 그 출처를 조사하여 원인을 제거한다. "
                    "금속이물 검출 내역 및 개선조치 사항을 모니터링 일지에 기록한다.",
                ],
                [
                    "감도 이상 발생 시",
                    "모니터링 담당자는 즉시 금속검출기의 작업을 중지하고 공정품을 보류한다. "
                    "감도를 재조정한 후 정상적으로 작동 시 재가동한다. "
                    "감도이상 발생 전부터 정상운전 확인시점까지 생산된 제품을 다시 검사한다. "
                    "재검사 후 그 내역 또는 개선조치 사항을 모니터링 일지에 기록한다.",
                ],
                [
                    "기계적 고장 시",
                    "모니터링 담당자는 즉시 금속검출기의 작업을 중지하고 공정품을 보류한다. "
                    "수리 후 정상적으로 작동 시 재가동한다. "
                    "수리 불가능할 때에는 납품업체에 수리를 의뢰한다.",
                ],
                [
                    "☆",
                    "금속검출기의 고장으로 정상 운전 확인 이후에 생산된 제품과 "
                    "금속검출기 미 통과제품에 대해서는 전량 부적합품 보관장소에 보관하고 "
                    "금속검출기 수리 완료 후 전량 재통과한다.",
                ],
                [
                    "공통: 개선조치 시",
                    "문제 발생 시 HACCP팀장에게 보고 후 조치하며, "
                    "개선조치 후 모니터링 일지에 기록 후 HACCP팀장에게 승인을 받는다.",
                ],
            ],
        },
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
            "label": "금속검출기 감도 모니터링",
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
                {"key": "passed_at", "label": "통과시간", "type": "datetime", "required": True},
                *(
                    {
                        "key": key,
                        "label": label,
                        "type": "select",
                        "options": CIRCLE_X,
                        "required": True,
                    }
                    for key, label in zip(
                        CCP_3P_V2_CHECK_KEYS,
                        ("Fe만 통과", "STS만 통과", "제품만 통과", "Fe+제품 통과", "STS+제품 통과"),
                        strict=True,
                    )
                ),
                _verdict(
                    {
                        "all": [
                            {"field": "fe_only", "eq": "○"},
                            {"field": "sts_only", "eq": "○"},
                            {"field": "product_only", "eq": "X"},
                            {"field": "product_fe", "eq": "○"},
                            {"field": "product_sus", "eq": "○"},
                        ]
                    }
                ),
            ],
        },
        {
            "key": "summary",
            "label": "금속검출기 제품 통과",
            "repeat": True,
            "max_rows": 10,
            "min_rows": 1,
            "nonconforming": {"any": [{"field": "detected_qty", "gt": 0}]},
            "fields": [
                {"key": "item_name", "label": "품명", "type": "text", "max_length": 50},
                {"key": "passed_qty", "label": "통과량", "type": "number", "required": True},
                {"key": "detected_qty", "label": "검출량", "type": "number", "required": True},
                # v1 행 비고를 옮겨 오므로 500자(v1 200자 — DP-03 M2 a)
                {"key": "note", "label": "특이사항", "type": "text", "max_length": 500},
            ],
        },
    ],
}

# 고정된 시작·종료 행은 새 양식 버전에서만 적용한다. 기존 승인본은 종전 양식을 유지한다.
CCP_1P_FIXED = deepcopy(CCP_1P)
CCP_2B_FIXED = deepcopy(CCP_2B)
CCP_3P_FIXED = deepcopy(CCP_3P_V2)
for _schema in (CCP_1P_FIXED, CCP_2B_FIXED, CCP_3P_FIXED):
    _section = next(s for s in _schema["sections"] if s.get("phase_order"))
    _section["fixed_phase_rows"] = True

# 건조시간은 기록·작성완료 필수값으로 남기되 행 판정에서는 제외한다.
_dry_section = next(s for s in CCP_2B_FIXED["sections"] if s["key"] == "rounds")
_dry_verdict = next(f for f in _dry_section["fields"] if f["key"] == "verdict")
_dry_minutes = next(f for f in _dry_section["fields"] if f["key"] == "dry_minutes")
_dry_minutes.pop("limit")
_dry_verdict["computed"] = {
    "all": [{"field": "temp_c", "min": 68.0, "max": 72.0}],
    "then": "적합",
    "else": "부적합",
}
CCP_2B_FIXED["guide"][0]["rows"][0] = [
    "한계기준",
    "환: 건조온도 70℃ ± 2℃, 건조시간 2시간 ± 5분(행 판정은 온도만)",
]

# v3: 시간은 시작·종료 측정일시 차이로 종료 행에만 계산한다.
CCP_2B_ELAPSED = deepcopy(CCP_2B_FIXED)
_elapsed_section = next(s for s in CCP_2B_ELAPSED["sections"] if s["key"] == "rounds")
_elapsed_section["elapsed"] = {
    "value_field": "dry_minutes",
    "verdict_field": "time_verdict",
    "min": 115,
    "max": 125,
}
_elapsed_fields = _elapsed_section["fields"]
_elapsed_temp_verdict = next(f for f in _elapsed_fields if f["key"] == "verdict")
_elapsed_temp_verdict["label"] = "온도 판정"
_elapsed_fields.remove(_elapsed_temp_verdict)
_elapsed_fields.insert(
    next(i for i, f in enumerate(_elapsed_fields) if f["key"] == "dry_minutes"),
    _elapsed_temp_verdict,
)
_elapsed_minutes = next(f for f in _elapsed_fields if f["key"] == "dry_minutes")
_elapsed_minutes.update(label="총 건조시간", readonly=True, required=False)
_elapsed_fields.insert(
    _elapsed_fields.index(_elapsed_minutes) + 1,
    {
        "key": "time_verdict",
        "label": "시간 판정",
        "type": "select",
        "options": VERDICT,
        "readonly": True,
    },
)
_elapsed_section["nonconforming"] = {
    "any": [
        {"field": "verdict", "eq": "부적합"},
        {"field": "time_verdict", "eq": "부적합"},
    ]
}
CCP_2B_ELAPSED["guide"][0]["rows"][0] = [
    "한계기준",
    "환: 건조온도 70℃ ± 2℃, 총 건조시간 2시간 ± 5분",
]
CCP_2B_ELAPSED["guide"][0]["rows"][2] = [
    "방법",
    "건조기 판넬 온도를 기록. 총 건조시간은 시작 전·종료 전 측정일시 차이로 자동 계산",
]

# v3: 자력 한계기준을 8,000G로 낮추고 자석봉 규격을 Φ42.7로 표시한다.
CCP_1P_8000 = deepcopy(CCP_1P_FIXED)
CCP_1P_8000["guide"][0]["rows"][0] = [
    "한계기준",
    "자력 8,000 가우스 이상 / 자석봉 청소상태 확인. 자석봉 Φ42.7 사용. "
    "분말 투입량 분당 1kg, 3530rpm 고정. 금속이물(쇳가루) 10mg/kg 이하",
]
_gauss_fields = next(s for s in CCP_1P_8000["sections"] if s["key"] == "rounds")["fields"]
next(f for f in _gauss_fields if f["key"] == "gauss")["limit"]["min"] = 8000
next(f for f in _gauss_fields if f["key"] == "verdict")["computed"]["all"][0]["min"] = 8000

# (type_code, version, name, schema, is_active)
P4_TEMPLATES = [
    ("D01", 1, "시험성적서", D01, True),
    ("D02", 1, "원산지 증명/수입면장", D02, True),
    ("D03", 1, "원료/부자재 육안검사일지", D03, False),  # P6a: LOT 문서(v2)로 바뀜
    ("CCP-1P", 1, "CCP-1P 모니터링일지(쇳가루 제거)", CCP_1P, False),
    ("CCP-2B", 1, "CCP-2B 모니터링일지(건조)", CCP_2B, False),
    ("CCP-3P", 1, "CCP-3P 모니터링일지(금속검출)", CCP_3P, False),  # P12 DP-03: v2로 바뀜
    ("D03", 2, "원료/부자재 육안검사일지", D03_V2, True),
    ("CCP-3P", 2, "CCP-3P 모니터링일지(금속검출)", CCP_3P_V2, False),
    ("CCP-1P", 2, "CCP-1P 모니터링일지(쇳가루 제거)", CCP_1P_FIXED, False),
    ("CCP-1P", 3, "CCP-1P 모니터링일지(쇳가루 제거)", CCP_1P_8000, True),
    ("CCP-2B", 2, "CCP-2B 모니터링일지(건조)", CCP_2B_FIXED, False),
    ("CCP-2B", 3, "CCP-2B 모니터링일지(건조)", CCP_2B_ELAPSED, True),
    ("CCP-3P", 3, "CCP-3P 모니터링일지(금속검출)", CCP_3P_FIXED, True),
]


# ---------------------------------------------------------------- P8 (스프린트 3) 점검표 양식
# 항목·키는 dev-notes/document/p8-s0-forms.md 2~4장(✅ D-107), 규칙 키는 p8-s2-spec 2장(✅ D-109).
# 표시용 필드 키 cadence(주기)·group(관리 구분)은 화면 표의 첫 두 칸이다(검증 없음).

OX_NA = ["O", "X", "NA"]
OX_LABELS = {"O": "O", "X": "X", "NA": "해당 없음"}
EVERY_FRIDAY = {"weekday": 5}
FIRST_MONDAY = {"first_weekday_of_month": 1}


def _check(key, label, cadence, group, options=OX, **extra):
    return {
        "key": key,
        "label": label,
        "type": "select",
        "options": list(options),
        "option_labels": {k: OX_LABELS[k] for k in options},
        "required": True,
        "cadence": cadence,
        "group": group,
        **extra,
    }


def _nonconforming(fields):
    return {"any": [{"field": f["key"], "eq": "X"} for f in fields if f["type"] == "select"]}


_DAILY = "매일 작업 전후"
_D10_CHECKS = [
    _check("d_hyg_clothes", "위생복장과 외출복장이 구분하여 보관되고 있는가?", _DAILY, "개인위생"),
    _check(
        "d_hyg_health",
        "종사자의 건강상태가 양호하고 개인장신구 등을 소지하지 않으며, 청결한 위생복장을 착용하고 "
        "작업하고 있는가?",
        _DAILY,
        "개인위생",
    ),
    _check(
        "d_hyg_facility",
        "위생설비(손세척·소독기 등) 중 이상이 없으며, 종사자는 위생처리를 하고 입실하는가?",
        _DAILY,
        "개인위생",
    ),
    _check(
        "d_pest_sealed",
        "작업장은 밀폐가 잘 이루어지고 있으며, 방충시설에는 이상이 없는가?",
        _DAILY,
        "방충방서",
    ),
    _check("d_equip_broken", "파손되거나 고장난 제조설비가 있는가?", _DAILY, "설비"),
    _check(
        "d_proc_zone",
        "청결구역작업과 일반구역작업이 시간차를 두고 이루어지고 있는가?",
        _DAILY,
        "공정관리",
    ),
    _check("d_proc_ccp_record", "각 공정별 CCP 모니터링은 잘 기록되고 있는가?", _DAILY, "공정관리"),
    _check(
        "d_proc_metal",
        "금속검출기 철(Fe)Ø2.0mm이상, 스테인레스(SUS)Ø2.5mm이상 점검이 잘 이루어지고 있는가?",
        _DAILY,
        "공정관리",
    ),
    _check("d_proc_package", "완제품의 포장 상태가 양호한가?", _DAILY, "공정관리"),
    _check(
        "d_proc_monitor_clean",
        "모니터링장비(온도계 등)는 사용 전 후 세척·소독을 실시하고 있는가?",
        _DAILY,
        "공정관리",
    ),
    _check(
        "d_pest_waste",
        "작업장 주변의 폐기물은 잘 정리되어지고 있고, 주기적으로 반출되고 있는가?",
        _DAILY,
        "방충방서",
    ),
    _check(
        "d_clean_contact",
        "작업장 바닥, 배수로, 위생시설, 제조설비(식품과 직접 닿는 부분)의 청소·소독 상태는 "
        "양호한가?",
        _DAILY,
        "청소소독",
    ),
    _check(
        "d_ccp_action",
        "중요관리점(CCP) 점검표를 작성 주기에 맞게 작성하고, 한계기준 이탈시 적절히 개선조치 "
        "하였는가",
        _DAILY,
        "점검",
    ),
    _check(
        "r_incoming",
        "원·부재료 입고 시 시험성적서를 수령하거나, 육안검사를 실시하고 있는가?",
        "입고 시",
        "입고검수",
        OX_NA,
        initial="O",  # D-109: 새 문서는 O(양호)로 시작
    ),
    _check(
        "w_pest_count",
        "쥐덫, 해충유인 포획장치(날파리, 바퀴벌레 등)에 포획된 개체수는?",
        "매주(금)",
        "방충방서",
        OX_NA,
        na_default=EVERY_FRIDAY,
    ),
    _check(
        "w_clean_noncontact",
        "작업장 벽, 제조설비(제품과 직접 닿지 않는 부분)에 대한 청소·소독 상태는 양호한가?",
        "매주(금)",
        "청소소독",
        OX_NA,
        na_default=EVERY_FRIDAY,
    ),
    _check(
        "w_laundry",
        "위생복 세탁은 실시하였는가?",
        "매주(금)",
        "청소소독",
        OX_NA,
        na_default=EVERY_FRIDAY,
    ),
    _check(
        "m_clean_all",
        "작업장 전체 청소 상태는 양호한가?",
        "매월 첫째 월",
        "청소",
        OX_NA,
        na_default=FIRST_MONDAY,
    ),
    _check(
        "m_education",
        "종사자 위생교육을 실시하였는가?",
        "매월 첫째 월",
        "교육",
        OX_NA,
        na_default=FIRST_MONDAY,
    ),
    _check(
        "m_product_test",
        "완제품에 대한 검사를 실시하였는가?",
        "매월 첫째 월",
        "검사",
        OX_NA,
        na_default=FIRST_MONDAY,
    ),
    _check(
        "m_ccp_verify",
        "중요관리공정(CCP) 검증표를 작성하였는가?",
        "매월 첫째 월",
        "검증",
        OX_NA,
        na_default=FIRST_MONDAY,
    ),
    # 연간 2줄: 종이 양식처럼 실시일만(선택, O/X 없음). 비어 있으면 미기재 — 부적합으로 세지 않음
    # (P8 S4 검토 A4, D-107 변경)
    {
        "key": "y_water_test_date",
        "label": "용수검사(지하수의 경우)를 실시하였는가?",
        "type": "date",
        "cadence": "연간",
        "group": "검사",
    },
    {
        "key": "y_calibration_date",
        "label": "살균기 온도계, 유속계와 세척기 압력계 및 냉장창고의 온도계는 검·교정하였는가?",
        "type": "date",
        "cadence": "연간",
        "group": "점검",
    },
]

D10 = {
    "requirement_only": True,
    "skippable": True,
    "guide": [{"title": "표기", "rows": [["결과", "양호 O · 불량 X · 해당 없음"]]}],
    "sections": [
        {"key": "info", "label": "기본정보", "repeat": False, "fields": [_inspector()]},
        {
            "key": "checks",
            "label": "점검 항목",
            "repeat": False,
            "nonconforming": _nonconforming(_D10_CHECKS),
            "fields": _D10_CHECKS,
        },
    ],
}

_D12_ITEMS = [
    (
        "raw_vacuum",
        "원료 중의 이물혼입방지",
        "원부재료 반입 시 물품 외부에 부착된 이물을 제거하기 위하여 이물질흡입기로 이물을 "
        "제거하고 이물이 있는지 확인하였는가?",
    ),
    (
        "raw_inspect",
        "원료 중의 이물혼입방지",
        "입고된 원부재료는 검수를 실시하여 혼입된 이물이 없는지를 확인하였는가?",
    ),
    (
        "equip_clean",
        "설비의 청소상태 불량에 의한 이물혼입 방지",
        "설비의 청소상태는 양호하며 습기의 제거는 잘 되어있는지를 확인하였는가?",
    ),
    (
        "equip_gap",
        "설비의 청소상태 불량에 의한 이물혼입 방지",
        "설비의 틈새에 세척되지 않고 끼어있는 이물질이 없는지를 확인하였는가?",
    ),
    (
        "worker_pen",
        "작업자에 의한 이물혼입 방지",
        "볼펜 등 필기구는 제조라인에서 떨어진 장소에서만 사용할 수 있게 하는가?",
    ),
    (
        "worker_roller",
        "작업자에 의한 이물혼입 방지",
        "작업자는 입/출입 시 수시로 끈끈이 롤러를 사용하여 머리카락, 이물을 제거하는가?",
    ),
    (
        "worker_hair",
        "작업자에 의한 이물혼입 방지",
        "작업 중 작업자의 위생모 사이로 머리카락이 새어나와 탈락되는 경우가 없는가?",
    ),
    (
        "work_waste",
        "작업 중 이물 혼입방지",
        "작업 중 발생가능한 비닐, 테이프 등은 폐기물보관함에 즉시 버려 제조공정에 혼입될 수 "
        "없도록 관리하는가?",
    ),
    (
        "work_screw",
        "작업 중 이물 혼입방지",
        "기계류에 대한 점검을 정기적으로 실시하여 느슨하거나 탈락의 우려가 있는 나사류 등이 "
        "있는지 확인하는가?",
    ),
    (
        "work_bolt_count",
        "작업 중 이물 혼입방지",
        "기계류 등을 분해하여 세척하거나 정비할 경우 분해 한 나사, 볼트등의 숫자를 확인하여 "
        "누락이 없도록 하는가?",
    ),
    (
        "work_oil",
        "작업 중 이물 혼입방지",
        "기계류에 대한 점검을 정기적으로 실시하여 오일, 기름때가 혼입되는지 관리하였는가?",
    ),
    (
        "pack_film",
        "포장 중 이물혼입 방지",
        "작업자는 내포장재(비닐) 조각이 파손되어 제품으로 혼입될 우려가 없는지 확인하는가?",
    ),
    (
        "pack_hair",
        "포장 중 이물혼입 방지",
        "내포장 작업 중 작업자의 위생모 사이로 머리카락이 새어나와 탈락되는 경우가 없는가?",
    ),
    (
        "pest_gap",
        "해충 등의 혼입방지",
        "건물 및 출입문에 해충이 유입될 수 있는 틈새가 발생하지 않았는가?",
    ),
    ("pest_door", "해충 등의 혼입방지", "작업외부로 연결되는 출입구등은 항상 닫혀있는가?"),
]
_D12_CHECKS = [_check(key, label, "1회/일", group) for key, group, label in _D12_ITEMS]

D12 = {
    "requirement_only": True,
    "skippable": True,
    "guide": [
        {
            "title": "점검 방법",
            "rows": [
                ["점검방법", "육안확인"],
                ["점검주기", "1회/일(작업 시)"],
                ["점검결과", "O 적합 · X 부적합"],
            ],
        }
    ],
    "sections": [
        {
            "key": "info",
            "label": "기본정보",
            "repeat": False,
            "fields": [
                {
                    "key": "process_name",
                    "label": "공정명",
                    "type": "text",
                    "max_length": 50,
                    "required": True,
                },
                _inspector(),
            ],
        },
        {
            "key": "checks",
            "label": "관리 항목",
            "repeat": False,
            "nonconforming": _nonconforming(_D12_CHECKS),
            "fields": _D12_CHECKS,
        },
    ],
}

_D11_ITEMS = [
    ("fly_trap_lamp", "비행성 해충점검", "포충등은 정상작동하며 청결한가?"),
    ("fly_lure_lamp", "비행성 해충점검", "유인등은 꺼지거나 깜박임이 없이 양호한가?"),
    (
        "count_increase",
        "비행성 해충 및 설치류 점검",
        "해충등 끈끈이에 포획된 개체수가 급격히 증가하지 않았나?",
    ),
    ("food_trace", "비행성 해충 및 설치류 점검", "음식물 등의 반입 흔적은 없는가?"),
    (
        "inner_trap_rodent",
        "비행성 해충 및 설치류 점검",
        "작업장 내부트랩에 설치류가 발견되지 않았는가?",
    ),
    ("trap_position", "작업장 외부트랩 및 방역", "트랩의 위치가 변경되거나 파손되지 않았는가?"),
    ("trap_rodent", "작업장 외부트랩 및 방역", "트랩에 설치류가 포획되거나 섭식의 흔적이 없는가?"),
    (
        "outer_trap_position",
        "작업장 외부트랩 및 방역",
        "외부트랩의 위치가 변경되거나 파손되지 않았는가?",
    ),
    (
        "outer_pest_control",
        "작업장 외부트랩 및 방역",
        "정해진 주기에 따라 외부의 방역을 실시하였는가?",
    ),
]
_D11_CHECKS = [_check(key, label, "주/1회", group) for key, group, label in _D11_ITEMS]

D11 = {
    "requirement_only": True,
    "skippable": True,
    "guide": [
        {
            "title": "점검 기준",
            "rows": [
                ["작업소명", "청결구역"],
                ["점검주기", "주/1회"],
                ["평가기준", "양호 O · 상태불량 X"],
            ],
        }
    ],
    "sections": [
        {
            "key": "info",
            "label": "기본정보",
            "repeat": False,
            "fields": [
                _inspector(),
                {
                    "key": "checked_on",
                    "label": "점검일",
                    "type": "date",
                    "required": True,
                    "date_window": {"from": 0, "to": 6},  # 그 주 월~일(VR-P8-02)
                },
                {"key": "remark", "label": "특이사항", "type": "text", "max_length": 500},
            ],
        },
        {
            "key": "checks",
            "label": "점검 항목",
            "repeat": False,
            "nonconforming": _nonconforming(_D11_CHECKS),
            "fields": _D11_CHECKS,
        },
    ],
}

# (type_code, version, name, schema, is_active)
P8_TEMPLATES = [
    ("D10", 1, "일반위생관리 및 공정점검표", D10, True),
    ("D12", 1, "공정별 이물관리 점검표", D12, True),
    ("D11", 1, "방충방서점검표", D11, True),
]


# ------------------------------------------------ P15 생산일지 (ERD v7.3, D-244·D-246)
# 결재 없는 양식(approval false), 시스템 섹션 frozen_*(작성완료 때 PLG가 씀 — N13), steps.done은
# 저장 때 PLG가 계산(N12). 필수 검사는 양식 required가 아니라 PLG completion_problems(R07).
# 설치: install_document_templates --production-log
# (별도 — S4b 결정 a, 수불 테스트·QA 시드 보호).
PROD_LOG = {
    "requirement_only": True,
    "approval": False,
    "layout": "prodlog",
    "sections": [
        {
            "key": "info",
            "label": "기본정보",
            "repeat": False,
            "fields": [
                {
                    "key": "pre_label",
                    "label": "원료 적합라벨 확인",
                    "type": "select",
                    "options": ["적합", "부적합"],
                },
                {
                    "key": "pre_clean",
                    "label": "검교정 상태 후 칭량도구 청결",
                    "type": "select",
                    "options": ["적합", "부적합"],
                },
                {
                    "key": "pre_lot",
                    "label": "작업 로트·제품명 재확인",
                    "type": "select",
                    "options": ["적합", "부적합"],
                },
                {"key": "inspector", "label": "점검자", "type": "staff"},
                {"key": "template_id", "label": "불러온 템플릿", "type": "number"},
                {"key": "template_name", "label": "템플릿 이름", "type": "text", "max_length": 40},
                {"key": "template_at", "label": "불러온 시각", "type": "datetime"},
            ],
        },
        {
            "key": "materials",
            "label": "1. 원료칭량",
            "repeat": True,
            "fields": [
                {"key": "bom_line_id", "label": "BOM 줄", "type": "number"},
                {"key": "worker", "label": "작업자", "type": "staff"},
                {"key": "note", "label": "비고", "type": "text", "max_length": 100},
                {"key": "used", "label": "사용량(직접 입력)", "type": "number"},
            ],
        },
        {
            "key": "steps",
            "label": "공정",
            "repeat": True,
            "max_rows": 30,
            "fields": [
                {
                    "key": "kind",
                    "label": "기능",
                    "type": "select",
                    "options": ["CCP-1P", "CCP-2B", "CCP-3P", "INNER", "OUTER", "GEN"],
                },
                {"key": "process_id", "label": "공정", "type": "number"},
                {"key": "name", "label": "표시명", "type": "text", "max_length": 40},
                {
                    "key": "mode",
                    "label": "입력 방식",
                    "type": "select",
                    "options": ["JUDGE", "TEMP_TIME", "QTY"],
                },
                {"key": "work_date", "label": "작업일", "type": "date"},
                {"key": "worker", "label": "작업자", "type": "staff"},
                {"key": "desc", "label": "공정설명", "type": "text", "max_length": 300},
                {"key": "dur_on", "label": "소요기간 기록", "type": "bool"},
                {"key": "dur_value", "label": "소요기간", "type": "number"},
                {
                    "key": "dur_unit",
                    "label": "소요기간 단위",
                    "type": "select",
                    "options": ["분", "시간", "일"],
                },
                {
                    "key": "verdict",
                    "label": "판정",
                    "type": "select",
                    "options": ["적합", "부적합"],
                },
                {"key": "temp", "label": "온도(℃)", "type": "number"},
                {"key": "time_min", "label": "시간(분)", "type": "number"},
                {"key": "qty", "label": "작업수량", "type": "number"},
                {"key": "qty_unit", "label": "수량 단위", "type": "text", "max_length": 10},
                {"key": "spec", "label": "포장 규격", "type": "text", "max_length": 40},
                {"key": "material", "label": "포장재질", "type": "text", "max_length": 100},
                {"key": "expiry", "label": "소비기한", "type": "date"},
                {"key": "fg_qty", "label": "완제품수량", "type": "number"},
                {"key": "fg_unit", "label": "완제품 단위", "type": "text", "max_length": 10},
                {"key": "remark", "label": "특이사항", "type": "text", "max_length": 300},
                {"key": "ccp_pulled_at", "label": "CCP 값 가져온 시각", "type": "datetime"},
                {"key": "done", "label": "필수 칸 다 참(시스템)", "type": "bool", "readonly": True},
            ],
        },
        {
            "key": "frozen_batch",
            "label": "고정 기본정보",
            "repeat": False,
            "system": True,
            "fields": [
                {"key": "manufactured_date", "label": "제조일자", "type": "date", "readonly": True},
                {"key": "lot_numbers", "label": "LOT NO", "type": "text", "readonly": True},
                {"key": "product", "label": "유형 및 제품명", "type": "text", "readonly": True},
                {"key": "report_no", "label": "품목제조보고번호", "type": "text", "readonly": True},
                {"key": "planned", "label": "생산지시량", "type": "text", "readonly": True},
                {"key": "output", "label": "실생산량", "type": "text", "readonly": True},
                {"key": "frozen_at", "label": "고정 시각", "type": "datetime", "readonly": True},
            ],
        },
        {
            "key": "frozen_materials",
            "label": "고정 원료칭량",
            "repeat": True,
            "system": True,
            "fields": [
                {"key": "bom_line_id", "label": "BOM 줄", "type": "number", "readonly": True},
                {"key": "line_no", "label": "순서", "type": "number", "readonly": True},
                {"key": "item_code", "label": "원료코드", "type": "text", "readonly": True},
                {"key": "item_name", "label": "원료명", "type": "text", "readonly": True},
                {"key": "origin", "label": "원산지", "type": "text", "readonly": True},
                {"key": "ratio_e6", "label": "비율(e6)", "type": "number", "readonly": True},
                {"key": "standard_e6", "label": "투입량(e6)", "type": "number", "readonly": True},
                {"key": "used_e6", "label": "사용량(e6)", "type": "number", "readonly": True},
                {"key": "unit", "label": "단위", "type": "text", "readonly": True},
                {"key": "first_date", "label": "투입일", "type": "date", "readonly": True},
                {"key": "alternatives", "label": "대체 원료", "type": "text", "readonly": True},
            ],
        },
    ],
}

P15_TEMPLATES = [
    ("PROD-LOG", 1, "생산일지", PROD_LOG, True),
]
