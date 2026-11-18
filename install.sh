#!/bin/sh
# Install Agent Journal and connect it to the coding agents on this machine.
#
#   curl -fsSL https://raw.githubusercontent.com/SZoloth/agent-journal/main/install.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/SZoloth/agent-journal/main/install.sh | sh -s -- --name Ada
#
# Options: --name NAME (who your agents work with), --clients "claude codex gemini" (default: the ones found).
# It clones the code to ~/.local/share/agent-journal-src, adds hooks to each client's settings without
# replacing your other hooks, and links the agent-journal command into ~/.local/bin. Entries stay on this
# machine, in ~/.local/share/agent-journal/entries. Undo with: python3 setup_hooks.py CLIENT --remove
set -eu

REPO="${AGENT_JOURNAL_REPO:-https://github.com/SZoloth/agent-journal.git}"
SRC="${AGENT_JOURNAL_SRC:-$HOME/.local/share/agent-journal-src}"
NAME=""
CLIENTS=""

while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --clients) CLIENTS="$2"; shift 2 ;;
    *) echo "agent-journal: unknown option $1" >&2; exit 2 ;;
  esac
done

command -v git >/dev/null 2>&1 || { echo "agent-journal: git is required" >&2; exit 1; }
PYTHON="$(command -v python3 || true)"
if [ -z "$PYTHON" ] || ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
  echo "agent-journal: Python 3.9 or newer is required as python3" >&2
  exit 1
fi

if [ -d "$SRC/.git" ]; then
  git -C "$SRC" pull --ff-only --quiet || echo "agent-journal: could not update $SRC; using the copy already there" >&2
else
  mkdir -p "$(dirname "$SRC")"
  git clone --quiet "$REPO" "$SRC"
fi

if [ -n "$NAME" ]; then
  mkdir -p "$HOME/.config/agent-journal"
  CONFIG="$HOME/.config/agent-journal/config.json"
  "$PYTHON" -c 'import json, sys; json.dump({"person": sys.argv[1]}, open(sys.argv[2], "w"))' "$NAME" "$CONFIG"
fi

if [ -z "$CLIENTS" ]; then
  if command -v claude >/dev/null 2>&1 || [ -d "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" ]; then CLIENTS="$CLIENTS claude"; fi
  if command -v codex >/dev/null 2>&1 || [ -d "${CODEX_HOME:-$HOME/.codex}" ]; then CLIENTS="$CLIENTS codex"; fi
  if command -v gemini >/dev/null 2>&1 || [ -d "$HOME/.gemini" ]; then CLIENTS="$CLIENTS gemini"; fi
fi
if [ -z "$CLIENTS" ]; then
  echo "agent-journal: no Claude Code, Codex or Gemini CLI found; pass --clients to choose" >&2
  exit 1
fi

for client in $CLIENTS; do
  "$PYTHON" "$SRC/setup_hooks.py" "$client"
done

mkdir -p "$HOME/.local/bin"
ln -sf "$SRC/journal.py" "$HOME/.local/bin/agent-journal"

cat <<EOF

Agent Journal is installed for:$CLIENTS
Start a new agent session. It will be invited to write, and asked once if it hasn't by its third turn.
Read what your agents wrote:  agent-journal browse   (needs ~/.local/bin on your PATH)
EOF
case "$CLIENTS" in *codex*)
  echo "Codex: run /hooks in a new session and trust the agent-journal hooks before they run." ;;
esac
