"""Copy a local DB read-only and create disposable browser fixtures in tools/."""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_db.resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    output = root / "tools" / "bulk-production-qa"
    target = output / f"data-{time.time_ns()}"
    (target / "db").mkdir(parents=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(target / "db" / "app.sqlite3") as copied:
            original.backup(copied)
    prototype = target / "legacy-prototype" / "src" / "js"
    prototype.mkdir(parents=True)
    shutil.copyfile(root / "data/legacy-prototype/src/js/data.js", prototype / "data.js")
    os.environ["HACCP_DATA_DIR"] = str(target)
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.development"
    sys.path.insert(0, str(root / "backend"))
    import django

    django.setup()
    from apps.inventory.fields import kst_now
    from apps.inventory.models import Bom, BomLine, Item, Staff, Supplier
    from apps.inventory.production import add_usage, create_batch, start_batch
    from apps.inventory.receiving import ReceiptInput, register_receipt

    staff = Staff.objects.filter(is_active=True).first()
    supplier = Supplier.objects.first()
    today = kst_now().date()
    semi = Item.objects.create(
        item_type_id="SEMI",
        item_code="BULKQA",
        short_code="BQA",
        name="QA 일괄 투입 18원료",
        base_unit="kg",
    )
    bom = Bom.objects.create(item=semi, version=1, base_quantity_e6=1000000, effective_from=today)
    lots = []
    for n in range(18):
        item = Item.objects.create(
            item_type_id="RAW",
            item_code=f"BULKQA{n:02}",
            short_code=f"BQ{n:02}",
            name=f"QA 원료 {n + 1:02}",
            base_unit="kg",
        )
        line = BomLine.objects.create(
            bom=bom, line_no=n + 1, component_item=item, quantity_e6=10000
        )
        lot = register_receipt(
            ReceiptInput(
                item_id=item.pk,
                supplier_id=supplier.pk,
                staff_id=staff.pk,
                received_date=today,
                quantity="10",
                judgment="PASS",
                expiration_status="NONE",
                idempotency_key=f"bulk-qa-{n}",
            )
        ).lot
        lots.append((lot, line))
    batch = create_batch(item_id=semi.pk, bom_id=bom.pk, planned_quantity="1", staff_id=staff.pk)
    start_batch(batch_id=batch.pk, staff_id=staff.pk)
    for lot, line in lots[:3]:
        add_usage(
            batch_id=batch.pk,
            lot_id=lot.pk,
            quantity="0.01",
            bom_line_id=line.pk,
            staff_id=staff.pk,
            idempotency_key=f"already-{lot.pk}",
        )
    fixture = {
        "batch_id": batch.pk,
        "staff_id": staff.pk,
        "lot_ids": [lot.pk for lot, _ in lots],
        "data_dir": str(target),
    }
    (output / "fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
    print(json.dumps(fixture))


if __name__ == "__main__":
    main()
