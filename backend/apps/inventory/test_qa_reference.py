"""Reference data: preserve sample links, real service integration and safe replay."""

import json
from collections import defaultdict
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.documents.models import Document
from apps.documents.seed import ensure_p4_templates

from .fields import kst_now
from .management.commands.seed_qa_inventory import Command
from .models import Bom, BomLine, Item, ProductionBatch, Staff, StockMovement, Supplier
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
