# ERD v7.2 (P14 역할 기반 결재, D-189): A20 approval.role · M16 approver_id NULL 허용 · M17 uq_approval_approver 없앰 · A21 approval_candidate
# SQLite는 approval 표를 다시 만든다(데이터 유지, D-185) — 운영 적용 전 백업

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0002_request_cancelled'),
        ('inventory', '0007_expiration_status'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='approval',
            name='uq_approval_approver',
        ),
        migrations.AddField(
            model_name='approval',
            name='role',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='approval',
            name='approver',
            field=models.ForeignKey(blank=True, db_column='approver_id', db_index=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='inventory.staff'),
        ),
        migrations.AddConstraint(
            model_name='approval',
            constraint=models.CheckConstraint(condition=models.Q(('role__isnull', True), ('role__in', ('owner', 'leader')), _connector='OR'), name='ck_approval_role'),
        ),
        migrations.AddConstraint(
            model_name='approval',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('approver__isnull', False), ('role__isnull', True)), models.Q(('approver__isnull', False), ('role__isnull', False), ('state__in', ('approved', 'rejected'))), models.Q(('approver__isnull', True), ('role__isnull', False), models.Q(('state__in', ('approved', 'rejected')), _negated=True)), _connector='OR'), name='ck_approval_approver'),
        ),
        migrations.CreateModel(
            name='ApprovalCandidate',
            fields=[
                ('pk', models.CompositePrimaryKey('approval', 'staff', blank=True, editable=False, primary_key=True, serialize=False)),
                ('approval', models.ForeignKey(db_column='approval_id', db_index=False, on_delete=django.db.models.deletion.CASCADE, related_name='candidates', to='approvals.approval')),
                ('staff', models.ForeignKey(db_column='staff_id', db_index=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='inventory.staff')),
            ],
            options={
                'db_table': 'approval_candidate',
                'indexes': [models.Index(fields=['staff'], name='ix_approval_candidate_staff')],
            },
        ),
    ]
