"""DOC-TC-090 / DOC-NFR-08: 문서 도메인은 결재·워크플로우를 import하지 않는다."""

import ast
from pathlib import Path

from django.test import SimpleTestCase

FORBIDDEN = ("apps.approvals", "apps.document_workflow")
PACKAGE = Path(__file__).resolve().parents[1]


class DomainBoundaryTests(SimpleTestCase):
    def test_tc090_no_forbidden_imports(self):
        offenders = []
        for path in PACKAGE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.startswith(FORBIDDEN):
                        offenders.append(f"{path.relative_to(PACKAGE)}: {name}")
        self.assertEqual(offenders, [])
