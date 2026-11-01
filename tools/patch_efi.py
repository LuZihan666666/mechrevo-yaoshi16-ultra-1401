#!/usr/bin/env python3
"""Preview or apply the narrowly scoped fixes documented in this repository."""

import argparse
import datetime
import hashlib
import os
from pathlib import Path
import plistlib
import re
import shutil
import struct
import sys
import uuid

APPLE_GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"
APIC_NAME = "APIC-YAOSHI-legacy.aml"


class PatchError(ValueError):
    pass


def convert_apic(raw):
    """Convert an x2APIC-only MADT into legacy LAPIC records, failing closed."""
    if len(raw) < 44 or raw[:4] != b"APIC":
        raise PatchError("Expected a complete APIC/MADT table")
    if struct.unpack_from("<I", raw, 4)[0] != len(raw) or sum(raw) % 256:
        raise PatchError("Invalid MADT length or checksum")
    entries, cpus, apic_ids, uids = [], [], set(), set()
    pos = 44
    while pos < len(raw):
        if pos + 2 > len(raw):
            raise PatchError("Truncated MADT entry")
        kind, size = raw[pos:pos + 2]
        if size < 2 or pos + size > len(raw):
            raise PatchError("Invalid MADT entry length")
        entry = raw[pos:pos + size]
        pos += size
        if kind == 0:
            raise PatchError("MADT already contains LAPIC entries; do not convert twice")
        if kind == 9:
            if size != 16:
                raise PatchError("Unexpected x2APIC record size")
            apic_id, flags, uid = struct.unpack_from("<III", entry, 4)
            if not flags & 1:
                if flags & 2:
                    raise PatchError("Online-capable disabled CPU needs manual review")
                continue
            if flags & ~3 or apic_id > 254 or uid > 254:
                raise PatchError("CPU cannot be represented safely by a legacy LAPIC")
            if apic_id in apic_ids or uid in uids:
                raise PatchError("Duplicate APIC ID or ACPI processor UID")
            apic_ids.add(apic_id)
            uids.add(uid)
            cpus.append((uid, apic_id))
            entries.append(struct.pack("<BBBBI", 0, 8, uid, apic_id, flags))
        elif kind == 10:
            if size != 12:
                raise PatchError("Unexpected x2APIC NMI record size")
            flags, uid, lint = struct.unpack_from("<HIB", entry, 2)
            if uid != 0xFFFFFFFF and uid > 254:
                raise PatchError("NMI UID cannot be represented safely")
            entries.append(struct.pack("<BBBHB", 4, 6, 255 if uid == 0xFFFFFFFF else uid,
                                       flags, lint))
        elif kind in (1, 2, 3, 4, 5):
            # IOAPIC, interrupt overrides, NMIs and address overrides are preserved.
            entries.append(entry)
        else:
            raise PatchError("Unreviewed MADT record type: %d" % kind)
    if not cpus:
        raise PatchError("No enabled x2APIC processors found")
    result = bytearray(raw[:44] + b"".join(entries))
    struct.pack_into("<I", result, 4, len(result))
    result[9] = 0
    result[9] = (-sum(result)) & 0xFF
    return bytes(result), cpus


def add_boot_arg(config, argument):
    target = config.setdefault("NVRAM", {}).setdefault("Add", {}).setdefault(APPLE_GUID, {})
    args = target.get("boot-args", "").split()
    if argument not in args:
        args.append(argument)
        target["boot-args"] = " ".join(args)


def kernel_entry(name, min_kernel="", max_kernel=""):
    return {"Arch": "x86_64", "BundlePath": name + ".kext",
            "Comment": "YAOSHI documented fix: " + name, "Enabled": True,
            "ExecutablePath": "Contents/MacOS/" + name, "PlistPath": "Contents/Info.plist",
            "MinKernel": min_kernel, "MaxKernel": max_kernel}


def kext_files(source, name, bundle_id):
    root = source / (name + ".kext")
    info = root / "Contents/Info.plist"
    if not info.is_file():
        raise PatchError("Missing dependency: " + str(info))
    meta = plistlib.loads(info.read_bytes())
    if meta.get("CFBundleIdentifier") != bundle_id:
        raise PatchError("Unexpected bundle identifier: " + name)
    if meta.get("CFBundleExecutable") != name or not (root / "Contents/MacOS" / name).is_file():
        raise PatchError("Missing or unexpected executable: " + name)
    files = {}
    for item in root.rglob("*"):
        if item.is_symlink():
            raise PatchError("Symlink in dependency: " + str(item))
        if item.is_file() and not item.name.startswith("._") and item.name != ".DS_Store":
            files["OC/Kexts/" + name + ".kext/" + item.relative_to(root).as_posix()] = item.read_bytes()
    return files


def plan_patches(efi, *, apic=None, brightness=False, touchpad=False, audio=False,
                 android_tether=False, dependencies=None, layout_id=28):
    efi = Path(efi).resolve()
    cfg = efi / "OC/config.plist"
    if not cfg.is_file() or cfg.is_symlink() or (efi / "OC").is_symlink():
        raise PatchError("Pass the EFI directory containing OC/config.plist")
    original = plistlib.loads(cfg.read_bytes())
    config = plistlib.loads(plistlib.dumps(original))
    proposed = {}
    if apic is not None:
        raw = Path(apic).read_bytes()
        aml, cpus = convert_apic(raw)
        # This repository only validates the 24-thread 275HX profile.
        if len(cpus) != 24 or {uid for uid, _ in cpus} != set(range(24)):
            raise PatchError("This kit expects 24 enabled CPU UIDs numbered 0..23")
        proposed["OC/ACPI/" + APIC_NAME] = aml
        acpi = config.setdefault("ACPI", {})
        drops = acpi.setdefault("Delete", [])
        for item in drops:
            if item.get("Enabled") and item.get("TableSignature") == b"APIC":
                if item.get("All") or item.get("TableLength") != len(raw) or item.get("OemTableId") != raw[16:24]:
                    raise PatchError("Existing conflicting APIC deletion needs manual review")
        if not any(d.get("Enabled") and d.get("TableSignature") == b"APIC" for d in drops):
            drops.append({"All": False, "Comment": "YAOSHI: replace this exact original MADT",
                          "Enabled": True, "OemTableId": raw[16:24],
                          "TableLength": len(raw), "TableSignature": b"APIC"})
        adds = acpi.setdefault("Add", [])
        item = next((x for x in adds if x.get("Path") == APIC_NAME), None)
        if item is not None:
            item["Enabled"] = True
        else:
            adds.append({"Comment": "YAOSHI: legacy LAPIC MADT generated from own firmware",
                         "Enabled": True, "Path": APIC_NAME})
    if brightness:
        add_boot_arg(config, "nvrmacpibl=1")
    if touchpad:
        rel = "OC/Kexts/LegionI2CArrowLake.kext/Contents/Info.plist"
        path = efi / rel
        if not path.is_file():
            raise PatchError("LegionI2CArrowLake.kext is missing; no generic injector is invented")
        data = plistlib.loads(path.read_bytes())
        personalities = data.get("IOKitPersonalities", {})
        matches = [x for x in personalities.values()
                   if "7f4c8086" in x.get("IOPCIMatch", "").lower()]
        if len(matches) != 1:
            raise PatchError("Expected exactly one Arrow Lake I2C personality")
        binary = efi / "OC/Kexts/VoodooI2C.kext/Contents/MacOS/VoodooI2C"
        if not binary.is_file():
            raise PatchError("VoodooI2C binary is missing")
        blob = binary.read_bytes()
        if b"VoodooI2CPCILakeController" in blob:
            raise PatchError("Installed VoodooI2C still contains the Lake class; do not apply this fix")
        if b"VoodooI2CPCIController" not in blob:
            raise PatchError("Expected PCIController class not found in VoodooI2C binary")
        current = matches[0].get("IOClass")
        if current not in ("VoodooI2CPCILakeController", "VoodooI2CPCIController"):
            raise PatchError("Unknown I2C class needs manual review")
        if current != "VoodooI2CPCIController":
            matches[0]["IOClass"] = "VoodooI2CPCIController"
            proposed[rel] = plistlib.dumps(data, sort_keys=False)
    if audio or android_tether:
        if dependencies is None:
            raise PatchError("Use --dependencies with verified extracted kexts")
        dependencies = Path(dependencies)
        adds = config.setdefault("Kernel", {}).setdefault("Add", [])
        if audio:
            if not any(x.get("BundlePath") == "Lilu.kext" and x.get("Enabled") for x in adds):
                raise PatchError("Audio requires enabled Lilu.kext (SimpleHDA needs Lilu >= 1.7.1)")
            lilu_info = efi / "OC/Kexts/Lilu.kext/Contents/Info.plist"
            if not lilu_info.is_file():
                raise PatchError("Lilu Info.plist is missing")
            version = plistlib.loads(lilu_info.read_bytes()).get("CFBundleVersion", "")
            numbers = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
            if not numbers or tuple(map(int, numbers.groups())) < (1, 7, 1):
                raise PatchError("SimpleHDA requires Lilu >= 1.7.1")
            names = [("AppleALC", "as.vit9696.AppleALC"), ("SimpleHDA", "cn.laobamac.SimpleHDA")]
            args = config.get("NVRAM", {}).get("Add", {}).get(APPLE_GUID, {}).get("boot-args", "").split()
            if not any(a.startswith("alcid=") for a in args):
                has_layout = any("layout-id" in value for value in
                                 config.get("DeviceProperties", {}).get("Add", {}).values())
                if not has_layout:
                    add_boot_arg(config, "alcid=%d" % layout_id)
            add_boot_arg(config, "keepsyms=1")
        else:
            names = []
        if android_tether:
            names.append(("HoRNDIS", "com.joshuawise.kexts.HoRNDIS"))
        for name, identifier in names:
            for rel, content in kext_files(dependencies, name, identifier).items():
                existing = efi / rel
                if existing.exists() and existing.read_bytes() != content:
                    raise PatchError("Dependency already exists with different content: " + rel)
                proposed[rel] = content
            entry = next((x for x in adds if x.get("BundlePath") == name + ".kext"), None)
            if entry is not None:
                if not entry.get("Enabled"):
                    raise PatchError("Existing disabled kext needs manual review: " + name)
            else:
                entry = kernel_entry(name, "25.0.0" if name == "SimpleHDA" else "",
                                     "25.99.99" if name == "SimpleHDA" else "")
                if name == "AppleALC":
                    index = next(i for i, x in enumerate(adds) if x.get("BundlePath") == "Lilu.kext") + 1
                    adds.insert(index, entry)
                elif name == "SimpleHDA":
                    index = next(i for i, x in enumerate(adds) if x.get("BundlePath") == "AppleALC.kext") + 1
                    adds.insert(index, entry)
                else:
                    adds.append(entry)
        if audio:
            order = [x.get("BundlePath") for x in adds]
            if not order.index("Lilu.kext") < order.index("AppleALC.kext") < order.index("SimpleHDA.kext"):
                raise PatchError("Expected load order Lilu -> AppleALC -> SimpleHDA")
    if config != original:
        proposed["OC/config.plist"] = plistlib.dumps(config, sort_keys=False)
    changes = {}
    for rel, content in proposed.items():
        dest = efi / rel
        if not dest.resolve().is_relative_to(efi) or dest.is_symlink():
            raise PatchError("Refusing a path outside EFI: " + rel)
        if not dest.is_file() or dest.read_bytes() != content:
            changes[rel] = content
    return changes


def apply_changes(efi, changes):
    """Back up privately, write config last, and roll back on an ordinary I/O failure."""
    efi = Path(efi).resolve()
    if not changes:
        return None
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = efi.parent / "yaoshi-backups" / (stamp + "-" + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True, mode=0o700)
    backup.chmod(0o700)
    shutil.copytree(efi, backup / "EFI", symlinks=True)
    originals = {rel: (efi / rel).read_bytes() if (efi / rel).is_file() else None for rel in changes}
    written = []
    temporary = []
    try:
        for rel in sorted(changes, key=lambda x: (x == "OC/config.plist", x)):
            target = efi / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".yaoshi-" + uuid.uuid4().hex)
            temporary.append(temp)
            temp.write_bytes(changes[rel])
            os.replace(temp, target)
            written.append(rel)
    except Exception:
        for rel in reversed(written):
            target, content = efi / rel, originals[rel]
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(content)
        raise
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("efi", type=Path, help="EFI directory containing OC/config.plist")
    parser.add_argument("--apic", type=Path, help="Own original APIC/MADT, never another laptop's table")
    parser.add_argument("--brightness", action="store_true")
    parser.add_argument("--touchpad", action="store_true")
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--android-tether", action="store_true")
    parser.add_argument("--dependencies", type=Path)
    parser.add_argument("--layout-id", type=int, default=28)
    parser.add_argument("--apply", action="store_true", help="Actually write changes; default is preview only")
    args = parser.parse_args()
    if not any((args.apic, args.brightness, args.touchpad, args.audio, args.android_tether)):
        parser.error("Select at least one documented patch")
    if not 1 <= args.layout_id <= 255:
        parser.error("layout-id must be between 1 and 255")
    changes = plan_patches(args.efi, apic=args.apic, brightness=args.brightness,
                           touchpad=args.touchpad, audio=args.audio,
                           android_tether=args.android_tether,
                           dependencies=args.dependencies, layout_id=args.layout_id)
    print("APPLY" if args.apply else "PREVIEW ONLY (no changes written)")
    for rel, data in changes.items():
        print("  %s  sha256=%s" % (rel, hashlib.sha256(data).hexdigest()))
    if not changes:
        print("Already matches the selected patches")
    if args.apply and changes:
        print("Private backup:", apply_changes(args.efi, changes))
        print("Restart required. Existing NVRAM boot-args may also need updating; see README.")


if __name__ == "__main__":
    try:
        main()
    except (PatchError, OSError, plistlib.InvalidFileException) as error:
        print("STOP:", error, file=sys.stderr)
        sys.exit(1)
