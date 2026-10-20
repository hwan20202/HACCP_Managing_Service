"""QA static releases must never collect into code, DB or upload directories."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class QaStaticSettingsTests(unittest.TestCase):
    def settings(self, base, static=None):
        env = os.environ.copy()
        env.update(
            {
                "HACCP_ENV_FILE": os.devnull,
                "DJANGO_SECRET_KEY": "test-only-secret-more-than-fifty-characters-1234567890",
                "DJANGO_ALLOWED_HOSTS": "qa.example.test",
                "DJANGO_HTTPS_ENABLED": "true",
                "HACCP_DATA_DIR": str(base / "production-data"),
                "HACCP_QA_DATA_DIR": str(base / "qa-data"),
            }
        )
        env.pop("HACCP_STATIC_DIR", None)
        if static is not None:
            env["HACCP_STATIC_DIR"] = str(static)
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "from config.settings.qa import STATIC_ROOT; print(STATIC_ROOT)",
            ],
            cwd=ROOT / "backend",
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_existing_static_default_and_separate_release_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for static in (None, base / "qa-data/static", base / "static-release"):
                with self.subTest(static=static):
                    result = self.settings(base, static)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    expected = static or base / "qa-data/static"
                    self.assertEqual(result.stdout.strip(), str(expected.resolve()))

    def test_static_collection_cannot_target_data_uploads_code_or_their_ancestors(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for static in (base, base / "qa-data", base / "qa-data/uploads", ROOT, ROOT / "static"):
                with self.subTest(static=static):
                    result = self.settings(base, static)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("static directory must be separate", result.stderr)
