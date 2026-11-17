import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import sync


class SyncTest(unittest.TestCase):
    def test_preparation_drops_metadata_and_refuses_to_replace_review(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"AGENT_JOURNAL_DIR": directory}):
            script = Path(sync.__file__).with_name("journal.py")
            entry = subprocess.check_output([sys.executable, str(script), "add", "--client", "PRIVATE_CLIENT",
                                             "--goal", "PRIVATE_GOAL"], input="A Markdown note\n", text=True).strip()
            copy = Path(directory) / f"{entry}.md"
            with patch("builtins.print"):
                sync.prepare(entry, copy)
            self.assertEqual(copy.read_text(), "A Markdown note\n")
            with self.assertRaises(FileExistsError):
                sync.prepare(entry, copy)

    def test_private_target_and_readback_gate(self):
        repo = "owner/review"
        with tempfile.TemporaryDirectory() as directory, patch("builtins.print"):
            path = Path(directory) / ("b" * 32 + ".md")
            body = b"Reviewed Markdown.\n"
            path.write_bytes(body)
            public = {"visibility": "public", "full_name": repo}
            private = {**public, "visibility": "private"}
            content = {"encoding": "base64", "content": base64.b64encode(body).decode(), "html_url": "test"}
            with patch("sync.gh_api", return_value=public) as api:
                with self.assertRaisesRegex(ValueError, "private"):
                    sync.publish(repo, path)
                api.assert_called_once_with("repos/owner/review")
            with patch("sync.gh_api", side_effect=[private, None, {}, content]) as api:
                sync.publish(repo, path)
                self.assertEqual(api.call_args_list[2].kwargs["payload"]["content"], content["content"])
            with patch("sync.gh_api", side_effect=[private, content]) as api:
                sync.publish(repo, path)
                self.assertEqual(api.call_count, 2)
            with patch("sync.gh_api", side_effect=[private, {**content, "content": "eA=="}]) as api:
                with self.assertRaisesRegex(ValueError, "different content"):
                    sync.publish(repo, path)
                self.assertEqual(api.call_count, 2)


if __name__ == "__main__":
    unittest.main()
