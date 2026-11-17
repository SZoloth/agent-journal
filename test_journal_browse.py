import unittest

from journal_browse import Browser


class Terminal:
    def getmaxyx(self):
        return 20, 62

    def erase(self):
        self.lines = []

    def addstr(self, y, x, text, attribute):
        self.lines.append(text)


class JournalBrowserTest(unittest.TestCase):
    def test_latest_note_is_visible_without_choosing_a_kind(self):
        metadata = {"project": "/project", "client": "codex", "created_at": "2026-11-17T22:00Z"}
        records = [
            {**metadata, "id": "event-id", "kind": "lifecycle", "body": "SessionStart"},
            {**metadata, "id": "note-id", "kind": "note", "body": "Tiny idea"},
        ]
        terminal = Terminal()
        browser = Browser(records, None, None, "")
        browser.handle("\n")
        browser.paint(terminal)
        self.assertIn("Tiny idea", terminal.lines)
        self.assertNotIn("SessionStart", terminal.lines)

    def test_narrow_project_picker_keeps_distinct_project_names_visible(self):
        parent = "/private/" + "shared-folder/" * 6
        records = [
            {"id": "alpha-id", "project": parent + "alpha", "kind": "reflection",
             "client": "codex", "created_at": "2026-11-17T22:00Z", "body": "Alpha observation"},
            {"id": "beta-id", "project": parent + "beta", "kind": "question",
             "client": "claude", "created_at": "2026-11-17T21:00Z", "body": "Beta question"},
        ]
        terminal = Terminal()
        browser = Browser(records, None, None, "")
        browser.handle("p")
        browser.paint(terminal)
        self.assertTrue(any("alpha" in line for line in terminal.lines))
        self.assertTrue(any("beta" in line for line in terminal.lines))

        for key in ("j", "\n", "\n"):
            browser.handle(key)
        browser.paint(terminal)
        self.assertIn("Alpha observation", terminal.lines)
        self.assertNotIn("Beta question", terminal.lines)
