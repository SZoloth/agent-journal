import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SERVER = Path(__file__).with_name("journal_mcp.py").resolve()


def request(request_id, method, params=None):
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


class JournalMCPTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name).resolve()
        self.root = self.workspace / "data"
        self.project = self.workspace / "a project"
        self.project.mkdir()
        self.other_project = self.workspace / "unrelated"
        self.other_project.mkdir()

    def exchange(self, *messages, allow_read=False, version="2024-11-05"):
        initialize = request(1, "initialize", {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        })
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        frames = [
            message if isinstance(message, bytes) else json.dumps(message, ensure_ascii=False).encode()
            for message in (initialize, initialized, *messages)
        ]
        command = [sys.executable, str(SERVER)]
        if allow_read:
            command.append("--allow-read")
        result = subprocess.run(
            command,
            input=b"\n".join(frames) + b"\n",
            capture_output=True,
            env={**os.environ, "AGENT_JOURNAL_DIR": str(self.root)},
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(
            responses[0]["result"]["protocolVersion"],
            version if version != "unsupported" else "2025-11-25",
        )
        return responses[1:]

    def test_write_only_server_persists_unicode_markdown(self):
        body = "Would **café** work?\n\nA second paragraph."
        listed, saved, denied, pong = self.exchange(
            request(2, "tools/list"),
            request(3, "tools/call", {"name": "journal_add", "arguments": {
                "project": str(self.project),
                "body": body,
                "kind": "question",
                "session": "desktop-1",
                "goal": "review text",
            }}),
            request(4, "tools/call", {"name": "journal_questions", "arguments": {
                "project": str(self.project),
            }}),
            request(5, "ping"),
        )
        self.assertEqual([tool["name"] for tool in listed["result"]["tools"]], ["journal_add"])
        entry = json.loads(saved["result"]["content"][0]["text"])["id"]
        stored = (self.root / "entries" / f"{entry}.md").read_text()
        self.assertTrue(stored.endswith(body))
        self.assertIn('client: "mcp"\n', stored)
        self.assertIn('session: "desktop-1"\n', stored)
        self.assertIn('goal: "review text"\n', stored)
        self.assertEqual(denied["error"]["code"], -32602)
        self.assertEqual(pong["result"], {})

    def test_reads_are_explicit_project_scoped_and_limited(self):
        _, _, listed, questions = self.exchange(
            request(2, "tools/call", {"name": "journal_add", "arguments": {
                "project": str(self.project), "kind": "question", "body": "What did we decide?",
            }}),
            request(3, "tools/call", {"name": "journal_add", "arguments": {
                "project": str(self.other_project), "kind": "question", "body": "Private other project",
            }}),
            request(4, "tools/list"),
            request(5, "tools/call", {"name": "journal_questions", "arguments": {
                "project": str(self.project), "limit": 1,
            }}),
            allow_read=True,
            version="2025-06-18",
        )
        self.assertEqual([tool["name"] for tool in listed["result"]["tools"]], [
            "journal_add", "journal_questions",
        ])
        result = json.loads(questions["result"]["content"][0]["text"])
        self.assertEqual([entry["body"] for entry in result["questions"]], ["What did we decide?"])

    def test_request_errors_do_not_write_or_end_the_server(self):
        malformed, invalid, unknown, extra, relative, ping = self.exchange(
            b"\xFF", {},
            request(2, "unknown"),
            request(3, "tools/call", {"name": "journal_add", "arguments": {
                "project": str(self.project), "body": "A note", "root": "/tmp",
            }}),
            request(4, "tools/call", {"name": "journal_add", "arguments": {
                "project": ".", "body": "A note",
            }}),
            request(5, "ping"),
            version="unsupported",
        )
        self.assertEqual([response["error"]["code"] for response in (malformed, invalid, unknown)], [
            -32700, -32600, -32601,
        ])
        for response in (extra, relative):
            self.assertTrue(response["result"]["isError"])
        self.assertEqual(ping["result"], {})
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
