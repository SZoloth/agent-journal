"""Prepare one journal entry for review or send a reviewed file to private GitHub."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from journal import DEFAULT_ROOT, entry_path, parse_entry


REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")
EXPORT = re.compile(r"[0-9a-f]{32}\.md")


def gh_api(path, *, payload=None, missing=False):
    command = ["gh", "api", "--hostname", "github.com", path]
    if payload is not None:
        command.extend(["--method", "PUT", "--input", "-"])
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else "",
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        if missing and "HTTP 404" in result.stderr:
            return None
        raise ValueError(f"GitHub API request failed: {path}")
    return json.loads(result.stdout)


def prepare(entry_id, output):
    root = Path(os.environ.get("AGENT_JOURNAL_DIR") or DEFAULT_ROOT).expanduser()
    if not root.is_absolute():
        raise ValueError("journal root must be absolute")
    if output.name != f"{entry_id}.md":
        raise ValueError("name the review file ENTRY_ID.md")
    entries = root.resolve() / "entries"
    if entries.is_symlink():
        raise ValueError("entries directory cannot be a symbolic link")
    record = parse_entry(entry_path(entries, entry_id))
    if record["kind"] not in ("note", "question", "reflection"):
        raise ValueError("only notes, questions, and reflections can be exported")
    body = record["body"]
    with output.open("x", encoding="utf-8", newline="") as file:
        file.write(body)
    print(output)


def publish(repository, source):
    if not REPO.fullmatch(repository) or not EXPORT.fullmatch(source.name):
        raise ValueError("expected OWNER/REPO and a reviewed ENTRY_ID.md file")
    if not source.is_file() or source.is_symlink():
        raise ValueError("review file must be a regular file")
    content = source.read_bytes()
    if not content.strip():
        raise ValueError("review file is empty")
    content.decode("utf-8")
    target = f"repos/{repository}"
    repo = gh_api(target)
    if not isinstance(repo, dict) or repo.get("visibility") != "private" or repo.get("full_name", "").casefold() != repository.casefold():
        raise ValueError("GitHub did not confirm the exact repository is private")
    path = f"{target}/contents/entries/{source.name}"
    existing = gh_api(path, missing=True)
    if existing is None:
        try:
            gh_api(path, payload={"message": f"docs: add journal entry {source.stem}",
                                  "content": base64.b64encode(content).decode("ascii")})
        except (ValueError, subprocess.TimeoutExpired):
            if gh_api(path, missing=True) is None:
                raise
        existing = gh_api(path)
    if not isinstance(existing, dict) or existing.get("encoding") != "base64" or base64.b64decode(existing["content"]) != content:
        raise ValueError("GitHub already contains different content at that entry ID")
    print(existing["html_url"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    draft = actions.add_parser("prepare", help="write a new review copy containing the Markdown body only")
    draft.add_argument("id")
    draft.add_argument("output", type=Path)
    upload = actions.add_parser("publish", help="send the exact reviewed file to a private repository")
    upload.add_argument("repository")
    upload.add_argument("file", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == "prepare":
            prepare(args.id, args.output)
        else:
            publish(args.repository, args.file)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"agent-journal sync: {error}\n")


if __name__ == "__main__":
    main()
