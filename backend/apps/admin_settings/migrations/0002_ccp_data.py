"""P16 ADM 묶음 ① 데이터(ERD v7.4 0002): 기본 CCP 2행 + P16 이전에 생산을 시작한 제조 배치 적용 기록.

- 기본 CCP(ADM-R04): MANUFACTURE 1P·2B·3P, PACKAGING 없음 — P16 이전 `rules.CCP_PROCESSES`와 같음.
- 적용 기록(ADM-R06, r2 A1 a): `started_at`이 있는 제조 배치(취소 포함)를 1P·2B·3P로 채움 — P16 이전
  규칙(`CCP_BY_ITEM = {}` → 모든 제조 배치 1P·2B·3P)과 같은 결과. 시작 전 배치는 기록 없음(처음 시작 때 R05).
- 시각 = 이 마이그레이션 실행 시각(D-267 B1).
- 되돌리기: 0001이 표를 지우므로 데이터 되돌리기는 하지 않음.
"""

from django.db import migrations
from django.utils import timezone


def forward(apps, schema_editor):
    CcpDefault = apps.get_model("admin_settings", "CcpDefault")
    now = timezone.now()
    for process_type, on in (("MANUFACTURE", True), ("PACKAGING", False)):
        CcpDefault.objects.get_or_create(
            process_type=process_type,
            defaults={"ccp_1p": on, "ccp_2b": on, "ccp_3p": on, "updated_at": now},
        )
    # 수불 표는 managed=False 모델이라 SQL로 한 번에(배치 수와 관계없이 1문장)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO batch_ccp_applied (batch_id, ccp_1p, ccp_2b, ccp_3p, decided_at)"
            " SELECT b.id, 1, 1, 1, %s FROM production_batches b"
            " WHERE b.process_type = 'MANUFACTURE' AND b.started_at IS NOT NULL"
            " AND NOT EXISTS (SELECT 1 FROM batch_ccp_applied a WHERE a.batch_id = b.id)",
            [schema_editor.connection.ops.adapt_datetimefield_value(now)],
        )


class Migration(migrations.Migration):
    dependencies = [("admin_settings", "0001_initial")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
