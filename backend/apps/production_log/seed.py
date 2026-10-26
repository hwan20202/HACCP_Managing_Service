"""개발 시드(S2 Q6 a, 운영 제외): 일반 공정 9·템플릿 3, 기본 제공 설명.

값은 엑셀 생산일지 3종 정리(PoC `prodlog-suite.html` seed)와 같다.
다시 실행해도 있는 것은 그대로 둔다.
"""

from django.db import transaction

from . import services
from .models import Process, ProcessTemplate

BUILTIN_DEFAULTS = {
    "CCP-1P": (
        "분쇄한 원료를 쇳가루 제거작업을 한다. [자력: 1만가우스 / 제거속도: 3530r/min]",
        None,
    ),
    "CCP-2B": ("건조기에 건조한다. [온도 70±2℃ 2시간±5분]", {"value": 2, "unit": "시간"}),
    "CCP-3P": ("건조한 제품을 금속검출기에 넣고 검사한다.", None),
    "INNER": ("원료를 포장재에 담아 밀봉한다.", None),
}

GENERAL = [
    ("분쇄", "JUDGE", "분쇄기를 가동하여 깨끗한 원료들을 곱게 분쇄한다.", None),
    ("혼합 - 제환 - 환주", "JUDGE", "쇳가루 제거한 원료를 혼합하여 환(성형)을 한다.", None),
    ("추출", "TEMP_TIME", "90~100℃에서 24~36시간 추출한다.", None),
    ("농축 및 살균", "TEMP_TIME", "100℃에서 5분 열처리한다.", {"value": 5, "unit": "분"}),
    ("건조 (SD건조기)", "JUDGE", "SD건조기에 건조한다.", None),
    ("접종", "JUDGE", "발효홍국균을 접종한다.", {"value": 1, "unit": "일"}),
    ("배양", "JUDGE", "소독한 배양기에 배양한다.", {"value": 3, "unit": "일"}),
    ("저온건조", "JUDGE", "저온건조기에 넣어 건조시킨다.", {"value": 2, "unit": "일"}),
    # S4a 리뷰 A4 b: EXO 살균은 CCP-2B가 아니라 일반 공정(온도·시간)
    (
        "살균 (건조)",
        "TEMP_TIME",
        "자외선으로 살균처리 후 70℃에서 2시간 열처리한다.",
        {"value": 2, "unit": "시간"},
    ),
]

# 단계: 공정 이름(일반) 또는 기능(기본 제공), 덮어쓸 값
TEMPLATES = [
    (
        "효력환",
        [
            ("분쇄", {}),
            ("CCP-1P", {}),
            ("혼합 - 제환 - 환주", {}),
            ("CCP-2B", {"desc": "성형한 환을 건조기에 건조한다. [온도 70±2℃ 2시간±5분]"}),
            ("INNER", {"name": "내포장 작업", "spec": "1환 3.75 g", "qty_unit": "환"}),
            ("CCP-3P", {}),
            ("OUTER", {"material": "내부: 종이, 용기: 폴리프로필렌(PP)"}),
        ],
    ),
    (
        "녹용농축분말",
        [
            ("추출", {}),
            ("농축 및 살균", {}),
            ("건조 (SD건조기)", {"name": "건조"}),
            ("CCP-1P", {"desc": "쇳가루 제거작업을 한다. [자력: 1만가우스 / 제거속도: 3530r/min]"}),
            ("INNER", {"spec": "개중량 8 g"}),
            ("CCP-3P", {}),
            ("OUTER", {"material": "폴리에틸렌(PE), PET"}),
        ],
    ),
    (
        "EXO-Boost 발효녹용",
        [
            ("살균 (건조)", {}),
            ("접종", {}),
            ("배양", {}),
            ("저온건조", {}),
            ("INNER", {"spec": "500 g 포장"}),
            ("CCP-3P", {"desc": "제품을 금속검출기에 넣고 검사한다."}),
            ("OUTER", {"material": "폴리에틸렌(PE), PET"}),
        ],
    ),
]


def seed_production_master(actor_id):
    """반환: {processes: 새 일반 공정, templates: 새 템플릿, builtins: 설명 채운 기본 제공} 수."""
    made = {"processes": 0, "templates": 0, "builtins": 0}
    with transaction.atomic():
        for kind, (desc, duration) in BUILTIN_DEFAULTS.items():
            p = Process.objects.get(kind=kind)
            if p.description is None and p.std_duration_value is None:
                services.update_process(
                    actor_id,
                    p.pk,
                    {"description": desc, "std_duration": duration},
                    p.version,
                )
                made["builtins"] += 1
        by_name = {p.name_key: p for p in Process.objects.filter(is_active=True)}
        for name, mode, desc, duration in GENERAL:
            if services.name_key(name) in by_name:
                continue
            out = services.create_process(
                actor_id,
                {
                    "name": name,
                    "mode": mode,
                    "description": desc,
                    "std_duration": duration,
                    "confirm_similar": True,
                },
            )
            by_name[services.name_key(name)] = Process.objects.get(pk=out["process_id"])
            made["processes"] += 1
        builtin = {p.kind: p for p in Process.objects.filter(is_builtin=True)}
        existing = set(
            ProcessTemplate.objects.filter(is_active=True).values_list("name_key", flat=True)
        )
        for name, steps in TEMPLATES:
            if services.name_key(name) in existing:
                continue
            rows = [
                {
                    "process_id": (builtin.get(key) or by_name[services.name_key(key)]).pk,
                    "overrides": overrides,
                }
                for key, overrides in steps
            ]
            services.create_template(
                actor_id, {"name": name, "steps": rows, "confirm_similar": True}
            )
            made["templates"] += 1
    return made
