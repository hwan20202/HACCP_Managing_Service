"""Load master data (staff, suppliers, items) and the default LOT number rules.

    python backend/manage.py seed_master --sample
    python backend/manage.py seed_master --staff data/import/staff.csv \
        --suppliers data/import/suppliers.csv --items data/import/items.csv
    python backend/manage.py seed_master --items items.csv --encoding cp949 --dry-run

Real business data stays out of Git: keep CSV files under data/ (ignored).
Empty templates with the expected headers are in apps/inventory/seed/templates/.
"""

import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory.master_import import (
    MasterImportError,
    ensure_default_lot_rules,
    import_items,
    import_staff,
    import_suppliers,
)

SAMPLE_FILE = Path(__file__).resolve().parents[2] / "seed" / "sample_master.json"


def read_csv(path, encoding):
    try:
        with open(path, encoding=encoding, newline="") as file:
            return list(csv.DictReader(file))
    except FileNotFoundError as error:
        raise CommandError(f"File not found: {path}") from error
    except UnicodeDecodeError as error:
        raise CommandError(
            f"Cannot read {path} as {encoding}. Excel CSV files often need --encoding cp949."
        ) from error


class Command(BaseCommand):
    help = "기준정보(직원·공급처·품목)와 기본 입고 LOT 규칙을 넣습니다. 같은 코드는 갱신합니다."

    def add_arguments(self, parser):
        parser.add_argument("--sample", action="store_true", help="가상 샘플 기준정보를 넣습니다.")
        parser.add_argument("--staff", help="직원 CSV 경로")
        parser.add_argument("--suppliers", help="공급처 CSV 경로")
        parser.add_argument("--items", help="품목 CSV 경로")
        parser.add_argument(
            "--encoding", default="utf-8-sig", help="CSV 인코딩 (기본 utf-8-sig, 엑셀은 cp949)"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="검증만 하고 DB에는 반영하지 않습니다."
        )

    def handle(self, *args, **options):
        sources = {}
        if options["sample"]:
            sample = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
            sources = {key: sample[key] for key in ("staff", "suppliers", "items")}
        for key in ("staff", "suppliers", "items"):
            if options[key]:
                if key in sources:
                    raise CommandError(f"--{key} cannot be combined with --sample.")
                sources[key] = read_csv(options[key], options["encoding"])

        importers = [
            ("staff", import_staff),
            ("suppliers", import_suppliers),
            ("items", import_items),
        ]
        try:
            with transaction.atomic():
                for key, importer in importers:
                    if key in sources:
                        self.stdout.write(str(importer(sources[key])))
                for rule in ensure_default_lot_rules():
                    self.stdout.write(
                        f"lot rule: created default {rule.lot_kind} rule '{rule.pattern}'"
                    )
                if options["dry_run"]:
                    transaction.set_rollback(True)
        except MasterImportError as error:
            raise CommandError(f"Nothing was saved.\n{error}") from error

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: nothing was saved."))
        else:
            self.stdout.write(self.style.SUCCESS("Master data saved."))
