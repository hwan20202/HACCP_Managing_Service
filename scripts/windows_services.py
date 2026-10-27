"""Generate WinSW service definitions without installing or starting services."""

import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def service_xml(service_id, executable, arguments, log_dir, description):
    root = ET.Element("service")
    values = {
        "id": service_id,
        "name": service_id,
        "description": description,
        "executable": str(executable),
        "arguments": subprocess.list2cmdline([str(arg) for arg in arguments]),
        "workingdirectory": str(ROOT),
        "startmode": "Automatic",
        "stoptimeout": "30 sec",
        "logpath": str(log_dir),
    }
    for key, value in values.items():
        ET.SubElement(root, key).text = value
    ET.SubElement(root, "env", name="PYTHONUTF8", value="1")
    ET.SubElement(root, "env", name="PYTHONUNBUFFERED", value="1")
    account = ET.SubElement(root, "serviceaccount")
    ET.SubElement(account, "domain").text = "NT AUTHORITY"
    ET.SubElement(account, "user").text = "LocalService"
    ET.SubElement(root, "onfailure", action="restart", delay="10 sec")
    log = ET.SubElement(root, "log", mode="roll-by-size")
    ET.SubElement(log, "sizeThreshold").text = "10240"
    ET.SubElement(log, "keepFiles").text = "8"
    ET.indent(root)
    return ET.ElementTree(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True, help="HTTPS site, e.g. haccp.company.example")
    parser.add_argument("--env-file", default=".env.production")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Generate these files on the target Windows PC so paths are correct.")
    if "://" in args.site and not args.site.startswith("https://"):
        raise SystemExit("Windows production services require an HTTPS site address.")
    env_path = (ROOT / args.env_file).resolve()
    if not env_path.is_file():
        raise SystemExit("Initialize and configure .env.production first.")
    os.environ["HACCP_ENV_FILE"] = str(env_path)
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.production"
    import django

    django.setup()
    from django.conf import settings

    if not settings.HTTPS_ENABLED:
        raise SystemExit("Set DJANGO_HTTPS_ENABLED=true before installing production services.")
    python = ROOT / ".venv/Scripts/python.exe"
    caddy = ROOT / "tools/caddy.exe"
    if not python.is_file() or not caddy.is_file():
        raise SystemExit("Create .venv and place Caddy at tools/caddy.exe first.")
    output = ROOT / "tools/services"
    output.mkdir(parents=True, exist_ok=True)
    log_dir = settings.DATA_DIR / "logs/services"
    log_dir.mkdir(parents=True, exist_ok=True)
    project = ROOT / "scripts/project.py"
    common = [project, "--env-file", env_path, "--production"]
    services = {
        "haccp-app": (common + ["serve"], "HACCP Django application / Waitress"),
        "haccp-proxy": (
            common + ["caddy", "--binary", caddy, "--site", args.site, "--bind", "0.0.0.0"],
            "HACCP HTTPS and static files / Caddy",
        ),
    }
    for name, (arguments, description) in services.items():
        destination = output / f"{name}.xml"
        service_xml(name, python, arguments, log_dir, description).write(
            destination, encoding="utf-8", xml_declaration=True
        )
        print(f"Generated {destination}")
    print(
        "No services were installed. Follow docs/handover/installation.md to install using WinSW."
    )


if __name__ == "__main__":
    main()
