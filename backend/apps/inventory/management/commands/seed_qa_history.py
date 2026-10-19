"""Append isolated historical QA transactions without replaying the reference seed."""

import calendar
import datetime
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory.errors import InventoryError
from apps.inventory.fields import kst_now
from apps.inventory.holds import hold_lot
from apps.inventory.ledger import stock_ledger
from apps.inventory.lot_numbers import find_rule
from apps.inventory.management.commands.seed_qa_inventory import Command as ReferenceCommand
from apps.inventory.models import (
    AuditLog,
    Bom,
    Inventory,
    Item,
    Lot,
    LotNumberRule,
    Staff,
    StockMovement,
    Supplier,
)
from apps.inventory.movements import adjust_stock, correct_movement, dispose, return_to_supplier
from apps.inventory.production import (
    add_output,
    add_usage,
    add_usages,
    complete_batch,
    create_batch,
    start_batch,
)
from apps.inventory.quantity import from_e6, to_e6
from apps.inventory.receiving import ReceiptInput, cancel_receipt, register_receipt

MARKER = "history-v1"
MONTH_OFFSETS = (12, 11, 7, 5, 2, 1, 0)


def month_start(day, months):
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    return datetime.date(year, month + 1, 1)


class Command(BaseCommand):
    help = "기존 QA DB에 월별 이력 추가. 기본은 계획 확인, --apply일 때 백업 후 적재"

    def add_arguments(self, parser):
        parser.add_argument("--date", help="고정 기준일 YYYY-MM-DD (기본 KST 오늘)")
        parser.add_argument("--apply", action="store_true", help="계획을 실제 QA DB에 추가")

    def handle(self, *args, **options):
        environment = getattr(settings, "HACCP_ENVIRONMENT", "production")
        if not (environment == "qa" and getattr(settings, "HACCP_QA_SEED_ENABLED", False)) and not (
            settings.DEBUG and environment != "production"
        ):
            raise CommandError("개발 또는 적재가 허용된 전용 QA 설정에서만 실행합니다.")
        try:
            self.day = (
                datetime.date.fromisoformat(options["date"])
                if options.get("date")
                else kst_now().date()
            )
        except ValueError as error:
            raise CommandError("기준일은 YYYY-MM-DD 형식이어야 합니다.") from error
        if self.day > kst_now().date():
            raise CommandError("미래 날짜는 사용할 수 없습니다.")
        self.days = [month_start(self.day, n) for n in MONTH_OFFSETS]
        # Each scenario finishes the day after receipt. On the first two days of a
        # month, omit that month rather than writing future or intraday timestamps.
        self.days = [day for day in self.days if day + datetime.timedelta(days=1) < self.day]
        if not AuditLog.objects.filter(table_name="qa_dataset", record_id="reference-v1").exists():
            raise CommandError(
                "기존 QA 기준 묶음(reference-v1)이 필요합니다. 신규 격리 DB는 먼저 준비하세요."
            )
        previous = AuditLog.objects.filter(table_name="qa_dataset", record_id=MARKER).last()
        if previous:
            if options.get("date") and str(self.day) != previous.after_json["date"]:
                raise CommandError("이미 적재된 묶음의 기준일은 변경할 수 없습니다.")
            self.save_report(previous.after_json)
            self.stdout.write("월별 QA 묶음이 이미 있습니다. 사용자 거래를 보존하고 건너뜁니다.")
            return
        self.preflight()
        if not options.get("apply"):
            self.stdout.write(
                json.dumps(
                    {
                        "date": str(self.day),
                        "months": [str(day)[:7] for day in self.days],
                        "mode": "계획 확인 — DB 변경 없음. --apply로 추가",
                        "scope": (
                            "월별 입고·생산·분할산출, 월경계, 부적합·보류·만료·미검사, "
                            "정정·취소·반품·폐기"
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        backup = ReferenceCommand().backup_db()
        with transaction.atomic():
            # Serialize competing invocations, including the completion marker.
            if AuditLog.objects.filter(table_name="qa_dataset", record_id=MARKER).exists():
                self.stdout.write("다른 실행이 월별 QA 묶음을 완료했습니다. 건너뜁니다.")
                return
            self.staff, _ = Staff.objects.get_or_create(
                staff_code="QA_HISTORY", defaults={"name": "QA 월별 검증자"}
            )
            self.suppliers = [
                Supplier.objects.get_or_create(
                    supplier_code=f"QA_HISTORY_{n}", defaults={"name": f"QA-월별 가상공급처{n}"}
                )[0]
                for n in (1, 2)
            ]
            self.tag = f"QA-HISTORY-{self.day}"
            self.lots, self.batches, self.checks = {}, [], []
            for kind in ("INCOMING", "PRODUCED"):
                item = self.items["1000004" if kind == "INCOMING" else "3000014"]
                try:
                    find_rule(lot_kind=kind, item=item, on_date=min(self.days))
                except InventoryError:
                    current = find_rule(lot_kind=kind, item=item, on_date=self.day)
                    LotNumberRule.objects.create(
                        lot_kind=kind,
                        item_type_id=current.item_type_id,
                        pattern=current.pattern,
                        effective_from=min(self.days),
                        notes=self.key("과거 가상 거래용 채번 규칙"),
                    )
            for number, day in enumerate(self.days):
                self.month_scenario(number, day)
            self.edge_scenarios()
            report = self.report(str(backup))
            AuditLog.objects.create(
                table_name="qa_dataset",
                record_id=MARKER,
                action="INSERT",
                staff=self.staff,
                reason="월별 QA 가상 거래 추가 (기존 거래·마스터 보존)",
                after_json=report,
            )
        self.save_report(report)
        self.stdout.write(
            f"월별 QA 추가 완료: LOT {len(self.lots)}, 배치 {len(self.batches)}, "
            f"검사 {len(self.checks)}"
        )

    def preflight(self):
        self.items = {}
        for code, name in [
            ("1000004", "녹용(뉴질랜드)"),
            ("1000005", "녹용(러시아)"),
            ("1000040", "덱스트린"),
            ("3000014", "녹용분말"),
        ]:
            item = Item.objects.filter(
                item_code=code, name=name, base_unit="kg", is_active=True
            ).first()
            if not item:
                raise CommandError(
                    f"QA 기준 품목 불일치: {code} {name}. 기존 마스터는 변경하지 않습니다."
                )
            self.items[code] = item
        self.bom = (
            Bom.objects.filter(item=self.items["3000014"], is_active=True)
            .order_by("-version")
            .first()
        )
        if (
            not self.bom
            or list(self.bom.lines.values_list("component_item__item_code", "quantity_e6"))
            != [("1000004", 1000000)]
            or self.bom.base_quantity_e6 != 1000000
        ):
            raise CommandError(
                "녹용분말 1kg BOM(녹용 1kg)을 확인하세요. 기존 BOM은 변경하지 않습니다."
            )
        self.line = self.bom.lines.get()
        if not self.line.alternatives.filter(item=self.items["1000005"]).exists():
            raise CommandError("QA 기준 BOM에 러시아 녹용 대체 관계가 필요합니다.")

    def key(self, label):
        return f"{self.tag}:{label}"

    def receive(
        self,
        label,
        day,
        quantity="1",
        code="1000004",
        status="NONE",
        judgment="PASS",
        expires=None,
        supplier=0,
    ):
        receipt = register_receipt(
            ReceiptInput(
                item_id=self.items[code].pk,
                supplier_id=self.suppliers[supplier].pk,
                staff_id=self.staff.pk,
                received_date=day,
                quantity=quantity,
                idempotency_key=self.key(label),
                supplier_lot_number=self.key(label),
                expiration_status=status,
                expiration_date=expires,
                judgment=judgment,
            )
        )
        self.lots[receipt.lot_id] = {"label": label, "expected_e6": to_e6(quantity)}
        return receipt

    def batch(self, label, day, quantity="1"):
        # Explicitly reuse the reviewed 1kg QA recipe for synthetic history. This does
        # not backdate the master or claim this BOM was in force in the past.
        batch = create_batch(
            item_id=self.items["3000014"].pk,
            staff_id=self.staff.pk,
            bom_id=self.bom.pk,
            planned_quantity=quantity,
            planned_date=day,
            manufactured_date=day,
            notes=self.key(label),
        )
        self.batches.append(batch.pk)
        return batch

    def reject(self, label, action):
        before = (
            StockMovement.objects.count(),
            dict(Inventory.objects.values_list("lot_id", "quantity_e6")),
        )
        try:
            with transaction.atomic():
                action()
        except InventoryError as error:
            after = (
                StockMovement.objects.count(),
                dict(Inventory.objects.values_list("lot_id", "quantity_e6")),
            )
            if before != after:
                raise CommandError(f"거부 시 재고 변경 발생: {label}") from error
            self.checks.append({"case": label, "message": str(error)})
        else:
            raise CommandError(f"거부되어야 하는 작업이 성공했습니다: {label}")

    def month_scenario(self, number, day):
        label = str(day)[:7]
        receipt = self.receive(label, day, str(10 + number))
        batch = self.batch(label, day)
        start_batch(batch_id=batch.pk, staff_id=self.staff.pk, started_at=day)
        add_usage(
            batch_id=batch.pk,
            lot_id=receipt.lot_id,
            quantity="1",
            staff_id=self.staff.pk,
            idempotency_key=self.key(label + "-input"),
            occurred_at=day,
        )
        self.lots[receipt.lot_id]["expected_e6"] -= 1000000
        for n, quantity in enumerate(["0.4", "0.6"]):
            out = add_output(
                batch_id=batch.pk,
                quantity=quantity,
                staff_id=self.staff.pk,
                idempotency_key=self.key(f"{label}-output-{n}"),
                occurred_at=day + datetime.timedelta(days=1),
            )
        self.lots[out.lot_id] = {"label": label + "-output", "expected_e6": 1000000}
        complete_batch(
            batch_id=batch.pk, staff_id=self.staff.pk, completed_at=day + datetime.timedelta(days=1)
        )
        before = StockMovement.objects.count()
        add_output(
            batch_id=batch.pk,
            quantity="0.6",
            staff_id=self.staff.pk,
            idempotency_key=self.key(f"{label}-output-1"),
        )
        if StockMovement.objects.count() != before:
            raise CommandError("산출 재시도로 중복 수불 발생")

    def edge_scenarios(self):
        last_month = month_start(self.day, 0) - datetime.timedelta(days=1)
        first_month = last_month + datetime.timedelta(days=1)
        if first_month >= self.day:
            first_month, last_month = (
                month_start(self.day, 1),
                month_start(self.day, 1) - datetime.timedelta(days=1),
            )
        boundary = self.receive("month-boundary", last_month, "2")
        adjust_stock(
            lot_id=boundary.lot_id,
            direction="OUT",
            quantity="0.5",
            staff_id=self.staff.pk,
            reason=self.key("월경계 2-0.5=1.5"),
            idempotency_key=self.key("boundary-out"),
            occurred_at=first_month,
        )
        self.lots[boundary.lot_id]["expected_e6"] = 1500000
        self.boundary = {
            "lot_id": boundary.lot_id,
            "from": str(first_month),
            "opening": "2",
            "out": "0.5",
            "closing": "1.5",
        }
        day = self.day - datetime.timedelta(days=2)
        expires = self.day + datetime.timedelta(days=180)
        for n, quantity in enumerate(["10", "0.4", "0.3"]):
            self.receive(
                f"same-expiry-{n}", day, quantity, code="1000040", status="KNOWN", expires=expires
            )
        bad = []
        for label, status, judgment, expiry in [
            ("rejected", "NONE", "FAIL", None),
            ("quarantine", "NONE", None, None),
            ("expired", "KNOWN", "PASS", self.day - datetime.timedelta(days=3)),
            ("held", "NONE", "PASS", None),
            ("expires-today", "KNOWN", "PASS", self.day),
        ]:
            row = self.receive(label, day, status=status, judgment=judgment, expires=expiry)
            if label == "held":
                hold_lot(
                    lot_id=row.lot_id,
                    source_type="MANUAL",
                    reason=self.key("보류 검증"),
                    staff_id=self.staff.pk,
                )
            if label != "expires-today":
                bad.append((label, row))
        planned = self.batch("manual-ready", day)
        start_batch(batch_id=planned.pk, staff_id=self.staff.pk)
        for label, row in bad:
            self.reject(
                label,
                lambda row=row: add_usage(
                    batch_id=planned.pk,
                    lot_id=row.lot_id,
                    quantity="0.1",
                    staff_id=self.staff.pk,
                    idempotency_key=self.key("blocked-" + str(row.pk)),
                ),
            )
        good = self.receive("manual-allocation", day, "2")
        self.reject(
            "수동 배분 1kg 요청에 0.5kg",
            lambda: add_usages(
                batch_id=planned.pk,
                entries=[{"lot_id": good.lot_id, "quantity": "0.5"}],
                staff_id=self.staff.pk,
                idempotency_key=self.key("mismatch"),
                expected_quantity="1",
                expected_bom_line_id=self.line.pk,
            ),
        )
        wrong = self.receive("outside-bom", day, code="1000040")
        self.reject(
            "BOM 외 원료",
            lambda: add_usage(
                batch_id=planned.pk,
                lot_id=wrong.lot_id,
                quantity="0.1",
                staff_id=self.staff.pk,
                idempotency_key=self.key("outside-bom-input"),
            ),
        )
        shortage = self.batch("shortage", day, "1000000000")
        self.reject(
            "재고 부족 시작 차단", lambda: start_batch(batch_id=shortage.pk, staff_id=self.staff.pk)
        )
        shortage.refresh_from_db()
        if shortage.status != "PLANNED":
            raise CommandError("시작 실패 배치의 상태가 변경되었습니다.")
        alternative = self.receive("alternative-ready", day, code="1000005", quantity="2")
        self.checks.append(
            {
                "case": "수동 QA 준비",
                "batch_id": planned.pk,
                "normal_lot_id": good.lot_id,
                "alternative_lot_id": alternative.lot_id,
                "shortage_batch_id": shortage.pk,
            }
        )
        for label in ["corrected", "cancelled", "returned", "disposed"]:
            row = self.receive(label, day, "1", code="1000040")
            common = {"staff_id": self.staff.pk, "reason": self.key(label)}
            if label == "corrected":
                correct_movement(
                    movement_id=row.stock_movement_id,
                    quantity="0.2",
                    idempotency_key=self.key(label + "-op"),
                    **common,
                )
                expected = 800000
            elif label == "cancelled":
                cancel_receipt(receipt_id=row.pk, **common)
                expected = 0
            else:
                action = return_to_supplier if label == "returned" else dispose
                action(
                    lot_id=row.lot_id,
                    quantity="1",
                    occurred_at=day + datetime.timedelta(days=1),
                    idempotency_key=self.key(label + "-op"),
                    **common,
                )
                expected = 0
            self.lots[row.lot_id]["expected_e6"] = expected

    def report(self, backup):
        earliest = min(self.days)
        for lot_id, row in self.lots.items():
            lot = Lot.objects.select_related("item").get(pk=lot_id)
            actual = Inventory.objects.get(lot_id=lot_id).quantity_e6
            ledger = stock_ledger(earliest, self.day, lot_id=lot_id)
            if actual != row["expected_e6"] or not ledger or ledger[0].closing_e6 != actual:
                raise CommandError(f"월별 QA 예상 재고/수불 불일치: {lot_id}")
            row["quantity"] = str(from_e6(actual))
            row.update(
                {
                    "item_code": lot.item.item_code,
                    "item_name": lot.item.name,
                    "lot_number": lot.lot_number,
                    "status": lot.status,
                    "expiration_status": lot.expiration_status,
                    "expiration_date": str(lot.expiration_date) if lot.expiration_date else None,
                }
            )
        monthly = []
        for day in self.days:
            end = min(self.day, day.replace(day=calendar.monthrange(day.year, day.month)[1]))
            items = stock_ledger(day, end)
            lots = [lot for item in items for lot in item.lots if lot.lot_id in self.lots]
            monthly.append(
                {
                    "from": str(day),
                    "to": str(end),
                    "movements": sum(len(lot.lines) for lot in lots),
                    "opening": str(from_e6(sum(lot.opening_e6 for lot in lots))),
                    "in": str(from_e6(sum(lot.in_e6 for lot in lots))),
                    "out": str(from_e6(sum(lot.out_e6 for lot in lots))),
                    "closing": str(from_e6(sum(lot.closing_e6 for lot in lots))),
                }
            )
        return {
            "date": str(self.day),
            "dataset": MARKER,
            "backup": backup,
            "assumptions": (
                "모든 날짜·수량·공급처는 가상. 기존 검토 BOM을 명시 선택한 합성 이력이며 "
                "과거 유효 BOM 재현 아님. 월별 합계는 추가 LOT만 집계(모두 kg)."
            ),
            "lots": self.lots,
            "batch_ids": self.batches,
            "months": monthly,
            "boundary": self.boundary,
            "checks": self.checks,
        }

    def save_report(self, report):
        directory = settings.DATA_DIR / "qa"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "QA-HISTORY-v1.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(f"Report: {target}")
