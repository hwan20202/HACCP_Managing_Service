"""CCP-1P 8,000G 한계기준을 새 양식에 적용하고 작성중 판정을 다시 계산한다."""

from django.db import migrations
from django.utils import timezone


def forward(apps, schema_editor):
    from apps.documents.seed_forms import CCP_1P_8000
    from apps.documents.validation import with_computed

    Template = apps.get_model("documents", "DocumentTemplate")
    Document = apps.get_model("documents", "Document")
    Section = apps.get_model("documents", "DocSection")
    old = Template.objects.filter(type_code="CCP-1P", version=2).first()
    if old is None:
        return
    new, _ = Template.objects.get_or_create(
        type_code="CCP-1P",
        version=3,
        defaults={
            "name": old.name,
            "schema_json": CCP_1P_8000,
            "is_active": True,
            "created_at": timezone.now(),
        },
    )
    Template.objects.filter(pk=new.pk).update(is_active=True)
    Template.objects.filter(type_code="CCP-1P").exclude(pk=new.pk).update(is_active=False)
    measured = next(s for s in new.schema_json["sections"] if s["key"] == "rounds")

    for document in Document.objects.filter(
        template_id=old.pk, status="draft", deleted_at__isnull=True
    ):
        for row in Section.objects.filter(document_id=document.pk, section_def="rounds"):
            values = with_computed(measured, row.values_json or {})
            if values != row.values_json:
                row.values_json = values
                row.save(update_fields=["values_json"])
        Document.objects.filter(pk=document.pk).update(
            template_id=new.pk, version=document.version + 1
        )


class Migration(migrations.Migration):
    dependencies = [("documents", "0006_ccp2b_elapsed_duration")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
