# Agent Journal

A local Markdown journal for agents to record what they noticed, questioned, liked, or found frustrating while working. An entry can describe a collaboration, a codebase, an observation that changed the work, or an idea worth bringing back later.

## Use it

Run `journal.py` with Python 3.9 or newer on macOS or Linux. To use `agent-journal` below, put a symlink to `journal.py` in a directory on your PATH.

```sh
agent-journal add --client codex --session example-thread --kind question --goal 'Review the installer' <<'MARKDOWN'
Can we detect that the CLI moved before the next hook runs?
MARKDOWN

agent-journal questions --project . --limit 3
agent-journal list --project . --kind reflection
agent-journal show ENTRY_ID
agent-journal resolve ENTRY_ID
```

Use `--kind note` for short observations, praise, complaints, or ideas. Use `--kind question` for an open question. `add` prints the entry ID. `list` and `questions` print one JSON record per line, newest first. `resolve` writes a linked entry and keeps the original question. `--project` defaults to the current directory on writes. The CLI uses the Git checkout root when available, so a script run from a subdirectory and a session resumed at the root can find the same entries. Different worktrees have different project paths. Supply an explicit project path to share a journal across them.

## Browse the journal in Terminal

```sh
agent-journal browse
agent-journal browse --project . --kind all --search "review"
```

The browser opens on the newest journal entries. Use the arrow keys to move through entries, **Enter** or **Tab** to switch to the preview, and **Esc** to return to the list. Press **/** to search, **p** to choose a project, **t** to choose an entry kind, and **q** to quit. Select **All kinds** to include lifecycle events. In a narrow terminal, the list and preview take turns using the full width.

The browser reads your existing Markdown files when it opens. Reopen it to see entries written during that visit. Use `list` or `show` from scripts and pipes.

## Connect a client

Keep this checkout in a stable location. Install the hooks for the clients you use.

```sh
python3 setup_hooks.py claude
python3 setup_hooks.py codex
python3 setup_hooks.py gemini
python3 setup_hooks.py claude-desktop
```

Open `/hooks` in a new Codex CLI session and review the definitions whose command ends in `adapter.py hook codex`. Codex runs those definitions once you trust them. If a sandbox asks for a writable location, allow the journal directory for that session. Restart clients after changing hooks. Run the same setup command with `--remove` to remove its hook groups. Use `--settings PATH` to target a different JSON settings file. If you move the checkout, remove the hooks before moving it and reinstall afterward.

Startup gives the agent a note command with the current session ID and project. Agents can jot things down as they come up and run the same command for every new note. They can mark an open question or add a short work goal when it helps. On resume, the agent can query the latest three open questions from the same project. The hook only supplies the command and never copies question text into a system prompt.

Lifecycle entries record events the client reports for a session or subagent. Repeated events of the same type and source share one record. A `Stop` entry means a turn stopped. A `SessionEnd` entry means the client sent its end event. Notes appear when the agent writes them. An abrupt shutdown can leave a session without an end event.

The shell hook captures direct `gh pr create` commands that print a PR URL and direct `gh pr merge` commands that pass the URL as an argument. It reads the current state with `gh pr view`. For compound shell commands, deferred auto-merges, GitHub MCP actions, and work done outside the agent, call the recorder explicitly. Repeating the same state in the same session returns the same entry ID.

```sh
python3 adapter.py pr --client claude --session SESSION_ID --project . \
  https://github.com/OWNER/REPO/pull/123
```

Restart Claude Desktop after setup and look for the `journal_add` tool. It accepts a Markdown body and an absolute project directory. The stdio server exposes writing by default. For a client you manage, launch `python3 /absolute/path/to/journal_mcp.py --allow-read` if you also want `journal_questions`.

```sh
grok mcp add --scope user --transport stdio agent-journal "$(command -v python3)" "$PWD/journal_mcp.py"
agy mcp add --type stdio agent-journal "$(command -v python3)" "$PWD/journal_mcp.py"
codex mcp add agent-journal -- "$(command -v python3)" "$PWD/journal_mcp.py"
```

Grok Build, Antigravity, and local Codex clients use stdio. In Antigravity, approve the individual local tool call when prompted. Grok Bot's custom connector form requires a server URL. To keep the journal local, ask the Bot to call the CLI through its per-command local execution flow. Other clients with shell access can run the CLI directly. Supply a session ID when the client has one.

## Storage and private GitHub sync

By default, entries live in `~/.local/share/agent-journal/entries/`. Override the root with `AGENT_JOURNAL_DIR` or `--root` before the subcommand. Use an absolute path. New journal directories and files are private to the user. Each entry has its own `<id>.md` file with version 1 front matter and a Markdown body. Front matter uses one JSON-encoded value per line. IDs are random for independent notes and deterministic when a writer supplies `--event-id`. Reusing an event ID with different content returns an error.

Set up a private GitHub repository and authenticate `gh` before exporting. Prepare a local review copy and give it the entry ID as a filename. The review copy contains the note body alone. Review and redact it before publishing it. Git retains past versions.

```sh
python3 sync.py prepare ENTRY_ID /absolute/review/path/ENTRY_ID.md
python3 sync.py publish OWNER/PRIVATE_REPO /absolute/review/path/ENTRY_ID.md
```

`publish` verifies the exact repository is private, sends the named file, and reads back the bytes. A retry with the same bytes returns the same link. A different file at that entry ID returns an error. The exporter omits lifecycle entries, PR milestones, and metadata such as project and session IDs. Keep the source checkout separate from the data repository.

## Verify the tool

### Daily macOS backup

On the configured Mac, launchd runs an encrypted backup at login and at 3:15 a.m. local time while your user session is active. If the Mac sleeps through the scheduled time, launchd runs the job on wake. The backup uses the journal in `~/.local/share/agent-journal/entries` and the recovery passphrase in Keychain. It keeps copies in iCloud Drive under `Backups/Agent Journal` and in the private GitHub backup repository. The reviewed export commands above serve a separate purpose.

1. Run `agent-journal browse` to see recent written entries. Lifecycle events in the kind filter indicate that a hook fired.
2. Run `python3 backup_service.py status` from this checkout, or `agent-journal-backup status` if the launcher is on your PATH. Check the last attempt, last successful run, entry count, and each destination's status. Open `~/Backups/Agent Journal/backup-error.log` if the job reports an error.
3. Run `python3 backup_service.py install` to reinstall the daily job. It expects a signed-in macOS user, configured iCloud Drive and GitHub CLI access, the existing `with-secret` and `launchd-timeout` helpers, and the recovery passphrase under `AGENT_JOURNAL_BACKUP_PASSPHRASE` in Keychain. On a replacement Mac, retrieve the passphrase from the 1Password item **Agent Journal Backup Recovery Passphrase** and enter it at the hidden prompt from `with-secret --add AGENT_JOURNAL_BACKUP_PASSPHRASE`.
4. Run `python3 backup_service.py run` to request a backup immediately. Recheck status after the run completes.

To restore, download an encrypted disk image from either destination and open it with the 1Password passphrase. Copy the mounted image's `entries` folder into a separate restore directory. For the original manual snapshot, extract the tar archive inside its image instead. Use `agent-journal --root /absolute/path/to/restored-folder list` to inspect the entries before moving any files into your active journal.

### Tests

```sh
python3 -B -m unittest -v
```

Tests cover concurrent writes, event replay, Markdown round trips, project lookup, MCP tool calls, PR receipt parsing, and private export checks. To check a client on your machine, start a fresh session in a personal project, let it write a short entry, and run `agent-journal list --project .` from the project root.
