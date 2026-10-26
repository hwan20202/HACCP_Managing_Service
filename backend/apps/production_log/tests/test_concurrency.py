"""S4a 외부 검토 R2: 실제 SQLite 잠금에서 동시 요청(파일 DB 전용).

  HACCP_TEST_FILE_DB=1 python manage.py test apps.production_log.tests.test_concurrency \\
      --settings=config.settings.test_filedb

모든 atomic()이 IMMEDIATE(쓰기 잠금)로 시작하므로 두 번째 요청은 첫 번째가 끝날 때까지 기다리고,
끝난 뒤의 상태로 검사한다 → 같은 이름은 409, 지워진 공정은 400(500이 아님).
"""

import os
import threading
import unittest

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase

from apps.production_log import errors, services
from apps.production_log.models import Process, ProcessTemplate
from apps.staff import services as staff_services


def _file_db():
    name = str(connection.settings_dict.get("NAME", ""))
    return "memory" not in name and name != ":memory:"


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and _file_db(), "파일 SQLite 테스트 DB에서만 실행"
)
class PlgConcurrencyTests(TransactionTestCase):
    def setUp(self):
        staff_services.ensure_dev_staff([1, 2])

    def race(self, first, second):
        """first는 끝내기 전 트랜잭션을 잡고 멈추고, second는 그동안 잠금을 기다린다."""
        locked, release, results = threading.Event(), threading.Event(), {}

        def run(name, func, hold):
            try:
                with transaction.atomic():
                    results[name] = ("ok", func())
                    if hold:
                        locked.set()
                        release.wait(10)
            except Exception as error:  # noqa: BLE001 - 결과 비교용
                results[name] = ("error", error)
                locked.set()
            finally:
                close_old_connections()

        a = threading.Thread(target=run, args=("first", first, True))
        a.start()
        locked.wait(10)
        b = threading.Thread(target=run, args=("second", second, False))
        b.start()
        b.join(0.5)
        waited = b.is_alive()  # 잠금을 기다리는 중이어야 함
        release.set()
        a.join(10)
        b.join(10)
        return results, waited

    def test_same_name_create(self):
        body = {"name": "분쇄", "mode": "JUDGE"}
        results, waited = self.race(
            lambda: services.create_process(1, body), lambda: services.create_process(2, body)
        )
        self.assertTrue(waited)
        self.assertEqual(results["first"][0], "ok")
        self.assertIsInstance(results["second"][1], errors.NameTaken)
        self.assertEqual(Process.objects.filter(name="분쇄").count(), 1)

    def test_delete_vs_template_using_it(self):
        with transaction.atomic():
            pid = services.create_process(1, {"name": "분쇄", "mode": "JUDGE"})["process_id"]
        results, waited = self.race(
            lambda: services.delete_process(1, pid, 1),
            lambda: services.create_template(2, {"name": "효력환", "steps": [{"process_id": pid}]}),
        )
        self.assertTrue(waited)
        self.assertEqual(results["first"][0], "ok")
        error = results["second"][1]
        self.assertIsInstance(error, errors.TemplateInvalid)
        self.assertEqual(error.details[0]["code"], "not_found")
        self.assertFalse(ProcessTemplate.objects.exists())
