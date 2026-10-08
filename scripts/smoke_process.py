"""Start a temporary development server and check it, including in CI."""

import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from project import ROOT


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "backend/manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SystemExit("Server exited before becoming ready.")
            try:
                with urlopen(url + "/health/live/", timeout=1) as response:
                    if response.status == 200:
                        break
            except URLError, TimeoutError:
                time.sleep(0.1)
        else:
            raise SystemExit("Server startup timed out.")
        subprocess.run(
            [sys.executable, "scripts/project.py", "smoke", "--url", url], cwd=ROOT, check=True
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
