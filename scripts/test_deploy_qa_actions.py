"""Runner deployment contract with fake Git/SSH commands; never connects to a server."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
git_binary = shutil.which("git")
git_bash = Path(git_binary).parents[1] / "bin/bash.exe" if git_binary else None
BASH = (
    str(git_bash) if os.name == "nt" and git_bash and git_bash.is_file() else shutil.which("bash")
)
STUB = r"""#!/usr/bin/env bash
name="${0##*/}"
printf '%s ' "$name" "$@" >> "$QA_TEST_LOG"
printf '\n' >> "$QA_TEST_LOG"
case "$name" in
  git)
    case "$1" in
      ls-remote)
        [[ "${QA_TEST_GIT_FAIL:-}" != 1 ]] || exit 2
        printf '%s\trefs/heads/main\n' "${QA_TEST_MAIN:-$DEPLOY_COMMIT}" ;;
      rev-parse) printf '%s\n' "$DEPLOY_COMMIT" ;;
      archive) for arg in "$@"; do
        if [[ "$arg" == --output=* ]]; then printf archive > "${arg#--output=}"; fi
        done ;;
      show) printf '# test deployment script\n' ;;
      *) exit 2 ;;
    esac ;;
  ssh-keygen) [[ "$1" != -F || "${QA_TEST_KEY_MISSING:-}" != 1 ]] ;;
  sha256sum) printf '%064d  source.tar.gz\n' 0 ;;
  ssh|scp) [[ "${QA_TEST_SSH_FAIL:-}" != 1 ]] ;;
  *) exit 2 ;;
esac
"""


@unittest.skipUnless(BASH, "Bash is required for the runner shell contract")
class ActionsDeployTests(unittest.TestCase):
    def execute(self, overrides=None):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            mocks = base / "commands"
            mocks.mkdir()
            for name in ("git", "ssh", "scp", "ssh-keygen", "sha256sum"):
                command = mocks / name
                command.write_text(STUB, encoding="utf-8", newline="\n")
                command.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "DEPLOY_COMMIT": "a" * 40,
                    "QA_SSH_HOST": "qa.example.test",
                    "QA_SSH_PORT": "22",
                    "QA_SSH_USER": "root",
                    "QA_SSH_KNOWN_HOSTS": "qa.example.test ssh-ed25519 TEST",
                    "QA_SSH_PRIVATE_KEY": "FAKE-PRIVATE-KEY-DO-NOT-LOG",
                    "RUNNER_TEMP": str(base),
                    "GITHUB_RUN_ID": "123",
                    "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_STEP_SUMMARY": str(base / "summary"),
                    "QA_TEST_LOG": str(base / "commands.log"),
                    "MOCK_BIN": str(mocks),
                    "DEPLOY_SCRIPT": str(ROOT / "scripts/deploy_qa_actions.sh"),
                }
            )
            env.update(overrides or {})
            result = subprocess.run(
                [
                    BASH,
                    "--noprofile",
                    "--norc",
                    "-c",
                    "if command -v cygpath >/dev/null; then "
                    'MOCK_BIN="$(cygpath -u "$MOCK_BIN")"; '
                    'RUNNER_TEMP="$(cygpath -u "$RUNNER_TEMP")"; export RUNNER_TEMP; fi; '
                    'export PATH="$MOCK_BIN:$PATH"; exec bash "$DEPLOY_SCRIPT"',
                ],
                env=env,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            log = base / "commands.log"
            commands = log.read_text() if log.exists() else ""
            self.assertEqual(list(base.glob("haccp-qa.*/id_ed25519")), [])
            self.assertNotIn(
                "FAKE-PRIVATE-KEY-DO-NOT-LOG", result.stdout + result.stderr + commands
            )
            return result, commands

    def test_checked_commit_is_sent_with_host_verification_and_code_only(self):
        result, commands = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scp ", commands)
        self.assertIn("StrictHostKeyChecking=yes", commands)
        self.assertIn("--commit '" + "a" * 40 + "'", commands)
        self.assertIn("--branch main --code-only", commands)
        self.assertNotIn("--fresh-data-once", commands)

    def test_newer_main_skips_before_ssh(self):
        result, commands = self.execute({"QA_TEST_MAIN": "b" * 40})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped", result.stdout)
        self.assertNotIn("ssh ", commands)

    def test_missing_inputs_bad_host_key_git_error_and_ssh_failure_do_not_deploy(self):
        for settings in (
            {"QA_SSH_PRIVATE_KEY": ""},
            {"QA_SSH_PORT": "22;command"},
            {"QA_TEST_KEY_MISSING": "1"},
            {"QA_TEST_GIT_FAIL": "1"},
            {"QA_TEST_SSH_FAIL": "1"},
        ):
            with self.subTest(settings=settings):
                result, commands = self.execute(settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("--branch main --code-only", commands)
