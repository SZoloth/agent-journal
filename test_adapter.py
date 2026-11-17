import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        self.env = dict(os.environ, AGENT_JOURNAL_DIR=str(self.cwd / "data"))

    def run_script(self, script, *args, payload=None, check=True):
        return subprocess.run(
            [sys.executable, str(HERE / script), *args], cwd=self.cwd, env=self.env,
            input=json.dumps(payload) if payload is not None else "", text=True,
            capture_output=True, check=check,
        )

    def entries(self, kind):
        return [json.loads(line) for line in self.run_script("journal.py", "list", "--kind", kind).stdout.splitlines()]

    def test_startup_offers_a_repeatable_freeform_note_command(self):
        payload = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "thread-1",
                   "cwd": str(self.cwd)}
        reply = self.run_script("adapter.py", "hook", "codex", payload=payload)
        context = json.loads(reply.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("--kind reflection", context)
        line = next(line for line in context.splitlines() if "journal.py add " in line)
        bodies = ["This alias is confusing.", "Idea: surface the project name."]
        for body in bodies:
            subprocess.run(shlex.split(line), input=body, text=True, check=True, capture_output=True, env=self.env)
        self.assertEqual({note["body"] for note in self.entries("note")}, set(bodies))

    def test_hooks_record_lifecycle_and_offer_scoped_commands(self):
        for client in ("codex", "claude"):
            payload = {
                "hook_event_name": "SessionStart", "source": "startup", "session_id": "thread-1",
                "cwd": str(self.cwd), "transcript_path": "PRIVATE_TRANSCRIPT", "prompt": "PRIVATE_PROMPT",
            }
            result = self.run_script("adapter.py", "hook", client, payload=payload)
            context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn(f"--client {client} --session thread-1", context)
            self.assertIn("questions --project", context)
            self.assertNotIn("PRIVATE_", context)
            for _ in range(2):
                result = self.run_script("adapter.py", "hook", client, payload={**payload, "hook_event_name": "Stop", "source": None})
                self.assertEqual(json.loads(result.stdout), {})
        entries = self.entries("lifecycle")
        self.assertEqual(len(entries), 4)
        self.assertNotIn("PRIVATE_", json.dumps(entries))

    def test_settings_install_replay_and_uninstall_preserve_other_hooks(self):
        path = self.cwd / "settings.json"
        original = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}, "env": {"EXAMPLE": "value"}}
        path.write_text(json.dumps(original))
        args = ("setup_hooks.py", "claude", "--settings", str(path))
        self.run_script(*args)
        installed = path.read_bytes()
        self.run_script(*args)
        self.assertEqual(path.read_bytes(), installed)
        self.assertEqual(len(json.loads(installed)["hooks"]["Stop"]), 2)
        self.run_script(*args, "--remove")
        self.assertEqual(json.loads(path.read_bytes()), original)

    def test_pr_records_verified_state_and_never_records_failed_lookup(self):
        url = "https://github.com/acme/example/pull/42"
        gh = self.cwd / "gh"
        gh.write_text("#!/bin/sh\n" + f"test \"$3\" = '{url}' || exit 1\n" +
                      f"printf '%s\\n' '{json.dumps({'url': url, 'state': 'OPEN'})}'\n")
        gh.chmod(0o700)
        self.env["PATH"] = str(self.cwd) + os.pathsep + self.env["PATH"]
        args = ("adapter.py", "pr", "--client", "codex", "--session", "thread-1")
        first = self.run_script(*args, url).stdout
        self.assertEqual(self.run_script(*args, url).stdout, first)
        self.assertEqual(self.run_script(*args, url[:-2] + "99", check=False).returncode, 1)
        entries = self.entries("milestone")
        self.assertEqual(len(entries), 1)
        self.assertIn(url, entries[0]["body"])

    def test_post_tool_hook_records_real_pr_receipts_once(self):
        url = "https://github.com/acme/example/pull/42"
        gh = self.cwd / "gh"
        gh.write_text("#!/bin/sh\n" + f"test \"$3\" = '{url}' || exit 1\n" +
                      f"printf '%s\\n' '{json.dumps({'url': url, 'state': 'MERGED'})}'\n")
        gh.chmod(0o700)
        self.env["PATH"] = str(self.cwd) + os.pathsep + self.env["PATH"]
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "test",
                   "cwd": str(self.cwd), "tool_input": {"command": f"gh pr merge '{url}' --squash"},
                   "tool_response": "Process exited with code 0\nOutput:\n"}
        for wrong in (
            {**payload, "tool_response": "Process exited with code 1\nOutput:\n"},
            {**payload, "tool_input": {"command": f"gh pr merge '{url}' && echo done"}},
            {**payload, "tool_input": {"command": f"gh pr merge '{url}' --help"}},
            {**payload, "tool_name": "Read"},
        ):
            self.run_script("adapter.py", "hook", "codex", payload=wrong)
        self.assertEqual(self.entries("milestone"), [])
        for _ in range(2):
            result = self.run_script("adapter.py", "hook", "codex", payload=payload)
            self.assertEqual(json.loads(result.stdout), {})
        entry, = self.entries("milestone")
        self.assertIn("pull request merged", entry["body"])


if __name__ == "__main__":
    unittest.main()
