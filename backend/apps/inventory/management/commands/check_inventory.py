"""Consistency checks for the inventory tables. Exits with an error when something is wrong.

    python backend/manage.py check_inventory

1. inventory equals the sum of stock_movements per LOT (v_inventory_mismatch, I3)
2. a closed LOT (DISPOSED / CONSUMED) holds no stock
3. a cancelled receipt's LOT holds no stock
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

CHECKS = [
    (
        "재고 ≠ 수불 합계 (I3)",
        "SELECT lot_id, quantity_e6, movement_sum_e6 FROM v_inventory_mismatch",
    ),
    (
        "종료 상태 LOT에 재고 있음",
        """SELECT l.id, l.lot_number, l.status, inv.quantity_e6
           FROM lots l JOIN inventory inv ON inv.lot_id = l.id
           WHERE l.status IN ('DISPOSED', 'CONSUMED') AND inv.quantity_e6 > 0""",
    ),
    (
        "취소된 입고의 LOT에 재고 있음",
        """SELECT r.id, l.lot_number, inv.quantity_e6
           FROM incoming_receipts r
           JOIN lots l ON l.id = r.lot_id
           JOIN inventory inv ON inv.lot_id = l.id
           WHERE r.receipt_status = 'CANCELLED' AND inv.quantity_e6 > 0""",
    ),
]


class Command(BaseCommand):
    help = "재고·수불 정합성을 점검합니다. 문제가 있으면 오류로 종료합니다."

    def handle(self, *args, **options):
        problems = 0
        with connection.cursor() as cursor:
            for label, sql in CHECKS:
                cursor.execute(sql)
                rows = cursor.fetchall()
                if rows:
                    problems += len(rows)
                    self.stdout.write(self.style.ERROR(f"[FAIL] {label}: {len(rows)}건"))
                    for row in rows[:20]:
                        self.stdout.write(f"    {row}")
                else:
                    self.stdout.write(f"[ OK ] {label}")
        if problems:
            raise CommandError(f"정합성 문제 {problems}건")
        self.stdout.write(self.style.SUCCESS("재고·수불 정합성 이상 없음"))
