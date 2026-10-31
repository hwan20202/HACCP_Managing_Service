"""Authoring preserves used recipe versions and rejects invalid replacement atomically."""

from django.db import connection

from .fields import kst_now
from .models import AuditLog, Bom, BomLine, ProductionBatch
from .quantity import to_e6
from .test_api import ApiTestCase


class BomManagementTests(ApiTestCase):
    def payload(self):
        from .models import Item

        self.semi = Item.objects.create(
            item_code="TEST-BOM-SEMI", name="테스트 제조품", item_type_id="SEMI", base_unit="kg"
        )
        return {
            "item_id": self.semi.pk,
            "staff_id": self.staff.pk,
            "base_quantity": "1000",
            "base_unit": "g",
            "effective_from": self.today,
            "lines": [{"item_id": self.raw.pk, "quantity": "500", "unit": "g"}],
        }

    def test_create_and_edit_unused_recipe(self):
        data = self.payload()
        response = self.post("/boms/", data)
        self.assertEqual(response.status_code, 201, response.content)
        bom = response.json()
        self.assertEqual(bom["base_quantity"], "1")
        self.assertEqual(bom["lines"][0]["quantity"], "0.5")
        data["lines"][0]["quantity"] = "700"
        updated = self.patch(f"/boms/{bom['id']}/", data)
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(updated.json()["id"], bom["id"])
        self.assertEqual(updated.json()["lines"][0]["quantity"], "0.7")

    def test_used_recipe_replaced_and_deletion_deactivates(self):
        data = self.payload()
        bom_id = self.post("/boms/", data).json()["id"]
        batch = ProductionBatch.objects.create(
            batch_number="TEST-BOM-VERSION",
            item=self.semi,
            bom_id=bom_id,
            process_type="MANUFACTURE",
            status="PLANNED",
            staff=self.staff,
        )
        data["lines"][0]["quantity"] = "900"
        response = self.patch(f"/boms/{bom_id}/", data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotEqual(response.json()["id"], bom_id)
        batch.refresh_from_db()
        self.assertEqual(batch.bom_id, bom_id)
        self.assertEqual(BomLine.objects.get(bom_id=bom_id).quantity_e6, to_e6("0.5"))
        result = self.post(f"/boms/{bom_id}/delete/", {"staff_id": self.staff.pk})
        self.assertTrue(result.json()["deactivated"])
        self.assertFalse(Bom.objects.get(pk=bom_id).is_active)

    def test_invalid_edit_rolls_back(self):
        data = self.payload()
        bom_id = self.post("/boms/", data).json()["id"]
        data["lines"].append(dict(data["lines"][0]))
        response = self.patch(f"/boms/{bom_id}/", data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(BomLine.objects.get(bom_id=bom_id).quantity_e6, to_e6("0.5"))

    def test_delete_unused_recipe(self):
        data = self.payload()
        bom_id = self.post("/boms/", data).json()["id"]
        response = self.post(f"/boms/{bom_id}/delete/", {"staff_id": self.staff.pk})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["deleted"])
        self.assertFalse(Bom.objects.filter(pk=bom_id).exists())

    def test_unchanged_new_version_is_rejected_after_unit_conversion(self):
        data = self.payload()
        bom_id = self.post("/boms/", data).json()["id"]
        data.update(base_quantity="1.000", base_unit="kg", new_version=True)
        data["lines"][0].update(quantity="0.500000", unit="kg")
        audits = AuditLog.objects.count()
        response = self.patch(f"/boms/{bom_id}/", data)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("변경된 내용이 없습니다", response.json()["error"]["message"])
        self.assertEqual(Bom.objects.filter(item=self.semi).count(), 1)
        self.assertEqual(AuditLog.objects.count(), audits)

    def test_used_recipe_metadata_preserves_version_and_lines(self):
        data = self.payload()
        bom_id = self.post("/boms/", data).json()["id"]
        ProductionBatch.objects.create(
            batch_number="TEST-BOM-METADATA",
            item=self.semi,
            bom_id=bom_id,
            process_type="MANUFACTURE",
            status="IN_PROGRESS",
            staff=self.staff,
        )
        line_id = BomLine.objects.get(bom_id=bom_id).pk
        data.update(is_active=False, notes="사용 중지 메모", new_version=True)
        response = self.patch(f"/boms/{bom_id}/", data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["id"], bom_id)
        self.assertFalse(response.json()["is_active"])
        self.assertEqual(BomLine.objects.get(bom_id=bom_id).pk, line_id)
        self.assertEqual(Bom.objects.filter(item=self.semi).count(), 1)
        audit = AuditLog.objects.filter(table_name="boms", record_id=str(bom_id)).last()
        self.assertTrue(audit.before_json["is_active"])
        self.assertFalse(audit.after_json["is_active"])
        resumed = self.patch(f"/boms/{bom_id}/", {"staff_id": self.staff.pk, "is_active": True})
        self.assertEqual(resumed.status_code, 200, resumed.content)
        self.assertTrue(resumed.json()["is_active"])
        self.assertEqual(resumed.json()["notes"], "사용 중지 메모")
        self.assertEqual(ProductionBatch.objects.get(bom_id=bom_id).status, "IN_PROGRESS")

    def test_notes_only_edit_keeps_version(self):
        data = self.payload()
        bom_id = self.post("/boms/", data).json()["id"]
        response = self.patch(
            f"/boms/{bom_id}/", {"staff_id": self.staff.pk, "notes": "  정정 메모  "}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["notes"], "정정 메모")
        self.assertEqual(response.json()["version"], 1)

    def test_status_change_does_not_require_active_components(self):
        data = self.payload()
        bom_id = self.post("/boms/", data).json()["id"]
        self.raw.is_active = False
        self.raw.save(update_fields=["is_active"])
        response = self.patch(f"/boms/{bom_id}/", {"staff_id": self.staff.pk, "is_active": False})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["is_active"])
        invalid = self.patch(f"/boms/{bom_id}/", {"staff_id": self.staff.pk, "is_active": "false"})
        self.assertEqual(invalid.status_code, 400)

    def test_changed_unused_recipe_can_create_new_version(self):
        data = self.payload()
        bom_id = self.post("/boms/", data).json()["id"]
        data.update(new_version=True)
        data["lines"][0]["quantity"] = "600"
        response = self.patch(f"/boms/{bom_id}/", data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotEqual(response.json()["id"], bom_id)
        self.assertEqual(response.json()["version"], 2)
        self.assertEqual(BomLine.objects.get(bom_id=bom_id).quantity_e6, to_e6("0.5"))

    def test_activation_switch_preserves_existing_production_and_changes_new_default(self):
        from .production import create_batch, standard_requirements

        data = self.payload()
        first_id = self.post("/boms/", data).json()["id"]
        running = ProductionBatch.objects.create(
            batch_number="TEST-BOM-RUNNING",
            item=self.semi,
            bom_id=first_id,
            process_type="MANUFACTURE",
            status="IN_PROGRESS",
            staff=self.staff,
        )
        planned = ProductionBatch.objects.create(
            batch_number="TEST-BOM-PLANNED",
            item=self.semi,
            bom_id=first_id,
            process_type="MANUFACTURE",
            status="PLANNED",
            staff=self.staff,
        )
        data.update(new_version=True, is_active=False)
        data["lines"][0]["quantity"] = "800"
        result = self.patch(f"/boms/{first_id}/", data)
        self.assertEqual(result.status_code, 200, result.content)
        second_id = result.json()["id"]
        self.assertTrue(Bom.objects.get(pk=first_id).is_active)
        response = self.patch(f"/boms/{second_id}/", {"staff_id": self.staff.pk, "is_active": True})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            list(Bom.objects.filter(item=self.semi, is_active=True).values_list("pk", flat=True)),
            [second_id],
        )
        running.refresh_from_db()
        planned.refresh_from_db()
        self.assertEqual((running.bom_id, running.status), (first_id, "IN_PROGRESS"))
        self.assertEqual((planned.bom_id, planned.status), (first_id, "PLANNED"))
        self.assertEqual(standard_requirements(bom_id=first_id, quantity="1")[0][1], to_e6("0.5"))
        new_batch = create_batch(item_id=self.semi.pk, staff_id=self.staff.pk)
        self.assertEqual(new_batch.bom_id, second_id)
        rejected = self.post(
            "/batches/",
            {
                "item_id": self.semi.pk,
                "staff_id": self.staff.pk,
                "bom_id": first_id,
            },
        )
        self.assertEqual(rejected.status_code, 400, rejected.content)
        self.assertTrue(
            AuditLog.objects.filter(
                table_name="boms",
                record_id=str(first_id),
                reason="v2 활성화로 기본 BOM 변경",
            ).exists()
        )

    def test_new_active_version_switches_atomically(self):
        data = self.payload()
        first_id = self.post("/boms/", data).json()["id"]
        data.update(new_version=True, is_active=True)
        data["lines"][0]["quantity"] = "800"
        response = self.patch(f"/boms/{first_id}/", data)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["is_active"])
        self.assertFalse(Bom.objects.get(pk=first_id).is_active)
        self.assertEqual(Bom.objects.filter(item=self.semi, is_active=True).count(), 1)
        second_id = response.json()["id"]
        data["lines"].append(dict(data["lines"][0]))
        invalid = self.patch(f"/boms/{second_id}/", data)
        self.assertEqual(invalid.status_code, 400)
        self.assertTrue(Bom.objects.get(pk=second_id).is_active)
        self.assertEqual(Bom.objects.filter(item=self.semi).count(), 2)

    def test_used_version_explicit_overwrite_is_rejected(self):
        data = self.payload()
        bom_id = self.post("/boms/", data).json()["id"]
        ProductionBatch.objects.create(
            batch_number="TEST-BOM-OVERWRITE",
            item=self.semi,
            bom_id=bom_id,
            process_type="MANUFACTURE",
            status="COMPLETED",
            manufactured_date=self.today,
            completed_at=kst_now(),
            staff=self.staff,
        )
        data.update(overwrite=True, new_version=False)
        data["lines"][0]["quantity"] = "900"
        response = self.patch(f"/boms/{bom_id}/", data)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("덮어쓸 수 없습니다", response.json()["error"]["message"])
        self.assertEqual(BomLine.objects.get(bom_id=bom_id).quantity_e6, to_e6("0.5"))
        self.assertEqual(Bom.objects.filter(item=self.semi).count(), 1)

    def test_activation_resolves_legacy_multiple_active_versions(self):
        data = self.payload()
        first_id = self.post("/boms/", data).json()["id"]
        # Recreate the pre-0011 legacy state: the unique index forbids two active versions.
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX ux_boms_one_active_per_item")
        legacy = Bom.objects.create(
            item=self.semi,
            version=2,
            base_quantity_e6=to_e6("1"),
            effective_from=self.today,
            is_active=True,
        )
        response = self.patch(f"/boms/{first_id}/", {"staff_id": self.staff.pk, "is_active": True})
        self.assertEqual(response.status_code, 200, response.content)
        legacy.refresh_from_db()
        self.assertFalse(legacy.is_active)
        self.assertTrue(Bom.objects.get(pk=first_id).is_active)

    def test_legacy_migration_keeps_default_and_completed_production(self):
        from importlib import import_module
        from types import SimpleNamespace

        from django.apps import apps
        from django.db import connection

        from .production import _active_bom

        data = self.payload()
        first_id = self.post("/boms/", data).json()["id"]
        # Recreate the pre-0011 legacy state: the unique index forbids two active versions.
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX ux_boms_one_active_per_item")
        second = Bom.objects.create(
            item=self.semi,
            version=2,
            base_quantity_e6=to_e6("1"),
            effective_from=self.today,
            is_active=True,
        )
        completed = ProductionBatch.objects.create(
            batch_number="TEST-BOM-LEGACY",
            item=self.semi,
            bom_id=first_id,
            process_type="MANUFACTURE",
            status="COMPLETED",
            staff=self.staff,
            manufactured_date=self.today,
            completed_at=kst_now(),
        )
        normalize = import_module(
            "apps.inventory.migrations.0010_normalize_active_boms"
        ).normalize_active_boms
        normalize(apps, SimpleNamespace(connection=connection))
        self.assertEqual(Bom.objects.filter(item=self.semi, is_active=True).count(), 1)
        self.assertFalse(Bom.objects.get(pk=first_id).is_active)
        self.assertEqual(_active_bom(self.semi).pk, second.pk)
        completed.refresh_from_db()
        self.assertEqual(completed.bom_id, first_id)
        self.assertEqual(completed.status, "COMPLETED")
        count = AuditLog.objects.count()
        normalize(apps, SimpleNamespace(connection=connection))
        self.assertEqual(AuditLog.objects.count(), count)
        # After cleanup the 0011 index can be created again.
        import_module("apps.inventory.migrations.0011_one_active_bom")
        from .sql_runner import run_sql_file

        run_sql_file("0011_one_active_bom.sql")(apps, SimpleNamespace(connection=connection))

    def test_plan_preview_identifies_bom_before_quantity_and_pins_it_on_save(self):
        data = self.payload()
        first_id = self.post("/boms/", data).json()["id"]
        data.update(new_version=True, is_active=True)
        data["lines"][0]["quantity"] = "600"
        second = self.patch(f"/boms/{first_id}/", data).json()
        before = ProductionBatch.objects.count()
        preview = self.get("/batches/preview/", item_id=self.semi.pk, planned_date=self.today)
        self.assertEqual(preview.status_code, 200, preview.content)
        self.assertEqual(preview.json()["bom_id"], second["id"])
        self.assertEqual(preview.json()["bom_version"], 2)
        self.assertEqual(ProductionBatch.objects.count(), before)
        batch = self.post(
            "/batches/",
            {
                "item_id": self.semi.pk,
                "staff_id": self.staff.pk,
                "planned_date": self.today,
                "planned_quantity": "1",
                "bom_id": preview.json()["bom_id"],
            },
        )
        self.assertEqual(batch.status_code, 201, batch.content)
        self.assertEqual(batch.json()["bom_version"], 2)
        self.assertEqual(batch.json()["status"], "PLANNED")
        self.patch(f"/boms/{first_id}/", {"staff_id": self.staff.pk, "is_active": True})
        stale = self.post(
            "/batches/",
            {
                "item_id": self.semi.pk,
                "staff_id": self.staff.pk,
                "bom_id": second["id"],
            },
        )
        self.assertEqual(stale.status_code, 400)


class SingleActiveBomTests(ApiTestCase):
    """Policy: 0 or 1 active version per item; old versions keep their open plans."""

    def setUp(self):
        super().setUp()
        from .models import Item

        self.semi = Item.objects.create(
            item_code="TEST-ONE-ACTIVE", name="단일활성 제조품", item_type_id="SEMI", base_unit="kg"
        )

    def recipe(self, quantity="500", **extra):
        return {
            "item_id": self.semi.pk,
            "staff_id": self.staff.pk,
            "base_quantity": "1000",
            "base_unit": "g",
            "effective_from": self.today,
            "lines": [{"item_id": self.raw.pk, "quantity": quantity, "unit": "g"}],
            **extra,
        }

    def plan(self, **extra):
        return self.post(
            "/batches/",
            {"item_id": self.semi.pk, "staff_id": self.staff.pk, "planned_quantity": "2", **extra},
        )

    def test_database_rejects_second_active_version(self):
        from django.db import IntegrityError, transaction

        self.post("/boms/", self.recipe())
        with self.assertRaises(IntegrityError), transaction.atomic():
            Bom.objects.create(
                item=self.semi, version=9, base_quantity_e6=to_e6(1), effective_from=self.today
            )

    def test_new_active_version_switches_default_and_keeps_open_plan(self):
        v1 = self.post("/boms/", self.recipe()).json()
        planned = self.plan().json()
        self.assertEqual(planned["bom_version"], 1)
        v2 = self.post("/boms/", self.recipe("700", new_version=True)).json()
        self.assertTrue(v2["is_active"])
        self.assertEqual(Bom.objects.filter(item=self.semi, is_active=True).get().pk, v2["id"])
        # v1 is no longer active but its open plan stays on v1.
        rows = {
            row["version"]: row
            for row in self.get("/boms/", item_id=self.semi.pk, include_inactive=1).json()[
                "results"
            ]
        }
        self.assertFalse(rows[1]["is_active"])
        self.assertEqual(rows[1]["open_batch_count"], 1)
        self.assertEqual(rows[2]["open_batch_count"], 0)
        self.assertEqual(ProductionBatch.objects.get(pk=planned["id"]).bom_id, v1["id"])
        detail = self.get(f"/batches/{planned['id']}/").json()
        self.assertFalse(detail["bom_is_active"])
        self.assertEqual(detail["active_bom"]["version"], 2)

    def test_inactive_new_version_keeps_current_default(self):
        v1 = self.post("/boms/", self.recipe()).json()
        v2 = self.post("/boms/", self.recipe("700", new_version=True, is_active=False)).json()
        self.assertFalse(v2["is_active"])
        self.assertTrue(Bom.objects.get(pk=v1["id"]).is_active)

    def test_all_inactive_is_allowed_but_plan_is_refused(self):
        v1 = self.post("/boms/", self.recipe()).json()
        response = self.patch(f"/boms/{v1['id']}/", {"staff_id": self.staff.pk, "is_active": False})
        self.assertEqual(response.status_code, 200, response.content)
        refused = self.plan()
        self.assertEqual(refused.status_code, 400, refused.content)
        self.assertIn("활성 BOM이 없습니다", refused.json()["error"]["message"])
        preview = self.get("/batches/preview/", item_id=self.semi.pk).json()
        self.assertIn("활성 BOM이 없습니다", preview["message"])
        self.assertFalse(ProductionBatch.objects.filter(item=self.semi).exists())

    def test_stale_screen_bom_is_refused_with_new_version(self):
        v1 = self.post("/boms/", self.recipe()).json()
        self.post("/boms/", self.recipe("700", new_version=True))
        refused = self.plan(bom_id=v1["id"])
        self.assertEqual(refused.status_code, 400, refused.content)
        self.assertIn("v1에서 v2", refused.json()["error"]["message"])

    def test_switch_bom_cancels_and_replans_atomically(self):
        self.post("/boms/", self.recipe())
        old = self.plan(planned_date=self.today, notes="오전 생산").json()
        v2 = self.post("/boms/", self.recipe("700", new_version=True)).json()
        response = self.post(f"/batches/{old['id']}/switch-bom/", {"staff_id": self.staff.pk})
        self.assertEqual(response.status_code, 201, response.content)
        new = response.json()
        self.assertNotEqual(new["id"], old["id"])
        self.assertNotEqual(new["batch_number"], old["batch_number"])
        self.assertEqual(new["bom_id"], v2["id"])
        self.assertEqual(new["planned_quantity"], old["planned_quantity"])
        self.assertEqual(new["planned_date"], old["planned_date"])
        self.assertEqual(new["notes"], "오전 생산")
        cancelled = ProductionBatch.objects.get(pk=old["id"])
        self.assertEqual(cancelled.status, "CANCELLED")
        self.assertIn(new["batch_number"], cancelled.cancel_reason)
        self.assertTrue(
            AuditLog.objects.filter(
                table_name="production_batches",
                record_id=str(new["id"]),
                reason__contains=old["batch_number"],
            ).exists()
        )
        # Second click: the old plan is already cancelled, nothing else is created.
        again = self.post(f"/batches/{old['id']}/switch-bom/", {"staff_id": self.staff.pk})
        self.assertEqual(again.status_code, 400, again.content)
        self.assertEqual(ProductionBatch.objects.filter(item=self.semi).count(), 2)

    def test_switch_bom_refuses_started_or_current_plans(self):
        self.post("/boms/", self.recipe())
        current = self.plan().json()
        same = self.post(f"/batches/{current['id']}/switch-bom/", {"staff_id": self.staff.pk})
        self.assertEqual(same.status_code, 400, same.content)
        self.assertIn("이미 활성 BOM", same.json()["error"]["message"])
        ProductionBatch.objects.filter(pk=current["id"]).update(status="IN_PROGRESS")
        self.post("/boms/", self.recipe("700", new_version=True))
        started = self.post(f"/batches/{current['id']}/switch-bom/", {"staff_id": self.staff.pk})
        self.assertEqual(started.status_code, 400, started.content)
        self.assertIn("시작 전 계획만", started.json()["error"]["message"])
        self.assertEqual(ProductionBatch.objects.filter(item=self.semi).count(), 1)

    def test_switch_bom_rolls_back_new_plan_when_cancel_fails(self):
        from unittest import mock

        from .errors import InventoryError

        self.post("/boms/", self.recipe())
        old = self.plan().json()
        self.post("/boms/", self.recipe("700", new_version=True))
        with mock.patch(
            "apps.inventory.production.cancel_batch", side_effect=InventoryError("취소 불가")
        ):
            response = self.post(f"/batches/{old['id']}/switch-bom/", {"staff_id": self.staff.pk})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(ProductionBatch.objects.filter(item=self.semi).count(), 1)
        self.assertEqual(ProductionBatch.objects.get(pk=old["id"]).status, "PLANNED")

    def test_future_effective_bom_blocks_plan_explicit_bom_and_switch_alike(self):
        import datetime

        future = (
            datetime.date.fromisoformat(str(self.today)) + datetime.timedelta(days=30)
        ).isoformat()
        self.post("/boms/", self.recipe())
        old = self.plan().json()
        v2 = self.post("/boms/", self.recipe("700", new_version=True, effective_from=future)).json()
        self.assertTrue(v2["is_active"])
        for label, response in (
            ("default", self.plan()),
            ("explicit bom_id", self.plan(bom_id=v2["id"])),
            (
                "switch",
                self.post(f"/batches/{old['id']}/switch-bom/", {"staff_id": self.staff.pk}),
            ),
        ):
            with self.subTest(label):
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("적용 시작일", response.json()["error"]["message"])
        # The refused switch left the old plan untouched and created nothing.
        self.assertEqual(ProductionBatch.objects.get(pk=old["id"]).status, "PLANNED")
        self.assertEqual(ProductionBatch.objects.filter(item=self.semi).count(), 1)
