"""QA redeploy. Run with the existing server Python as root; never installs services.

No secrets are printed. The one-time refresh marker survives failures deliberately.
All old code/data/configuration are retained. Rollback never deletes new QA activity.
"""

import argparse
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

BASE = Path("/opt/biodot-qa")
CURRENT = BASE / "current"
APP_ENV = Path("/etc/biodot/qa.env")
CADDY_ENV = Path("/etc/biodot/caddy.env")
PYTHON = Path("/opt/biodot-qa/bin/python3.14")
MARKER = BASE / "qa-refresh-20261016.json"


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def private_copy(source, target):
    shutil.copy2(source, target)
    target.chmod(0o600)


def schema_files(code):
    """Include SQL used by RunPython as well as Django migration modules."""
    return {
        path.relative_to(code).as_posix(): path.read_bytes()
        for path in (code / "backend").rglob("*")
        if path.is_file()
        and (path.suffix == ".sql" or ("migrations" in path.parts and path.suffix == ".py"))
    }


def require_code_only_compatibility(current, stage):
    if schema_files(current) != schema_files(stage):
        raise SystemExit("Migration/SQL changes require a separate manual database deployment")
    for name in ("requirements",):
        before = {p.name: p.read_bytes() for p in (current / name).glob("*.txt")}
        after = {p.name: p.read_bytes() for p in (stage / name).glob("*.txt")}
        if not before or before != after:
            raise SystemExit("Dependency changes require a separately prepared virtualenv")
    if (current / ".python-version").read_bytes() != (stage / ".python-version").read_bytes():
        raise SystemExit("Python version changes require manual preparation")


def check_schema_without_writes(code, env_file):
    app(
        code,
        env_file,
        "backend/manage.py",
        "makemigrations",
        "--check",
        "--dry-run",
        "--noinput",
        "--settings=config.settings.qa",
    )
    app(code, env_file, "backend/manage.py", "migrate", "--check", "--settings=config.settings.qa")


def configured_site(proxy):
    value = proxy.get("HACCP_SITE_ADDRESS", "")
    parsed = urlsplit(value if "://" in value else "https://" + value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("Expected one HTTPS site in the existing Caddy environment")
    return parsed.netloc


def business_fingerprint(data):
    """Compare all stored business rows while writes are stopped, without logging content."""
    digest = hashlib.sha256()
    with closing(
        sqlite3.connect(f"file:{(data / 'db/app.sqlite3').as_posix()}?mode=ro", uri=True)
    ) as db:
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%' AND name != 'django_migrations' ORDER BY name"
        ).fetchall()
        for (name,) in tables:
            quoted = '"' + name.replace('"', '""') + '"'
            rows = sorted(repr(row) for row in db.execute(f"SELECT * FROM {quoted}"))
            digest.update(json.dumps([name, rows], ensure_ascii=True).encode())
    return digest.hexdigest()


def update_env(path, replacements):
    # Preserve authentication hash and every unrelated line byte-for-byte.
    text = path.read_text()
    lines, found = [], set()
    for line in text.splitlines():
        key = line.split("=", 1)[0].strip()
        if key in replacements:
            line = f"{key}={replacements[key]}"
            found.add(key)
        lines.append(line)
    lines.extend(f"{k}={v}" for k, v in replacements.items() if k not in found)
    temp = path.with_suffix(".next")
    temp.write_text("\n".join(lines) + "\n")
    shutil.copystat(path, temp)
    os.chown(temp, path.stat().st_uid, path.stat().st_gid)
    os.replace(temp, path)


def app(code, env_file, *args, seed=False):
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith(("HACCP_", "DJANGO_")):
            del environment[key]
    environment["HACCP_ENV_FILE"] = str(env_file)
    if seed:
        environment["HACCP_QA_SEED_ENABLED"] = "true"
    python = code / ".venv/bin/python" if (code / ".venv/bin/python").exists() else PYTHON
    run("runuser", "-u", "biodot-qa", "--", python, *args, cwd=code, env=environment)


def isolated_regressions(code, uid, gid):
    """Run deployment regression scenarios in memory, with a separate temporary data path."""
    with tempfile.TemporaryDirectory(prefix="biodot-qa-regression-") as directory:
        temp = Path(directory)
        os.chown(temp, uid, gid)
        env_file = temp / "isolated.env"
        env_file.write_text(f"HACCP_DATA_DIR={temp / 'data'}\nDJANGO_HTTPS_ENABLED=false\n")
        env_file.chmod(0o600)
        os.chown(env_file, uid, gid)
        app(
            code,
            env_file,
            "backend/manage.py",
            "test",
            "apps.inventory.test_api",
            "apps.inventory.test_qa_safety",
            "apps.inventory.test_expiration",
            "apps.inventory.test_overview",
            "--settings=config.settings.test",
            "--verbosity=1",
            "--noinput",
        )


def restore(record):
    backup = Path(record["backup"])
    run("systemctl", "stop", "biodot-qa", "caddy")
    old_code = Path(record["old_code"])
    if old_code.exists() or old_code.is_symlink():
        if CURRENT.exists() or CURRENT.is_symlink():
            saved = BASE / ("retained-new-code-" + str(time.time_ns()))
            os.replace(CURRENT, saved)
        os.replace(old_code, CURRENT)
    for name, target in (("qa.env", APP_ENV), ("caddy.env", CADDY_ENV)):
        if (backup / name).exists():
            shutil.copy2(backup / name, target)
            saved_stat = record[name + "_owner"]
            os.chown(target, *saved_stat)
            target.chmod(record[name + "_mode"])
    run("systemctl", "restart", "biodot-qa", "caddy")
    print("Previous code and environment restored; both datasets retained.")


def main():
    import pwd

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--commit")
    parser.add_argument("--fresh-data-once", action="store_true")
    parser.add_argument("--rollback", type=Path)
    parser.add_argument(
        "--code-only", action="store_true", help="Never migrate or seed the server DB"
    )
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    if args.code_only and (args.fresh_data_once or args.rollback):
        parser.error("--code-only cannot be combined with data refresh or rollback")
    if os.geteuid() != 0:
        raise SystemExit("Run as root on the QA server.")
    import fcntl

    lock = (BASE / "redeploy.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if args.rollback:
        restore(json.loads(args.rollback.read_text()))
        return
    if not args.archive or not args.sha256 or not args.commit:
        parser.error("--archive --sha256 --commit are required")
    if hashlib.file_digest(args.archive.open("rb"), "sha256").hexdigest() != args.sha256:
        raise SystemExit("Archive SHA256 mismatch")
    if args.fresh_data_once and MARKER.exists():
        raise SystemExit(
            "One-time refresh already attempted; inspect saved record. Do not repeat seed."
        )
    os.umask(0o077)
    config = dotenv_values(APP_ENV, interpolate=False)
    proxy = dotenv_values(CADDY_ENV, interpolate=False)
    old_data = Path(config.get("HACCP_QA_DATA_DIR", "")).resolve()
    if old_data.parent != Path("/srv/biodot") or not old_data.name.startswith("qa-data"):
        raise SystemExit("Unexpected QA data path")
    if not (old_data / "db/app.sqlite3").is_file():
        raise SystemExit("Existing QA database is missing")
    site = configured_site(proxy)
    if not proxy.get("HACCP_QA_AUTH_HASH"):
        raise SystemExit("Existing QA proxy authentication/site must be configured")
    if config.get("DJANGO_HTTPS_ENABLED", "").lower() != "true":
        raise SystemExit("Existing HTTPS settings were not confirmed")
    # Do not replace the installed unit. Refuse unexpected interpreter/layout instead.
    unit = subprocess.check_output(
        ["systemctl", "show", "biodot-qa", "-p", "ExecStart", "--value"], text=True
    )
    venv_python = CURRENT / ".venv/bin/python"
    if not any(str(p) in unit for p in (PYTHON, venv_python)) or "--qa" not in unit:
        raise SystemExit(
            "Installed app unit differs from expected Python/QA command; inspect privately"
        )
    caddy_unit = subprocess.check_output(
        ["systemctl", "show", "caddy", "-p", "EnvironmentFiles", "--value"], text=True
    )
    if str(CADDY_ENV) not in caddy_unit:
        raise SystemExit("Caddy must read /etc/biodot/caddy.env")
    runtime = venv_python if str(venv_python) in unit else PYTHON
    run(runtime, "-m", "pip", "check")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    backup = BASE / "backups" / stamp
    backup.mkdir(parents=True, mode=0o700)
    backup.chmod(0o700)
    stage = BASE / ("release-" + args.commit[:12] + "-" + stamp)
    stage.mkdir(mode=0o755)
    stage.chmod(0o755)
    with tarfile.open(args.archive) as archive:
        if archive.pax_headers.get("comment") != args.commit:
            raise SystemExit("Archive is not git archive of the requested commit")
        archive.extractall(stage, filter="data")
    for directory, _, files in os.walk(stage):
        Path(directory).chmod(0o755)
        for name in files:
            (Path(directory) / name).chmod(0o644)
    # Existing installation keeps dependencies in current/.venv. Copy it intact;
    # its Python points to the existing /opt interpreter and no packages are installed.
    if runtime == venv_python:
        shutil.copytree(CURRENT / ".venv", stage / ".venv", symlinks=True)
        owner = pwd.getpwnam("biodot-qa")
        for directory, _, files in os.walk(stage / ".venv"):
            os.chown(directory, owner.pw_uid, owner.pw_gid)
            for name in files:
                os.chown(Path(directory) / name, owner.pw_uid, owner.pw_gid, follow_symlinks=False)
    for name in ("base.txt", "production.txt"):
        if (CURRENT / "requirements" / name).read_bytes() != (
            stage / "requirements" / name
        ).read_bytes():
            raise SystemExit("Dependency change needs a separately prepared virtualenv")
    if args.code_only:
        require_code_only_compatibility(CURRENT, stage)
    owner = pwd.getpwnam("biodot-qa")
    isolated_regressions(stage, owner.pw_uid, owner.pw_gid)
    (stage / "QA-DEPLOYED-REVISION.txt").write_text(args.branch + "\n" + args.commit + "\n")
    new_data = Path("/srv/biodot/qa-data-" + stamp) if args.fresh_data_once else old_data
    static_dir = (
        BASE / ("static-" + args.commit[:12] + "-" + stamp)
        if args.code_only
        else new_data / "static"
    )
    if args.code_only:
        static_dir.mkdir(mode=0o755)
        os.chown(static_dir, owner.pw_uid, owner.pw_gid)
    old_code = BASE / ("previous-code-" + stamp)
    record = {
        "commit": args.commit,
        "archive_sha256": args.sha256,
        "backup": str(backup),
        "old_code": str(old_code),
        "old_data": str(old_data),
        "new_data": str(new_data),
        "fresh_data": args.fresh_data_once,
        "code_only": args.code_only,
        "static_dir": str(static_dir),
        "isolated_regressions": "passed",
        "previous_revision": (CURRENT / "QA-DEPLOYED-REVISION.txt").read_text()
        if (CURRENT / "QA-DEPLOYED-REVISION.txt").exists()
        else "unknown",
    }
    for name, path in (("qa.env", APP_ENV), ("caddy.env", CADDY_ENV)):
        record[name + "_mode"] = path.stat().st_mode & 0o777
        record[name + "_owner"] = [path.stat().st_uid, path.stat().st_gid]
        private_copy(path, backup / name)
    record_path = backup / "deployment.json"
    record_path.write_text(json.dumps(record, indent=2))
    record_path.chmod(0o600)
    new_env = backup / "new-qa.env"
    private_copy(APP_ENV, new_env)
    update_env(
        new_env,
        {
            "HACCP_QA_DATA_DIR": str(new_data),
            "HACCP_STATIC_DIR": str(static_dir),
            "HACCP_QA_SEED_ENABLED": "false",
        },
    )
    # App user needs access to its staging environment, not to backup credentials.
    staging_env = Path("/etc/biodot/qa-staging-" + stamp + ".env")
    private_copy(new_env, staging_env)
    account = pwd.getpwnam("biodot-qa")
    os.chown(staging_env, account.pw_uid, account.pw_gid)
    if args.code_only:
        check_schema_without_writes(stage, staging_env)
    if args.fresh_data_once:
        new_data.mkdir(mode=0o711)  # fails if anything already occupies this path
        os.chown(new_data, account.pw_uid, account.pw_gid)
        MARKER.write_text(json.dumps(record, indent=2))
        MARKER.chmod(0o600)
    stopped = False
    previous_handlers = {}

    def interrupted(signum, frame):
        raise SystemExit(f"Deployment interrupted by signal {signum}")

    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        sig = getattr(signal, name)
        previous_handlers[sig] = signal.signal(sig, interrupted)
    try:
        stopped = True
        run("systemctl", "stop", "caddy", "biodot-qa")
        before_data = business_fingerprint(old_data) if not args.fresh_data_once else None
        # Stop all application writes before copying DB + WAL + attachments + static.
        with tarfile.open(backup / "qa-data.tar.gz", "w:gz") as archive:
            archive.add(old_data, arcname=old_data.name)
        with tarfile.open(backup / "qa-data.tar.gz") as archive:
            if f"{old_data.name}/db/app.sqlite3" not in archive.getnames():
                raise RuntimeError("Backup database missing")
            # Read every payload to detect truncated archive before switching.
            for member in archive.getmembers():
                if member.isfile():
                    with archive.extractfile(member) as stream:
                        while stream.read(1024 * 1024):
                            pass
        if args.code_only:
            check_schema_without_writes(stage, staging_env)
        else:
            app(stage, staging_env, "scripts/project.py", "--env-file", staging_env, "--qa", "init")
        if args.fresh_data_once:
            app(
                stage,
                staging_env,
                "backend/manage.py",
                "install_document_templates",
                "--settings=config.settings.qa",
            )
            app(
                stage,
                staging_env,
                "backend/manage.py",
                "seed_qa_inventory",
                "--stage",
                "run",
                "--settings=config.settings.qa",
                seed=True,
            )
        app(
            stage,
            staging_env,
            "scripts/project.py",
            "--env-file",
            staging_env,
            "--qa",
            "collectstatic",
        )
        app(
            stage,
            staging_env,
            "backend/manage.py",
            "check",
            "--deploy",
            "--settings=config.settings.qa",
        )
        app(
            stage,
            staging_env,
            "backend/manage.py",
            "check_inventory",
            "--settings=config.settings.qa",
        )
        if before_data is not None:
            if business_fingerprint(old_data) != before_data:
                raise RuntimeError(
                    "Business data changed during code-only deployment; inspect backup"
                )
            record["business_data_preserved"] = True
            record_path.write_text(json.dumps(record, indent=2))
        new_data.chmod(0o711)
        for directory, _, files in os.walk(static_dir):
            Path(directory).chmod(0o755)
            for name in files:
                (Path(directory) / name).chmod(0o644)
        run(
            "runuser",
            "-u",
            "caddy",
            "--",
            "test",
            "-r",
            static_dir / "prototype/js/modules/production-api.js",
        )
        proxy_environment = os.environ.copy()
        proxy_environment.update({k: v for k, v in proxy.items() if v is not None})
        proxy_environment["HACCP_STATIC_DIR"] = str(static_dir)
        validation = subprocess.run(
            ["caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
            env=proxy_environment,
            capture_output=True,
        )
        if validation.returncode:
            raise RuntimeError("Existing Caddy configuration failed validation; settings retained")
        update_env(
            APP_ENV,
            {
                "HACCP_QA_DATA_DIR": str(new_data),
                "HACCP_STATIC_DIR": str(static_dir),
                "HACCP_QA_SEED_ENABLED": "false",
            },
        )
        update_env(CADDY_ENV, {"HACCP_STATIC_DIR": str(static_dir)})
        os.replace(CURRENT, old_code)
        os.replace(stage, CURRENT)
        run("systemctl", "restart", "biodot-qa", "caddy")
        for attempt in range(20):
            try:
                request = urllib.request.Request(
                    "http://127.0.0.1:8002/health/ready/",
                    headers={"Host": site, "X-Forwarded-Proto": "https"},
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    if response.status == 200:
                        break
            except Exception:
                if attempt == 19:
                    raise
                time.sleep(1)
        run("systemctl", "is-active", "biodot-qa", "caddy")
        # TLS verification stays on. An unauthenticated request must still be blocked.
        result = subprocess.check_output(
            [
                "curl",
                "--silent",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code}",
                "https://" + site + "/",
            ],
            text=True,
        )
        if result != "401":
            raise RuntimeError("HTTPS QA authentication check failed")
        print("DEPLOYED", args.commit, "DATA", new_data, "RECORD", record_path)
        print("Browser/iPad business QA remains to be performed.")
    except BaseException:
        # Finish recovery even if the SSH session sends another termination signal.
        for sig in previous_handlers:
            signal.signal(sig, signal.SIG_IGN)
        if stopped:
            restore(record)
        raise
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
