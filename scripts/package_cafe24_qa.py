"""Package the committed feature branch for manual SSH upload. Never deploys."""

import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main():
    if git("branch", "--show-current") != "feature/inventory-production":
        raise SystemExit("Only feature/inventory-production may be packaged")
    if git("status", "--porcelain"):
        raise SystemExit("Commit reviewed changes before packaging")
    commit = git("rev-parse", "HEAD")
    target = ROOT / "tools" / "qa-deploy" / ("redeploy-" + commit[:12])
    target.mkdir(parents=True, exist_ok=False)
    source = target / "source.tar.gz"
    subprocess.run(
        ["git", "archive", "--format=tar.gz", f"--output={source}", commit], cwd=ROOT, check=True
    )
    digest = hashlib.file_digest(source.open("rb"), "sha256").hexdigest()
    with tarfile.open(source) as archive:
        assert archive.pax_headers["comment"] == commit
        files = {
            member.name: hashlib.sha256(archive.extractfile(member).read()).hexdigest()
            for member in archive.getmembers()
            if member.isfile()
        }
        (target / "redeploy_cafe24_qa.py").write_bytes(
            archive.extractfile("scripts/redeploy_cafe24_qa.py").read()
        )
    manifest = {
        "branch": "feature/inventory-production",
        "commit": commit,
        "previous_server_commit": "adab64cdd860f93ec3d50fe231b71fec420b1019",
        "archive_sha256": digest,
        "files": files,
        "changed_files": git("diff", "--name-only", "adab64c", commit).splitlines(),
        "remote_executed": False,
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    remote = "/root/biodot-qa-" + commit[:12]
    command = (
        f"/opt/biodot-qa/current/.venv/bin/python {remote}/redeploy_cafe24_qa.py "
        f"--archive {remote}/source.tar.gz --sha256 {digest} --commit {commit} --fresh-data-once"
    )
    (target / "run-redeploy.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\numask 077\n"
        f"cd {remote}\nsha256sum -c SHA256SUMS\nexec {command}\n",
        encoding="utf-8",
        newline="\n",
    )
    checksums = "".join(
        f"{hashlib.file_digest(p.open('rb'), 'sha256').hexdigest()}  {p.name}\n"
        for p in sorted(target.iterdir())
        if p.is_file()
    )
    (target / "SHA256SUMS").write_text(checksums, encoding="ascii", newline="\n")
    print(target)
    print("Commit:", commit)
    print("PowerShell upload:")
    print(f'scp -r "{target}" root@175.118.124.141:{remote}')
    print("ssh root@175.118.124.141")
    print("Server command:")
    print(f"bash {remote}/run-redeploy.sh")


if __name__ == "__main__":
    main()
