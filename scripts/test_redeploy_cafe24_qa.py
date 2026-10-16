"""Local tests of config preservation and rollback; no server calls."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import redeploy_cafe24_qa as deploy


class RedeployTests(unittest.TestCase):
    def test_env_update_preserves_auth_and_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "qa.env"
            original = (
                "HACCP_QA_AUTH_HASH='$2a$test-only'\n"
                "DJANGO_HTTPS_ENABLED=true\n"
                "HACCP_STATIC_DIR=/old/static\n"
            )
            env.write_text(original)
            with patch.object(deploy.os, "chown", create=True):
                deploy.update_env(env, {"HACCP_STATIC_DIR": "/new/static"})
            self.assertEqual(env.read_text(), original.replace("/old/static", "/new/static"))

    def test_rollback_preserves_new_code_and_restores_old_env(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            current, old, backup = base / "current", base / "old", base / "backup"
            for path in (current, old, backup):
                path.mkdir()
            (current / "new.txt").write_text("new")
            (old / "old.txt").write_text("old")
            app_env, proxy_env = base / "qa.env", base / "caddy.env"
            record = {"backup": str(backup), "old_code": str(old)}
            for name in ("qa.env", "caddy.env"):
                (backup / name).write_text("original")
                (base / name).write_text("changed")
                record[name + "_owner"] = [0, 0]
                record[name + "_mode"] = 0o600
            with (
                patch.object(deploy, "BASE", base),
                patch.object(deploy, "CURRENT", current),
                patch.object(deploy, "APP_ENV", app_env),
                patch.object(deploy, "CADDY_ENV", proxy_env),
                patch.object(deploy, "run"),
                patch.object(deploy.os, "chown", create=True),
            ):
                deploy.restore(json.loads(json.dumps(record)))
            self.assertTrue((current / "old.txt").exists())
            retained = list(base.glob("retained-new-code-*/new.txt"))
            self.assertEqual(len(retained), 1)
            self.assertEqual(app_env.read_text(), "original")
            self.assertEqual(proxy_env.read_text(), "original")
