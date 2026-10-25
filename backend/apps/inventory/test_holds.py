"""Holds (holds.py, sql/0003_holds.sql): LOT / batch holds, propagation, release."""

import json

from django.db import IntegrityError, connection, transaction

from .errors import InventoryError
from .holds import hold_batch, hold_lot, release_hold
from .models import Hold
from .production import add_output, add_usage, complete_batch, fefo_candidates
from .test_production import ProductionTestCase


def usable(lot):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT is_usable, active_hold_count FROM v_lot_availability WHERE lot_id = %s",
            [lot.pk],
        )
        return cursor.fetchone()


class HoldTests(ProductionTestCase):
    def test_batch_api_manual_hold_and_release_without_document_approval(self):
        lot = self.receive(self.raw, "10", "r1")
        batch = self.batch(self.semi)
        self.use(batch, lot, "1", "u1")
        output = self.output(batch, "100", "o1").lot
        base = "/api/v1/inventory"

        def post(path, data):
            return self.client.post(base + path, json.dumps(data), content_type="application/json")

        response = post(
            "/holds/",
            {
                "batch_id": batch.pk,
                "source_type": "MANUAL",
                "reason": "CCP 이탈 확인",
                "staff_id": self.staff.pk,
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        hold_id = response.json()["id"]
        self.assertIsNone(response.json()["source_document_id"])
        detail = self.client.get(f"{base}/batches/{batch.pk}/").json()
        self.assertEqual(detail["active_hold_count"], 1)
        self.assertEqual(len(detail["holds"]), 1)  # LOT propagation is not a second batch hold.
        self.assertEqual(detail["holds"][0]["reason"], "CCP 이탈 확인")
        listing = self.client.get(f"{base}/batches/", {"item_id": self.semi.pk}).json()["results"]
        self.assertEqual(listing[0]["active_hold_count"], 1)
        self.assertEqual(usable(output), (0, 1))
        rejected = post(
            f"/batches/{batch.pk}/outputs/",
            {
                "quantity": "1",
                "staff_id": self.staff.pk,
                "idempotency_key": "held-output",
            },
        )
        self.assertGreaterEqual(rejected.status_code, 400)

        independent = self.lot_hold(output)
        response = post(
            f"/holds/{hold_id}/release/",
            {
                "disposition": "RELEASE",
                "reason": "개선조치 완료 및 현장 확인",
                "staff_id": self.staff.pk,
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["released_by"]["id"], self.staff.pk)
        detail = self.client.get(f"{base}/batches/{batch.pk}/").json()
        self.assertEqual(detail["active_hold_count"], 0)
        self.assertFalse(detail["holds"][0]["is_open"])
        self.assertEqual(detail["holds"][0]["release_reason"], "개선조치 완료 및 현장 확인")
        listing = self.client.get(f"{base}/batches/", {"item_id": self.semi.pk}).json()["results"]
        self.assertEqual(listing[0]["active_hold_count"], 0)
        independent.refresh_from_db()
        self.assertIsNone(independent.released_at)
        self.assertEqual(usable(output), (0, 1))  # Direct LOT hold remains in effect.

    def lot_hold(self, lot, source="MANUAL", **extra):
        return hold_lot(
            lot_id=lot.pk, source_type=source, reason="이물 의심", staff_id=self.staff.pk, **extra
        )

    def test_lot_hold_blocks_use_until_released(self):
        lot = self.receive(self.raw, "10", "r1")
        hold = self.lot_hold(lot)
        self.assertEqual(usable(lot), (0, 1))
        self.assertEqual(self.lot_hold(lot).pk, hold.pk)  # one open direct hold per LOT
        batch = self.batch(self.semi)
        with self.assertRaises(InventoryError):
            self.use(batch, lot, "1", "u1")
        self.assertEqual(fefo_candidates(item_id=self.raw.pk, quantity="1"), [])
        release_hold(
            hold_id=hold.pk, disposition="RELEASE", reason="이상 없음", staff_id=self.staff.pk
        )
        self.assertEqual(usable(lot), (1, 0))
        self.use(batch, lot, "1", "u1")
        with self.assertRaises(InventoryError):
            release_hold(hold_id=hold.pk, disposition="RELEASE", reason="x", staff_id=self.staff.pk)

    def test_evidence_and_codes(self):
        lot = self.receive(self.raw, "10", "r1")
        with self.assertRaises(InventoryError):
            self.lot_hold(lot, source="CCP")  # needs document_id
        with self.assertRaises(InventoryError):
            self.lot_hold(lot, source="PROPAGATED")  # only made by batch holds
        with self.assertRaises(InventoryError):
            self.lot_hold(lot, source="NOPE")
        hold = self.lot_hold(lot, source="CCP", source_document_id=77)
        self.assertEqual(hold.source_document_id, 77)
        with self.assertRaises(InventoryError):
            release_hold(hold_id=hold.pk, disposition="KEEP", reason="x", staff_id=self.staff.pk)
        with self.assertRaises(InventoryError):
            release_hold(hold_id=hold.pk, disposition="RELEASE", reason=" ", staff_id=self.staff.pk)

    def test_batch_hold_propagates_and_blocks_the_batch(self):
        raw_lot = self.receive(self.raw, "20", "r1")
        batch = self.batch(self.semi)
        self.use(batch, raw_lot, "5", "u1")
        out = self.output(batch, "100", "o1").lot
        self.assertEqual(self.output(batch, "100", "o2").lot, out)  # 1 배치 = 1 LOT (10/15)
        hold = hold_batch(
            batch_id=batch.pk,
            source_type="CCP",
            reason="금속검출 이탈",
            staff_id=self.staff.pk,
            source_document_id=5,
        )
        children = list(hold.propagated_holds.order_by("lot_id"))
        self.assertEqual([c.lot_id for c in children], [out.pk])
        self.assertTrue(all(c.source_type_id == "PROPAGATED" for c in children))
        self.assertEqual((usable(out), usable(raw_lot)), ((0, 1), (1, 0)))  # inputs untouched
        for action in (
            lambda: add_usage(
                batch_id=batch.pk,
                lot_id=raw_lot.pk,
                quantity="1",
                staff_id=self.staff.pk,
                idempotency_key="u2",
            ),
            lambda: add_output(
                batch_id=batch.pk, quantity="1", staff_id=self.staff.pk, idempotency_key="o3"
            ),
        ):
            with self.assertRaises(InventoryError):
                action()
        with self.assertRaises(InventoryError):
            complete_batch(batch_id=batch.pk, staff_id=self.staff.pk)
        self.assertEqual(
            hold_batch(
                batch_id=batch.pk, source_type="MANUAL", reason="x", staff_id=self.staff.pk
            ).pk,
            hold.pk,
        )

        # The LOT is handled first (disposed), then the batch hold is released.
        release_hold(
            hold_id=children[0].pk, disposition="DISPOSE", reason="폐기", staff_id=self.staff.pk
        )
        release_hold(
            hold_id=hold.pk, disposition="RELEASE", reason="개선조치 완료", staff_id=self.staff.pk
        )
        children = list(Hold.objects.filter(parent_hold=hold).order_by("lot_id"))
        self.assertEqual([c.disposition_id for c in children], ["DISPOSE"])  # kept as handled
        self.assertEqual(usable(out), (1, 0))

    def test_hold_rows_are_kept(self):
        lot = self.receive(self.raw, "10", "r1")
        hold = self.lot_hold(lot)
        release_hold(hold_id=hold.pk, disposition="RELEASE", reason="ok", staff_id=self.staff.pk)
        for sql in ("DELETE FROM holds", "UPDATE holds SET reason = 'x'"):
            with self.subTest(sql), self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql)
