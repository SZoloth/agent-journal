from base64 import b64decode
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import backup


class BackupTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "journal" / "entries"
        self.work = self.root / "local"
        self.cloud = self.root / "icloud" / "Backups" / "Journal"
        self.cloud.parent.parent.mkdir()
        locations = patch.multiple(backup, SOURCE=self.source, WORK=self.work, ICLOUD=self.cloud)
        locations.start()
        self.addCleanup(locations.stop)

    def add_note(self):
        journal = Path(backup.__file__).with_name("journal.py").resolve()
        subprocess.run(
            [sys.executable, str(journal), "--root", str(self.source.parent),
             "add", "--client", "test", "--project", str(self.root)],
            input=b"A synthetic backup note\n", capture_output=True, check=True, timeout=10,
        )

    def run_backup(self):
        with patch.dict(os.environ, {backup.SECRET: "temporary-test-passphrase"}):
            return backup.run_backup()

    @unittest.skipUnless(Path("/usr/bin/hdiutil").exists(), "macOS disk images are required")
    def test_real_encrypted_archive_reuses_ciphertext_after_pending_upload(self):
        self.add_note()
        with patch.object(backup, "verify_github") as github, patch.object(
            backup, "icloud_uploaded", side_effect=(False, True),
        ):
            first = self.run_backup()
            self.assertEqual(first["state"], "pending", first)
            second = self.run_backup()
            self.assertEqual(second["state"], "success", second)
        self.assertEqual(first["entries"], 1)
        self.assertEqual(first["ciphertext_sha256"], second["ciphertext_sha256"])
        local, = self.work.glob("journal-*.dmg")
        copy = self.cloud / local.name
        self.assertEqual(local.read_bytes(), copy.read_bytes())
        self.assertEqual(github.call_count, 2)
        self.assertEqual(github.call_args.args, (local, second["ciphertext_sha256"]))
        self.assertEqual(list(self.work.glob(".scratch-*")), [])
        self.assertTrue(backup.status()[1])

    def test_refuses_redirected_icloud_ancestor(self):
        redirect = self.root / "unapproved"
        redirect.mkdir()
        self.cloud.parent.symlink_to(redirect, target_is_directory=True)
        with self.assertRaisesRegex(backup.BackupError, "invalid_icloud_directory"):
            backup.stage_icloud(self.root / "journal-fixture.dmg", "")
        self.assertEqual(list(redirect.iterdir()), [])

    def test_github_only_uploads_missing_ciphertext_and_checks_private_repo(self):
        archive = self.root / "journal-fixture.dmg"
        archive.write_bytes(b"mock encrypted bytes")
        expected = backup.hash_file(archive)
        repo_response = {"full_name": backup.REPO, "visibility": "private"}
        uploads = []

        def github(*args, data=None, **kwargs):
            if args[0] == f"repos/{backup.REPO}":
                return subprocess.CompletedProcess(args, 0, json.dumps(repo_response).encode(), b"")
            if args[:2] == ("--method", "PUT"):
                uploads.append(b64decode(json.loads(data)["content"]))
                return subprocess.CompletedProcess(args, 0, b"", b"")
            self.assertEqual(args[:2], ("-H", "Accept: application/vnd.github.raw"))
            if uploads:
                return subprocess.CompletedProcess(args, 0, uploads[-1], b"")
            return subprocess.CompletedProcess(args, 1, b"", b"gh: Not Found (HTTP 404)")

        with patch.object(backup, "github_api", side_effect=github):
            backup.verify_github(archive, expected)
            backup.verify_github(archive, expected)
            self.assertEqual(uploads, [b"mock encrypted bytes"])
            repo_response["visibility"] = "public"
            with self.assertRaisesRegex(backup.BackupError, "github_repo_not_private"):
                backup.verify_github(archive, expected)
        self.assertEqual(len(uploads), 1)

    def test_empty_store_and_stale_receipt_fail_status(self):
        self.assertEqual(backup.status(), ({"state": "missing"}, False))
        self.source.mkdir(parents=True)
        receipt = self.run_backup()
        self.assertEqual(receipt["error"], "journal_has_no_entries")
        self.assertFalse(backup.status()[1])
        backup.write_receipt({
            "state": "success",
            "last_success_at": (backup.now() - timedelta(hours=40)).isoformat(),
        })
        expired, success = backup.status()
        self.assertFalse(success)
        self.assertEqual(expired["state"], "stale")


if __name__ == "__main__":
    unittest.main()
