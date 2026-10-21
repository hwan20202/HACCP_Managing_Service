"""P14 r13·r14 작성 권한 — REQ 쪽 ROLE-TC-31·46·48·50 (p14-s2-spec.md 2.6, 10.6, 11장).

묶음 문서마다 can_write(R07 — 점검자는 문서마다), 묶음 permissions.assign_inspector(R08),
헤더 없는 묶음 조회(r14 D-202 Q7 b), [내 문서]의 작성 권한자(r13), 주기 문서 만들기는 누구나(R06).
"""

from django.test import TestCase

from apps.doc_requirements import periodic, todo
from apps.doc_requirements import services as req
from apps.document_workflow.tests.base import invariant_violations
from apps.document_workflow.tests.p7 import DAY as P7_DAY
from apps.document_workflow.tests.p7 import d03, setup_p7
from apps.documents import services as doc
from apps.documents.models import Document
from apps.documents.tests.p8 import MON, TUE, setup_p8
from apps.documents.tests.p8 import periodic as per
from apps.staff import roles
from apps.staff.tests.base import RolesFileMixin, default_roles

from .base import setup_req
from .test_p9 import RulesFileMixin, today


class IncomingBundleWriteTests(RolesFileMixin, TestCase):
    """ROLE-TC-48·50: 입고일 묶음 can_write·permissions, 헤더 없음."""

    def setUp(self):
        setup_p7()

    def tearDown(self):
        self.assertEqual(invariant_violations(), [])

    def docs(self, actor):
        body = req.incoming_bundle(actor, P7_DAY)
        return body, {
            x["document"]["document_id"]: x["document"] for x in body["lots"] if x["document"]
        }

    def test_tc48(self):
        mine = d03("draft", inspector=4)["document_id"]  # 4 = 역할 없음, 이 문서 점검자
        other = d03("draft", inspector=2)["document_id"]
        body, docs = self.docs(4)
        self.assertEqual((docs[mine]["can_write"], docs[other]["can_write"]), (True, False))
        self.assertEqual(body["permissions"], {"assign_inspector": False})
        body, docs = self.docs(2)  # 담당자
        self.assertTrue(docs[other]["can_write"])
        self.assertEqual(body["permissions"], {"assign_inspector": True})
        data = default_roles()
        data["forms"]["D03"]["writers"] = ["DEV-004"]
        self.use_roles(data)
        body, docs = self.docs(4)  # 작성 권한자: 쓰기 O, 점검자 지정 X
        self.assertEqual(
            (docs[other]["can_write"], body["permissions"]), (True, {"assign_inspector": False})
        )

    def test_tc50_no_header(self):
        made = d03("draft")["document_id"]
        response = self.client.get(f"/api/v1/incoming-inspections?received_date={P7_DAY}")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        line = next(x["document"] for x in body["lots"] if x["document"]["document_id"] == made)
        self.assertEqual(
            (line["my_slots"], line["can_submit"], line["submit_block"], line["can_write"]),
            ([], False, "role_required", False),
        )
        self.assertEqual(body["permissions"], {"assign_inspector": False})
        response = self.client.get(
            f"/api/v1/incoming-inspections?received_date={P7_DAY}", HTTP_X_STAFF_ID="999"
        )
        self.assertEqual((response.status_code, response.json()["code"]), (403, "INVALID_STAFF"))


class PeriodicBundleWriteTests(TestCase):
    """ROLE-TC-48·50: 주 묶음 — 헤더 없음 200, 담당자 can_write·assign_inspector."""

    def setUp(self):
        setup_p8()

    def get(self, staff=None):
        headers = {} if staff is None else {"HTTP_X_STAFF_ID": str(staff)}
        return self.client.get(
            f"/api/v1/periodic-bundles?type_code=D10&week_start={MON}", **headers
        )

    def test_tc48_tc50(self):
        per("D10", MON)
        body = self.get().json()
        cell = body["days"][0]["document"]
        self.assertEqual((cell["can_write"], cell["my_slots"]), (False, []))
        self.assertEqual(body["permissions"], {"assign_inspector": False})
        body = self.get(2).json()  # D10 담당자
        self.assertEqual(
            (body["days"][0]["document"]["can_write"], body["permissions"]),
            (True, {"assign_inspector": True}),
        )
        self.assertFalse(self.get(4).json()["days"][0]["document"]["can_write"])


class MineWriterTests(RolesFileMixin, RulesFileMixin, TestCase):
    """ROLE-TC-31(r13): [내 문서] = 점검자 + 양식 담당자 + 작성 권한자(작성자는 안 봄)."""

    def setUp(self):
        super().setUp()
        setup_req()
        setup_p8()

    def mine(self, actor):
        with today(TUE):
            out = todo.todo_list(actor, TUE, True)
        return {r["document_id"] for g in out["groups"] for r in g["rows"] if r.get("document_id")}

    def test_tc31_writer(self):
        made = per("D10", TUE, actor=4)["document_id"]  # 작성자 = 4(안 봄)
        self.assertNotIn(made, self.mine(4))
        data = default_roles()
        data["forms"]["D10"]["writers"] = ["DEV-004"]
        self.use_roles(data)
        self.assertIn(made, self.mine(4))


class PeriodicOpenTests(RulesFileMixin, TestCase):
    """ROLE-TC-46(R06): 주기 문서 하나 만들기는 역할 없이 — 만든 문서 수정은 403(R07)."""

    def setUp(self):
        super().setUp()
        setup_req()
        setup_p8()

    def test_tc46(self):
        out = periodic.open_periodic_document(4, "D10", MON)
        document_id = out["document_id"] if "document_id" in out else out["document"]["document_id"]
        self.assertEqual(Document.objects.get(pk=document_id).created_by_id, 4)
        with self.assertRaises(roles.RoleRequired):
            doc.update_document(
                4, document_id, {"expected_version": 1, "document": {"subject": "x"}}
            )
