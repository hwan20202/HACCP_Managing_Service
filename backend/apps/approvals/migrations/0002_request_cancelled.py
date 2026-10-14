# ERD v7 M12: approval_request.status에 cancelled(상신 취소, P10 C5 S4)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("approvals", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="approvalrequest",
            name="ck_request_status",
        ),
        migrations.AddConstraint(
            model_name="approvalrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("status__in", ("in_progress", "approved", "rejected", "cancelled"))
                ),
                name="ck_request_status",
            ),
        ),
    ]
