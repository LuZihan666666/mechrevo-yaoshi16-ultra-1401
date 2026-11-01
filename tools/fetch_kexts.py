#!/usr/bin/env python3
"""Fetch only the upstream releases tested here; verify archive SHA-256 first."""

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import tempfile
import urllib.request
import zipfile

RELEASES = {
    "AppleALC": (
        "https://github.com/acidanthera/AppleALC/releases/download/1.9.8/AppleALC-1.9.8-RELEASE.zip",
        "d4d36cd2da7863cf7cbfcb0892d45c08457f4f4ddd065a073dd010e46bd63bcb"),
    "SimpleHDA": (
        "https://github.com/laobamac/SimpleHDA/releases/download/v1.0.0/SimpleHDA-Tahoe-v1.0.0-RELEASE.zip",
        "89198256664078c91155d673ee7cebb08134dad1b71d5e34b0aa4ef0d4877f8f"),
    "HoRNDIS": (
        "https://github.com/iKeramat/HoRNDIS/releases/download/mac-15.5/HoRNDIS.zip",
        "bda966158dd51bc6972ada8485d6a3d3d595130d7e106e3807434de3cdf7c14a"),
}


def fetch(name, output):
    url, expected = RELEASES[name]
    archive = output / (name + ".zip")
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Archive size or SHA-256 mismatch: " + name)
        archive.write_bytes(data)
    destination = output / (name + ".kext")
    if destination.exists():
        raise FileExistsError("Refusing to overwrite an existing bundle: " + str(destination))
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        staging = Path(temporary) / (name + ".kext")
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                path = PurePosixPath(member.filename)
                parts = path.parts
                if path.is_absolute() or ".." in parts or "\\" in member.filename or any(":" in x for x in parts):
                    raise ValueError("Unsafe ZIP path")
                if name + ".kext" not in parts or "__MACOSX" in parts:
                    continue
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Unexpected symlink in bundle")
                index = parts.index(name + ".kext")
                relative = parts[index + 1:]
                if not relative or parts[-1].startswith("._"):
                    continue
                if member.file_size > 32 * 1024 * 1024:
                    raise ValueError("Oversized bundle member")
                target = staging.joinpath(*relative)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(package.read(member))
        info = staging / "Contents/Info.plist"
        meta = plistlib.loads(info.read_bytes())
        executable = staging / "Contents/MacOS" / meta["CFBundleExecutable"]
        if not executable.is_file():
            raise ValueError("Missing bundle executable")
        executable.chmod(0o755)
        shutil.move(str(staging), str(destination))
    print(name, "verified:", expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("downloads"))
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--android-tether", action="store_true")
    args = parser.parse_args()
    if not args.audio and not args.android_tether:
        parser.error("Select --audio or --android-tether")
    args.output.mkdir(parents=True, exist_ok=True)
    names = (["AppleALC", "SimpleHDA"] if args.audio else []) + (["HoRNDIS"] if args.android_tether else [])
    for name in names:
        fetch(name, args.output)


if __name__ == "__main__":
    main()
