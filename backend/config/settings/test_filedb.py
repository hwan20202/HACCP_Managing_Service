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
        # 운영(base.py)·메모리 테스트(test.py)와 같은 방식: 모든 atomic()이 쓰기 잠금으로 시작
        # (수불 규칙 S5, C2 — ISS-030 a, D-129)
        "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
    }
}
