import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).with_name("journal.py").resolve()


class JournalTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name).resolve()
        self.root = self.work / "private" / "journal"
        self.project = self.work / "sample project"
        self.project.mkdir()

    def command(self, *args, body="", check=True, cwd=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            input=body.encode("utf-8"),
            capture_output=True,
            cwd=cwd or self.project,
            check=check,
            timeout=15,
        )

    def add(self, *args, body="An observation"):
        return self.command("add", "--client", "codex", *args, body=body).stdout.decode().strip()

    def records(self, *args):
        return [json.loads(line) for line in self.command(*args).stdout.splitlines()]

    def test_browse_requires_a_terminal(self):
        result = self.command("browse", "--kind", "all", "--project", ".", "--search", "test", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"browse needs an interactive terminal", result.stderr)
        self.assertEqual(result.stdout, b"")

    def test_markdown_preserves_body_and_private_permissions(self):
        body = "A complaint with café\r\n\r\n---\n\nNo trailing newline"
        entry = self.add("--goal", 'Review: "launch"\nDecide', body=body)
        record, = self.records("list")
        self.assertEqual(record["id"], entry)
        self.assertEqual(record["body"], body)
        self.assertEqual(record["goal"], 'Review: "launch"\nDecide')
        self.assertRegex(record["created_at"], r"^\d{4}-\d\d-\d\dT.*Z$")
        self.assertEqual(record["schema_version"], 1)
        raw = self.command("show", entry).stdout
        self.assertTrue(raw.startswith(b"---\n"))
        self.assertTrue(raw.endswith(b"---\n" + body.encode()))
        relative_file = self.root / "entries" / f"{entry}.md"
        for path in (self.root.parent, self.root, relative_file.parent):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(relative_file.stat().st_mode), 0o600)
        self.assertNotEqual(self.command("show", "../../private", check=False).returncode, 0)

    def test_concurrent_writes_and_event_replays(self):
        def write(number):
            return self.add("--session", "abc", body=f"Observation {number}")

        def milestone(_):
            return self.add("--kind", "milestone", "--event-id", "example/repo#7:open", body="PR opened")

        with ThreadPoolExecutor(max_workers=6) as pool:
            entries = list(pool.map(write, range(12)))
            milestone_ids = set(pool.map(milestone, range(6)))
        self.assertEqual(len(set(entries)), 12)
        self.assertEqual(len(milestone_ids), 1)
        self.assertEqual(
            {record["body"] for record in self.records("list", "--session", "abc")},
            {f"Observation {number}" for number in range(12)},
        )
        result = self.command(
            "add", "--client", "codex", "--kind", "milestone",
            "--event-id", "example/repo#7:open", body="A contradictory replay", check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        milestone_record, = self.records("list", "--kind", "milestone")
        self.assertEqual(milestone_record["body"], "PR opened")

    def test_questions_resolve_without_rewriting_history(self):
        first = self.add("--kind", "question", body="Will resume pick this up?")
        second = self.add("--kind", "question", body="Can another agent answer this?")
        other_dir = self.work / "other"
        other_dir.mkdir()
        self.add("--project", str(other_dir), "--kind", "question", body="Other project")
        self.assertEqual(
            [record["id"] for record in self.records("questions", "--project", ".", "--limit", "1")],
            [second],
        )
        original = self.command("show", second).stdout
        resolution = self.command("resolve", second).stdout
        self.assertEqual(self.command("resolve", second).stdout, resolution)
        self.assertEqual(self.command("show", second).stdout, original)
        question, = self.records("questions", "--project", ".")
        self.assertEqual(question["id"], first)
        closed, = self.records("list", "--kind", "resolution")
        self.assertEqual(closed["relates_to"], second)
        self.assertNotEqual(self.command("resolve", closed["id"], check=False).returncode, 0)

    def test_project_filter_accepts_git_subdirectories(self):
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        folder = self.project / "subdir"
        folder.mkdir()
        entry = self.command("add", "--client", "claude", cwd=folder, body="A note").stdout.decode().strip()
        record, = self.records("list", "--project", ".")
        self.assertEqual(record["id"], entry)
        self.assertEqual(record["project"], str(self.project))
        env = {**os.environ, "AGENT_JOURNAL_DIR": str(self.root)}
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "list"], env=env, capture_output=True, check=True, timeout=15,
        )
        self.assertEqual(json.loads(result.stdout)["id"], entry)

    def test_relative_storage_root_cannot_write_into_session_directory(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", "relative", "add", "--client", "claude"],
            cwd=self.project,
            input=b"A private note",
            capture_output=True,
            timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.project / "relative").exists())

    def test_malformed_entry_reports_clean_error(self):
        entry = self.add()
        path = self.root / "entries" / f"{entry}.md"
        raw = path.read_text()
        path.write_text(raw.replace('relates_to: null\n', ''))
        result = self.command("list", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"invalid journal entry", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
