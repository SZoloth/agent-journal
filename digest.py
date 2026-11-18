#!/usr/bin/env python3
"""Write a weekly Markdown digest of what agents wrote in the journal."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import journal

PROMPT = """You are reading one week of a private journal that AI coding agents keep while working with {person}.
Write a short briefing for {person} with these sections, as Markdown with ### headings:
### About working with {person}
### Complaints and friction
### Open questions
### Ideas worth a look
Use only what the entries say. Cite each point with the entry id in backticks. Leave a section as "Nothing this week." when no entry supports it. Do not invent, soften or add advice of your own. Keep it under 300 words.

Entries (JSON Lines):
"""


def load(root, since):
    entries = journal.read_entries(root / "entries")
    resolved = {entry["relates_to"] for entry in entries if entry["kind"] == "resolution"}
    week = [entry for entry in entries if entry["created_at"] >= since and entry["kind"] in (*journal.WRITTEN_KINDS, "milestone")]
    open_questions = [entry for entry in entries if entry["kind"] == "question" and entry["id"] not in resolved]
    return sorted(week, key=lambda entry: entry["created_at"]), open_questions


def summarize(entries, person):
    written = [{key: entry[key] for key in ("id", "kind", "client", "project", "goal", "body")}
               for entry in entries if entry["kind"] in journal.WRITTEN_KINDS]
    if not written:
        return None
    prompt = PROMPT.format(person=person) + "\n".join(json.dumps(entry) for entry in written)
    env = dict(os.environ, AGENT_JOURNAL_HEADLESS="1")
    try:
        result = subprocess.run(
            ["claude", "--print", "--model", "sonnet", "--setting-sources", "project", "--no-session-persistence"],
            input=prompt, capture_output=True, text=True, timeout=300, env=env, cwd="/",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def render(entries, open_questions, summary, start, end):
    lines = [f"# Agent journal, {start:%b %-d} to {end:%b %-d, %Y}", ""]
    written = [entry for entry in entries if entry["kind"] in journal.WRITTEN_KINDS]
    sessions = {(entry.get("session") or "").split("/")[0] for entry in written}
    lines += [f"{len(written)} entries from {len(sessions)} sessions; "
              f"{sum(entry['kind'] == 'milestone' for entry in entries)} pull request milestones.", ""]
    if summary:
        lines += ["## Summary", "", "_Written by Sonnet from the entries below; check the cited ids._", "", summary, ""]
    if open_questions:
        lines += ["## Open questions", ""]
        lines += [f"- `{entry['id'][:8]}` {entry['body'].strip()} ({Path(entry['project']).name})" for entry in open_questions[:15]]
        lines.append("")
    lines += ["## Entries", ""]
    for entry in written:
        when = entry["created_at"][:16].replace("T", " ")
        where = Path(entry["project"]).name or entry["project"]
        goal = f", {entry['goal']}" if entry.get("goal") else ""
        goal += f" · form: {entry['form']}" if entry.get("form") else ""
        lines += [f"### {when} UTC · {entry['client']} · {entry['kind']} · {where}{goal} · `{entry['id'][:8]}`", "",
                  entry["body"].strip(), ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("AGENT_JOURNAL_DIR") or journal.DEFAULT_ROOT)
    parser.add_argument("--out", required=True, help="folder for the weekly digest files")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--no-summary", action="store_true", help="skip the model-written summary")
    args = parser.parse_args()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    root = Path(args.root).expanduser().resolve()
    entries, open_questions = load(root, start.isoformat().replace("+00:00", "Z"))
    from adapter import person
    summary = None if args.no_summary else summarize(entries, person())
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    year, week, _ = start.astimezone().isocalendar()
    path = out / f"{year}-W{week:02d}.md"
    path.write_text(render(entries, open_questions, summary, start.astimezone(), end.astimezone()), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    sys.exit(main())
