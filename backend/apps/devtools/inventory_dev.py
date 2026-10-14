"""개발 전용 수불 데이터 만들기 (C2, D-128 — D-081 Q8 a).

문서 쪽 개발 도구(작성 요구 [임시] 화면, 콘솔 프리셋, 개발 시드)가 쓰는 입고 LOT·생산 배치를
수불 앱(apps.inventory) 테이블에 만든다. 수불 코드는 고치지 않고 공개 함수·모델만 쓴다.
- 입고 LOT: 수불 입고 서비스 `register_receipt`(LOT 번호·재고 이동·입고 기록·훅을 수불 규칙대로)
- 입고 LOT 문서: 수불 입고 훅이 require_for_lot을 부른다(문서 결과는 receive_lot 반환)
- 생산 배치: **개발 전용으로 직접 INSERT**(번호 PB-MMDD-nn, 상태 IN_PROGRESS). 수불 생산 서비스
  (create_batch·start_batch)는 MVP에서 반제품(SEMI)만 제조하므로 개발 품목(완제품)에는 쓰지 않는다.
  포장배치는 수불 0006으로 만들 수 없다
- 품목·공급처: 개발용 가상 기준정보(이름으로 찾거나 만듦)와 수불 기본 LOT 규칙
개발 설정(개발 콘솔)과 테스트에서만 쓴다. 운영 코드(REQ·DOC·WF·EFF)는 이 모듈을 import하지 않는다.
"""

import threading
import uuid
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

from django.db import connection
from django.utils import timezone

from apps.core.http import ApiError
from apps.inventory import document_bridge
from apps.inventory.errors import InventoryError
from apps.inventory.master_import import ensure_default_lot_rules
from apps.inventory.models import Item, Supplier
from apps.inventory.receiving import ReceiptInput, register_receipt

# (품목 코드, LOT 약어, 구분, 이름, 기준 단위, 원산지) — 가상 값
DEV_ITEMS = [
    ("1900001", "AYJ", "RAW", "유자", "kg", "국산"),
    ("2900001", "CPC", "PACKAGING", "파우치", "box", None),
    ("4900001", None, "FINISHED", "유자차", "kg", None),
    ("4900002", None, "FINISHED", "유자환", "kg", None),
]
RECEIVABLE = ("RAW", "PACKAGING")


class InventoryRejected(ApiError):
    status = 400
    code = "INVENTORY_REJECTED"
    message = "수불이 입고를 거부했습니다."


def ensure_master():
    """개발 품목 4개와 수불 기본 LOT 규칙. 반환: {품목 이름: id}."""
    ensure_default_lot_rules()
    ids = {}
    for code, short, kind, name, unit, origin in DEV_ITEMS:
        item, _ = Item.objects.get_or_create(
            item_code=code,
            defaults={
                "short_code": short,
                "item_type_id": kind,
                "name": name,
                "base_unit": unit,
                "origin_country": origin,
            },
        )
        ids[name] = item.pk
    return ids


def item_choices():
    """입고·배치 화면의 품목 선택지(활성 품목, 구분·단위 포함)."""
    rows = Item.objects.filter(is_active=True).order_by("id")
    return [
        {
            "id": item.pk,
            "name": item.name,
            "item_type": item.item_type_id,
            "base_unit": item.base_unit,
            "receivable": item.item_type_id in RECEIVABLE,
        }
        for item in rows
    ]


def is_receivable(item_id):
    return Item.objects.filter(pk=item_id, item_type_id__in=RECEIVABLE, is_active=True).exists()


def item_exists(item_id):
    return Item.objects.filter(pk=item_id).exists()


def supplier_id(name):
    """공급처를 이름으로 찾거나 만든다(개발 전용 코드 DEV-S…)."""
    found = Supplier.objects.filter(name=name).order_by("id").first()
    if found:
        return found.pk
    code = f"DEV-S{Supplier.objects.count() + 1:03d}"
    while Supplier.objects.filter(supplier_code=code).exists():
        code = f"DEV-S{uuid.uuid4().hex[:6]}"
    return Supplier.objects.create(supplier_code=code, name=name).pk


def receive(**kwargs):
    """receive_lot(...)과 같고 lot_id만 돌려준다."""
    return receive_lot(**kwargs)[0]


def receive_lot(
    *,
    item_id,
    supplier_name,
    received_date,
    quantity,
    staff_id,
    expiration_date=None,
    expiration_status=None,
    inspection=None,
    idempotency_key=None,
    documents=True,
):
    """수불 입고 서비스로 입고 LOT 1개. 반환: (lot_id, 문서 결과).

    수불 입고 훅(document_bridge.incoming_received)이 같은 트랜잭션에서 LOT 문서(D01·D02·D03)를
    만든다 — 문서 결과는 require_for_lot 반환과 같다(같은 요청 키로 다시 부르면 None).
    inspection을 주면 새 D03에 채우고 그 최종판정을 수불이 입고 판정으로 반영한다(수불 입고 화면).
    판정이 없으면 LOT은 QUARANTINE.

    idempotency_key를 주면 같은 키로 다시 불러도 입고가 늘지 않는다(수불 규칙 — 개발 시드용).
    expiration_status(수불 0007): 소비기한 유무 KNOWN(있음) / NONE(없음). 원료는 둘 중 하나여야
    입고된다. 개발 도구 기본값: 날짜가 있으면 KNOWN(수불이 정함), 없으면 NONE.
    documents=False: 문서 없이 LOT만 — 훅 연결 전에 입고된 LOT 흉내(P7 S5 "문서 없음" 줄 확인용).
    """
    if expiration_status is None and expiration_date is None:
        expiration_status = "NONE"
    ensure_default_lot_rules()  # 수불 기본 LOT 번호 규칙(없을 때만 만듦)
    data = ReceiptInput(
        item_id=item_id,
        supplier_id=supplier_id(supplier_name),
        staff_id=staff_id,
        received_date=received_date,
        quantity=Decimal(str(quantity)),
        idempotency_key=idempotency_key or f"dev-{uuid.uuid4().hex}",
        expiration_date=expiration_date,
        expiration_status=expiration_status,
        inspection=inspection,
    )
    try:
        if documents:
            receipt = register_receipt(data)
        else:
            with _without_lot_documents():
                receipt = register_receipt(data)
    except InventoryError as error:  # 수불 입고 규칙 거부(예: 미래 입고일) → 400
        raise InventoryRejected(str(error)) from error
    return receipt.lot_id, receipt.documents


_HOOK_LOCK = threading.Lock()


@contextmanager
def _without_lot_documents():
    """개발 전용: 입고 훅을 잠시 빈 함수로(문서 없는 예전 LOT 흉내). 운영 코드는 쓰지 않는다."""
    with _HOOK_LOCK, patch.object(document_bridge, "incoming_received", lambda **_: None):
        yield


def _planned_e6(item_id, quantity_kg):
    """화면의 생산량(kg) → 품목 기준 단위 수량 ×10⁶. 0이거나 바꿀 수 없으면 None."""
    if not quantity_kg:
        return None
    item = Item.objects.get(pk=item_id)
    kg = Decimal(str(quantity_kg))
    if item.base_unit == "kg":
        amount = kg
    elif item.base_unit == "g":
        amount = kg * 1000
    elif item.unit_weight_mg:
        amount = kg * 1_000_000 / item.unit_weight_mg
    else:
        return None
    return int(amount * 1_000_000)


def make_batch(*, item_id, process_type, manufactured_date, quantity_kg, staff_id, notes=None):
    """개발 전용 생산 배치(IN_PROGRESS). 번호는 같은 INSERT 안에서 계산(PB-MMDD-nn). 반환: id.

    notes를 주면 같은 notes 배치가 있을 때 새로 만들지 않고 그 id를 돌려준다(개발 시드용).
    """
    if process_type == "PACKAGING":  # 수불 0006: 포장배치는 MVP 범위 밖(새로 만들지 않음)
        raise InventoryRejected("포장배치는 이번 범위(입고 ~ 제조 벌크 산출)에서 만들지 않습니다.")
    if notes:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM production_batches WHERE notes = %s", [notes])
            row = cursor.fetchone()
        if row:
            return row[0]
    prefix = f"PB-{manufactured_date:%m%d}-"
    started = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO production_batches (batch_number, process_type, item_id, status,"
            " manufactured_date, planned_quantity_e6, started_at, staff_id, notes) "
            "SELECT %s || printf('%%02d', COALESCE(MAX(CAST(substr(batch_number, %s) AS INTEGER)),"
            " 0) + 1), %s, %s, 'IN_PROGRESS', %s, %s, %s, %s, %s "
            "FROM production_batches WHERE batch_number LIKE %s",
            [
                prefix,
                len(prefix) + 1,
                process_type,
                item_id,
                manufactured_date.isoformat(),
                _planned_e6(item_id, quantity_kg),
                started,
                staff_id,
                notes,
                prefix + "%",
            ],
        )
        return cursor.lastrowid


def use_lot(lot_id, staff_id):
    """수불 기준 "사용된 LOT"(입고 외 이동, P1) — 재고조정(감소) 1 기준 단위."""
    from apps.inventory.movements import adjust_stock

    adjust_stock(
        lot_id=lot_id,
        direction="OUT",
        quantity=Decimal("1"),
        reason="개발 콘솔 준비: 사용된 LOT 흉내",
        staff_id=staff_id,
        idempotency_key=f"dev-use-{uuid.uuid4().hex}",
    )


def touch_lot(lot_id):
    """다시 호출 전 자기 쓰기(LOT updated_at). 반환: 영향 행 수."""
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE lots SET status = status WHERE id = %s AND lot_kind = 'INCOMING'", [lot_id]
        )
        return cursor.rowcount


def touch_batch(batch_id):
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE production_batches SET updated_at = updated_at WHERE id = %s", [batch_id]
        )
        return cursor.rowcount


def lot_number(lot_id):
    with connection.cursor() as cursor:
        cursor.execute("SELECT lot_number FROM lots WHERE id = %s", [lot_id])
        row = cursor.fetchone()
    return row[0] if row else None


__all__ = [
    "DEV_ITEMS",
    "ensure_master",
    "item_choices",
    "is_receivable",
    "item_exists",
    "supplier_id",
    "receive",
    "receive_lot",
    "make_batch",
    "use_lot",
    "touch_lot",
    "touch_batch",
    "lot_number",
]
