"""P16 S6: 처음 설정·마지막 활성 직원의 동시 요청(파일 SQLite 전용 — R62·R65).

  HACCP_TEST_FILE_DB=1 python manage.py test apps.admin_settings.tests.test_concurrency \\
      --settings=config.settings.test_filedb

모든 atomic()이 IMMEDIATE(쓰기 잠금)로 시작하므로 두 번째 요청은 첫 번째가 커밋할 때까지 기다리고,
그 뒤의 상태로 다시 판정한다 → 첫 등록은 먼저 커밋한 쪽만(다른 쪽 400 setup_finished),
남은 두 직원을 서로 비활성하면 한쪽만(다른 쪽 400 last_active_staff).
"""

import os
import threading
import unittest

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase

from apps.admin_settings import services
from apps.admin_settings.errors import ValidationFailed
from apps.admin_settings.models import AdminChangeLog
from apps.staff.models import Staff


def _file_db():
    name = str(connection.settings_dict.get("NAME", ""))
    return "memory" not in name and name != ":memory:"


def _codes(error):
    return [d["code"] for d in error.details]


@unittest.skipUnless(
    os.environ.get("HACCP_TEST_FILE_DB") and _file_db(), "파일 SQLite 테스트 DB에서만 실행"
)
class AdminConcurrencyTests(TransactionTestCase):
    def setUp(self):
        # staff는 수불 표(managed=False)라 TransactionTestCase의 표 비우기에서 빠짐 — 직접 비움
        AdminChangeLog.objects.all().delete()
        Staff.objects.all().delete()

    tearDown = setUp

    def race(self, first, second):
        """first는 커밋 전 트랜잭션을 잡고 멈추고, second는 그동안 잠금을 기다린다."""
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

    def test_first_registration_once(self):
        """R62: 활성 0명에서 헤더 없는 첫 등록 두 건 — 먼저 커밋한 쪽만."""
        results, waited = self.race(
            lambda: services.create_staff(None, {"name": "가", "staff_code": "S-001"}),
            lambda: services.create_staff(None, {"name": "나", "staff_code": "S-002"}),
        )
        self.assertTrue(waited)
        self.assertEqual(results["first"][0], "ok")
        self.assertEqual(results["second"][0], "error")
        self.assertIsInstance(results["second"][1], ValidationFailed)
        self.assertEqual(_codes(results["second"][1]), ["setup_finished"])
        self.assertEqual(list(Staff.objects.values_list("staff_code", flat=True)), ["S-001"])
        self.assertEqual(
            list(AdminChangeLog.objects.values_list("action", flat=True)), ["bootstrap_create"]
        )

    def test_activate_vs_create(self):
        """R62: 0명에서 다시 활성과 첫 등록이 겹쳐도 한쪽만."""
        old = Staff.objects.create(staff_code="OLD-1", name="옛 직원", is_active=False)
        results, waited = self.race(
            lambda: services.set_staff_active(None, old.pk, {"active": True}),
            lambda: services.create_staff(None, {"name": "새", "staff_code": "S-001"}),
        )
        self.assertTrue(waited)
        self.assertEqual(results["first"][0], "ok")
        self.assertEqual(_codes(results["second"][1]), ["setup_finished"])
        self.assertEqual(Staff.objects.filter(is_active=True).count(), 1)

    def test_last_two_deactivate_each_other(self):
        """R65: 남은 활성 두 명이 서로를 비활성 — 한쪽만, 활성 1명은 남음."""
        a = Staff.objects.create(staff_code="S-001", name="가")
        b = Staff.objects.create(staff_code="S-002", name="나")
        off = {"active": False, "confirm_impact": True}
        results, waited = self.race(
            lambda: services.set_staff_active(a.pk, b.pk, off),
            lambda: services.set_staff_active(b.pk, a.pk, off),
        )
        self.assertTrue(waited)
        self.assertEqual(results["first"][0], "ok")
        self.assertEqual(_codes(results["second"][1]), ["last_active_staff"])
        self.assertEqual(Staff.objects.filter(is_active=True).count(), 1)
