"""CCP 시작·종료 기본행과 CCP-2B 온도 단독 판정.

새 문서는 새 양식을 사용한다. 기존 작성중 문서는 기본행을 보충하고 새 양식으로
옮긴다. 결재 이력이 있는 완료 문서와 그 스냅샷은 그대로 보존한다.
"""

from django.db import migrations
from django.db.models import Max
from django.utils import timezone

FORMS = (
    ("CCP-1P", 1, 2, "rounds", "작업시작 전", "작업 중", "작업종료 후"),
    ("CCP-2B", 1, 2, "rounds", "건조시작 전", "작업 중", "건조종료 전"),
    ("CCP-3P", 2, 3, "checks", "시작", "중간", "종료"),
)


def forward(apps, schema_editor):
    from apps.documents.seed_forms import CCP_1P_FIXED, CCP_2B_FIXED, CCP_3P_FIXED
    from apps.documents.validation import with_computed

    Template = apps.get_model("documents", "DocumentTemplate")
    Document = apps.get_model("documents", "Document")
    Section = apps.get_model("documents", "DocSection")
    schemas = (CCP_1P_FIXED, CCP_2B_FIXED, CCP_3P_FIXED)

    for (code, old_version, new_version, key, first, middle, last), schema in zip(
        FORMS, schemas, strict=True
    ):
        old = Template.objects.filter(type_code=code, version=old_version).first()
        if old is None:
            continue
        new, _ = Template.objects.get_or_create(
            type_code=code,
            version=new_version,
            defaults={
                "name": old.name,
                "schema_json": schema,
                "is_active": True,
                "created_at": timezone.now(),
            },
        )
        Template.objects.filter(pk=new.pk).update(is_active=True)
        Template.objects.filter(type_code=code).exclude(pk=new.pk).update(is_active=False)
        measured = next(s for s in new.schema_json["sections"] if s["key"] == key)

        for document in Document.objects.filter(
            template_id=old.pk, status="draft", deleted_at__isnull=True
        ):
            rows = list(
                Section.objects.filter(document_id=document.pk, section_def=key).order_by("row_no")
            )
            anchors = {first: [], last: []}
            for row in rows:
                phase = (row.values_json or {}).get("phase")
                if phase in anchors:
                    anchors[phase].append(row)
                if code == "CCP-2B":
                    computed = with_computed(measured, row.values_json or {})
                    if computed != row.values_json:
                        row.values_json = computed
                        row.save(update_fields=["values_json"])

            # 예전 작성중 문서에 시작·종료가 여럿 있으면 첫 기록을 기본행으로
            # 유지하고 나머지는 중간 재측정으로 보존한다.
            for phase in (first, last):
                for row in anchors[phase][1:]:
                    row.values_json = {**(row.values_json or {}), "phase": middle}
                    row.save(update_fields=["values_json"])

            next_no = (
                Section.objects.filter(document_id=document.pk, section_def=key).aggregate(
                    n=Max("row_no")
                )["n"]
                or 0
            )
            for phase in (first, last):
                if not anchors[phase]:
                    next_no += 1
                    Section.objects.create(
                        document_id=document.pk,
                        section_def=key,
                        row_no=next_no,
                        values_json={"phase": phase},
                        recorded_at=None,
                        recorded_by_id=None,
                    )
            Document.objects.filter(pk=document.pk).update(
                template_id=new.pk, version=document.version + 1
            )


class Migration(migrations.Migration):
    dependencies = [("documents", "0004_ccp3p_v2")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
