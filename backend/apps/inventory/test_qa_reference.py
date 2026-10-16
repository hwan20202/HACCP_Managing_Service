"""Reference data: preserve sample links, real service integration and safe replay."""

import json
import tempfile
from collections import defaultdict
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.documents.models import Document
from apps.documents.seed import ensure_p4_templates

from .fields import kst_now
from .management.commands.seed_qa_inventory import Command
from .models import (
    AuditLog,
    Bom,
    BomLine,
    Item,
    Lot,
    ProductionBatch,
    Staff,
    StockMovement,
    Supplier,
)
from .movements import adjust_stock
from .quantity import to_e6


class ReferenceScenarioTests(TestCase):
    def setUp(self):
        call_command("seed_master", "--sample", stdout=StringIO())
        ensure_p4_templates()
        self.fixture = json.loads(
            (Path(__file__).parent / "seed/qa_reference.json").read_text(encoding="utf-8")
        )

    def command(self):
        cmd = Command()
        cmd.day, cmd.tag = kst_now().date(), "QA-TEST"
        cmd.staff, _ = Staff.objects.get_or_create(
            staff_code="QA_REF", defaults={"name": "QA test"}
        )
        cmd.suppliers = [
            Supplier.objects.get_or_create(supplier_code=f"QA{n}", defaults={"name": f"QA{n}"})[0]
            for n in (1, 2)
        ]
        cmd.expected, cmd.initial = defaultdict(int), defaultdict(int)
        cmd.lots, cmd.events, cmd.checks, cmd.remaps = {}, [], [], []
        cmd.items = cmd.masters(self.fixture)
        cmd.boms = cmd.make_boms(self.fixture)
        return cmd

    def test_sample_code_and_short_code_move_without_breaking_bom_links(self):
        sample = Item.objects.get(item_code="1000003")
        parent = Item.objects.get(item_code="3000501")
        bom = Bom.objects.create(
            item=parent, version=1, base_quantity_e6=to_e6("1"), effective_from=kst_now().date()
        )
        line = BomLine.objects.create(
            bom=bom, line_no=1, component_item=sample, quantity_e6=to_e6("1")
        )
        cmd = self.command()
        sample.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual((sample.item_code, sample.short_code), ("1999003", "QA_SAMPLE_AGC"))
        self.assertEqual(line.component_item_id, sample.pk)
        self.assertEqual(cmd.items["1000032"].short_code, "AGC")
        self.assertEqual(cmd.items["1000003"].name, "사양벌꿀")

    def test_reference_production_and_replay_preserve_stock_and_document_counts(self):
        cmd = self.command()
        cmd.prepare()
        cmd.run_scenarios(self.fixture)
        cmd.validate()
        self.assertEqual(len(cmd.lots), 33)
        self.assertEqual(cmd.expected[cmd.extract[0].pk], 0)
        self.assertEqual(cmd.expected[cmd.extract[1].pk], to_e6("7.941"))
        self.assertEqual(cmd.expected[cmd.openings[1].pk], 0)
        self.assertEqual(ProductionBatch.objects.filter(status="COMPLETED").count(), 3)
        before = (StockMovement.objects.count(), Document.objects.count())
        again = self.command()
        again.prepare()
        again.run_scenarios(self.fixture)
        again.validate()
        self.assertEqual((StockMovement.objects.count(), Document.objects.count()), before)

    @override_settings(DEBUG=False)
    def test_production_settings_refuse_seed_before_any_write(self):
        with self.assertRaises(CommandError):
            Command().handle(date=None, stage="prepare")


class HostedQaSeedTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.enterContext(
            override_settings(
                DEBUG=False,
                HACCP_ENVIRONMENT="qa",
                HACCP_QA_SEED_ENABLED=True,
                DATA_DIR=Path(self.directory.name),
            )
        )
        # Backup implementation is exercised against a real isolated file DB in rehearsal.
        self.enterContext(mock.patch.object(Command, "backup_db", return_value="test-backup"))

    def seed(self, stage="prepare", date=None):
        Command(stdout=StringIO()).handle(date=date, stage=stage)

    def test_fresh_qa_rules_repeat_after_date_rollover_and_manual_activity(self):
        self.seed()
        self.assertEqual((Item.objects.count(), Lot.objects.count()), (24, 30))
        self.assertEqual(Document.objects.count(), 84)
        marker = AuditLog.objects.get(table_name="qa_dataset")
        lot = Lot.objects.filter(item__item_code="1000003").first()
        adjust_stock(
            lot_id=lot.pk,
            direction="OUT",
            quantity="0.1",
            reason="manual QA",
            staff_id=Staff.objects.get(staff_code="QA_REF").pk,
            idempotency_key="manual",
        )
        before = (StockMovement.objects.count(), Document.objects.count())
        with mock.patch(
            "apps.inventory.management.commands.seed_qa_inventory.kst_now",
            return_value=kst_now() + timedelta(days=1),
        ):
            self.seed()
        self.assertEqual((StockMovement.objects.count(), Document.objects.count()), before)
        self.assertEqual(AuditLog.objects.filter(table_name="qa_dataset").count(), 1)
        self.assertEqual(marker.after_json["stage"], "prepare")

    def test_deer_powder_rejects_red_ginseng_without_bom_line(self):
        from .errors import InventoryError
        from .models import Inventory, ProductionMaterialUsage
        from .production import add_usage, create_batch, start_batch

        self.seed()
        staff = Staff.objects.get(staff_code="QA_REF")
        batch = create_batch(
            item_id=Item.objects.get(item_code="3000014").pk,
            staff_id=staff.pk,
            planned_quantity="1",
        )
        start_batch(batch_id=batch.pk, staff_id=staff.pk)
        ginseng = Lot.objects.filter(item__item_code="1000015").first()
        before = (
            StockMovement.objects.count(),
            ProductionMaterialUsage.objects.count(),
            Inventory.objects.get(lot=ginseng).quantity_e6,
        )
        with self.assertRaisesRegex(InventoryError, "BOM"):
            add_usage(
                batch_id=batch.pk,
                lot_id=ginseng.pk,
                quantity="0.1",
                staff_id=staff.pk,
                idempotency_key="wrong-red-ginseng",
            )
        self.assertEqual(
            before,
            (
                StockMovement.objects.count(),
                ProductionMaterialUsage.objects.count(),
                Inventory.objects.get(lot=ginseng).quantity_e6,
            ),
        )

    def test_prepare_to_run_then_prepare_does_not_replay_completed_activity(self):
        self.seed()
        self.seed("run")
        self.assertEqual(ProductionBatch.objects.filter(status="COMPLETED").count(), 3)
        before = (Lot.objects.count(), StockMovement.objects.count(), Document.objects.count())
        self.seed("run")
        self.seed("prepare")
        self.assertEqual(
            (Lot.objects.count(), StockMovement.objects.count(), Document.objects.count()), before
        )

    def test_production_ignores_qa_opt_in_and_disabled_qa_refuses(self):
        for environment, enabled in [("production", True), ("qa", False)]:
            with (
                self.subTest(environment=environment, enabled=enabled),
                override_settings(HACCP_ENVIRONMENT=environment, HACCP_QA_SEED_ENABLED=enabled),
                self.assertRaises(CommandError),
            ):
                self.seed()
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_existing_business_db_and_explicit_new_dataset_date_are_refused(self):
        self.seed()
        with self.assertRaises(CommandError):
            self.seed(date=str(kst_now().date() - timedelta(days=1)))
        AuditLog.objects.filter(table_name="qa_dataset").delete()
        before = StockMovement.objects.count()
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(StockMovement.objects.count(), before)


class TemplateInstallerTests(TestCase):
    def test_repeated_install_has_no_sample_staff_documents_or_transactions(self):
        from apps.documents.models import DocumentTemplate

        call_command("install_document_templates", stdout=StringIO())
        first = list(DocumentTemplate.objects.values_list("template_id", flat=True))
        call_command("install_document_templates", stdout=StringIO())
        self.assertEqual(
            list(DocumentTemplate.objects.values_list("template_id", flat=True)), first
        )
        self.assertEqual(DocumentTemplate.objects.filter(is_active=True).count(), 9)
        self.assertEqual(
            (Staff.objects.count(), Document.objects.count(), StockMovement.objects.count()),
            (0, 0, 0),
        )

    def test_inactive_template_is_preserved_and_install_refused(self):
        from apps.documents.models import DocumentTemplate

        call_command("install_document_templates", stdout=StringIO())
        DocumentTemplate.objects.filter(type_code="D01").update(is_active=False)
        with self.assertRaises(CommandError):
            call_command("install_document_templates", stdout=StringIO())
        self.assertFalse(DocumentTemplate.objects.get(type_code="D01").is_active)
