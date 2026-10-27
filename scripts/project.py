"""Portable project commands. Run with the project's virtualenv Python."""

import argparse
import importlib.metadata
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def django_setup(production=False, qa=False):
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ["DJANGO_SETTINGS_MODULE"] = (
        "config.settings.qa"
        if qa
        else "config.settings.production"
        if production
        else "config.settings.development"
    )
    import django

    django.setup()


def run_command(*args):
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True)


def initialize(args):
    env_path = Path(os.environ["HACCP_ENV_FILE"])
    if not env_path.exists():
        template = ROOT / (
            ".env.qa.example"
            if args.qa
            else ".env.production.example"
            if args.production
            else ".env.example"
        )
        contents = template.read_text(encoding="utf-8").replace(
            "replace-with-generated-secret", secrets.token_urlsafe(64)
        )
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(contents, encoding="utf-8")
        env_path.chmod(0o600)
        print(f"Created {env_path.name} with a unique secret.")
    else:
        print(f"Keeping existing {env_path.name}.")
    django_setup(args.production, args.qa)
    from django.conf import settings
    from django.core.management import call_command

    for name in ("db", "uploads", "logs", "backups", "static"):
        (settings.DATA_DIR / name).mkdir(parents=True, exist_ok=True)
    call_command("migrate", interactive=False)
    if args.qa:
        prototype = settings.PROTOTYPE_DATA_FILE
        if not prototype.exists():
            prototype.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "data/legacy-prototype/src/js/data.js", prototype)
    print("Initialized. Existing database records and uploads were preserved.")


def check(args):
    if sys.version_info[:2] != (3, 14):
        raise SystemExit("This project is tested with Python 3.14. Use Python 3.14.x.")
    if sqlite3.sqlite_version_info < (3, 37):
        raise SystemExit("SQLite 3.37+ is required (STRICT tables).")
    print(f"Python {sys.version.split()[0]} | SQLite {sqlite3.sqlite_version}", flush=True)
    run_command("-m", "pip", "check")
    run_command("-m", "ruff", "check", ".")
    run_command("-m", "ruff", "format", "--check", ".")
    run_command("-m", "unittest", "discover", "-s", "scripts", "-p", "test_*.py", "-v")
    settings_name = (
        "config.settings.qa"
        if args.qa
        else "config.settings.production"
        if args.production
        else "config.settings.development"
    )
    options = [f"--settings={settings_name}"]
    run_command("backend/manage.py", "check", *options)
    run_command("backend/manage.py", "makemigrations", "--check", "--dry-run", *options)
    run_command(
        "backend/manage.py", "test", "apps", "--settings=config.settings.test", "--verbosity=2"
    )


def serve(args):
    django_setup(production=True, qa=args.qa)
    from config.wsgi import application
    from waitress import serve as waitress_serve

    print(f"Waitress listening on http://127.0.0.1:{args.port} (production settings).", flush=True)
    waitress_serve(
        application,
        host="127.0.0.1",
        port=args.port,
        threads=4,
        channel_timeout=60,
        max_request_body_size=30 * 1024 * 1024,
        trusted_proxy="127.0.0.1",
        trusted_proxy_headers={"x-forwarded-proto"},
        clear_untrusted_proxy_headers=True,
        expose_tracebacks=False,
    )


def smoke(args):
    endpoints = {
        "/": ("text/html", "HACCP"),
        "/test/": ("text/html", "live-status"),
        "/static/prototype/css/main.css": ("text/css", ":root"),
        "/static/prototype/js/app.js": ("javascript", "HACCP_DATA"),
        "/static/system-test/app.js": ("javascript", "fetch"),
        "/health/live/": ("application/json", '"status": "ok"'),
        "/health/ready/": ("application/json", '"database": "ok"'),
    }
    for path, (content_type, expected) in endpoints.items():
        with urlopen(args.url.rstrip("/") + path, timeout=10) as response:
            body = response.read().decode("utf-8")
            if response.status != 200 or content_type not in response.headers.get(
                "Content-Type", ""
            ):
                raise SystemExit(f"FAIL {path}: unexpected status/content type")
            if expected not in body:
                raise SystemExit(f"FAIL {path}: expected content was not found")
        print(f"PASS {path}")
    for path in ("/data/reference/", "/private-media/", "/.env", "/admin/", "/files/"):
        try:
            with urlopen(args.url.rstrip("/") + path, timeout=10):
                raise SystemExit(f"FAIL {path}: private path was accessible")
        except HTTPError as error:
            if error.code not in (400, 403, 404):
                raise
        print(f"PASS private path blocked: {path}")


def caddy(args):
    django_setup(args.production, args.qa)
    from django.conf import settings

    executable = args.binary or shutil.which("caddy")
    if not executable:
        raise SystemExit(
            "Install Caddy, or pass --binary /path/to/caddy. See docs/handover/installation.md."
        )
    env = os.environ.copy()
    env.update(
        HACCP_STATIC_DIR=settings.STATIC_ROOT.as_posix(),
        HACCP_SITE_ADDRESS=args.site,
        HACCP_BIND=args.bind,
        HACCP_UPSTREAM=f"127.0.0.1:{args.upstream_port}",
        XDG_DATA_HOME=settings.DATA_DIR.as_posix(),
        XDG_CONFIG_HOME=(settings.DATA_DIR / "config").as_posix(),
    )
    subprocess.run(
        [
            executable,
            "run",
            "--config",
            str(ROOT / ("infra/caddy/Caddyfile.qa" if args.qa else "infra/caddy/Caddyfile")),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )


def backup(args):
    if not args.writes_stopped:
        raise SystemExit(
            "Stop application writes, then pass --writes-stopped. "
            "See docs/handover/installation.md."
        )
    django_setup(args.production, args.qa)
    import zipfile
    from datetime import datetime, timezone

    from django.conf import settings

    db_path = Path(settings.DATABASES["default"]["NAME"])
    if not db_path.is_file():
        raise SystemExit("Database does not exist; initialize the project first.")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = settings.DATA_DIR / "backups" / timestamp
    directory.mkdir(parents=True, exist_ok=False)
    # SQLite's backup API produces a consistent DB, including committed WAL contents.
    with sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True) as source:
        with sqlite3.connect(directory / "app.sqlite3") as target:
            source.backup(target)
    with zipfile.ZipFile(directory / "uploads.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(settings.MEDIA_ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(settings.MEDIA_ROOT))
    metadata = {
        "created_at": timestamp,
        "python": sys.version.split()[0],
        "django": importlib.metadata.version("Django"),
        "sqlite": sqlite3.sqlite_version,
    }
    (directory / "manifest.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Backup: {directory}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", help="Path to a private environment file")
    environment = parser.add_mutually_exclusive_group()
    environment.add_argument("--production", action="store_true", help="Use production settings")
    environment.add_argument("--qa", action="store_true", help="Use isolated hosted QA settings")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create local configuration/directories and apply migrations")
    sub.add_parser("check", help="Check versions, formatting, migrations and automated tests")
    run_parser = sub.add_parser("run", help="Start the development server on loopback")
    run_parser.add_argument("--port", type=int, default=8000)
    serve_parser = sub.add_parser("serve", help="Run production Waitress on loopback")
    serve_parser.add_argument("--port", type=int, default=8001)
    sub.add_parser("collectstatic", help="Collect static files for Caddy")
    smoke_parser = sub.add_parser("smoke", help="Check a running server over real HTTP")
    smoke_parser.add_argument("--url", default="http://127.0.0.1:8000")
    caddy_parser = sub.add_parser("caddy", help="Run Caddy using common configuration")
    caddy_parser.add_argument("--binary", help="Path to the Caddy executable")
    caddy_parser.add_argument("--site", default="http://127.0.0.1:8080")
    caddy_parser.add_argument("--bind", default="127.0.0.1")
    caddy_parser.add_argument("--upstream-port", type=int, default=8001)
    backup_parser = sub.add_parser("backup", help="Back up SQLite and uploaded files")
    backup_parser.add_argument("--writes-stopped", action="store_true")
    args = parser.parse_args()
    env_path = Path(args.env_file).expanduser()
    os.environ["HACCP_ENV_FILE"] = str((ROOT / env_path).resolve())
    if args.command == "run":
        if args.production or args.qa:
            raise SystemExit("Use 'serve' for production/QA; 'run' is development only.")
        run_command("backend/manage.py", "runserver", f"127.0.0.1:{args.port}")
    elif args.command == "collectstatic":
        django_setup(args.production, args.qa)
        from django.core.management import call_command

        call_command("collectstatic", interactive=False, clear=True)
    else:
        {
            "init": initialize,
            "check": check,
            "serve": serve,
            "smoke": smoke,
            "caddy": caddy,
            "backup": backup,
        }[args.command](args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (subprocess.CalledProcessError, URLError) as error:
        print(f"Command failed: {error}", file=sys.stderr)
        sys.exit(1)
