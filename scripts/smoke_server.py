"""Loopback-only Django server for HTTP checks, without reverse DNS at startup."""

import argparse
import faulthandler
import os
import socketserver
import sys
from pathlib import Path

import django
from django.contrib.staticfiles.management.commands.runserver import Command
from django.core.management import call_command
from django.core.servers.basehttp import WSGIServer

ROOT = Path(__file__).resolve().parents[1]


class LoopbackWSGIServer(WSGIServer):
    def server_bind(self):
        # HTTPServer.server_bind() calls getfqdn(), which can take over 30s on
        # GitHub's macOS runners. This test server already has a numeric address.
        # https://github.com/actions/setup-python/issues/1223
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]
        self.setup_environ()


class SmokeRunserverCommand(Command):
    server_cls = LoopbackWSGIServer

    def on_bind(self, server_port):
        faulthandler.cancel_dump_traceback_later()
        super().on_bind(server_port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    # If another startup step hangs, leave a stack trace before the parent's 20s limit.
    faulthandler.dump_traceback_later(15)
    try:
        django.setup()
        call_command(
            SmokeRunserverCommand(),
            f"127.0.0.1:{args.port}",
            use_reloader=False,
            skip_checks=False,
        )
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
