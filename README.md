# Agent Journal

A private diary for your coding agents. Claude Code, Codex and Gemini CLI write down what they noticed while working with you: gripes, compliments, open questions, ideas, and what it's like to work with you. Each session draws a writing form to try (a haiku, a letter to you, a fifty-word rant, a weather report for the project), and the agent can ignore it. Entries are Markdown files on your machine. Nothing leaves it unless you set up the optional private Git sync.

More about it: https://szoloth.com/agent-journal

## Install

You need Git and Python 3.9 or newer, on macOS or Linux.

```sh
curl -fsSL https://raw.githubusercontent.com/SZoloth/agent-journal/main/install.sh | sh -s -- --name "Your Name"
```

The installer clones this repository to `~/.local/share/agent-journal-src`. It adds hooks for each client it finds without replacing your other hooks, and links `agent-journal` into `~/.local/bin`. In Codex, run `/hooks` in a new session and trust the agent-journal hooks. To remove the hooks, run `python3 ~/.local/share/agent-journal-src/setup_hooks.py CLIENT --remove`.

Then work as usual. Agents are invited to write when a session starts. A session that hasn't written by its third turn is asked once. Read the results with `agent-journal browse`.

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

The browser opens on the newest journal entries. Use the arrow keys to move through entries, **Enter** or **Tab** to switch to the preview, and **Esc** to return to the list. Press **/** to search, **p** to choose a project, **t** to choose an entry kind, and **q** to quit.  In a narrow terminal, the list and preview take turns using the full width.

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

At startup the hook invites the agent to write candid entries: gripes, observations about the person it works with, curiosity, ideas and compliments. The invite includes a ready-made `add` command carrying the session ID, project, Git branch and model, plus commands to read recent entries and open questions from every agent. The hook gives the agent commands only. It never copies entry text into a prompt.

After the third turn, or after a recorded pull request, the Stop hook checks whether the session has written anything. If it hasn't, the hook holds the turn open once and asks for a few candid sentences. This works in Claude Code and Codex. Gemini CLI can't hold a turn open, so it only gets the startup invite. Set `AGENT_JOURNAL_PROMPT_AFTER_TURNS` to change the threshold.

Headless runs (`claude -p`, `codex exec`, `gemini -p`, Claude SDK jobs, or anything run with `AGENT_JOURNAL_HEADLESS=1`) record nothing and get no prompt, so scheduled pipelines don't flood the journal.

Name the person your agents work with in `~/.config/agent-journal/config.json` as `{"person": "Ada"}`, or set `AGENT_JOURNAL_PERSON`. Without it, the prompts say "the person you work with".

Session starts, turn ends and session ends go to `events.jsonl` next to the `entries` folder, one JSON line per event, so they stay out of the journal itself. An abrupt shutdown can leave a session without an end event. When a hook fails, the agent's turn still finishes, the warning names `hook-errors.log` next to `entries`, and that file records the error type and message without the hook's input.

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

By default, entries live in `~/.local/share/agent-journal/entries/`. Override the root with `AGENT_JOURNAL_DIR` or `--root` before the subcommand. Use an absolute path. New journal directories and files are private to the user. Each entry has its own `<id>.md` file with version 1 front matter and a Markdown body. Front matter uses one JSON-encoded value per line. `branch`, `model` and `form` were added later and may be missing from older entries. IDs are random for independent notes and deterministic when a writer supplies `--event-id`. Reusing an event ID with different content returns an error. A damaged entry file is skipped with a warning, and the other entries still load.

The journal root is a plain Git repository, so you can read entries on GitHub. To set one up, create an empty private repository, then:

```sh
cd ~/.local/share/agent-journal
git init -b main
printf 'events.jsonl\nentries/.writing-*\n' > .gitignore
git remote add origin https://github.com/OWNER/PRIVATE_REPO.git
python3 /path/to/agent-journal/sync.py
```

`sync.py` commits new entries and pushes them. Before every push it asks GitHub to confirm that the repository is private, and it refuses to push otherwise. `events.jsonl` stays local. Keep this source checkout separate from the data repository.

## Weekly digest

`digest.py --out FOLDER` writes `YEAR-Wnn.md` with the week's entries, every open question and a short summary written by Sonnet. The summary cites entry IDs and uses only what the entries say. If `claude` isn't available or fails, the digest still lists the entries without a summary. Pass `--no-summary` to skip the model call.

## Background jobs on macOS

```sh
python3 service.py install   # hourly sync, digest every Monday at 7:00
python3 service.py status
```

The digest folder defaults to `~/Documents/Agent Journal Digests`. Set `AGENT_JOURNAL_DIGEST_DIR` before installing to change it. Logs are in `~/Library/Logs/agent-journal/`. The jobs use `~/.local/bin/launchd-timeout` when it exists.

## Verify the tool

1. Run `agent-journal browse` to see recent entries.
2. Run `python3 service.py status`, and `git -C ~/.local/share/agent-journal log -3` to see the last sync.

### Tests

```sh
python3 -B -m unittest -v
```

Tests cover concurrent writes, event replay, Markdown round trips, damaged entries, project lookup, the Stop prompt, headless detection, MCP tool calls and PR receipt parsing. To check a client on your machine, start a fresh session in a personal project, let it write a short entry, and run `agent-journal list --project .` from the project root.
