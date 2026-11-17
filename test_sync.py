import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent


class SyncTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.remote = self.work / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        self.root = self.work / "journal"
        (self.root / "entries").mkdir(parents=True)
        git = ["git", "-C", str(self.root)]
        subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
        # sync.py derives OWNER/REPO from a github.com URL, then asks gh about it.
        subprocess.run([*git, "remote", "add", "origin", "https://github.com/acme/journal.git"], check=True)
        subprocess.run([*git, "config", "url." + str(self.remote) + ".insteadOf", "https://github.com/acme/journal.git"], check=True)
        (self.root / "entries" / ("a" * 32 + ".md")).write_text("an entry")

    def sync(self, visibility):
        gh = self.work / "bin" / "gh"
        gh.parent.mkdir(exist_ok=True)
        gh.write_text(f"#!/bin/sh\necho {visibility}\n")
        gh.chmod(0o700)
        env = dict(os.environ, PATH=f"{gh.parent}{os.pathsep}{os.environ['PATH']}")
        return subprocess.run([sys.executable, str(HERE / "sync.py"), "--root", str(self.root)],
                              env=env, capture_output=True, text=True)

    def remote_log(self):
        return subprocess.run(["git", "-C", str(self.remote), "log", "--oneline", "--all"],
                              capture_output=True, text=True).stdout

    def test_refuses_to_push_unless_github_confirms_private(self):
        result = self.sync("PUBLIC")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to push", result.stderr)
        self.assertEqual(self.remote_log(), "")

    def test_commits_and_pushes_to_a_private_repo(self):
        result = self.sync("PRIVATE")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("add 1 entries", self.remote_log())


if __name__ == "__main__":
    unittest.main()
