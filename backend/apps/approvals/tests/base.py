"""APR 테스트 준비물. apps.documents를 import하지 않고 SQL로 최소 행만 만든다(도메인 경계 유지)."""

import json

from django.db import connection
from django.utils import timezone

from apps.staff.models import Staff


def ensure_staff(n=5):
    for i in range(1, n + 1):
        Staff.objects.get_or_create(staff_id=i)


def make_template(type_code="CCP_MONITORING", version=1):
    now = timezone.now().isoformat()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO document_template (type_code, version, name, schema_json,"
            " is_active, created_at) VALUES (%s, %s, %s, %s, 1, %s)",
            [type_code, version, f"{type_code} v{version}", json.dumps({"sections": []}), now],
        )
        return cursor.lastrowid


def make_document(template_id, status="submitted", work_date="2026-10-10", subject="CCP-2B/라인A"):
    now = timezone.now().isoformat()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO document (template_id, subject, work_date, created_by, status, created_at,"
            " updated_at, version) VALUES (%s, %s, %s, 3, %s, %s, %s, 2)",
            [template_id, subject, work_date, status, now, now],
        )
        return cursor.lastrowid


def ref(document_id, template_id, work_date="2026-10-10", subject="CCP-2B/라인A", version=2):
    return {
        "document_id": document_id,
        "version": version,
        "template_id": template_id,
        "subject": subject,
        "work_date": work_date,
    }


def snapshot_for(document_id):
    return {
        "document_id": document_id,
        "version": 2,
        "sections": [{"row_no": 1, "values": {"t": 87}}],
    }


SLOTS = [
    {"slot_no": 1, "label": "담당", "approver_id": 3},
    {"slot_no": 2, "label": "검토", "approver_id": 2},
    {"slot_no": 3, "approver_id": 1},
]
