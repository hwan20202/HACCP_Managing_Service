"""PLG-TC-27 / PLG-NFR-01: 계층 경계.

- PLG는 수불(apps.inventory)·REQ 뷰 읽기(apps.doc_requirements.sources)를 import하지 않는다.
- DOC·REQ는 PLG(apps.production_log)를 import하지 않는다.
"""

import ast
from pathlib import Path

from django.test import SimpleTestCase

APPS = Path(__file__).resolve().parents[2]


def imports(package):
    found = []
    for path in (APPS / package).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found += [(path, alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found += [(path, node.module)]
    return found


class BoundaryTests(SimpleTestCase):
    def test_tc27_plg_does_not_read_inventory(self):
        bad = [
            f"{p.name}: {m}"
            for p, m in imports("production_log")
            if m.startswith(("apps.inventory", "apps.doc_requirements"))
        ]
        self.assertEqual(bad, [])

    def test_tc27_doc_req_do_not_import_plg(self):
        bad = [
            f"{p.relative_to(APPS)}: {m}"
            for package in ("documents", "doc_requirements")
            for p, m in imports(package)
            if m.startswith("apps.production_log")
        ]
        self.assertEqual(bad, [])
