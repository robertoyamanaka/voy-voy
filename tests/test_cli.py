import pytest

from voyvoy.cli import build_parser


def test_cli_has_the_subcommands():
    parser = build_parser()
    for cmd in ("init", "doctor", "watch", "playbook", "restore", "mcp", "bridge"):
        assert parser.parse_args([cmd] + (["--room", "r"] if cmd == "bridge" else [])).command == cmd
    with pytest.raises(SystemExit):
        parser.parse_args(["nope"])


def test_init_without_a_terminal_explains_instead_of_crashing(monkeypatch, tmp_path, capsys):
    import io

    import voyvoy.cli as cli
    import voyvoy.config as config

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr("voyvoy.setup.mac_too_old", lambda: None)
    monkeypatch.setattr("voyvoy.setup.ensure_home", lambda: tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.main(["init"]) == 2
    assert "/voy:setup" in capsys.readouterr().out


def test_playbook_command_prints_the_default_with_sources(monkeypatch, tmp_path, capsys):
    import voyvoy.cli as cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("voyvoy.playbook.VOY_HOME", tmp_path / "home")
    assert cli.main(["playbook"]) == 0
    out = capsys.readouterr().out
    assert "## Pace   <!-- from default -->" in out and "Add yours in ~/.voy/playbook.md" in out
