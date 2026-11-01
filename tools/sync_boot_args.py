#!/usr/bin/env python3
"""Explicitly synchronize only this kit's boot arguments on the target macOS PC."""

import argparse
import datetime
import os
import platform
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import uuid

GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"


def allowed(argument):
    return argument in ("nvrmacpibl=1", "keepsyms=1") or bool(re.fullmatch(r"alcid=\d{1,3}", argument))


def validate_change(current, desired):
    if [x for x in current.split() if not allowed(x)] != [x for x in desired.split() if not allowed(x)]:
        raise ValueError("Other boot arguments differ: verify the booted EFI before writing NVRAM")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("efi", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Run only on the target macOS computer, never on the helper Mac")
    if platform.machine() != "x86_64":
        parser.error("This kit targets an Intel PC; refusing to change an Apple silicon Mac")
    efi = args.efi.resolve()
    config = plistlib.loads((efi / "OC/config.plist").read_bytes())
    actual_model = subprocess.check_output(["/usr/sbin/sysctl", "-n", "hw.model"], text=True).strip()
    configured_model = config.get("PlatformInfo", {}).get("Generic", {}).get("SystemProductName")
    if not configured_model or configured_model != actual_model:
        parser.error("EFI SMBIOS model differs from the running computer; verify the booted EFI")
    desired = config["NVRAM"]["Add"][GUID]["boot-args"]
    result = subprocess.run(["/usr/sbin/nvram", "boot-args"], check=True,
                            text=True, capture_output=True)
    current = result.stdout.split("\t", 1)[1].rstrip("\n")
    validate_change(current, desired)
    print("Current:", current)
    print("Desired:", desired)
    if current == desired:
        print("No change needed")
        return
    if not args.apply:
        print("PREVIEW ONLY; rerun with --apply on the target computer")
        return
    if os.geteuid() != 0:
        parser.error("--apply requires administrator privileges")
    folder = efi.parent / "yaoshi-backups"
    folder.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = folder / ("boot-args-" + stamp + "-" + uuid.uuid4().hex[:8] + ".txt")
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(current + "\n")
    subprocess.run(["/usr/sbin/nvram", "boot-args=" + desired], check=True)
    print("Saved previous value to", backup)
    print("NVRAM updated; restart required")


if __name__ == "__main__":
    main()
