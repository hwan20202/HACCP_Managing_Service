"""WF-TC-050·051 / WF-NFR-01: 경계와 스키마."""

import ast
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

APPS = Path(__file__).resolve().parents[2]
WF = APPS / "document_workflow"


def imports(package, *, skip_tests=False):
    for path in package.rglob("*.py"):
        if skip_tests and "tests" in path.relative_to(package).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield path, alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                yield path, node.module
                for alias in node.names:
                    yield path, f"{node.module}.{alias.name}"


class BoundaryTests(SimpleTestCase):
    def test_tc050_wf_uses_public_functions_only(self):
        offenders = [
            f"{p.relative_to(APPS)}: {name}"
            for p, name in imports(WF, skip_tests=True)
            if name.startswith(("apps.documents.models", "apps.approvals.models"))
            or name.endswith(".models")
        ]
        self.assertEqual(offenders, [])

    def test_tc050_domains_do_not_import_wf(self):
        offenders = [
            f"{p.relative_to(APPS)}: {name}"
            for package in (APPS / "documents", APPS / "approvals")
            for p, name in imports(package)
            if name.startswith("apps.document_workflow")
        ]
        self.assertEqual(offenders, [])


class NoSchemaTests(TestCase):
    def test_tc051_no_models_or_migrations(self):
        from django.apps import apps

        self.assertEqual(list(apps.get_app_config("document_workflow").get_models()), [])
        self.assertFalse((WF / "migrations").exists())
        self.assertFalse((WF / "models.py").exists())
        call_command(
            "makemigrations", "--check", "--dry-run", stdout=StringIO()
        )  # 변경 있으면 SystemExit
