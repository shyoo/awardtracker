"""Native uc_driver on Apple Silicon without Rosetta ("[Errno 86] Bad CPU type")."""
import io
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from plugins import mac_driver

UNPATCHED_JS = b"window.cdc_adoQpoasnfa76pfcZLmcfl_Array = window.Array;"


def thin_macho(cpu_type, body=b""):
    return struct.pack("<II", 0xFEEDFACF, cpu_type) + b"\0" * 24 + body


def fat_macho(*cpu_types):
    data = struct.pack(">II", 0xCAFEBABE, len(cpu_types))
    for cpu in cpu_types:
        data += struct.pack(">IIIII", cpu, 0, 0, 0, 0)
    return data


class MachOTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, data):
        path = os.path.join(self.dir, "bin")
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_thin_binaries(self):
        self.assertEqual(mac_driver.macho_architectures(self.write(thin_macho(0x01000007))), {"x86_64"})
        self.assertEqual(mac_driver.macho_architectures(self.write(thin_macho(0x0100000C))), {"arm64"})

    def test_universal_binary(self):
        self.assertEqual(mac_driver.macho_architectures(self.write(fat_macho(0x01000007, 0x0100000C))),
                         {"x86_64", "arm64"})

    def test_not_macho(self):
        self.assertEqual(mac_driver.macho_architectures(self.write(b"MZ\x90\x00not a mach-o")), set())
        self.assertEqual(mac_driver.macho_architectures(os.path.join(self.dir, "missing")), set())


class VersionParsingTests(unittest.TestCase):
    def test_parses_chrome_and_chromedriver_output(self):
        self.assertEqual(mac_driver._version_major("Google Chrome 141.0.7390.122"), 141)
        self.assertEqual(mac_driver._version_major("ChromeDriver 141.0.7390.122 (abc-refs/branch-heads/7390@{#1})"), 141)
        self.assertIsNone(mac_driver._version_major(""))


class EnsureNativeDriverTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.target = os.path.join(self.dir, "uc_driver")
        mac_driver.rosetta_available.cache_clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        mac_driver.rosetta_available.cache_clear()

    def test_no_op_unless_apple_silicon_without_rosetta(self):
        with patch.object(mac_driver, "is_apple_silicon", return_value=False), \
             patch.object(mac_driver, "install_native_uc_driver") as install:
            mac_driver.ensure_native_uc_driver("/chrome")
        install.assert_not_called()

        with patch.object(mac_driver, "is_apple_silicon", return_value=True), \
             patch.object(mac_driver, "rosetta_available", return_value=True), \
             patch.object(mac_driver, "install_native_uc_driver") as install:
            mac_driver.ensure_native_uc_driver("/chrome")
        install.assert_not_called()

    def _ensure(self, usable):
        with patch.object(mac_driver, "needs_native_uc_driver", return_value=True), \
             patch.object(mac_driver, "executable_major_version", return_value=141), \
             patch.object(mac_driver, "_local_uc_driver", return_value=self.target), \
             patch.object(mac_driver, "driver_is_usable", return_value=usable), \
             patch.object(mac_driver, "install_native_uc_driver") as install:
            mac_driver.ensure_native_uc_driver("/chrome")
        return install

    def test_installs_when_driver_is_intel_or_stale(self):
        self._ensure(usable=False).assert_called_once_with(self.target, 141)

    def test_keeps_a_usable_native_driver(self):
        self._ensure(usable=True).assert_not_called()

    def test_failures_are_logged_not_raised(self):
        with patch.object(mac_driver, "needs_native_uc_driver", return_value=True), \
             patch.object(mac_driver, "executable_major_version", return_value=141), \
             patch.object(mac_driver, "_local_uc_driver", return_value=self.target), \
             patch.object(mac_driver, "driver_is_usable", return_value=False), \
             patch.object(mac_driver, "install_native_uc_driver", side_effect=RuntimeError("offline")), \
             patch.object(mac_driver, "_log") as log:
            mac_driver.ensure_native_uc_driver("/chrome")
        self.assertIn("offline", log.call_args[0][0])

    def test_driver_is_usable_rejects_intel_unpatched_and_mismatched(self):
        def make(cpu, body):
            with open(self.target, "wb") as fh:
                fh.write(thin_macho(cpu, body))

        with patch.object(mac_driver, "executable_major_version", return_value=141), \
             patch.object(mac_driver, "_is_patched", side_effect=lambda p: UNPATCHED_JS not in open(p, "rb").read()):
            make(0x01000007, b"")
            self.assertFalse(mac_driver.driver_is_usable(self.target, 141))  # Intel
            make(0x0100000C, UNPATCHED_JS)
            self.assertFalse(mac_driver.driver_is_usable(self.target, 141))  # not UC-patched
            make(0x0100000C, b"")
            self.assertTrue(mac_driver.driver_is_usable(self.target, 141))
            self.assertFalse(mac_driver.driver_is_usable(self.target, 142))  # Chrome updated


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.target = os.path.join(self.dir, "drivers", "uc_driver")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _zip(self, payload):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("chromedriver-mac-arm64/LICENSE.chromedriver", "license")
            zf.writestr("chromedriver-mac-arm64/chromedriver", payload)
        return buf.getvalue()

    def test_download_patch_sign_and_replace(self):
        payload = thin_macho(0x0100000C, UNPATCHED_JS)
        commands = []

        class FakePatcher:
            def __init__(self, executable_path):
                self.path = executable_path

            def patch_exe(self):
                with open(self.path, "r+b") as fh:
                    data = fh.read().replace(b"cdc_adoQpoasnfa76pfcZLmcfl_", b"\n" * 27)
                    fh.seek(0)
                    fh.write(data)

        def fake_run(cmd, **kwargs):
            commands.append(cmd)

        with patch.object(mac_driver, "chromedriver_download_url", return_value="https://example.invalid/cd.zip"), \
             patch.object(mac_driver, "_fetch", return_value=self._zip(payload)), \
             patch.object(mac_driver, "executable_major_version", return_value=141), \
             patch.object(mac_driver.subprocess, "run", side_effect=fake_run), \
             patch("seleniumbase.undetected.patcher.Patcher", FakePatcher):
            mac_driver.install_native_uc_driver(self.target, 141)

        with open(self.target, "rb") as fh:
            installed = fh.read()
        self.assertNotIn(UNPATCHED_JS, installed)
        self.assertEqual(len(installed), len(payload))
        self.assertIn(["/usr/bin/codesign", "--force", "--sign", "-", self.target + ".native-tmp"], commands)
        self.assertFalse(os.path.exists(self.target + ".native-tmp"))

    def test_failed_verification_leaves_existing_driver(self):
        os.makedirs(os.path.dirname(self.target))
        with open(self.target, "wb") as fh:
            fh.write(b"old")

        with patch.object(mac_driver, "chromedriver_download_url", return_value="https://example.invalid/cd.zip"), \
             patch.object(mac_driver, "_fetch", return_value=self._zip(thin_macho(0x0100000C))), \
             patch.object(mac_driver, "executable_major_version", return_value=None), \
             patch.object(mac_driver.subprocess, "run"), \
             patch("seleniumbase.undetected.patcher.Patcher"):
            with self.assertRaises(RuntimeError):
                mac_driver.install_native_uc_driver(self.target, 141)

        with open(self.target, "rb") as fh:
            self.assertEqual(fh.read(), b"old")
        self.assertFalse(os.path.exists(self.target + ".native-tmp"))

    def test_download_url_lookup(self):
        data = {"milestones": {"141": {"downloads": {"chromedriver": [
            {"platform": "mac-x64", "url": "https://x/mac-x64.zip"},
            {"platform": "mac-arm64", "url": "https://x/mac-arm64.zip"},
        ]}}}}
        import json
        with patch.object(mac_driver, "_fetch", return_value=json.dumps(data).encode()):
            self.assertEqual(mac_driver.chromedriver_download_url(141), "https://x/mac-arm64.zip")
            with self.assertRaises(RuntimeError):
                mac_driver.chromedriver_download_url(99)


class SbKwargsHookTests(unittest.TestCase):
    def test_uc_launches_ensure_the_native_driver(self):
        from plugins import base
        with patch.object(base, "get_chrome_binary", return_value="/chrome"), \
             patch.object(mac_driver, "ensure_native_uc_driver") as ensure:
            base.get_sb_kwargs(uc=True)
            base.get_sb_kwargs(uc=False)
        ensure.assert_called_once_with("/chrome")


if __name__ == "__main__":
    unittest.main()
