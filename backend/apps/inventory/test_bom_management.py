"""Authoring preserves used recipe versions and rejects invalid replacement atomically."""

from .models import Bom, BomLine, ProductionBatch
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
