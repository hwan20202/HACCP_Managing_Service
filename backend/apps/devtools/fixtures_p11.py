"""P11 개발 콘솔 프리셋 사전 조건 (dev-notes/dashboard/p11-s2-spec.md 4.1, A5 a — ISS-019 방식).

모두 실제 공개 함수(개발 배치 → REQ-F02 → DOC 행 저장·F19·F31·작성완료)로 만든다. 개발 설정에서만.

POST /api/dev/fixtures/ccp {
  work_date: YYYY-MM-DD          (기본 오늘, 미래 불가 — 배치 생산일 = 문서 작업일),
  batches: 1~5                   (기본 2 — 제조 배치, 품목 유자차, 배치마다 CCP-1P·2B·3P),
  rows: [{process: 1P|2B|3P, batch: n(1부터), values: {...}}]
        (측정 섹션에 행 추가. values는 정상 행 기본값 위에 덮어씀 — 1P·2B rounds, 3P checks.
         기본 측정시점: 행이 2개 이상이면 첫 행 처음·마지막 행 끝, 나머지 중간),
  deviations: [{process, batch, row?: n(그 문서 측정 행 순서, 1부터 — 없으면 행 없이),
                checker_ids: [..], checked_by?: staff}],
  status: {"CCP-2B": "completed"}  (그 양식 문서를 작성완료로 — 측정 행 2개 이상 필요)
}
→ 201 {work_date, batches: [{batch_id, label, documents: {"1P": id, …}}], deviations: [id…]}
"""

import datetime

from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.core.http import ApiError, error_response, json_response, parse_json_body
from apps.doc_requirements import services as req
from apps.documents import services as doc

from . import inventory_dev
from .fixtures import ACTOR, _bad

PROCESSES = ("1P", "2B", "3P")
KEYS = ("work_date", "batches", "rows", "deviations", "status")
SECTION = {"1P": "rounds", "2B": "rounds", "3P": "checks"}
_SPECIMENS = {k: "○" for k in ("fe_only", "sts_only")}  # 3P v2(P12 DP-03)
# 측정시점(처음·중간·끝): 행이 2개 이상이면 첫 행 = 처음, 마지막 행 = 끝(작성완료 phase_order)
PHASES = {
    "1P": ("작업시작 전", "작업 중", "작업종료 후"),
    "2B": ("건조시작 전", "작업 중", "건조종료 전"),
    "3P": ("시작", "중간", "종료"),
}


def _good(process, day, n, total):
    at = f"{day.isoformat()}T{8 + n:02d}:00"
    first, middle, last = PHASES[process]
    phase = first if n == 1 and total > 1 else last if n == total and total > 1 else middle
    if process == "1P":
        return {"phase": phase, "measured_at": at, "gauss": 10500, "rod_cleaned": "O"}
    if process == "2B":
        return {"phase": phase, "measured_at": at, "temp_c": 70.0, "dry_minutes": 120}
    return {
        "phase": phase,
        "passed_at": at,
        **_SPECIMENS,
        "product_only": "X",
        "product_fe": "○",
        "product_sus": "○",
    }


def _clean(body):
    unknown = [k for k in body if k not in KEYS]
    if unknown:
        raise _bad(f"알 수 없는 항목: {', '.join(unknown)}")
    today = timezone.localdate()
    raw = body.get("work_date")
    if raw is None:
        day = today
    else:
        try:
            if not isinstance(raw, str) or len(raw) != 10:
                raise ValueError(raw)
            day = datetime.date.fromisoformat(raw)
        except ValueError:
            raise _bad("work_date는 YYYY-MM-DD입니다.") from None
        if day > today:
            raise _bad("work_date는 오늘 이후일 수 없습니다.")
    batches = body.get("batches", 2)
    if isinstance(batches, bool) or not isinstance(batches, int) or not 1 <= batches <= 5:
        raise _bad("batches는 1~5입니다.")
    rows = body.get("rows", [])
    deviations = body.get("deviations", [])
    if not isinstance(rows, list) or not isinstance(deviations, list):
        raise _bad("rows·deviations는 목록입니다.")
    for item in [*rows, *deviations]:
        if not isinstance(item, dict) or item.get("process") not in PROCESSES:
            raise _bad("process는 1P·2B·3P입니다.")
        n = item.get("batch", 1)
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= batches:
            raise _bad(f"batch는 1~{batches}입니다.")
    for item in rows:
        if not isinstance(item.get("values", {}), dict):
            raise _bad("rows.values는 필드 값 객체입니다.")
    for item in deviations:
        row = item.get("row")
        if row is not None and (isinstance(row, bool) or not isinstance(row, int) or row < 1):
            raise _bad("deviations.row는 1 이상의 정수입니다.")
        checker_ids = item.get("checker_ids", [])
        if not isinstance(checker_ids, list) or any(
            isinstance(staff_id, bool) or not isinstance(staff_id, int) or staff_id < 1
            for staff_id in checker_ids
        ):
            raise _bad("deviations.checker_ids는 직원 ID 목록입니다.")
        checked_by = item.get("checked_by")
        if checked_by is not None and (
            isinstance(checked_by, bool) or not isinstance(checked_by, int) or checked_by < 1
        ):
            raise _bad("deviations.checked_by는 직원 ID입니다.")
    status = body.get("status") or {}
    if not isinstance(status, dict) or any(
        k not in [f"CCP-{p}" for p in PROCESSES] or v != "completed" for k, v in status.items()
    ):
        raise _bad('status는 {"CCP-1P": "completed"} 모양입니다.')
    return day, batches, rows, deviations, status


def _version(document_id):
    return doc.get_document(document_id)["version"]


def _add_rows(document_id, section_def, values_list):
    detail = doc.get_document(document_id)
    info = next(s for s in detail["sections"] if s["section_def"] == "info")
    sections = {"update": [{"section_id": info["section_id"], "values": {"inspector": 4}}]}
    if values_list:
        sections["add"] = [{"section_def": section_def, "values": v} for v in values_list]
    doc.update_document(
        ACTOR, document_id, {"expected_version": detail["version"], "sections": sections}
    )
    rows = [s for s in doc.get_document(document_id)["sections"] if s["section_def"] == section_def]
    return sorted(rows, key=lambda s: s["row_no"])


@csrf_exempt
@require_http_methods(["POST"])
def ccp_fixture(request):
    try:
        day, count, rows, deviations, status = _clean(parse_json_body(request))
        items = inventory_dev.ensure_master()
        made, dev_ids = [], []
        with transaction.atomic():
            for n in range(1, count + 1):
                batch_id = inventory_dev.make_batch(
                    item_id=items["유자차"],
                    process_type="MANUFACTURE",
                    manufactured_date=day,
                    quantity_kg=1200,
                    staff_id=ACTOR,
                )
                result = req.require_for_batch(ACTOR, batch_id)
                documents = {d["process_code"]: d["document_id"] for d in result["documents"]}
                made.append(
                    {
                        "batch_id": batch_id,
                        "label": inventory_dev_label(batch_id),
                        "documents": documents,
                    }
                )
            saved = {}
            for n, batch in enumerate(made, start=1):
                for process in PROCESSES:
                    wanted = [r for r in rows if r["process"] == process and r.get("batch", 1) == n]
                    values = [
                        {**_good(process, day, i, len(wanted)), **(r.get("values") or {})}
                        for i, r in enumerate(wanted, start=1)
                    ]
                    document_id = batch["documents"][process]
                    saved[(process, n)] = _add_rows(document_id, SECTION[process], values)
            for item in deviations:
                n, process = item.get("batch", 1), item["process"]
                document_id = made[n - 1]["documents"][process]
                section_id = None
                if item.get("row") is not None:
                    rows_of = saved[(process, n)]
                    if not 1 <= item["row"] <= len(rows_of):
                        raise _bad(f"{process} 배치 {n}에 {item['row']}번째 행이 없습니다.")
                    section_id = rows_of[item["row"] - 1]["section_id"]
                out = doc.create_deviation(
                    ACTOR,
                    document_id,
                    {
                        "section_id": section_id,
                        "description": "콘솔 준비 — 한계기준 이탈",
                        "action_result": "재측정",
                        "checker_ids": item.get("checker_ids") or [],
                    },
                )
                if item.get("checked_by") is not None:
                    out = doc.check_deviation(
                        item["checked_by"], out["deviation_id"], out["version"]
                    )
                dev_ids.append(out["deviation_id"])
            for code in status:
                process = code[4:]
                for batch in made:
                    document_id = batch["documents"][process]
                    doc.complete_document(ACTOR, document_id, _version(document_id))
        return json_response(
            {"work_date": day.isoformat(), "batches": made, "deviations": dev_ids}, status=201
        )
    except ApiError as error:
        return error_response(error)


def inventory_dev_label(batch_id):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT batch_number FROM production_batches WHERE id = %s", [batch_id])
        row = cursor.fetchone()
    return row[0] if row else None
