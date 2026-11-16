import subprocess

import pytest

from voyvoy.config import ConfigError, load_config
from voyvoy.setup import install_voy_tap, run_setup, update_config


@pytest.fixture
def native(tmp_path):
    d = tmp_path / "native"
    (d / "Sources" / "voy-tap").mkdir(parents=True)
    (d / "Package.swift").write_text("// pkg")
    (d / "Info.plist").write_text("<plist/>")
    (d / "Sources" / "voy-tap" / "main.swift").write_text("print(1)")
    return d


class Runner:
    def __init__(self, native):
        self.native, self.calls = native, []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv[0])
        if argv[0] == "swift":
            out = self.native / ".build" / "release"
            out.mkdir(parents=True, exist_ok=True)
            (out / "voy-tap").write_text("binary")
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_builds_signs_and_installs_once_then_skips(native, tmp_path):
    run = Runner(native)
    assert install_voy_tap(native, tmp_path / "bin", run=run) == "installed"
    assert run.calls == ["swift", "codesign"] and (tmp_path / "bin" / "voy-tap").exists()
    run.calls.clear()
    assert install_voy_tap(native, tmp_path / "bin", run=run) == "up to date"  # no rebuild → no new macOS prompt
    assert run.calls == []


def test_rebuilds_when_the_swift_sources_change(native, tmp_path):
    run = Runner(native)
    install_voy_tap(native, tmp_path / "bin", run=run)
    (native / "Sources" / "voy-tap" / "main.swift").write_text("print(2)")
    run.calls.clear()
    assert install_voy_tap(native, tmp_path / "bin", run=run) == "installed" and run.calls[0] == "swift"


def test_update_config_roundtrips_and_requires_an_owner(tmp_path):
    p = update_config("Yama", "wss://p.livekit.cloud", "APIkey", 's3"cret', path=tmp_path / "config.toml")
    cfg = load_config(p, env={})
    assert cfg.owner == "Yama" and cfg.livekit.api_secret == 's3"cret'
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(ConfigError):
        update_config("", "wss://x", "k", "s", path=tmp_path / "c2.toml")
    with pytest.raises(ConfigError, match="wss://"):
        update_config("Yama", "p.livekit.cloud", path=tmp_path / "c3.toml")


def test_changing_only_the_name_keeps_the_keys_and_your_edits(tmp_path):
    p = update_config("Yama", "wss://p.livekit.cloud", "APIkey", "secret", path=tmp_path / "config.toml")
    p.write_text(p.read_text().replace('# llm = "google/gemini-2.5-flash"', 'llm = "openai/gpt-4.1-mini"')
                 + '\n# my own note\n')
    update_config(owner="Sam", path=p)
    cfg = load_config(p, env={})
    assert cfg.owner == "Sam" and cfg.livekit.api_key == "APIkey" and cfg.livekit.api_secret == "secret"
    assert cfg.models.llm == "openai/gpt-4.1-mini" and "# my own note" in p.read_text()
    update_config(api_secret="new", path=p)
    assert load_config(p, env={}).livekit.api_secret == "new" and load_config(p, env={}).owner == "Sam"


def test_update_config_adds_keys_missing_from_a_hand_written_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[models]\nllm = "x"\n')
    update_config("Ana", "wss://a.livekit.cloud", "k", "s", path=p)
    cfg = load_config(p, env={})
    assert (cfg.owner, cfg.livekit.url, cfg.models.llm) == ("Ana", "wss://a.livekit.cloud", "x")


def test_run_setup_keeps_going_when_a_step_fails(monkeypatch, tmp_path):
    import voyvoy.setup as setup

    monkeypatch.setattr(setup, "mac_too_old", lambda: None)
    monkeypatch.setattr(setup, "ensure_home", lambda: tmp_path)
    monkeypatch.setattr(setup, "ensure_contacts", lambda: False)
    monkeypatch.setattr("voyvoy.playbook.ensure_starter", lambda: False)

    def no_swift():
        raise RuntimeError("Building voy-tap failed. Install Xcode command line tools.")

    monkeypatch.setattr(setup, "install_voy_tap", no_swift)
    monkeypatch.setattr("voyvoy.doctor.run_checks", lambda env: [])
    monkeypatch.setattr("voyvoy.doctor.RealDoctorEnv", lambda: None)
    out = run_setup()
    assert out[0]["name"] == "voy-tap build" and "Xcode" in out[0]["hint"]
    assert out[1]["name"] == "BlackHole install" and "Skipped" in out[1]["hint"]


def test_run_setup_stops_early_on_old_macos(monkeypatch):
    import voyvoy.setup as setup

    monkeypatch.setattr(setup, "mac_too_old", lambda: "13.6")
    assert run_setup() == [{"name": "macOS ≥ 14.2", "ok": False,
                            "hint": "You have macOS 13.6. VoyVoy needs macOS 14.2 or later to hear meeting apps."}]
