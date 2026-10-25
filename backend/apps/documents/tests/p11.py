"""P11 테스트 준비물 (dev-notes/dashboard/p11-s2-spec.md 6장).

CCP 문서는 REQ-F02처럼 N1(get_or_create_document)으로 만든다 — record_key `CCP-{공정}|batch:{id}`.
배치 12·15·16·17(제조). 오늘은 services._today(REQ 테스트는 periodic._today도)를 바꿔
2026-10-13(화)로 고정.
"""

import datetime
from contextlib import ExitStack
from unittest import mock

from django.db import connection, transaction

from apps.documents import services
from apps.documents.models import Document
from apps.documents.tests.p4 import stub
from apps.documents.tests.p8 import setup_p8

TODAY = "2026-10-13"
BATCHES = (12, 15, 16, 17)
SPECIMENS = {k: "○" for k in ("fe_only", "sts_only")}  # 3P v2(P12 DP-03)


def setup_p11():
    templates = setup_p8()
    stub("items", id=1, name="유자")
    stub("items", id=2, name="유자차")
    stub("lots", id=88, lot_number="RM-1013-01", item_id=1, lot_kind="INCOMING",
         status="QUARANTINE")  # fmt: skip
    stub("receipt", lot_id=88, supplier_name="고흥농협", received_date=TODAY, quantity=500)
    for n, batch_id in enumerate(BATCHES, start=1):
        stub("production_batches", id=batch_id, batch_number=f"PB-1013-0{n}",
             process_type="MANUFACTURE", item_id=2, status="IN_PROGRESS")  # fmt: skip
    return templates


def fixed_today(day=TODAY, *modules):
    """DOC 오늘(+ 넘긴 모듈의 _today — REQ periodic 등)을 함께 고정(컨텍스트 관리자).

    문서 쪽 테스트는 REQ를 import하지 않는다(REQ 경계 테스트 TC-030)."""
    value = datetime.date.fromisoformat(day)
    stack = ExitStack()
    for module in (services, *modules):
        stack.enter_context(mock.patch.object(module, "_today", return_value=value))
    return stack


def ccp_doc(code, batch_id, day=TODAY):
    with transaction.atomic():
        return services.get_or_create_document(
            3,
            code,
            f"{code}|batch:{batch_id}",
            day,
            [
                {
                    "production_batch_id": batch_id,
                    "process_code": code[4:],
                    "label": f"PB-{batch_id}",
                }
            ],
            values={"info": {"item_name": "유자차", "batch_qty_kg": 1200}},
        )["document"]["document_id"]


def version_of(document_id):
    return Document.objects.values_list("version", flat=True).get(pk=document_id)


def add_rows(document_id, section_def, rows):
    """행 추가. 반환: 새 행 section_id 목록(row_no 순)."""
    before = services.get_document(document_id)
    existing = {
        s["values"].get("phase"): s
        for s in before["sections"]
        if s["section_def"] == section_def
        and s["values"].get("phase")
        in ("작업시작 전", "작업종료 후", "건조시작 전", "건조종료 전", "시작", "종료")
    }
    update, add, targets = [], [], []
    for values in rows:
        if before["template"]["type_code"] == "CCP-2B" and before["template"]["version"] >= 3:
            values = {k: v for k, v in values.items() if k not in ("dry_minutes", "time_verdict")}
        anchor = existing.get(values.get("phase"))
        if anchor:
            update.append(
                {
                    "section_id": anchor["section_id"],
                    "values": {k: v for k, v in values.items() if k != "phase"},
                }
            )
            targets.append(anchor["section_id"])
        else:
            add.append({"section_def": section_def, "values": values})
            targets.append(None)
    parts = {}
    if update:
        parts["update"] = update
    if add:
        parts["add"] = add
    result = services.update_document(
        3,
        document_id,
        {
            "expected_version": version_of(document_id),
            "sections": parts,
        },
    )
    now = [s for s in result["sections"] if s["section_def"] == section_def]
    original_ids = {s["section_id"] for s in before["sections"]}
    added = iter(
        sorted((s for s in now if s["section_id"] not in original_ids), key=lambda s: s["row_no"])
    )
    return [target if target is not None else next(added)["section_id"] for target in targets]


def at(hm, day=TODAY):
    return f"{day}T{hm}"


def r1p(hm, gauss=10500, rod="O", phase="작업 중", day=TODAY):
    return {"phase": phase, "measured_at": at(hm, day), "gauss": gauss, "rod_cleaned": rod}


def r2b(hm, temp=70.0, minutes=120, phase="작업 중", day=TODAY):
    return {"phase": phase, "measured_at": at(hm, day), "temp_c": temp, "dry_minutes": minutes}


def r3p(hm, phase="중간", day=TODAY, **override):
    row = {"phase": phase, "passed_at": at(hm, day), **SPECIMENS}
    row.update(product_only="X", product_fe="○", product_sus="○")
    row.update(override)
    return row


def summary(detected, passed=100):
    return {"passed_qty": passed, "detected_qty": detected}


def deviation(document_id, section_id=None, checkers=(3,), actor=3):
    return services.create_deviation(
        actor,
        document_id,
        {"section_id": section_id, "description": "이탈", "checker_ids": list(checkers)},
    )


def set_status(document_id, status):
    """상태만 SQL로(목록은 상태만 읽는다 — P10 테스트와 같은 방식)."""
    if status == "skipped":  # 양식 규칙과 무관하게 조건만 확인(CCP는 실제로는 작성 안 함 불가)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE document SET status = 'skipped', skipped_at = %s, skipped_by = 3, "
                "skip_reason = '휴무' WHERE document_id = %s",
                ["2026-10-13 00:00:00", document_id],
            )
        return
    done = status in ("completed", "submitted", "approved", "rejected")
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE document SET status = %s, completed_at = %s, completed_by = %s "
            "WHERE document_id = %s",
            [status, "2026-10-13 00:00:00" if done else None, 3 if done else None, document_id],
        )


def delete_doc(document_id):
    Document.objects.filter(pk=document_id).update(
        deleted_at="2026-10-13 01:00:00", deleted_by_id=3
    )


def d03_doc(lot_id=88, day=TODAY):
    with transaction.atomic():
        return services.get_or_create_document(
            3,
            "D03",
            f"D03|lot:{lot_id}",
            day,
            [{"lot_id": lot_id, "label": "RM-1013-01"}],
            values={"info": {"received_date": day, "item_name": "유자"}},
        )["document"]["document_id"]
