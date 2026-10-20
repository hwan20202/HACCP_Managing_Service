"""Local tests of config preservation and rollback; no server calls."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import redeploy_cafe24_qa as deploy


class RedeployTests(unittest.TestCase):
    def test_code_only_rejects_migration_sql_dependencies_and_python_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            current, stage = Path(directory) / "old", Path(directory) / "new"
            files = {
                "backend/apps/inventory/migrations/0001_initial.py": "migration",
                "backend/apps/inventory/sql/0001.sql": "CREATE TABLE test (id INTEGER)",
                "requirements/base.txt": "Django==5.2.18",
                "requirements/production.txt": "-r base.txt",
                ".python-version": "3.14",
            }
            for root in (current, stage):
                for name, content in files.items():
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content)
            deploy.require_code_only_compatibility(current, stage)
            for name, content in files.items():
                with self.subTest(name=name):
                    target = stage / name
                    target.write_text(content + "\nchanged")
                    with self.assertRaises(SystemExit):
                        deploy.require_code_only_compatibility(current, stage)
                    target.write_text(content)
            added = stage / "backend/apps/inventory/migrations/0002_new.py"
            added.write_text("new migration")
            with self.assertRaises(SystemExit):
                deploy.require_code_only_compatibility(current, stage)

    def test_pending_or_missing_migrations_are_checked_without_applying_them(self):
        with patch.object(deploy, "app") as app:
            deploy.check_schema_without_writes(Path("/code"), Path("/env"))
        commands = [call.args[2:] for call in app.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertIn("makemigrations", commands[0])
        self.assertIn("--dry-run", commands[0])
        self.assertIn("migrate", commands[1])
        self.assertTrue(all("--check" in command for command in commands))
        with patch.object(deploy, "app", side_effect=RuntimeError("pending migration")):
            with self.assertRaisesRegex(RuntimeError, "pending"):
                deploy.check_schema_without_writes(Path("/code"), Path("/env"))

    def test_site_comes_from_server_configuration(self):
        self.assertEqual(
            deploy.configured_site({"HACCP_SITE_ADDRESS": "qa.example.test"}), "qa.example.test"
        )
        self.assertEqual(
            deploy.configured_site({"HACCP_SITE_ADDRESS": "https://qa.example.test/"}),
            "qa.example.test",
        )
        for value in ("", "http://qa.example.test", "https://user:password@qa.example.test"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                deploy.configured_site({"HACCP_SITE_ADDRESS": value})

    def test_regressions_use_memory_settings_and_a_separate_data_directory(self):
        seen = []

        def inspect(code, env_file, *args):
            self.assertEqual(code, Path("/staged-code"))
            self.assertIn("--settings=config.settings.test", args)
            self.assertIn("apps.inventory.test_overview", args)
            contents = env_file.read_text()
            self.assertIn(str(env_file.parent / "data"), contents)
            self.assertNotIn("qa.env", contents)
            self.assertNotIn("qa-data", contents)
            seen.append(env_file)

        with (
            patch.object(deploy, "app", side_effect=inspect),
            patch.object(deploy.os, "chown", create=True),
        ):
            deploy.isolated_regressions(Path("/staged-code"), 0, 0)
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0].exists())

    def test_business_fingerprint_detects_values_not_only_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "db").mkdir()
            with sqlite3.connect(data / "db/app.sqlite3") as db:
                db.execute("CREATE TABLE inventory (id INTEGER, quantity INTEGER)")
                db.execute("INSERT INTO inventory VALUES (1, 10)")
            db.close()
            before = deploy.business_fingerprint(data)
            self.assertEqual(before, deploy.business_fingerprint(data))
            with sqlite3.connect(data / "db/app.sqlite3") as db:
                db.execute("UPDATE inventory SET quantity=9")
            db.close()
            self.assertNotEqual(before, deploy.business_fingerprint(data))

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
            old_static, new_static = base / "static-old", base / "static-new"
            for folder, content in ((old_static, "old css"), (new_static, "new css")):
                folder.mkdir()
                (folder / "app.css").write_text(content)
            app_env, proxy_env = base / "qa.env", base / "caddy.env"
            record = {"backup": str(backup), "old_code": str(old)}
            for name in ("qa.env", "caddy.env"):
                (backup / name).write_text(f"HACCP_STATIC_DIR={old_static}\n")
                (base / name).write_text(f"HACCP_STATIC_DIR={new_static}\n")
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
            self.assertEqual(app_env.read_text(), f"HACCP_STATIC_DIR={old_static}\n")
            self.assertEqual(proxy_env.read_text(), f"HACCP_STATIC_DIR={old_static}\n")
            self.assertEqual((old_static / "app.css").read_text(), "old css")
            self.assertEqual((new_static / "app.css").read_text(), "new css")
