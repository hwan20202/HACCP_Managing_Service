"""Run the production core SQL files from Django migrations.

Django's RunSQL splits a script with sqlparse, which can break CREATE TRIGGER ... BEGIN ... END
blocks. This runner splits with sqlite3.complete_statement (SQLite's own tokenizer) instead,
so statements, triggers and comments containing ';' are handled the way the sqlite3 shell does.
"""

import re
import sqlite3
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent / "sql"

_COMMENTS = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)
_CREATE = re.compile(
    r"^CREATE\s+(?:UNIQUE\s+)?(TABLE|VIEW|TRIGGER|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
    re.IGNORECASE,
)


def _strip_comments(statement):
    return _COMMENTS.sub("", statement).strip()


def split_statements(script):
    """Split a SQL script into complete statements, dropping comment-only chunks."""
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if _strip_comments(buffer):
                statements.append(buffer.strip())
            buffer = ""
    if _strip_comments(buffer):
        raise ValueError(f"Incomplete SQL statement at end of script: {buffer.strip()[:200]}")
    return statements


def read_sql(filename):
    return (SQL_DIR / filename).read_text(encoding="utf-8")


def run_sql_file(filename):
    """Return a RunPython forward function that executes the SQL file.

    PRAGMA statements are skipped: inside a migration transaction they have no effect.
    Connection-level PRAGMAs are configured in settings (see config/settings/base.py).
    """

    def forward(_apps, schema_editor):
        with schema_editor.connection.cursor() as cursor:
            for statement in split_statements(read_sql(filename)):
                if _strip_comments(statement).upper().startswith("PRAGMA"):
                    continue
                cursor.execute(statement)

    return forward


def drop_sql_file_objects(filename):
    """Return a RunPython reverse function that drops what the SQL file created.

    Views first, then triggers, then tables in reverse creation order (indexes go with tables).
    """

    def reverse(_apps, schema_editor):
        created = {"VIEW": [], "TRIGGER": [], "TABLE": []}
        for statement in split_statements(read_sql(filename)):
            match = _CREATE.match(_strip_comments(statement))
            if match and match.group(1).upper() in created:
                created[match.group(1).upper()].append(match.group(2))
        with schema_editor.connection.cursor() as cursor:
            for kind in ("VIEW", "TRIGGER", "TABLE"):
                for name in reversed(created[kind]):
                    cursor.execute(f'DROP {kind} IF EXISTS "{name}"')

    return reverse


def recreate_from_sql_file(filename, names):
    """Return a RunPython function that runs the CREATE statements for `names` from a file.

    Used when a later migration redefines a view from an earlier file (0002 redefines
    v_stock_ledger): its reverse drops the new definition, then restores the earlier one.
    """

    def run(_apps, schema_editor):
        wanted = {name.lower() for name in names}
        with schema_editor.connection.cursor() as cursor:
            for statement in split_statements(read_sql(filename)):
                match = _CREATE.match(_strip_comments(statement))
                if match and match.group(2).lower() in wanted:
                    cursor.execute(statement)

    return run


def chain(*functions):
    """Combine RunPython functions into one, run in order."""

    def run(apps, schema_editor):
        for function in functions:
            function(apps, schema_editor)

    return run
