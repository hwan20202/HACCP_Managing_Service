"""Historical seed must preserve existing QA activity and reconcile monthly balances."""

import datetime
import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.documents.models import Document

from .fields import kst_now
from .ledger import stock_ledger
from .management.commands.seed_qa_history import MARKER, Command
from .management.commands.seed_qa_inventory import Command as ReferenceCommand
from .models import AuditLog, Inventory, Lot, LotNumberRule, ProductionBatch, StockMovement
from .movements import adjust_stock


class HistoricalQaTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.enterContext(
            override_settings(
                DEBUG=False,
                HACCP_ENVIRONMENT="qa",
                HACCP_QA_SEED_ENABLED=True,
                DATA_DIR=self.directory,
            )
        )
        self.backup = self.enterContext(
            mock.patch.object(ReferenceCommand, "backup_db", return_value="backup")
        )
        ReferenceCommand(stdout=StringIO()).handle(date=None, stage="prepare")
        self.backup.reset_mock()

    def run_seed(self, apply=True, date=None):
        Command(stdout=StringIO()).handle(apply=apply, date=date)

    def report(self):
        return json.loads((self.directory / "qa/QA-HISTORY-v1.json").read_text(encoding="utf-8"))

    def test_plan_does_not_write_or_backup(self):
        before = (Lot.objects.count(), Document.objects.count(), AuditLog.objects.count())
        self.run_seed(apply=False)
        self.assertEqual(
            before, (Lot.objects.count(), Document.objects.count(), AuditLog.objects.count())
        )
        self.backup.assert_not_called()

    def test_multimonth_balances_existing_lots_and_user_replay_are_preserved(self):
        existing = dict(Inventory.objects.values_list("lot_id", "quantity_e6"))
        documents = list(Document.objects.values_list("pk", flat=True))
        self.run_seed()
        report = self.report()
        self.backup.assert_called_once()
        self.assertGreaterEqual(len(report["months"]), 6)
        for month in report["months"]:
            self.assertGreaterEqual(month["movements"], 4)
            self.assertAlmostEqual(
                float(month["opening"]) + float(month["in"]) - float(month["out"]),
                float(month["closing"]),
            )
        self.assertEqual(
            existing,
            dict(
                Inventory.objects.filter(lot_id__in=existing).values_list("lot_id", "quantity_e6")
            ),
        )
        self.assertEqual(Document.objects.filter(pk__in=documents).count(), len(documents))
        boundary = report["boundary"]
        day = datetime.date.fromisoformat(boundary["from"])
        [item] = stock_ledger(day, day, lot_id=boundary["lot_id"])
        self.assertEqual(
            (item.opening_e6, item.out_e6, item.closing_e6), (2000000, 500000, 1500000)
        )
        same = [
            int(pk) for pk, row in report["lots"].items() if row["label"].startswith("same-expiry")
        ]
        self.assertEqual(Lot.objects.filter(pk__in=same).count(), 3)
        self.assertEqual(sum(Inventory.objects.get(lot_id=pk).quantity_e6 for pk in same), 10700000)
        ready = next(check for check in report["checks"] if check["case"] == "수동 QA 준비")
        self.assertEqual(
            ProductionBatch.objects.get(pk=ready["shortage_batch_id"]).status, "PLANNED"
        )
        self.assertEqual(
            ProductionBatch.objects.filter(pk__in=report["batch_ids"], status="COMPLETED").count(),
            len(report["months"]),
        )
        adjust_stock(
            lot_id=ready["normal_lot_id"],
            direction="OUT",
            quantity="0.1",
            reason="사용자 추가 QA",
            staff_id=ProductionBatch.objects.get(pk=ready["batch_id"]).staff_id,
            idempotency_key="user-after-history",
        )
        before = (
            StockMovement.objects.count(),
            Document.objects.count(),
            dict(Inventory.objects.values_list("lot_id", "quantity_e6")),
        )
        self.run_seed()
        self.assertEqual(
            before,
            (
                StockMovement.objects.count(),
                Document.objects.count(),
                dict(Inventory.objects.values_list("lot_id", "quantity_e6")),
            ),
        )
        self.assertEqual(
            AuditLog.objects.filter(table_name="qa_dataset", record_id=MARKER).count(), 1
        )

    def test_failure_rolls_back_transactions_documents_rules_and_marker(self):
        before = (
            StockMovement.objects.count(),
            Document.objects.count(),
            LotNumberRule.objects.count(),
        )
        with mock.patch.object(Command, "edge_scenarios", side_effect=CommandError("검증 실패")):
            with self.assertRaises(CommandError):
                self.run_seed()
        self.assertEqual(
            before,
            (
                StockMovement.objects.count(),
                Document.objects.count(),
                LotNumberRule.objects.count(),
            ),
        )
        self.assertFalse(AuditLog.objects.filter(record_id=MARKER).exists())

    def test_production_disabled_qa_missing_marker_and_future_are_refused(self):
        for environment, enabled, debug in [
            ("production", True, False),
            ("production", True, True),
            ("qa", False, False),
        ]:
            with override_settings(
                HACCP_ENVIRONMENT=environment, HACCP_QA_SEED_ENABLED=enabled, DEBUG=debug
            ):
                with self.assertRaises(CommandError):
                    self.run_seed()
        with self.assertRaises(CommandError):
            self.run_seed(date=str(kst_now().date() + datetime.timedelta(days=1)))
        AuditLog.objects.filter(record_id="reference-v1").delete()
        with self.assertRaises(CommandError):
            self.run_seed()
        self.backup.assert_not_called()
