"""PLG 테스트 준비물. 문서 행은 SQL로 최소한만 만든다(DOC 내부 함수 없이)."""

import json

from django.db import connection, transaction
from django.test import TestCase
from django.utils import timezone

from apps.production_log import services
from apps.production_log.models import Process
from apps.staff import services as staff_services


def run(fn, *args, **kwargs):
    with transaction.atomic():
        return fn(*args, **kwargs)


def builtin(kind):
    return Process.objects.get(kind=kind)


def make_prod_log_row(process_id):
    """PROD-LOG 양식·문서·steps 행 1개(공정 사용 이력 — PLG-R15)."""
    now = timezone.now().isoformat()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO document_template (type_code, version, name, schema_json, is_active,"
            " created_at) VALUES ('PROD-LOG', 1, '생산일지', %s, 1, %s)",
            [json.dumps({"sections": []}), now],
        )
        template_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO document (template_id, work_date, created_by, status, created_at,"
            " updated_at, version) VALUES (%s, '2026-10-26', 1, 'draft', %s, %s, 1)",
            [template_id, now, now],
        )
        document_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO doc_section (document_id, section_def, row_no, values_json)"
            " VALUES (%s, 'steps', 1, %s)",
            [document_id, json.dumps({"kind": "GEN", "process_id": process_id, "name": "x"})],
        )
    return document_id


class PlgTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        staff_services.ensure_dev_staff(range(1, 4))

    def new_process(self, name="분쇄", mode="JUDGE", actor=1, **extra):
        return run(services.create_process, actor, {"name": name, "mode": mode, **extra})

    def new_template(self, name="효력환", process_ids=None, actor=1, **extra):
        if process_ids is None:
            process_ids = [self.new_process()["process_id"], builtin("CCP-1P").pk]
        steps = [{"process_id": pid} for pid in process_ids]
        return run(services.create_template, actor, {"name": name, "steps": steps, **extra})

    def assertRaisesCode(self, code, fn, *args, **kwargs):
        try:
            run(fn, *args, **kwargs)
        except services.errors.PlgError as error:
            self.assertEqual(error.code, code, error.details)
            return error
        self.fail(f"{code} 예외가 나야 합니다")
