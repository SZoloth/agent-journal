#!/usr/bin/env python3
"""Install and inspect the Agent Journal macOS backup job."""

import argparse
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile


LABEL = "com.agent-journal.backup"
HOUR, MINUTE = 3, 15
HOME = Path.home()
ROOT = HOME / "Backups" / "Agent Journal"
PLIST = HOME / "Library" / "LaunchAgents" / f"{LABEL}.plist"
SCRIPT = Path(__file__).resolve().with_name("backup.py")
LAUNCHCTL = "/bin/launchctl"


def domain():
    return f"gui/{os.getuid()}"


def loaded():
    return subprocess.run([LAUNCHCTL, "print", f"{domain()}/{LABEL}"], text=True, capture_output=True)


def definition():
    local_bin = HOME / ".local" / "bin"
    timeout = local_bin / "launchd-timeout"
    loader = local_bin / "with-secret"
    if not all(path.is_file() for path in (timeout, loader, SCRIPT)):
        raise ValueError("Install with-secret and launchd-timeout in ~/.local/bin and keep backup.py next to this installer.")
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(timeout), "600", str(loader), "AGENT_JOURNAL_BACKUP_PASSPHRASE",
            "--", sys.executable, "-B", str(SCRIPT), "run",
        ],
        "EnvironmentVariables": {
            "PATH": f"{local_bin}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "GH_PROMPT_DISABLED": "1",
        },
        "RunAtLoad": True,
        "StartCalendarInterval": {"Hour": HOUR, "Minute": MINUTE},
        "StandardOutPath": str(ROOT / "backup.log"),
        "StandardErrorPath": str(ROOT / "backup-error.log"),
        "Umask": 0o077,
    }


def install():
    ROOT.mkdir(parents=True, mode=0o700, exist_ok=True)
    if ROOT.is_symlink() or ROOT.stat().st_uid != os.getuid() or ROOT.stat().st_mode & 0o077:
        raise ValueError("The Agent Journal backup folder must be private and owned by your account.")
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    desired = plistlib.dumps(definition())
    current = loaded()
    if PLIST.exists() and PLIST.read_bytes() == desired and not current.returncode:
        print(f"{LABEL} is installed for {HOUR:02d}:{MINUTE:02d} local time.")
        return
    if not current.returncode:
        if re.search(r"(?m)^\s*state = running\s*$", current.stdout):
            raise ValueError("A backup is running. Wait for it to finish before reinstalling.")
        subprocess.run([LAUNCHCTL, "bootout", f"{domain()}/{LABEL}"], check=True)
    with tempfile.NamedTemporaryFile(dir=PLIST.parent, delete=False) as output:
        temp = Path(output.name)
        try:
            output.write(desired)
            output.flush()
            subprocess.run(["/usr/bin/plutil", "-lint", str(temp)], capture_output=True, check=True)
            temp.replace(PLIST)
        finally:
            temp.unlink(missing_ok=True)
    subprocess.run([LAUNCHCTL, "bootstrap", domain(), str(PLIST)], check=True)
    print(f"Installed {LABEL} for {HOUR:02d}:{MINUTE:02d} local time.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "run"))
    action = parser.parse_args().action
    try:
        if action == "install":
            install()
            return
        current = loaded()
        if action == "run":
            if current.returncode:
                raise ValueError("The backup job is missing. Run backup_service.py install first.")
            subprocess.run([LAUNCHCTL, "kickstart", f"{domain()}/{LABEL}"], check=True)
            print("Backup requested. Run backup_service.py status to see the result.")
            return
        print(f"Schedule: {HOUR:02d}:{MINUTE:02d} local time" if not current.returncode else "Schedule: not loaded",
              flush=True)
        if not current.returncode:
            for line in current.stdout.splitlines():
                if line.startswith(("\tstate = ", "\tlast exit code = ", "\truns = ")):
                    print(line.strip(), flush=True)
        status = subprocess.run([sys.executable, "-B", str(SCRIPT), "status"])
        launch_failed = re.search(r"(?m)^\tlast exit code = [1-9]\d*\s*$", current.stdout)
        sys.exit(status.returncode or bool(current.returncode or launch_failed))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"agent-journal backup service: {error}\n")


if __name__ == "__main__":
    main()
