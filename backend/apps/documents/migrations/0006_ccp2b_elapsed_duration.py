"""CCP-2B 건조시간을 종료 전 측정일시 차이로 계산한다."""

from django.db import migrations
from django.utils import timezone


def forward(apps, schema_editor):
    from apps.documents.seed_forms import CCP_2B_ELAPSED
    from apps.documents.validation import elapsed_values

    Template = apps.get_model("documents", "DocumentTemplate")
    Document = apps.get_model("documents", "Document")
    Section = apps.get_model("documents", "DocSection")
    old = Template.objects.filter(type_code="CCP-2B", version=2).first()
    if old is None:
        return
    new, _ = Template.objects.get_or_create(
        type_code="CCP-2B",
        version=3,
        defaults={
            "name": old.name,
            "schema_json": CCP_2B_ELAPSED,
            "is_active": True,
            "created_at": timezone.now(),
        },
    )
    Template.objects.filter(pk=new.pk).update(is_active=True)
    Template.objects.filter(type_code="CCP-2B").exclude(pk=new.pk).update(is_active=False)
    section = next(s for s in new.schema_json["sections"] if s["key"] == "rounds")

    for document in Document.objects.filter(
        template_id=old.pk, status="draft", deleted_at__isnull=True
    ):
        rows = list(Section.objects.filter(document_id=document.pk, section_def="rounds"))
        cleaned = []
        for row in rows:
            values = dict(row.values_json or {})
            values.pop("dry_minutes", None)
            values.pop("time_verdict", None)
            cleaned.append((row, values))
        calculated, _ = elapsed_values(section, [values for _, values in cleaned])
        for row, values in cleaned:
            if values.get("phase") == "건조종료 전":
                values.update(
                    {key: value for key, value in calculated.items() if value is not None}
                )
            if values != row.values_json:
                row.values_json = values
                row.save(update_fields=["values_json"])
        Document.objects.filter(pk=document.pk).update(
            template_id=new.pk, version=document.version + 1
        )


class Migration(migrations.Migration):
    dependencies = [("documents", "0005_ccp_fixed_phase_rows")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
