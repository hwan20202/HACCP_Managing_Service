"""동시 실행 테스트용: 파일 SQLite 테스트 DB (메모리 DB는 연결 간 잠금 동작이 다르다).

HACCP_TEST_FILE_DB=1 python manage.py test apps.documents.tests.test_concurrency \
    apps.document_workflow.tests.test_concurrency --settings=config.settings.test_filedb
"""

import tempfile
from pathlib import Path

from .test import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(Path(tempfile.gettempdir()) / "haccp_test_base.sqlite3"),
        "TEST": {"NAME": str(Path(tempfile.gettempdir()) / "haccp_test_concurrency.sqlite3")},
        "OPTIONS": {"timeout": 20},
    }
}
