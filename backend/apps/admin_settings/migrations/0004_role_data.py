"""P16 ADM 묶음 ② 데이터 — 문서 권한 버전 1행 + 마이그레이션 시점 활성 양식 코드마다 기본 구성(R31).

사람은 넣지 않는다(R40 — 새 설치는 처음 설정에서, 기존 서버는 `import_roles`로).
기본 구성 값은 `store.default_form` 하나를 `ensure_form_rows`와 같이 쓴다(ERD v7.4 S3b).
시각 = 실행 시각(D-267 B1).
"""

from django.db import migrations
from django.utils import timezone


def forward(apps, schema_editor):
    from apps.admin_settings.store import default_form

    Template = apps.get_model("documents", "DocumentTemplate")
    now = timezone.now()
    connection = schema_editor.connection
    stamp = connection.ops.adapt_datetimefield_value(now)
    codes = sorted(set(Template.objects.filter(is_active=True).values_list("type_code", flat=True)))
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO role_config (id, version, updated_at) VALUES (1, 1, %s)"
            " ON CONFLICT(id) DO NOTHING",
            [stamp],
        )
        for code in codes:
            slots, label_owner, label_leader = default_form(code)
            cursor.execute(
                "INSERT INTO role_form (type_code, slots, label_owner, label_leader, created_at)"
                " VALUES (%s, %s, %s, %s, %s) ON CONFLICT(type_code) DO NOTHING",
                [code, slots, label_owner, label_leader, stamp],
            )


class Migration(migrations.Migration):
    dependencies = [("admin_settings", "0003_roles")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
