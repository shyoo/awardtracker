"""Native ``uc_driver`` for Apple Silicon Macs that cannot run Intel binaries.

SeleniumBase deliberately installs the *Intel* chromedriver as ``uc_driver`` on
Apple Silicon: UC Mode patches bytes inside the driver, which invalidates an
arm64 binary's code signature, while an x86_64 binary runs unsigned under
Rosetta. Without Rosetta (it is not installed, or was removed by a macOS
upgrade) every launch then fails with ``[Errno 86] Bad CPU type in
executable``, and SeleniumBase keeps re-downloading the same Intel build.

When Rosetta is unavailable this installs the matching native arm64
chromedriver from Chrome for Testing, applies the same UC patch, and re-signs
it ad hoc. SeleniumBase keeps a ``uc_driver`` whose version matches Chrome and
does not re-patch one that is already patched, so it uses this driver as is.
"""
from __future__ import annotations

import io
import json
import os
import platform
import re
import ssl
import struct
import subprocess
import sys
import threading
import urllib.request
import zipfile
from functools import lru_cache
from typing import Optional, Set

CFT_MILESTONES_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/"
    "latest-versions-per-milestone-with-downloads.json"
)
CFT_PLATFORM = "mac-arm64"

_CPU_TYPES = {0x01000007: "x86_64", 0x0100000C: "arm64"}
_lock = threading.Lock()


def _log(message: str, warning: bool = False) -> None:
    try:
        from core.applog import app_log
        (app_log.warning if warning else app_log.info)(message)
    except Exception:
        pass


def is_apple_silicon() -> bool:
    """True for a native arm64 process on macOS (not one translated by Rosetta)."""
    return sys.platform == "darwin" and platform.machine() == "arm64"


@lru_cache(maxsize=1)
def rosetta_available() -> bool:
    """Whether this Mac can run x86_64 executables."""
    try:
        result = subprocess.run(["/usr/bin/arch", "-x86_64", "/usr/bin/true"],
                                capture_output=True, timeout=15)
        return result.returncode == 0
    except Exception:
        return False


def needs_native_uc_driver() -> bool:
    return is_apple_silicon() and not rosetta_available()


def macho_architectures(path: str) -> Set[str]:
    """CPU architectures in a Mach-O executable (thin or universal); empty if unreadable."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(8)
            if len(header) < 8:
                return set()
            magic = struct.unpack(">I", header[:4])[0]
            if magic in (0xCAFEBABE, 0xCAFEBABF):  # universal binary, big-endian table
                count = struct.unpack(">I", header[4:8])[0]
                entry_size = 20 if magic == 0xCAFEBABE else 32
                table = fh.read(entry_size * min(count, 32))
                return {_CPU_TYPES.get(struct.unpack(">I", table[i:i + 4])[0], "other")
                        for i in range(0, len(table) - 3, entry_size)}
            if magic in (0xCFFAEDFE, 0xCEFAEDFE):  # thin, little-endian
                return {_CPU_TYPES.get(struct.unpack("<I", header[4:8])[0], "other")}
    except OSError:
        pass
    return set()


def _version_major(output: str) -> Optional[int]:
    match = re.search(r"(\d+)\.\d+\.\d+", output or "")
    return int(match.group(1)) if match else None


def executable_major_version(path: str) -> Optional[int]:
    """Major version printed by ``<path> --version`` (Chrome or chromedriver)."""
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30)
        return _version_major(result.stdout)
    except Exception:
        return None


def _local_uc_driver() -> str:
    from seleniumbase.core import browser_launcher
    return browser_launcher.LOCAL_UC_DRIVER


def _is_patched(path: str) -> bool:
    from seleniumbase.undetected.patcher import Patcher
    return Patcher(executable_path=path).is_binary_patched(path)


def driver_is_usable(path: str, chrome_major: int) -> bool:
    return (os.path.isfile(path)
            and "arm64" in macho_architectures(path)
            and _is_patched(path)
            and executable_major_version(path) == chrome_major)


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    return ctx


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AwardTracker"})
    with urllib.request.urlopen(request, context=_ssl_context(), timeout=60) as response:
        return response.read()


def chromedriver_download_url(chrome_major: int) -> str:
    data = json.loads(_fetch(CFT_MILESTONES_URL))
    milestone = data.get("milestones", {}).get(str(chrome_major))
    if not milestone:
        raise RuntimeError(f"Chrome for Testing has no chromedriver for Chrome {chrome_major}.")
    for item in milestone.get("downloads", {}).get("chromedriver", []):
        if item.get("platform") == CFT_PLATFORM:
            return item["url"]
    raise RuntimeError(f"No {CFT_PLATFORM} chromedriver for Chrome {chrome_major}.")


def _extract_chromedriver(archive: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for name in zf.namelist():
            if name.rsplit("/", 1)[-1] == "chromedriver":
                return zf.read(name)
    raise RuntimeError("The chromedriver download did not contain a chromedriver binary.")


def install_native_uc_driver(target: str, chrome_major: int) -> None:
    """Download, UC-patch and ad-hoc sign an arm64 chromedriver, then move it to ``target``."""
    from seleniumbase.undetected.patcher import Patcher

    url = chromedriver_download_url(chrome_major)
    _log(f"Installing native arm64 uc_driver for Chrome {chrome_major} (Rosetta is unavailable).")
    binary = _extract_chromedriver(_fetch(url))

    os.makedirs(os.path.dirname(target), exist_ok=True)
    staging = target + ".native-tmp"
    with open(staging, "wb") as fh:
        fh.write(binary)
    try:
        os.chmod(staging, 0o755)
        Patcher(executable_path=staging).patch_exe()
        # Patching changed signed bytes; an arm64 binary with a broken signature is killed on launch.
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", staging],
                       check=True, capture_output=True, timeout=60)
        if executable_major_version(staging) != chrome_major:
            raise RuntimeError("The patched chromedriver did not start.")
        os.replace(staging, target)
    finally:
        if os.path.exists(staging):
            os.remove(staging)


def ensure_native_uc_driver(chrome_binary: Optional[str]) -> None:
    """Make sure UC Mode has a runnable driver on Apple Silicon Macs without Rosetta.

    Does nothing elsewhere. Failures are logged rather than raised, so the
    launch proceeds and reports SeleniumBase's own error.
    """
    if not needs_native_uc_driver() or not chrome_binary:
        return
    try:
        chrome_major = executable_major_version(chrome_binary)
        if not chrome_major:
            _log("Could not read the Chrome version; leaving uc_driver to SeleniumBase.", warning=True)
            return
        target = _local_uc_driver()
        with _lock:
            if not driver_is_usable(target, chrome_major):
                install_native_uc_driver(target, chrome_major)
    except Exception as e:
        _log(f"Could not install a native uc_driver: {e}", warning=True)
