"""P8 S4 WF 몫 (p8-s2-spec 7장 P8-TC-036·070): 작성 안 함 문서 상신 거부, D10 일괄 상신·승인.

WF 코드는 바뀌지 않았다 — 일괄 대상 설정(HACCP_BATCH_TYPES 기본 D03·D10·D11·D12)만.
"""

from django.test import TestCase

from apps.document_workflow import services as wf
from apps.document_workflow.tests.base import invariant_violations
from apps.document_workflow.tests.p7 import sql, status_of, version_of
from apps.documents import services as doc
from apps.documents.tests.p8 import MON, TUE, WED, fill, periodic, setup_p8


def slot_of(document_id, slot_no):
    return sql(
        "SELECT a.approval_id FROM approval a JOIN approval_request r USING (request_id) "
        "WHERE r.document_id = %s AND a.slot_no = %s",
        [document_id, slot_no],
    )[0][0]


def completed(day, code="D10"):
    detail = fill(periodic(code, day)["document_id"])
    return doc.complete_document(3, detail["document_id"], detail["version"])


class P8WorkflowTests(TestCase):
    def setUp(self):
        setup_p8()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def test_tc036_skipped_not_submittable(self):
        made = periodic("D10", TUE)
        doc.skip_documents(3, [{"document_id": made["document_id"], "expected_version": 1}], "휴무")
        items = [{"document_id": made["document_id"], "expected_version": 2}]
        body = wf.batch_submit(3, items)
        self.assertEqual(body["results"][0]["error"]["code"], "DOCUMENT_LOCKED")
        with self.assertRaises(Exception) as ctx:
            wf.submit(3, made["document_id"], 2)
        self.assertEqual(getattr(ctx.exception, "code", None), "DOCUMENT_LOCKED")
        self.assertEqual(status_of(made["document_id"]), ("skipped", 2))

    def test_tc070_batch_approve_d10(self):
        made = [completed(day) for day in (MON, TUE, WED)]
        items = [
            {"document_id": m["document_id"], "expected_version": version_of(m["document_id"])}
            for m in made
        ]
        submitted = wf.batch_submit(3, items)
        self.assertEqual(submitted["succeeded"], 3, submitted)
        first, second = ([slot_of(m["document_id"], n) for m in made] for n in (1, 2))
        self.assertEqual(wf.batch_approve(3, first)["succeeded"], 3)
        self.assertEqual(wf.batch_approve(1, second)["succeeded"], 3)
        self.assertEqual({status_of(m["document_id"])[0] for m in made}, {"approved"})

    def test_d11_batch_submit(self):
        made = completed(MON, "D11")
        items = [{"document_id": made["document_id"], "expected_version": made["version"]}]
        self.assertEqual(wf.batch_submit(3, items)["succeeded"], 1)
