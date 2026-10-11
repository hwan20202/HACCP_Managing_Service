"""P4 API 테스트 (수준 A): A02 변경, A09·A10(작성완료·재개), A15~A17(개선조치), trace(TC-181)."""

from django.conf import settings
from django.test import override_settings

from apps.documents import flows
from apps.documents.tests.p4 import filled_ccp1p, new_d01, setup_p4, version_of
from apps.documents.tests.test_api import TRACE_MIDDLEWARE, ApiTestCase


class P4ApiTestCase(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.p4 = setup_p4()

    def post(self, path, body, **kwargs):
        return self.send("post", path, body, **kwargs)


class CompleteApiTests(P4ApiTestCase):
    def test_tc135_complete(self):
        document_id = filled_ccp1p()
        path = f"documents/{document_id}/complete"
        self.assertError(self.post(path, {}), 400, "INVALID_REQUEST")
        self.assertError(self.post(path, {"expected_version": 1, "x": 1}), 400, "INVALID_REQUEST")
        ok = self.post(path, {"expected_version": version_of(document_id)})
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.json()["status"], "completed")
        d01 = new_d01()["document"]["document_id"]
        failed = self.post(f"documents/{d01}/complete", {"expected_version": 1})
        self.assertError(failed, 400, "COMPLETION_INCOMPLETE")
        self.assertEqual(failed.json()["details"][0]["code"], "files_required")
        self.assertError(
            self.post(path, {"expected_version": 1}, staff=None), 400, "STAFF_HEADER_MISSING"
        )

    def test_tc137_reopen(self):
        document_id = filled_ccp1p()
        self.post(
            f"documents/{document_id}/complete", {"expected_version": version_of(document_id)}
        )
        path = f"documents/{document_id}/reopen"
        self.assertError(self.post(path, {"expected_version": 1}), 409, "VERSION_CONFLICT")
        ok = self.post(path, {"expected_version": version_of(document_id)})
        self.assertEqual((ok.status_code, ok.json()["status"]), (200, "draft"))
        self.assertIsNone(ok.json()["completed_at"])
        self.assertError(
            self.post(path, {"expected_version": version_of(document_id)}),
            409,
            "INVALID_TRANSITION",
        )

    def test_tc151_templates_include_flag(self):
        items = {i["type_code"]: i for i in self.client.get("/api/v1/templates").json()["items"]}
        self.assertTrue(items["CCP-1P"]["requirement_only"])
        self.assertFalse(items["HYGIENE_CHECK"]["requirement_only"])

    def test_list_target_param(self):
        new_d01()
        items = self.client.get("/api/v1/documents?target=RM-1011-01").json()["items"]
        self.assertEqual([i["target_summary"] for i in items], ["LOT RM-1011-01"])
        self.assertError(
            self.client.get("/api/v1/documents?target=" + "x" * 51), 400, "INVALID_FILTER"
        )


class DeviationApiTests(P4ApiTestCase):
    def test_tc176_create_update_delete(self):
        document_id = filled_ccp1p()
        created = self.post(
            f"documents/{document_id}/deviations",
            {"description": "09:50 자력 9,800G", "actor_id": 4, "checker_ids": [2]},
            staff=4,
        )
        self.assertEqual(created.status_code, 201, created.content)
        deviation_id = created.json()["deviation_id"]
        updated = self.send(
            "patch",
            f"deviations/{deviation_id}",
            {"expected_version": 1, "action_result": "재조정 후 적합"},
            staff=2,
            auto_version=False,
        )
        self.assertEqual((updated.status_code, updated.json()["version"]), (200, 2))
        self.assertError(
            self.send(
                "patch", f"deviations/{deviation_id}", {"action_result": "x"}, auto_version=False
            ),
            400,
            "INVALID_REQUEST",
        )
        self.assertError(self.send("delete", f"deviations/{deviation_id}"), 400, "INVALID_REQUEST")
        self.assertError(
            self.send("delete", f"deviations/{deviation_id}?expected_version=1"),
            409,
            "VERSION_CONFLICT",
        )
        deleted = self.send("delete", f"deviations/{deviation_id}?expected_version=2")
        self.assertEqual(deleted.status_code, 204)
        self.assertError(
            self.send("delete", f"deviations/{deviation_id}?expected_version=3"),
            404,
            "DEVIATION_NOT_FOUND",
        )
        self.assertError(
            self.post(f"documents/{document_id}/deviations", {"description": "x"}, staff=None),
            400,
            "STAFF_HEADER_MISSING",
        )
        self.assertError(
            self.post(f"documents/{document_id}/deviations", {"description": "x", "y": 1}),
            400,
            "INVALID_REQUEST",
        )


@override_settings(
    ROOT_URLCONF="apps.devtools.test_urls",
    MIDDLEWARE=[*settings.MIDDLEWARE, TRACE_MIDDLEWARE],
)
class P4TraceApiTests(P4ApiTestCase):
    """DOC-TC-181: 새 API의 trace 단계 순서가 p4-s2-flows.md와 같다."""

    def ids(self, response):
        return [s["step_id"] for s in response.json()["trace"]["steps"]]

    def ids_by_header(self, response):
        data = self.client.get(f"/api/dev/traces/{response['X-Trace-Id']}").json()
        return [s["step_id"] for s in data["steps"]]

    def test_tc181_new_api_traces(self):
        document_id = filled_ccp1p()
        complete = self.post(
            f"documents/{document_id}/complete", {"expected_version": version_of(document_id)}
        )
        self.assertTrue(flows.matches("DOC-CMP", self.ids(complete)), self.ids(complete))
        reopen = self.post(
            f"documents/{document_id}/reopen", {"expected_version": version_of(document_id)}
        )
        self.assertTrue(flows.matches("DOC-ROP", self.ids(reopen)), self.ids(reopen))
        created = self.post(f"documents/{document_id}/deviations", {"description": "x"})
        self.assertTrue(flows.matches("DOC-DVC", self.ids(created)), self.ids(created))
        deviation_id = created.json()["deviation_id"]
        updated = self.send(
            "patch",
            f"deviations/{deviation_id}",
            {"expected_version": 1, "action_result": "y"},
            auto_version=False,
        )
        self.assertTrue(flows.matches("DOC-DVU", self.ids(updated)), self.ids(updated))
        deleted = self.send("delete", f"deviations/{deviation_id}?expected_version=2")
        self.assertEqual(deleted.status_code, 204)
        ids = self.ids_by_header(deleted)
        self.assertTrue(flows.matches("DOC-DVD", ids), ids)

    def test_snapshot_includes_p4_tables(self):
        document_id = filled_ccp1p()
        self.post(f"documents/{document_id}/deviations", {"description": "x", "checker_ids": [5]})
        data = self.client.get(f"/api/dev/snapshot?document_id={document_id}").json()
        tables = data["tables"]
        self.assertEqual(tables["document_ref"][0]["production_batch_id"], 12)
        self.assertEqual(len(tables["deviation_action"]), 1)
        self.assertEqual(tables["deviation_checker"][0]["staff_id"], 5)
        self.assertIn({"staff_id": 5}, tables["staff"])
