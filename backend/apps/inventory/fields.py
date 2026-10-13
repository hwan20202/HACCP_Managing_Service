"""Field types matching the SQLite storage rules of the production core schema (S3, S4)."""

import datetime
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Func

KST = ZoneInfo("Asia/Seoul")
KST_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def kst_now():
    """Current time in KST, truncated to seconds."""
    return datetime.datetime.now(KST).replace(microsecond=0)


def to_kst_text(value):
    """Format a datetime as the stored KST text 'YYYY-MM-DD HH:MM:SS'.

    Aware values are converted to KST. Naive values are taken as KST already.
    Microseconds are dropped because the schema CHECK requires second precision.
    """
    if value.tzinfo is not None:
        value = value.astimezone(KST)
    return value.strftime(KST_DATETIME_FORMAT)


def parse_kst_text(value):
    """Parse stored KST text into an aware datetime in KST."""
    try:
        parsed = datetime.datetime.strptime(value, KST_DATETIME_FORMAT)
    except ValueError as error:
        raise ValidationError(f"'{value}' is not 'YYYY-MM-DD HH:MM:SS'.") from error
    return parsed.replace(tzinfo=KST)


class LocalNow(Func):
    """SQL datetime('now', 'localtime'): the DB default used by the core schema.

    Used as db_default so Django leaves these columns to the database instead of
    inserting NULL into a NOT NULL column.
    """

    template = "datetime('now', 'localtime')"
    output_field = models.TextField()
    allowed_default = True


class KSTDateTimeField(models.Field):
    """Datetime stored as KST text without a zone suffix (rule S4).

    Django's DateTimeField stores UTC when USE_TZ=True and may write microseconds,
    which would break the schema CHECK (x IS datetime(x)). This field always writes
    'YYYY-MM-DD HH:MM:SS' in KST and reads it back as an aware KST datetime.
    """

    description = "Datetime stored as KST text 'YYYY-MM-DD HH:MM:SS'"

    def get_internal_type(self):
        return "TextField"

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        return parse_kst_text(value)

    def to_python(self, value):
        if value is None or isinstance(value, datetime.datetime):
            return value
        return parse_kst_text(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return None
        if isinstance(value, datetime.datetime):
            return to_kst_text(value)
        if isinstance(value, str):
            return to_kst_text(parse_kst_text(value))
        raise ValidationError(f"Unsupported datetime value: {value!r}")
