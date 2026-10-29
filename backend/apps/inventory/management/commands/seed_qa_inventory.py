"""Explicit development/hosted-QA fixtures; never part of normal deployment."""

import datetime
import hashlib
import json
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.doc_requirements.services import docs_for_batch, docs_for_lot
from apps.documents.seed import ensure_p4_templates
from apps.inventory.errors import InventoryError
from apps.inventory.fields import kst_now
from apps.inventory.holds import hold_lot
from apps.inventory.ledger import stock_ledger
from apps.inventory.master_import import ensure_default_lot_rules
from apps.inventory.models import (
    AuditLog,
    Bom,
    BomLine,
    BomLineAlternative,
    Inventory,
    Item,
    ProductionBatch,
    Staff,
    StockMovement,
    Supplier,
)
from apps.inventory.movements import dispose, record_opening_balance
from apps.inventory.production import (
    add_output,
    add_usage,
    complete_batch,
    create_batch,
    fefo_candidates,
    start_batch,
)
from apps.inventory.quantity import from_e6, to_e6
from apps.inventory.receiving import ReceiptInput, register_receipt


class Command(BaseCommand):
    help = "개발·전용 QA DB 백업 후 공통 BOM·가상 재고 적재 (배포와 별도 실행)"

    def add_arguments(self, parser):
        parser.add_argument("--stage", choices=["prepare", "run"], default="prepare")
        parser.add_argument("--date", help="QA 기준일 YYYY-MM-DD (기본 KST 오늘)")

    def handle(self, *args, **options):
        hosted_qa = getattr(settings, "HACCP_ENVIRONMENT", "production") == "qa"
        if not settings.DEBUG and not (
            hosted_qa and getattr(settings, "HACCP_QA_SEED_ENABLED", False)
        ):
            raise CommandError("개발 또는 적재가 명시적으로 허용된 전용 QA 설정에서만 실행합니다.")
        day = datetime.date.fromisoformat(options["date"]) if options["date"] else kst_now().date()
        if day > kst_now().date():
            raise CommandError("미래 날짜는 사용할 수 없습니다.")
        backup = self.backup_db()
        fixture = json.loads(
            (Path(__file__).parents[2] / "seed/qa_reference.json").read_text(encoding="utf-8")
        )
        fingerprint = hashlib.sha256(
            json.dumps(fixture, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.day, self.tag = day, f"QA-REF-{day}"
        self.expected, self.initial, self.lots = defaultdict(int), defaultdict(int), {}
        self.events, self.checks, self.remaps = [], [], []
        with transaction.atomic():
            # BEGIN IMMEDIATE serializes concurrent first seeds. Keep the completion marker
            # in the same DB transaction as stock, not only in an external JSON report.
            previous = (
                AuditLog.objects.filter(table_name="qa_dataset", record_id="reference-v1")
                .order_by("id")
                .last()
            )
            if previous:
                state = previous.after_json
                if state["fixture_hash"] != fingerprint:
                    raise CommandError(
                        "기존 QA 묶음과 소스가 다릅니다. 별도 QA 저장 공간을 사용하세요."
                    )
                if options["date"] and options["date"] != state["date"]:
                    raise CommandError(
                        "기존 QA 날짜는 고정입니다. 새 날짜로 중복 적재하지 않습니다."
                    )
                if options["stage"] == "prepare" or state["stage"] == "run":
                    self.stdout.write(
                        f"QA 묶음이 이미 있습니다: {state['date']} / {state['stage']}. "
                        "사용자 거래·첨부파일을 보존하고 적재를 건너뜁니다."
                    )
                    return
                day = datetime.date.fromisoformat(state["date"])
                self.day, self.tag = day, f"QA-REF-{day}"
            elif hosted_qa and StockMovement.objects.exists():
                raise CommandError(
                    "적재 기록 없는 기존 거래 DB에는 QA 데이터를 섞지 않습니다. "
                    "새 QA 데이터 디렉터리를 준비하세요."
                )
            ensure_default_lot_rules()
            self.staff, _ = Staff.objects.get_or_create(
                staff_code="QA_REF", defaults={"name": "QA 기준자료 검증자"}
            )
            self.suppliers = [
                Supplier.objects.get_or_create(
                    supplier_code=f"QA_REF_{n}", defaults={"name": f"QA 가상공급처{n}"}
                )[0]
                for n in (1, 2)
            ]
            ensure_p4_templates()
            self.items = self.masters(fixture)
            self.boms = self.make_boms(fixture)
            self.prepare()
            if options["stage"] == "run":
                self.run_scenarios(fixture)
            self.validate()
            AuditLog.objects.create(
                table_name="qa_dataset",
                record_id="reference-v1",
                action="INSERT",
                staff=self.staff,
                reason="QA 가정 데이터 적재 완료 (운영 데이터 아님)",
                after_json={
                    "date": str(day),
                    "stage": options["stage"],
                    "fixture_hash": fingerprint,
                    "lot_ids": sorted(self.lots),
                    "sources": fixture["sources"],
                    "sample_code_remaps": self.remaps,
                },
            )
        report = {
            "date": str(day),
            "stage": options["stage"],
            "backup": str(backup),
            "sources": fixture["sources"],
            "sample_code_remaps": self.remaps,
            "actual_values": (
                "품목명·약어·세 제품 BOM은 공통 참고본. BOM은 1kg 기준, 사용량 g→kg 변환."
            ),
            "assumptions": (
                "입고일·소비기한·수량·공급처·판정·기초재고·산출량·단위 kg는 QA 설정. "
                "실제 거래 재현 아님. 추출액은 구매분으로만 준비."
            ),
            "events": self.events,
            "checks": self.checks,
            "lots": [
                {
                    "id": lot.pk,
                    "item_code": lot.item.item_code,
                    "name": lot.item.name,
                    "lot_number": lot.lot_number,
                    "expiration_status": lot.expiration_status,
                    "initial": str(from_e6(self.initial[lot.pk])),
                    "expected": str(from_e6(self.expected[lot.pk])),
                    "actual": str(from_e6(Inventory.objects.get(lot=lot).quantity_e6)),
                    "unit": lot.item.base_unit,
                }
                for lot in self.lots.values()
            ],
        }
        directory = settings.DATA_DIR / "qa"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{self.tag}-{options['stage']}.json"
        contents = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        target.write_text(contents, encoding="utf-8")
        self.stdout.write(
            f"Backup: {backup}\nReport: {target}\n"
            f"LOT {len(self.lots)}개, 검사 {len(self.checks)}개 통과"
        )

    def backup_db(self):
        db_path = Path(settings.DATABASES["default"]["NAME"])
        if not db_path.is_file():
            raise CommandError("마이그레이션된 파일 DB가 필요합니다.")
        backup = db_path.with_name(f"app-before-qa-{kst_now():%Y%m%d-%H%M%S-%f}.sqlite3")
        with sqlite3.connect(db_path) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        return backup

    def masters(self, fixture):
        result = {}
        for entry in fixture["items"]:
            code = entry["item_code"]
            existing = Item.objects.filter(item_code=code).first()
            if existing and existing.name != entry["name"]:
                if not existing.name.startswith("가상"):
                    raise CommandError(f"확인되지 않은 실제 품목 충돌: {code} {existing.name}")
                # Keep IDs, BOM/LOT/document links; only move explicitly named sample codes.
                new_code = f"{code[0]}999{int(code[1:]):03d}"
                if Item.objects.filter(item_code=new_code).exists():
                    raise CommandError(f"샘플 이동 코드도 중복: {new_code}")
                existing.item_code = new_code
                existing.save(update_fields=["item_code"])
                self.remaps.append(
                    {"id": existing.pk, "name": existing.name, "before": code, "after": new_code}
                )
                AuditLog.objects.create(
                    table_name="items",
                    record_id=str(existing.pk),
                    action="UPDATE",
                    before_json={"item_code": code},
                    after_json={"item_code": new_code},
                    reason=f"{self.tag}: 실제 참고품목과 가상 샘플 코드 분리",
                    staff=self.staff,
                )
            short = entry.get("short_code")
            collision = (
                Item.objects.filter(short_code=short).exclude(item_code=code).first()
                if short
                else None
            )
            if collision:
                if not collision.name.startswith("가상"):
                    raise CommandError(f"실제 품목 약어 충돌: {short}")
                replacement = f"QA_SAMPLE_{short}"
                if Item.objects.filter(short_code=replacement).exists():
                    raise CommandError(f"샘플 약어 이동 대상 중복: {replacement}")
                collision.short_code = replacement
                collision.save(update_fields=["short_code"])
                self.remaps.append(
                    {"id": collision.pk, "short_before": short, "short_after": replacement}
                )
                AuditLog.objects.create(
                    table_name="items",
                    record_id=str(collision.pk),
                    action="UPDATE",
                    before_json={"short_code": short},
                    after_json={"short_code": replacement},
                    reason=f"{self.tag}: 실제 약어와 가상 샘플 약어 분리",
                    staff=self.staff,
                )
            defaults = {k: entry[k] for k in ("name", "short_code", "base_unit")}
            defaults["item_type_id"] = entry["item_type"]
            if "shelf_life_months" in entry:
                defaults["shelf_life_months"] = entry["shelf_life_months"]
            item, made = Item.objects.get_or_create(item_code=code, defaults=defaults)
            if not made and any(getattr(item, k) != v for k, v in defaults.items()):
                raise CommandError(f"이미 존재하는 품목의 규격이 다릅니다: {code}")
            result[code] = item
        return result

    def make_boms(self, fixture):
        result = {}
        for entry in fixture["boms"]:
            item = self.items[entry["item_code"]]
            bom, made = Bom.objects.get_or_create(
                item=item,
                version=1,
                defaults={
                    "base_quantity_e6": to_e6(entry["base_quantity"]),
                    "effective_from": self.day - datetime.timedelta(days=7),
                    "created_by": self.staff,
                    "notes": "QA_REFERENCE: 양쪽 참고본 공통 배합, 질량 기준 시험용",
                    # 품목당 활성 BOM 은 하나 (0011): 이미 쓰는 버전이 있으면 비활성으로 둔다.
                    "is_active": not Bom.objects.filter(item=item, is_active=True).exists(),
                },
            )
            if not made and not (bom.notes or "").startswith("QA_REFERENCE:"):
                raise CommandError(f"기존 BOM을 덮어쓸 수 없습니다: {item.item_code}")
            if not made:
                actual = {
                    row.component_item.item_code: (
                        row.quantity_e6,
                        sorted(row.alternatives.values_list("item__item_code", flat=True)),
                    )
                    for row in bom.lines.select_related("component_item")
                }
                expected = {
                    line["item_code"]: (
                        to_e6(line["quantity"]),
                        [line["alternative"]] if line.get("alternative") else [],
                    )
                    for line in entry["lines"]
                }
                if actual != expected or bom.base_quantity_e6 != to_e6(entry["base_quantity"]):
                    raise CommandError(f"기존 QA BOM 내용이 변경되었습니다: {item.item_code}")
            if made:
                for n, line in enumerate(entry["lines"], 1):
                    row = BomLine.objects.create(
                        bom=bom,
                        line_no=n,
                        component_item=self.items[line["item_code"]],
                        quantity_e6=to_e6(line["quantity"]),
                        notes=line["source"],
                    )
                    if line.get("alternative"):
                        BomLineAlternative.objects.create(
                            bom_line=row, item=self.items[line["alternative"]]
                        )
            result[item.item_code] = bom
        return result

    def remember(self, lot, quantity, label, movement_id=None):
        self.lots[lot.pk] = lot
        self.expected[lot.pk] += to_e6(quantity)
        self.initial[lot.pk] += to_e6(quantity)
        self.events.append(
            {
                "kind": "starting_stock",
                "label": label,
                "lot_id": lot.pk,
                "quantity": str(quantity),
                "movement_id": movement_id,
            }
        )
        return lot

    def receive(
        self,
        code,
        quantity,
        label,
        *,
        offset=-4,
        status="KNOWN",
        expires=None,
        judgment="PASS",
        supplier=0,
    ):
        expiry = (expires or self.day + datetime.timedelta(days=180)) if status == "KNOWN" else None
        receipt = register_receipt(
            ReceiptInput(
                item_id=self.items[code].pk,
                supplier_id=self.suppliers[supplier].pk,
                staff_id=self.staff.pk,
                received_date=self.day + datetime.timedelta(days=offset),
                quantity=quantity,
                idempotency_key=f"{self.tag}:{label}",
                expiration_date=expiry,
                expiration_status=status,
                judgment=judgment,
            )
        )
        assert len(docs_for_lot(receipt.lot_id)["documents"]) == 3
        return self.remember(receipt.lot, quantity, label, receipt.stock_movement_id)

    def prepare(self):
        for code, item in self.items.items():
            if item.item_type_id == "RAW" and code not in {"1000004", "1000005", "1000009"}:
                self.receive(code, "10", f"raw-{code}")
        self.raw_deer = self.receive("1000004", "2", "deer-none-old", status="NONE")
        self.receive("1000004", "0.5", "deer-none-new", offset=-2, status="NONE", supplier=1)
        self.receive("1000005", "1", "deer-alternative", status="NONE")
        self.cornus = [
            self.receive("1000009", q, f"cornus-{n}", supplier=n % 2)
            for n, q in enumerate(["6", "4", "1"])
        ]
        self.extract = [
            self.receive(
                "3000033",
                q,
                f"extract-{n}",
                offset=-5 + n,
                expires=self.day + datetime.timedelta(days=90 + n * 30),
            )
            for n, q in enumerate(["20", "10"])
        ]
        self.bad = self.receive("1000040", "0.4", "rejected", judgment="FAIL")
        self.expired = self.receive(
            "1000040", "0.5", "expired", expires=self.day - datetime.timedelta(days=1)
        )
        self.held = self.receive("1000040", "0.3", "held")
        hold_lot(
            lot_id=self.held.pk,
            source_type="MANUAL",
            reason=f"{self.tag}: 보류 차단 QA 가정",
            staff_id=self.staff.pk,
        )
        self.openings = []
        for code, q, label, status in [
            ("3000017", "42.5", "powder-opening", "UNKNOWN"),
            ("1000040", "0.2", "empty-history", "NONE"),
        ]:
            move = record_opening_balance(
                item_id=self.items[code].pk,
                quantity=q,
                staff_id=self.staff.pk,
                occurred_at=self.day - datetime.timedelta(days=6),
                idempotency_key=f"{self.tag}:{label}",
                lot_number=f"{self.tag}-{label}",
                expiration_status=status,
                reason="QA 가정 기초재고 (실제 실사값 아님)",
            )
            self.openings.append(self.remember(move.lot, q, label, move.pk))

    def batch(self, code):
        marker = f"{self.tag}:{code}"
        batch = ProductionBatch.objects.filter(notes=marker).first()
        if batch is None:
            batch = create_batch(
                item_id=self.items[code].pk,
                staff_id=self.staff.pk,
                bom_id=self.boms[code].pk,
                planned_quantity={"3000014": "1", "3000011": "5", "3000017": "30"}[code],
                manufactured_date=self.day - datetime.timedelta(days=1),
                notes=marker,
            )
        if batch.status == "PLANNED":
            start_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        # ISS-064(P15): 생산일지 양식을 설치하면 생산일지도 연결 문서 — CCP 일지만 센다
        linked = docs_for_batch(batch.pk)["documents"]
        assert len([d for d in linked if str(d["type_code"]).startswith("CCP-")]) == 3
        return batch

    def use(self, batch, lot, quantity, label, bom_line_id=None):
        row = add_usage(
            batch_id=batch.pk,
            lot_id=lot.pk,
            quantity=quantity,
            staff_id=self.staff.pk,
            idempotency_key=f"{self.tag}:{label}",
            bom_line_id=bom_line_id,
        )
        self.expected[lot.pk] -= to_e6(quantity)
        self.events.append(
            {
                "kind": "use",
                "batch_id": batch.pk,
                "lot_id": lot.pk,
                "quantity": str(quantity),
                "movement_id": row.stock_movement_id,
            }
        )

    def output(self, batch, quantity, label):
        row = add_output(
            batch_id=batch.pk,
            quantity=quantity,
            staff_id=self.staff.pk,
            idempotency_key=f"{self.tag}:{label}",
        )
        self.lots[row.lot_id] = row.lot
        self.expected[row.lot_id] += to_e6(quantity)
        self.events.append(
            {
                "kind": "output",
                "batch_id": batch.pk,
                "lot_id": row.lot_id,
                "quantity": quantity,
                "movement_id": row.stock_movement_id,
            }
        )
        return row.lot

    def run_scenarios(self, fixture):
        deer = self.batch("3000014")
        self.use(deer, self.raw_deer, "1", "deer-input")
        deer_lot = self.output(deer, "1", "deer-output")
        complete_batch(batch_id=deer.pk, staff_id=self.staff.pk)
        efficacy = self.batch("3000011")
        for line in fixture["boms"][0]["lines"]:
            code, quantity = line["item_code"], Decimal(line["quantity"]) * 5
            if code == "3000014":
                lot = deer_lot
            elif code == "1000009":
                lot = self.cornus[0]
            else:
                lot = next(row for row in self.lots.values() if row.item_id == self.items[code].pk)
            self.use(efficacy, lot, str(quantity), f"efficacy-{code}")
        self.output(efficacy, "2", "efficacy-output1")
        lot = self.output(efficacy, "3", "efficacy-output2")
        before = StockMovement.objects.filter(lot=lot).count()
        add_output(
            batch_id=efficacy.pk,
            quantity="3",
            staff_id=self.staff.pk,
            idempotency_key=f"{self.tag}:efficacy-output2",
        )
        assert StockMovement.objects.filter(lot=lot).count() == before
        self.checks.append("분할 산출 2+3=5kg, 동일 LOT·재전송 중복 없음")
        complete_batch(batch_id=efficacy.pk, staff_id=self.staff.pk)
        powder = self.batch("3000017")
        bad_cases = (
            []
            if powder.status == "COMPLETED"
            else [("부적합", self.bad), ("만료", self.expired), ("보류", self.held)]
        )
        for label, bad in bad_cases:
            count = StockMovement.objects.count()
            try:
                add_usage(
                    batch_id=powder.pk,
                    lot_id=bad.pk,
                    quantity="0.1",
                    staff_id=self.staff.pk,
                    idempotency_key=f"{self.tag}:bad-{label}",
                )
            except InventoryError:
                assert StockMovement.objects.count() == count
                self.checks.append(f"{label} LOT 투입 거부, 수불 변화 없음")
            else:
                raise CommandError(f"{label} LOT이 투입됨")
        if powder.status != "COMPLETED":
            picks = fefo_candidates(item_id=self.items["3000033"].pk, quantity="22.059")
            assert [(row.pk, q) for row, q, _ in picks] == [
                (self.extract[0].pk, to_e6("20")),
                (self.extract[1].pk, to_e6("2.059")),
            ]
        for n, (lot, q) in enumerate(zip(self.extract, ["20", "2.059"], strict=True)):
            self.use(powder, lot, q, f"powder-extract-{n}")
        self.checks.append("구매 추출액 FEFO: 20kg 소진 + 다음 LOT 2.059kg 투입")
        dex = next(
            row
            for row in self.lots.values()
            if row.item_id == self.items["1000040"].pk
            and row.expiration_date
            and row.expiration_date > self.day
            and row.pk not in {self.held.pk, self.bad.pk}
        )
        self.use(powder, dex, "7.941", "powder-dextrin")
        self.output(powder, "10", "powder-output1")
        self.output(powder, "20", "powder-output2")
        complete_batch(batch_id=powder.pk, staff_id=self.staff.pk)
        empty = self.openings[1]
        dispose(
            lot_id=empty.pk,
            quantity="0.2",
            staff_id=self.staff.pk,
            reason="QA 가정: 소진 이력 검증",
            idempotency_key=f"{self.tag}:empty",
        )
        self.expected[empty.pk] -= to_e6("0.2")

    def validate(self):
        for lot_id, expected in self.expected.items():
            actual = Inventory.objects.get(lot_id=lot_id).quantity_e6
            if actual != expected:
                raise CommandError(f"예상 재고 불일치 LOT {lot_id}: {expected} != {actual}")
            ledger = stock_ledger(self.day - datetime.timedelta(days=7), self.day, lot_id=lot_id)
            assert ledger[0].lots[0].closing_e6 == expected
        self.checks.append(f"전체 QA LOT {len(self.lots)}개 예상값=현재고=수불 기말 대조")
