"""기본 제공 공정 5종(D3, S2 Q6 a). 운영에도 들어간다. 일반 공정·템플릿은 개발 시드 명령."""

from django.db import migrations
from django.utils import timezone

BUILTINS = (
    ("CCP-1P", "쇳가루 제거"),
    ("CCP-2B", "건조"),
    ("CCP-3P", "금속검출기"),  # S4a 리뷰 A3: 화면 S1·PoC와 같게
    ("INNER", "내포장"),
    ("OUTER", "외포장"),
)


def forward(apps, schema_editor):
    Process = apps.get_model("production_log", "Process")
    now = timezone.now()
    for kind, name in BUILTINS:
        Process.objects.get_or_create(
            kind=kind,
            defaults={
                "name": name,
                "name_key": name.lower(),
                "is_builtin": True,
                "created_at": now,
                "updated_at": now,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("production_log", "0001_initial")]
    # S4a 리뷰 A6 a: 되돌려도 기본 제공(기준 데이터)은 지우지 않음 — 쓰인 공정이 있으면 삭제가 PROTECT로
    # 멈추기 때문. 앱 전체 되돌리기(zero)는 0001이 표를 지움. 운영 되돌리기는 백업 복구.
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
