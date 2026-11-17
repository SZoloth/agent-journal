#!/usr/bin/env python3
"""Read and write a local Markdown journal."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from tempfile import NamedTemporaryFile
from uuid import uuid4


KINDS = ("note", "question", "reflection", "milestone", "lifecycle")
ENTRY_ID = re.compile(r"[0-9a-f]{32}")
OPTIONAL_FIELDS = ("session", "goal", "event_id", "relates_to")
DEFAULT_ROOT = "~/.local/share/agent-journal"


def project_path(value):
    path = Path(value).expanduser().resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            timeout=2,
            env={
                key: val for key, val in os.environ.items()
                if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"}
            },
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return str(path)
    if result.returncode == 0:
        git_root = os.fsdecode(result.stdout.removesuffix(b"\n"))
        return str(Path(git_root).resolve())
    return str(path)


def entry_path(directory, entry_id):
    if not ENTRY_ID.fullmatch(entry_id):
        raise ValueError("entry ID must be 32 lowercase hexadecimal characters")
    return directory / f"{entry_id}.md"


def read_markdown(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise ValueError(f"entry is not a regular file: {path.name}")
        return file.read()


def parse_entry(path):
    raw = read_markdown(path)
    try:
        header, separator, body = raw[4:].partition(b"\n---\n")
        if not raw.startswith(b"---\n") or not separator:
            raise ValueError
        record = dict(
            (key.decode("ascii"), json.loads(value))
            for key, value in (line.split(b": ", 1) for line in header.split(b"\n"))
        )
        if record.get("schema_version") != 1 or record.get("id") != path.stem:
            raise ValueError
        if not all(isinstance(record.get(key), str) for key in ("created_at", "kind", "client", "project")):
            raise ValueError
        if not all(key in record and (record[key] is None or isinstance(record[key], str)) for key in OPTIONAL_FIELDS):
            raise ValueError
        record["body"] = body.decode("utf-8")
        return record
    except ValueError:
        raise ValueError(f"invalid journal entry: {path.name}") from None


def write_entry(directory, *, kind, client, project, body, session=None, goal=None, event_id=None, relates_to=None):
    if not client.strip():
        raise ValueError("client cannot be blank")
    if event_id is not None and not event_id.strip():
        raise ValueError("event ID cannot be blank")
    if relates_to is not None and not ENTRY_ID.fullmatch(relates_to):
        raise ValueError("related entry ID must be 32 lowercase hexadecimal characters")
    if not body.strip():
        raise ValueError("entry body cannot be blank")

    entry_id = uuid4().hex
    if event_id is not None:
        key = json.dumps((kind, event_id), ensure_ascii=True).encode("ascii")
        entry_id = sha256(key).hexdigest()[:32]
    values = {
        "schema_version": 1,
        "id": entry_id,
        "kind": kind,
        "client": client,
        "session": session,
        "project": project,
        "goal": goal,
        "event_id": event_id,
        "relates_to": relates_to,
    }
    created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    metadata = {**values, "created_at": created_at}
    header = "\n".join(f"{key}: {json.dumps(value)}" for key, value in metadata.items())
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = entry_path(directory, entry_id)
    with NamedTemporaryFile(dir=directory, prefix=".writing-") as pending:
        pending.write(f"---\n{header}\n---\n{body}".encode("utf-8"))
        pending.flush()
        os.fsync(pending.fileno())
        # A hard link publishes the completed file only if its ID is still unused.
        try:
            os.link(pending.name, path)
        except FileExistsError:
            existing = parse_entry(path)
            if event_id is None or any(existing.get(key) != value for key, value in values.items()):
                raise ValueError(f"entry already exists with different metadata: {entry_id}") from None
            if existing["body"] != body:
                raise ValueError(f"entry already exists with different content: {entry_id}") from None
    return entry_id


def read_entries(directory):
    entries = (
        parse_entry(path)
        for path in directory.glob("*.md")
        if ENTRY_ID.fullmatch(path.stem)
    )
    return sorted(entries, key=lambda entry: (entry["created_at"], entry["id"]), reverse=True)


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("AGENT_JOURNAL_DIR") or DEFAULT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="write a Markdown entry from stdin")
    add.add_argument("--client", required=True)
    add.add_argument("--session")
    add.add_argument("--project", default=".")
    add.add_argument("--goal")
    add.add_argument("--kind", choices=KINDS, default="note")
    add.add_argument("--event-id")
    add.add_argument("--relates-to")
    listing = commands.add_parser("list", help="list matching entries as JSON Lines")
    listing.add_argument("--project")
    listing.add_argument("--session")
    listing.add_argument("--kind", choices=(*KINDS, "resolution"))
    listing.add_argument("--limit", type=positive_int, default=20)
    browser = commands.add_parser("browse", help="find and read entries in an interactive terminal")
    browser.add_argument("--project", help="open with this project selected")
    browser.add_argument("--kind", choices=("all", *KINDS, "resolution"),
                         help="choose an entry kind (default: hide lifecycle events)")
    browser.add_argument("--search", default="", help="open with this text search applied")
    show = commands.add_parser("show", help="print an entry as Markdown")
    show.add_argument("id")
    questions = commands.add_parser("questions", help="list open questions for a project as JSON Lines")
    questions.add_argument("--project", required=True)
    questions.add_argument("--limit", type=positive_int, default=20)
    resolve = commands.add_parser("resolve", help="record a question's resolution")
    resolve.add_argument("id")
    return parser.parse_args()


def run(args, directory):
    if args.command == "add":
        body = sys.stdin.buffer.read().decode("utf-8")
        print(write_entry(
            directory, kind=args.kind, client=args.client, project=project_path(args.project),
            session=args.session, goal=args.goal, event_id=args.event_id, relates_to=args.relates_to,
            body=body,
        ))
        return
    if args.command == "show":
        sys.stdout.buffer.write(read_markdown(entry_path(directory, args.id)))
        return
    if args.command == "resolve":
        entry = parse_entry(entry_path(directory, args.id))
        if entry["kind"] != "question":
            raise ValueError("only questions can be resolved")
        print(write_entry(
            directory, kind="resolution", client="journal", project=entry["project"],
            event_id=args.id, relates_to=args.id, body="Resolved.\n",
        ))
        return

    if args.command == "browse" and not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ValueError("browse needs an interactive terminal; use list or show for scripts")
    records = read_entries(directory)
    project = project_path(args.project) if args.project is not None else None
    if args.command == "browse":
        try:
            import curses
        except ImportError:
            raise ValueError("browse needs Python's curses module") from None
        from journal_browse import browse

        try:
            browse(records, project=project, kind=args.kind, query=args.search)
        except curses.error as error:
            raise ValueError(f"could not open the terminal browser: {error}") from None
        return
    if args.command == "questions":
        resolved = {entry["relates_to"] for entry in records if entry["kind"] == "resolution"}
        records = [
            entry for entry in records
            if entry["kind"] == "question" and entry["project"] == project and entry["id"] not in resolved
        ]
    else:
        filters = {"project": project, "kind": args.kind, "session": args.session}
        records = [
            entry for entry in records
            if all(value is None or entry.get(key) == value for key, value in filters.items())
        ]
    for entry in records[:args.limit]:
        print(json.dumps(entry))


def main():
    args = parse_args()
    os.umask(0o077)
    try:
        root = Path(args.root).expanduser()
        if not root.is_absolute():
            raise ValueError("journal root must be an absolute path")
        directory = root.resolve() / "entries"
        if directory.is_symlink():
            raise ValueError("entries directory cannot be a symbolic link")
        run(args, directory)
    except (OSError, ValueError) as error:
        sys.exit(f"journal: {error}")


if __name__ == "__main__":
    main()
