import hashlib

import pytest

from voyvoy.audio.devices import Device
from voyvoy.setup_blackhole import InstallError, ensure_blackhole

BH = Device("BlackHole2ch_UID", "BlackHole 2ch", True, True)
MBP = Device("mbp", "MacBook Pro Microphone", True, False)
PKG = b"fake signed pkg bytes"
SHA = hashlib.sha256(PKG).hexdigest()
SIGNED = "Status: signed by a developer certificate issued by Apple for distribution\n" \
         "1. Developer ID Installer: Existential Audio Inc. (Q5C99V536K)\n"


class World:
    def __init__(self, present=False, appears=True, signature=SIGNED):
        self.present, self.appears, self.signature = present, appears, signature
        self.commands = []

    def devices(self):
        return [MBP, BH] if self.present else [MBP]

    def download(self, url, dest):
        dest.write_bytes(PKG)

    def run(self, argv, **kwargs):
        import subprocess

        self.commands.append(argv)
        if argv[0] == "pkgutil":
            return subprocess.CompletedProcess(argv, 0, stdout=self.signature, stderr="")
        if argv[0] == "osascript":
            self.present = self.appears
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(argv)


def install(world, tmp_path, sha=SHA):
    return ensure_blackhole(world.devices, world.download, run=world.run, tmp=tmp_path, sha256=sha, wait_s=0.2)


def test_already_installed_does_nothing(tmp_path):
    w = World(present=True)
    assert install(w, tmp_path) is False and w.commands == []


def test_installs_verified_package_with_the_macos_password_dialog(tmp_path):
    w = World()
    assert install(w, tmp_path) is True
    osa = [c for c in w.commands if c[0] == "osascript"][0]
    assert "with administrator privileges" in osa[-1] and "/usr/sbin/installer -pkg" in osa[-1]


def test_checksum_mismatch_never_runs_the_installer(tmp_path):
    w = World()
    with pytest.raises(InstallError, match="checksum"):
        install(w, tmp_path, sha="0" * 64)
    assert not any(c[0] == "osascript" for c in w.commands)


def test_wrong_signer_never_runs_the_installer(tmp_path):
    w = World(signature="Status: signed by a developer certificate\n1. Developer ID Installer: Someone Else (XXXX)\n")
    with pytest.raises(InstallError, match="signature"):
        install(w, tmp_path)
    assert not any(c[0] == "osascript" for c in w.commands)


def test_device_not_showing_up_after_install_is_reported(tmp_path):
    with pytest.raises(InstallError, match="didn't show up"):
        install(World(appears=False), tmp_path)


def test_download_request_uses_a_plain_voyvoy_user_agent():
    from voyvoy.setup_blackhole import download_request

    req = download_request("https://example.com/x.pkg")
    assert req.get_header("User-agent", "").startswith("voyvoy-installer/")  # their server 406s Python-urllib
