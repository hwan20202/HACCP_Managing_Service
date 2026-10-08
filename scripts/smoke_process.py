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
    started = time.monotonic()
    print(f"Starting smoke server at {url}", flush=True)
    process = subprocess.Popen(
        [sys.executable, "-u", "scripts/smoke_server.py", str(port)],
        cwd=ROOT,
        # Inherit output so CI includes Django startup errors and diagnostic traces.
    )
    try:
        deadline = started + 20
        last_error = "No HTTP response received."
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SystemExit(
                    f"Server exited before becoming ready (exit code {process.returncode}). "
                    "See server output above."
                )
            try:
                with urlopen(url + "/health/live/", timeout=1) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError) as error:
                last_error = str(error)
                time.sleep(0.1)
        else:
            raise SystemExit(
                f"Server startup timed out after 20s at {url}/health/live/. "
                f"Last error: {last_error}. See server output above."
            )
        print(f"Smoke server ready in {time.monotonic() - started:.2f}s", flush=True)
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
