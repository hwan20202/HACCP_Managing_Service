"""P12 DP-03: CCP-3P를 v2(캔디류 양식)로 바꾼다 — 문서·행·결재 스냅샷 모두.

v1 양식이 없는 DB(새 DB)에서는 아무것도 하지 않는다(양식은 시드 `ensure_p4_templates`가 v2로 만듦).
되돌리기 없음(기록 값을 바꾸는 한 방향 작업 — DP-03).
"""

from django.db import migrations
from django.db.models import Max
from django.utils import timezone

TYPE_CODE = "CCP-3P"


def forward(apps, schema_editor):
    from apps.documents import ccp3p_v2
    from apps.documents.seed_forms import CCP_3P_V2

    Template = apps.get_model("documents", "DocumentTemplate")
    Document = apps.get_model("documents", "Document")
    Section = apps.get_model("documents", "DocSection")
    Request = apps.get_model("approvals", "ApprovalRequest")

    v1 = Template.objects.filter(type_code=TYPE_CODE, version=1).first()
    if v1 is None:
        return
    v2, _ = Template.objects.get_or_create(
        type_code=TYPE_CODE,
        version=2,
        defaults={
            "name": v1.name,
            "schema_json": CCP_3P_V2,
            "is_active": True,
            "created_at": timezone.now(),
        },
    )
    Template.objects.filter(pk=v1.pk).update(is_active=False)
    section = ccp3p_v2.checks_section_of(v2.schema_json)
    summary = {
        "template_id": v2.template_id,
        "type_code": v2.type_code,
        "version": v2.version,
        "name": v2.name,
    }

    for document in Document.objects.filter(template_id=v1.template_id):
        rows = list(Section.objects.filter(document_id=document.pk).order_by("row_no"))
        checks = [r for r in rows if r.section_def == "checks"]
        summaries = [r for r in rows if r.section_def == "summary"]
        info = next((r for r in rows if r.section_def == "info"), None)
        new_checks, new_summaries, added = ccp3p_v2.convert(
            [r.values_json for r in checks],
            [r.values_json for r in summaries],
            (info.values_json or {}).get("item_name") if info else None,
            section,
        )
        for row, values in zip(checks, new_checks, strict=True):
            row.values_json = values
            row.save(update_fields=["values_json"])
        for row, values in zip(summaries, new_summaries, strict=False):
            row.values_json = values
            row.save(update_fields=["values_json"])
        if added:
            last = Section.objects.filter(document_id=document.pk, section_def="summary").aggregate(
                n=Max("row_no")
            )["n"]
            Section.objects.create(
                document_id=document.pk,
                section_def="summary",
                row_no=(last or 0) + 1,
                values_json=new_summaries[-1],
            )
        # 열어 둔 수정 화면이 옛 값(v1 키)으로 덮어쓰지 않게 버전을 올린다(VERSION_CONFLICT)
        Document.objects.filter(pk=document.pk).update(
            template_id=v2.template_id, version=document.version + 1
        )

    for request in Request.objects.filter(template_id=v1.template_id):
        request.snapshot_json = ccp3p_v2.convert_snapshot(request.snapshot_json, summary, section)
        request.template_id = v2.template_id
        request.save(update_fields=["snapshot_json", "template_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0003_p8_document_skipped"),
        ("approvals", "0003_p14_role_slots"),
    ]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
