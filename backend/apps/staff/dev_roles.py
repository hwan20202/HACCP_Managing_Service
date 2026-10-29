"""개발·테스트용 기본 문서 권한 — 가상 직원(DEV-001…)과 `roles.json`(P16 묶음 ②).

P14까지는 `roles.json`을 실행 중에 읽었다. P16부터 역할 원본은 DB(ADM 문서 권한)라, 개발 시드·
테스트가 가상 직원을 만들 때(`services.ensure_dev_staff`) 이 파일의 역할을 DB에 넣는다.
운영 서버는 이 경로를 쓰지 않는다(새 설치는 처음 설정, 기존 서버는 `import_roles` — ADM-R40·R41).

- 문서 권한에 사람이 0명이면: 있는 가상 직원 모두의 역할 + 파일의 양식 slots·labels.
- 아니면: 이번에 새로 만든 가상 직원의 역할만 더한다(테스트가 바꾼 설정은 그대로).
"""

import json
from pathlib import Path

from django.db import connection

from apps.admin_settings import store as adm_store
from apps.admin_settings.models import RoleForm

from .models import Staff

DEV_FILE = Path(__file__).resolve().parent / "roles.json"


def dev_data():
    return json.loads(DEV_FILE.read_text(encoding="utf-8"))


def ensure_dev_roles(new_ids=()):
    data = dev_data()
    rows = adm_store.role_rows()
    empty = not rows["leaders"] and not any(
        f["owners"] or f["writers"] for f in rows["forms"].values()
    )
    codes = set(data["haccp_leaders"])
    for form in data["forms"].values():
        codes.update(form["owners"])
        codes.update(form.get("writers", []))
    ids = dict(Staff.objects.filter(staff_code__in=codes).values_list("staff_code", "id"))
    target = set(ids.values()) if empty else {i for i in new_ids if i in ids.values()}
    if not target:
        return
    adm_store.ensure_role_version()
    put_file_roles(data, ids, target, shape=empty)


def put_file_roles(data, ids, target, shape):
    """파일 역할 중 target 직원만 넣는다(이미 있으면 그대로).

    shape면 양식 slots·labels도 파일대로.
    """
    adm_store.ensure_form_rows(data["forms"])
    forms = dict(
        RoleForm.objects.filter(type_code__in=data["forms"]).values_list("type_code", "id")
    )
    with connection.cursor() as cursor:
        for code in data["haccp_leaders"]:
            if ids.get(code) in target:
                cursor.execute(
                    "INSERT INTO role_leader (staff_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    [ids[code]],
                )
        for type_code, form in data["forms"].items():
            if shape:
                labels = form.get("labels", {})
                cursor.execute(
                    "UPDATE role_form SET slots = %s, label_owner = %s, label_leader = %s"
                    " WHERE id = %s",
                    [
                        form["slots"],
                        (labels.get("owner") or "").strip() or None,
                        (labels.get("leader") or "").strip() or None,
                        forms[type_code],
                    ],
                )
            for role, key in (("owner", "owners"), ("writer", "writers")):
                for code in form.get(key, []):
                    if ids.get(code) in target:
                        cursor.execute(
                            "INSERT INTO role_form_member (role_form_id, role, staff_id)"
                            " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                            [forms[type_code], role, ids[code]],
                        )
