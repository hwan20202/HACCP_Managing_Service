from django.db import models


class Staff(models.Model):
    """사람 식별자. 이름 등 속성은 두지 않는다(D-003). 문서·결재 도메인이 함께 참조한다."""

    staff_id = models.AutoField(primary_key=True)

    class Meta:
        db_table = "staff"
        ordering = ["staff_id"]

    def __str__(self):
        return f"staff {self.staff_id}"
