#!/usr/bin/env python3
"""Commit new journal entries and push them to the journal's private Git remote."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

from journal import DEFAULT_ROOT


def git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check, timeout=120)


def private_remote(root):
    url = git(root, "remote", "get-url", "origin").stdout.strip()
    slug = url.removesuffix(".git").split("github.com")[-1].lstrip(":/")
    visibility = subprocess.run(["gh", "repo", "view", slug, "--json", "visibility", "-q", ".visibility"],
                                capture_output=True, text=True, timeout=30)
    if visibility.returncode or visibility.stdout.strip() != "PRIVATE":
        raise ValueError(f"refusing to push: GitHub did not confirm {slug} is private")


def sync(root):
    if not (root / ".git").is_dir():
        raise ValueError(f"{root} is not a Git repository; see the README to set one up")
    git(root, "add", "--all", "entries")
    staged = git(root, "diff", "--cached", "--name-only").stdout.split()
    if staged:
        git(root, "commit", "--quiet", "-m", f"chore(journal): add {len(staged)} entries")
    ahead = git(root, "rev-list", "--count", "@{upstream}..HEAD", check=False)
    if ahead.returncode == 0 and ahead.stdout.strip() == "0":
        print("journal sync: nothing to push")
        return
    private_remote(root)
    git(root, "push", "--quiet", "origin", "HEAD")
    print(f"journal sync: pushed {len(staged)} new entries")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("AGENT_JOURNAL_DIR") or DEFAULT_ROOT)
    args = parser.parse_args()
    try:
        sync(Path(args.root).expanduser().resolve())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", "") or ""
        sys.exit(f"journal sync: {error} {detail.strip()}".strip())


if __name__ == "__main__":
    main()
