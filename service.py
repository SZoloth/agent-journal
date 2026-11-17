#!/usr/bin/env python3
"""Install or inspect the macOS launchd jobs that sync the journal and write the weekly digest."""

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

HOME = Path.home()
HERE = Path(__file__).resolve().parent
LOGS = HOME / "Library" / "Logs" / "agent-journal"
AGENTS = HOME / "Library" / "LaunchAgents"
LAUNCHCTL = "/bin/launchctl"
RETIRED = ("com.agent-journal.backup",)
DIGEST_DIR = os.environ.get("AGENT_JOURNAL_DIGEST_DIR",
                            str(HOME / "Documents" / "Agent Journal Digests"))


def jobs():
    timeout = HOME / ".local" / "bin" / "launchd-timeout"
    wrap = [str(timeout)] if timeout.is_file() else []
    return {
        "com.agent-journal.sync": {
            "ProgramArguments": [*wrap, *(["300"] if wrap else []), sys.executable, "-B", str(HERE / "sync.py")],
            "StartInterval": 3600,
            "RunAtLoad": True,
        },
        "com.agent-journal.digest": {
            "ProgramArguments": [*wrap, *(["600"] if wrap else []), sys.executable, "-B", str(HERE / "digest.py"),
                                 "--out", DIGEST_DIR],
            "StartCalendarInterval": {"Weekday": 1, "Hour": 7, "Minute": 0},
        },
    }


def domain():
    return f"gui/{os.getuid()}"


def unload(label):
    subprocess.run([LAUNCHCTL, "bootout", f"{domain()}/{label}"], capture_output=True)


def install():
    LOGS.mkdir(parents=True, exist_ok=True)
    for label in RETIRED:
        unload(label)
        (AGENTS / f"{label}.plist").unlink(missing_ok=True)
    for label, job in jobs().items():
        plist = AGENTS / f"{label}.plist"
        job = {
            "Label": label, **job,
            "EnvironmentVariables": {
                "PATH": f"{HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                "GH_PROMPT_DISABLED": "1",
            },
            "StandardOutPath": str(LOGS / f"{label}.log"),
            "StandardErrorPath": str(LOGS / f"{label}.err.log"),
            "Umask": 0o077,
        }
        unload(label)
        plist.write_bytes(plistlib.dumps(job))
        subprocess.run([LAUNCHCTL, "bootstrap", domain(), str(plist)], check=True)
        print(f"installed {label}")


def status():
    for label in jobs():
        result = subprocess.run([LAUNCHCTL, "print", f"{domain()}/{label}"], capture_output=True, text=True)
        state = "not loaded" if result.returncode else next(
            (line.strip() for line in result.stdout.splitlines() if "last exit code" in line), "loaded")
        print(f"{label}: {state}")
        log = LOGS / f"{label}.err.log"
        if log.exists() and log.stat().st_size:
            print("  last error: " + log.read_text().strip().splitlines()[-1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status"))
    action = parser.parse_args().action
    try:
        install() if action == "install" else status()
    except (OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"agent-journal service: {error}\n")


if __name__ == "__main__":
    main()
