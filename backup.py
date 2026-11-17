#!/usr/bin/env python3
"""Back up the local journal to encrypted disk images."""

import argparse
from base64 import b64encode
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
import time

import journal


SOURCE = Path(journal.DEFAULT_ROOT).expanduser() / "entries"
WORK = Path.home() / "Backups" / "Agent Journal"
ICLOUD = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Backups/Agent Journal"
REPO = "SZoloth/agent-journal-backup"
SECRET = "AGENT_JOURNAL_BACKUP_PASSPHRASE"
MAX_GITHUB_BYTES = 95 * 1024 * 1024
STALE_AFTER = timedelta(hours=30)
UPLOAD_CHECK = """
function run(argv) {
  ObjC.import('Foundation');
  const file = $.NSURL.fileURLWithPath(argv[0]);
  const values = file.resourceValuesForKeysError($([$.NSURLUbiquitousItemIsUploadedKey]), null);
  return JSON.stringify(ObjC.deepUnwrap(values));
}
"""


class BackupError(Exception):
    pass


def now():
    return datetime.now(timezone.utc)


def hash_file(path):
    if path.is_symlink() or not path.is_file():
        raise BackupError("invalid_archive_file")
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_file(path, write):
    with NamedTemporaryFile(dir=path.parent, prefix=".backup-", delete=False) as temporary:
        pending = Path(temporary.name)
        try:
            write(temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary.close()
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)


def command(argv, *, data=None, timeout=90):
    env = dict(os.environ)
    env.pop(SECRET, None)
    return subprocess.run(
        argv, input=data, capture_output=True, timeout=timeout, env=env,
    )


def snapshot(folder):
    entries = folder / "entries"
    entries.mkdir(parents=True)
    if not SOURCE.is_dir() or SOURCE.resolve() != SOURCE:
        raise BackupError("journal_entries_unavailable")
    records = {}
    for path in sorted(SOURCE.glob("*.md")):
        if not journal.ENTRY_ID.fullmatch(path.stem):
            continue
        raw = journal.read_markdown(path)
        staged = entries / path.name
        staged.write_bytes(raw)
        journal.parse_entry(staged)
        records[path.stem] = hashlib.sha256(raw).hexdigest()
    manifest = json.dumps(
        {"format": 1, "entries": records}, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    (folder / "manifest.json").write_bytes(manifest)
    return manifest, records


def verify_archive(archive, mount, passphrase, manifest, records):
    mount.mkdir()
    try:
        result = command([
            "/usr/bin/hdiutil", "attach", "-quiet", "-readonly", "-nobrowse", "-noautoopen",
            "-mountpoint", str(mount), "-stdinpass", str(archive),
        ], data=passphrase, timeout=40)
        if result.returncode or not mount.is_mount():
            raise BackupError("archive_attach_failed")
        if journal.read_markdown(mount / "manifest.json") != manifest:
            raise BackupError("archive_manifest_mismatch")
        entries = mount / "entries"
        if {path.name for path in entries.iterdir()} != {f"{key}.md" for key in records}:
            raise BackupError("archive_entries_mismatch")
        for key, expected in records.items():
            if hash_file(entries / f"{key}.md") != expected:
                raise BackupError("archive_entry_mismatch")
    finally:
        if mount.is_mount():
            result = command(["/usr/bin/hdiutil", "detach", "-quiet", str(mount)], timeout=15)
            if result.returncode:
                result = command(["/usr/bin/hdiutil", "detach", "-quiet", "-force", str(mount)], timeout=15)
            if result.returncode:
                raise BackupError("archive_detach_failed")


def local_archive(scratch, folder, name, passphrase, manifest, records):
    local = WORK / name
    if local.exists() or local.is_symlink():
        if local.is_symlink() or not local.is_file():
            raise BackupError("invalid_local_archive")
        archive = local
    else:
        archive = scratch / name
        result = command([
            "/usr/bin/hdiutil", "create", "-quiet", "-srcfolder", str(folder),
            "-fs", "HFS+", "-format", "UDZO", "-volname", "Agent Journal",
            "-encryption", "AES-256", "-stdinpass", str(archive),
        ], data=passphrase, timeout=85)
        if result.returncode:
            raise BackupError("archive_create_failed")
        archive.chmod(0o600)
    verify_archive(archive, scratch / "mount", passphrase, manifest, records)
    if archive != local:
        os.replace(archive, local)
    return local


def stage_icloud(archive, expected):
    cloud_root = ICLOUD.parent.parent
    if not cloud_root.is_dir():
        raise BackupError("icloud_root_unavailable")
    if ICLOUD.resolve() != ICLOUD:
        raise BackupError("invalid_icloud_directory")
    ICLOUD.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = ICLOUD / archive.name
    if not (destination.exists() or destination.is_symlink()):
        def copy(output):
            with archive.open("rb") as source:
                shutil.copyfileobj(source, output)
        replace_file(destination, copy)
    if hash_file(destination) != expected:
        raise BackupError("icloud_readback_mismatch")
    return destination


def github_api(*args, data=None, timeout=35):
    return command(["gh", "api", "--hostname", "github.com", *args], data=data, timeout=timeout)


def verify_github(archive, expected):
    repo_path = f"repos/{REPO}"
    info = github_api(repo_path)
    if info.returncode:
        raise BackupError("github_repo_unavailable")
    repo = json.loads(info.stdout)
    if not isinstance(repo, dict) or str(repo.get("full_name")).casefold() != REPO.casefold() or repo.get("visibility") != "private":
        raise BackupError("github_repo_not_private")
    endpoint = f"{repo_path}/contents/backups/{archive.name}"
    accept = ["-H", "Accept: application/vnd.github.raw"]
    result = github_api(*accept, endpoint)
    if result.returncode:
        if b"(HTTP 404)" not in result.stderr:
            raise BackupError("github_read_failed")
        if archive.stat().st_size > MAX_GITHUB_BYTES:
            raise BackupError("github_archive_too_large")
        uploaded = github_api(
            "--method", "PUT", endpoint, "--input", "-",
            data=json.dumps({
                "message": "docs: back up encrypted journal snapshot",
                "content": b64encode(archive.read_bytes()).decode("ascii"),
            }).encode("utf-8"),
            timeout=85,
        )
        result = github_api(*accept, endpoint)
        if uploaded.returncode and result.returncode:
            raise BackupError("github_upload_failed")
    if result.returncode or hashlib.sha256(result.stdout).hexdigest() != expected:
        raise BackupError("github_readback_mismatch")


def icloud_uploaded(path, budget=35):
    deadline = time.monotonic() + budget
    while True:
        try:
            result = command(
                ["/usr/bin/osascript", "-l", "JavaScript", "-", str(path)],
                data=UPLOAD_CHECK.encode("utf-8"), timeout=5,
            )
            if not result.returncode:
                values = json.loads(result.stdout)
                if isinstance(values, dict) and values.get("NSURLUbiquitousItemIsUploadedKey") is True:
                    return True
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(2, remaining))


def read_receipt():
    try:
        receipt = json.loads(journal.read_markdown(WORK / "status.json"))
    except (OSError, ValueError):
        return {}
    return receipt if isinstance(receipt, dict) else {}


def write_receipt(receipt):
    payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    replace_file(WORK / "status.json", lambda file: file.write(payload))


def run_backup():
    passphrase = os.environ.pop(SECRET, "")
    if WORK.resolve() != WORK:
        raise BackupError("invalid_backup_work_directory")
    WORK.mkdir(parents=True, exist_ok=True, mode=0o700)
    if WORK.stat().st_mode & 0o077:
        raise BackupError("backup_folder_must_be_private")
    with os.fdopen(os.open(WORK / "backup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError("backup_already_running") from None
        return backup_locked(passphrase)


def backup_locked(passphrase):
    receipt = {
        "state": "running",
        "attempted_at": now().isoformat(),
        "last_success_at": read_receipt().get("last_success_at"),
        "destinations": {},
    }
    write_receipt(receipt)
    stage = "validate_passphrase"
    try:
        if not passphrase or any(char in passphrase for char in "\r\n\0"):
            raise BackupError("missing_or_invalid_backup_passphrase")
        secret_input = passphrase.encode("utf-8") + b"\n"
        with TemporaryDirectory(prefix=".scratch-", dir=WORK) as temporary:
            scratch = Path(temporary)
            stage = "snapshot_failed"
            payload = scratch / "payload"
            manifest, records = snapshot(payload)
            if not records:
                raise BackupError("journal_has_no_entries")
            snapshot_id = hashlib.sha256(manifest).hexdigest()
            receipt.update(entries=len(records), snapshot=snapshot_id)
            stage = "local_archive_failed"
            archive = local_archive(
                scratch, payload, f"journal-{snapshot_id}.dmg", secret_input, manifest, records,
            )
        expected = hash_file(archive)
        receipt["ciphertext_sha256"] = expected
        destinations = receipt["destinations"]
        destinations["local"] = "archive_verified"
        errors = []
        cloud = None
        try:
            cloud = stage_icloud(archive, expected)
            destinations["icloud"] = "local_readback_verified"
        except BackupError as error:
            errors.append(str(error))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            errors.append("icloud_local_copy_failed")
        try:
            verify_github(archive, expected)
            destinations["github"] = "remote_readback_verified"
        except BackupError as error:
            errors.append(str(error))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            errors.append("github_backup_failed")
        if cloud is not None and icloud_uploaded(cloud):
            destinations["icloud"] = "upload_confirmed"
        if errors:
            receipt.update(state="failure", error=errors[0], errors=errors)
        elif destinations.get("icloud") != "upload_confirmed":
            receipt["state"] = "pending"
            receipt["error"] = "icloud_upload_pending"
        else:
            receipt["state"] = "success"
            receipt["last_success_at"] = now().isoformat()
    except BackupError as error:
        receipt.update(state="failure", error=str(error))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        receipt.update(state="failure", error=stage)
    write_receipt(receipt)
    return receipt


def status():
    receipt = read_receipt()
    if not receipt:
        return {"state": "missing"}, False
    success = receipt.get("state") == "success"
    if success:
        try:
            date = datetime.fromisoformat(receipt["last_success_at"])
            if date.tzinfo is None or now() - date > STALE_AFTER:
                receipt["state"] = "stale"
                success = False
        except (KeyError, TypeError, ValueError):
            receipt["state"] = "invalid"
            success = False
    return receipt, success


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "status"))
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == "status":
        receipt, success = status()
    else:
        try:
            receipt = run_backup()
        except (BackupError, OSError) as error:
            code = str(error) if isinstance(error, BackupError) else "backup_work_folder_unavailable"
            receipt = {"state": "failure", "error": code}
        success = receipt["state"] == "success"
    print(json.dumps(receipt, sort_keys=True))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
