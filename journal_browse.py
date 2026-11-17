"""Read-only terminal browser for one snapshot of the journal."""

import curses
from pathlib import Path
import sys
import unicodedata


KINDS = ("all", "reflection", "question", "note", "milestone", "lifecycle", "resolution")
LABELS = {None: "Journal entries", "all": "All kinds"}
UP = (curses.KEY_UP, "k")
DOWN = (curses.KEY_DOWN, "j")
ENTER = ("\n", "\r", curses.KEY_ENTER)


def clean(value, multiline=False):
    value = str(value or "").replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    return "".join(
        char if not unicodedata.category(char).startswith("C") else
        ("\n" if char == "\n" and multiline else " ")
        for char in value
    )


def fit(text, width):
    columns = 0
    for index, char in enumerate(text):
        size = 0 if unicodedata.category(char).startswith("M") else (
            2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        )
        columns += size
        if columns > width:
            return text[:index]
    return text


def fit_right(text, width):
    if fit(text, width) == text:
        return text
    return "…" + fit(text[::-1], max(0, width - 1))[::-1]


def wrap(text, width):
    for line in text.split("\n"):
        while True:
            head = fit(line, width)
            if head == line or not head:
                yield head
                break
            split = head.rfind(" ")
            if split > 0 and head[:split].strip():
                head = head[:split]
            yield head
            line = line[len(head):].lstrip()


def draw(window, y, x, text, width, attribute=curses.A_NORMAL):
    height, columns = window.getmaxyx()
    width = min(width, columns - x - (y == height - 1))
    if 0 <= y < height and width > 0:
        try:
            window.addstr(y, x, fit(text, width), attribute)
        except curses.error:
            # A resize can invalidate coordinates between measurement and paint.
            pass


def kind_label(kind):
    return LABELS.get(kind, clean(kind).capitalize())


def project_label(project):
    if project is None:
        return "All projects"
    home = str(Path.home())
    if project == home or project.startswith(home + "/"):
        return "~" + project[len(home):]
    return project


def filtered(records, project, kind, query):
    needle = query.casefold().strip()
    return [
        record for record in records
        if (project is None or record["project"] == project)
        and (kind == "all" or record["kind"] == kind or (
            kind is None and record["kind"] != "lifecycle"
        ))
        and (not needle or any(needle in str(value).casefold() for value in record.values() if value is not None))
    ]


class Browser:
    def __init__(self, records, project, kind, query):
        self.records = records
        self.project = project
        self.kind = kind
        self.query = clean(query)
        self.projects = [None, *sorted({entry["project"] for entry in records})]
        if project is not None and project not in self.projects:
            self.projects.append(project)
        self.mode = "list"
        self.previous_query = self.query
        self.options = ()
        self.option = 0
        self.selected = 0
        self.top = 0
        self.scroll = 0
        self.update_matches()

    def update_matches(self):
        self.matches = filtered(self.records, self.project, self.kind, self.query)
        self.selected = self.top = self.scroll = 0

    def move(self, direction, page):
        if self.mode in ("project", "kind"):
            self.option = min(max(0, self.option + direction * page), len(self.options) - 1)
        elif self.mode == "preview":
            self.scroll = min(max(0, self.scroll + direction * page), self.preview_max)
        elif self.matches:
            selected = min(max(0, self.selected + direction * page), len(self.matches) - 1)
            if selected != self.selected:
                self.selected = selected
                self.scroll = 0

    def pick(self, mode, values, current):
        self.mode = mode
        self.options = values
        self.option = values.index(current)

    def handle(self, key):
        if self.mode == "search":
            if key in ENTER:
                self.mode = "list"
            elif key == "\x1b":
                self.mode = "list"
                self.query = self.previous_query
                self.update_matches()
            elif key in (curses.KEY_BACKSPACE, "\x08", "\x7f"):
                self.query = self.query[:-1]
                self.update_matches()
            elif isinstance(key, str) and key.isprintable():
                self.query += key
                self.update_matches()
            return True
        if key == "q":
            return False
        if key == "\x1b":
            self.mode = "list"
        elif self.mode in ("project", "kind") and key in ENTER:
            if self.mode == "project":
                self.project = self.options[self.option]
            else:
                self.kind = self.options[self.option]
            self.mode = "list"
            self.update_matches()
        elif key in (*UP, *DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
            direction = -1 if key in (*UP, curses.KEY_PPAGE) else 1
            page = self.page if key in (curses.KEY_PPAGE, curses.KEY_NPAGE) else 1
            self.move(direction, page)
        elif self.mode in ("list", "preview"):
            if key in (*ENTER, "\t") and self.matches:
                self.mode = "preview" if self.mode == "list" else "list"
            elif key == "/":
                self.previous_query = self.query
                self.query = ""
                self.update_matches()
                self.mode = "search"
            elif key == "p":
                self.pick("project", self.projects, self.project)
            elif key == "t":
                self.pick("kind", (None, *KINDS), self.kind)
        return True

    def paint_picker(self, window, width, rows):
        self.page = max(rows - 1, 1)
        label = project_label if self.mode == "project" else kind_label
        draw(window, 2, 0, "Choose a project" if self.mode == "project" else "Choose a kind", width, curses.A_BOLD)
        offset = max(0, self.option - self.page + 1)
        for row, value in enumerate(self.options[offset:offset + self.page], start=3):
            selected = offset + row - 3 == self.option
            text = fit_right(clean(label(value)), width - 2)
            draw(window, row, 0, ("> " if selected else "  ") + text, width,
                 curses.A_REVERSE if selected else curses.A_NORMAL)

    def paint_list(self, window, width, rows):
        self.page = max(rows // 3, 1)
        if not self.matches:
            empty = "No journal entries." if not self.records else "No entries match these filters."
            draw(window, 3, 0, empty, width)
            return
        self.top = min(self.top, self.selected)
        self.top = max(self.top, self.selected - self.page + 1)
        for index, entry in enumerate(self.matches[self.top:self.top + self.page], start=self.top):
            y = 2 + (index - self.top) * 3
            selected = index == self.selected
            active = selected and self.mode == "list"
            marker = "> " if selected else "  "
            stamp = clean(entry["created_at"])[:16].replace("T", " ")
            heading = f"{marker}{stamp}  {clean(entry['client'])}"
            prefix = f"  {kind_label(entry['kind'])}  "
            path = fit_right(clean(project_label(entry["project"])), width - len(prefix))
            detail = prefix + path
            snippet = next((line.strip() for line in clean(entry["body"], multiline=True).split("\n") if line.strip()), "")
            draw(window, y, 0, heading, width, curses.A_REVERSE if active else curses.A_BOLD)
            if rows - (y - 2) >= 2:
                draw(window, y + 1, 0, detail, width, curses.A_DIM)
            if rows - (y - 2) >= 3:
                draw(window, y + 2, 0, f"  {snippet}", width)

    def paint_preview(self, window, x, width, rows):
        self.preview_max = 0
        if not self.matches:
            return
        entry = self.matches[self.selected]
        stamp = clean(entry["created_at"])[:16].replace("T", " ")
        title = f"{kind_label(entry['kind'])} · {clean(entry['client'])} · {stamp} UTC"
        draw(window, 2, x, title, width, curses.A_BOLD | (
            curses.A_REVERSE if self.mode == "preview" else curses.A_NORMAL
        ))
        details = [
            clean(project_label(entry["project"])),
            "ID " + clean(entry["id"]),
        ]
        if entry.get("goal"):
            details.append("Goal " + clean(entry["goal"]))
        lines = list(wrap("\n".join(details) + "\n\n" + clean(entry["body"], multiline=True), width))
        page = max(rows - 1, 1)
        if self.mode == "preview":
            self.page = page
        self.preview_max = max(len(lines) - page, 0)
        self.scroll = min(self.scroll, self.preview_max)
        for row, line in enumerate(lines[self.scroll:self.scroll + page], start=3):
            draw(window, row, x, line, width)

    def paint(self, window):
        height, width = window.getmaxyx()
        window.erase()
        self.page, self.preview_max = 1, 0
        heading = f"Agent Journal  {len(self.matches)}/{len(self.records)}"
        if len(heading) + len(" entries") <= width:
            heading += " entries"
        draw(window, 0, 0, heading, width, curses.A_BOLD)
        if height < 7 or width < 20:
            draw(window, 1, 0, "Resize to browse. q Quit", width)
            return
        project = fit_right(clean(project_label(self.project)), width // 2)
        scope = f"{project}  ·  {kind_label(self.kind)}"
        if self.query and self.mode != "search":
            scope += "  ·  /" + self.query
        draw(window, 1, 0, scope, width, curses.A_DIM)
        if self.mode == "search":
            tail = fit(self.query[::-1], width - 10)[::-1]
            hints = ["Enter Apply   Esc Cancel", f"Search / {tail}"]
        elif self.mode in ("project", "kind"):
            hints = list(wrap("↑↓/j k Move   Enter Choose   Esc Back   q Quit", width - 1))
        else:
            hints = list(wrap("↑↓/j k Move   PgUp/PgDn Page   Enter/Tab Preview/list   / Search   p Project   t Kind   Esc Back   q Quit", width - 1))
        if len(hints) > height - 5:
            hints = ["↑↓ Enter   / p t q"]
        rows = height - 2 - len(hints)
        if self.mode in ("project", "kind"):
            self.paint_picker(window, width, rows)
        elif width >= 88:
            divider = max(30, width // 3)
            self.paint_list(window, divider, rows)
            for row in range(2, 2 + rows):
                draw(window, row, divider, "│", 1, curses.A_DIM)
            self.paint_preview(window, divider + 2, width - divider - 2, rows)
        elif self.mode == "preview":
            self.paint_preview(window, 0, width, rows)
        else:
            self.paint_list(window, width, rows)
        for y, hint in enumerate(hints, start=height - len(hints)):
            draw(window, y, 0, hint, width, curses.A_DIM)

    def run(self, window):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        curses.set_escdelay(100)
        while True:
            self.paint(window)
            window.refresh()
            if not self.handle(window.get_wch()):
                return


def browse(records, *, project=None, kind=None, query=""):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("browse needs an interactive terminal")
    try:
        curses.wrapper(Browser(records, project, kind, query).run)
    except KeyboardInterrupt:
        return
    except curses.error as error:
        raise ValueError("could not open the terminal browser; check TERM") from error
