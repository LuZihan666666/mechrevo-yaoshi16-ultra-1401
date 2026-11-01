import hashlib
import importlib.util
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import patch_efi as patch
import sync_boot_args as sync_args


def madt():
    header = bytearray(44)
    header[:4] = b"APIC"
    header[8] = 5
    header[10:16] = b"TEST  "
    header[16:24] = b"YAOSHI  "
    struct.pack_into("<II", header, 36, 0xFEE00000, 1)
    records = [struct.pack("<BBHIII", 9, 16, 0, uid * 2, 1, uid) for uid in range(24)]
    records += [struct.pack("<BBHIII", 9, 16, 0, 0xFFFFFFFF, 0, uid) for uid in range(24, 48)]
    records += [struct.pack("<BBBBII", 1, 12, 24, 0, 0xFEC00000, 0)]
    records += [struct.pack("<BBBBIH", 2, 10, 0, 0, 2, 0)]
    records += [struct.pack("<BBBBIH", 2, 10, 0, 9, 9, 13)]
    records += [struct.pack("<BBHIB3s", 10, 12, 13, 0xFFFFFFFF, 1, b"\0\0\0")]
    result = header + b"".join(records)
    struct.pack_into("<I", result, 4, len(result))
    result[9] = (-sum(result)) & 0xFF
    return bytes(result)


def seed_efi(efi):
    (efi / "OC/Kexts/Lilu.kext/Contents").mkdir(parents=True)
    (efi / "OC/Kexts/Lilu.kext/Contents/Info.plist").write_bytes(
        plistlib.dumps({"CFBundleVersion": "1.7.3"}))
    config = {"ACPI": {"Add": [], "Delete": []},
              "Kernel": {"Add": [patch.kernel_entry("Lilu")]},
              "DeviceProperties": {"Add": {"TEST_DEVICE": {"unchanged": b"\x12\x34"}}},
              "PlatformInfo": {"Generic": {"SystemSerialNumber": "TEST_ONLY",
                                            "SystemProductName": "MacBookPro16,2"}},
              "NVRAM": {"Add": {patch.APPLE_GUID: {"boot-args": "-v nvfb=1 nvaccel=1"}}}}
    (efi / "OC/config.plist").write_bytes(plistlib.dumps(config))
    return config


def fake_kext(root, name, identifier):
    path = root / (name + ".kext") / "Contents"
    (path / "MacOS").mkdir(parents=True)
    (path / "Info.plist").write_bytes(plistlib.dumps(
        {"CFBundleIdentifier": identifier, "CFBundleExecutable": name}))
    (path / "MacOS" / name).write_bytes(b"synthetic-test-executable")


def digest_tree(root):
    return {str(x.relative_to(root)): hashlib.sha256(x.read_bytes()).hexdigest()
            for x in root.rglob("*") if x.is_file()}


class MadtTests(unittest.TestCase):
    def test_topology_and_interrupt_records_survive_conversion(self):
        raw = madt()
        self.assertEqual(len(raw), 856)
        result, cpus = patch.convert_apic(raw)
        self.assertEqual(len(result), 274)
        self.assertEqual(sum(result) % 256, 0)
        self.assertEqual(struct.unpack_from("<I", result, 4)[0], len(result))
        self.assertEqual(cpus, [(uid, uid * 2) for uid in range(24)])
        for uid in range(24):
            self.assertEqual(struct.unpack_from("<BBBBI", result, 44 + uid * 8),
                             (0, 8, uid, uid * 2, 1))
        self.assertEqual(result[44 + 24 * 8:-6], raw[-44:-12])
        self.assertEqual(result[-6:], struct.pack("<BBBHB", 4, 6, 255, 13, 1))

    def test_bad_checksum_and_truncation_are_rejected(self):
        broken = bytearray(madt())
        broken[-1] ^= 1
        for data in (bytes(broken), madt()[:-1], b"APIC"):
            with self.assertRaises(patch.PatchError):
                patch.convert_apic(data)

    def test_already_converted_table_is_not_converted_again(self):
        result, _ = patch.convert_apic(madt())
        with self.assertRaises(patch.PatchError):
            patch.convert_apic(result)

    def test_unrepresentable_ids_fail_instead_of_truncating(self):
        raw = bytearray(madt())
        struct.pack_into("<I", raw, 48, 300)
        raw[9] = 0
        raw[9] = (-sum(raw)) & 255
        with self.assertRaises(patch.PatchError):
            patch.convert_apic(bytes(raw))


class EfiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.efi = self.root / "EFI"
        self.original = seed_efi(self.efi)

    def tearDown(self):
        self.temp.cleanup()

    def test_preview_does_not_write_and_cli_is_preview_by_default(self):
        before = digest_tree(self.root)
        changes = patch.plan_patches(self.efi, brightness=True)
        self.assertEqual(set(changes), {"OC/config.plist"})
        result = subprocess.run([sys.executable, str(ROOT / "tools/patch_efi.py"),
                                 str(self.efi), "--brightness"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PREVIEW ONLY", result.stdout)
        self.assertEqual(digest_tree(self.root), before)

    def test_apic_patch_is_exact_and_idempotent(self):
        source = self.root / "APIC.aml"
        source.write_bytes(madt())
        changes = patch.plan_patches(self.efi, apic=source)
        cfg = plistlib.loads(changes["OC/config.plist"])
        self.assertEqual(cfg["PlatformInfo"], self.original["PlatformInfo"])
        self.assertEqual(cfg["DeviceProperties"], self.original["DeviceProperties"])
        delete = cfg["ACPI"]["Delete"][0]
        self.assertFalse(delete["All"])
        self.assertEqual(delete["OemTableId"], b"YAOSHI  ")
        self.assertEqual(delete["TableLength"], 856)
        backup = patch.apply_changes(self.efi, changes)
        self.assertEqual(plistlib.loads((backup / "EFI/OC/config.plist").read_bytes()), self.original)
        self.assertEqual(patch.plan_patches(self.efi, apic=source), {})

    def test_touchpad_only_changes_injector_and_refuses_old_class_binary(self):
        folder = self.efi / "OC/Kexts/LegionI2CArrowLake.kext/Contents"
        folder.mkdir(parents=True)
        personality = {"IOClass": "VoodooI2CPCILakeController",
                       "IOPCIMatch": "0x7f4c8086&0xFFFCFFFF", "I2CClkRate": 133000000}
        original = {"IOKitPersonalities": {"ArrowLake": personality}}
        (folder / "Info.plist").write_bytes(plistlib.dumps(original))
        binary = self.efi / "OC/Kexts/VoodooI2C.kext/Contents/MacOS/VoodooI2C"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"synthetic VoodooI2CPCIController")
        changes = patch.plan_patches(self.efi, touchpad=True)
        self.assertEqual(len(changes), 1)
        changed = plistlib.loads(next(iter(changes.values())))
        self.assertEqual(changed["IOKitPersonalities"]["ArrowLake"]["IOPCIMatch"], personality["IOPCIMatch"])
        self.assertEqual(changed["IOKitPersonalities"]["ArrowLake"]["IOClass"], "VoodooI2CPCIController")
        binary.write_bytes(b"VoodooI2CPCILakeController VoodooI2CPCIController")
        with self.assertRaises(patch.PatchError):
            patch.plan_patches(self.efi, touchpad=True)

    def test_audio_orders_dependencies_preserves_identity_and_is_idempotent(self):
        deps = self.root / "downloads"
        fake_kext(deps, "AppleALC", "as.vit9696.AppleALC")
        fake_kext(deps, "SimpleHDA", "cn.laobamac.SimpleHDA")
        changes = patch.plan_patches(self.efi, audio=True, dependencies=deps)
        cfg = plistlib.loads(changes["OC/config.plist"])
        self.assertEqual(cfg["PlatformInfo"], self.original["PlatformInfo"])
        self.assertEqual([x["BundlePath"] for x in cfg["Kernel"]["Add"]],
                         ["Lilu.kext", "AppleALC.kext", "SimpleHDA.kext"])
        self.assertIn("alcid=28", cfg["NVRAM"]["Add"][patch.APPLE_GUID]["boot-args"])
        patch.apply_changes(self.efi, changes)
        self.assertEqual(patch.plan_patches(self.efi, audio=True, dependencies=deps), {})

    def test_audio_refuses_overwriting_different_existing_bundle(self):
        deps = self.root / "downloads"
        fake_kext(deps, "AppleALC", "as.vit9696.AppleALC")
        fake_kext(deps, "SimpleHDA", "cn.laobamac.SimpleHDA")
        fake_kext(self.efi / "OC/Kexts", "AppleALC", "different.local.bundle")
        with self.assertRaises(patch.PatchError):
            patch.plan_patches(self.efi, audio=True, dependencies=deps)

    def test_write_failure_restores_preexisting_contents(self):
        before = digest_tree(self.efi)
        real_replace = patch.os.replace
        calls = 0

        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated removable disk failure")
            return real_replace(source, destination)

        changes = {"OC/ACPI/test.aml": b"test", "OC/config.plist": b"not committed"}
        with mock.patch.object(patch.os, "replace", side_effect=fail_second):
            with self.assertRaises(OSError):
                patch.apply_changes(self.efi, changes)
        self.assertEqual(digest_tree(self.efi), before)

    @unittest.skipIf(sys.platform == "win32", "symlink creation may require privileges on Windows")
    def test_symlink_outside_efi_is_refused(self):
        target = self.root / "outside"
        target.mkdir()
        (self.efi / "OC/ACPI").symlink_to(target, target_is_directory=True)
        source = self.root / "APIC.aml"
        source.write_bytes(madt())
        with self.assertRaises(patch.PatchError):
            patch.plan_patches(self.efi, apic=source)


class BootArgTests(unittest.TestCase):
    def test_only_documented_changes_are_accepted(self):
        sync_args.validate_change("-v nvfb=1", "-v nvfb=1 nvrmacpibl=1 alcid=28 keepsyms=1")
        with self.assertRaises(ValueError):
            sync_args.validate_change("-v nvfb=1", "-v nvfb=0 nvrmacpibl=1")


if __name__ == "__main__":
    unittest.main()
