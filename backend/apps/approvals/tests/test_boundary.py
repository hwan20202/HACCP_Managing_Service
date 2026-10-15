"""APR-TC-050 / APR-NFR-05: 결재 도메인은 문서·워크플로우를 import하지 않는다."""

import ast
from pathlib import Path

from django.test import SimpleTestCase

FORBIDDEN = ("apps.documents", "apps.document_workflow")
PACKAGE = Path(__file__).resolve().parents[1]


class DomainBoundaryTests(SimpleTestCase):
    def test_tc050_no_forbidden_imports(self):
        offenders = []
        for path in PACKAGE.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                offenders += [
                    f"{path.relative_to(PACKAGE)}: {n}" for n in names if n.startswith(FORBIDDEN)
                ]
        self.assertEqual(offenders, [])
