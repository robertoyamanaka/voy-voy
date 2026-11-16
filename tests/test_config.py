import pytest

from voyvoy.config import CONFIG_TEMPLATE, Config, ConfigError, load_config, render_config


def test_env_overrides_file(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('owner = "Roberto"\n[livekit]\nurl="wss://file"\napi_key="k"\napi_secret="s"\n')
    cfg = load_config(p, env={"LIVEKIT_URL": "wss://env"})
    assert cfg.livekit.url == "wss://env" and cfg.livekit.api_key == "k"
    assert cfg.models.stt == "deepgram/nova-3"
    assert cfg.models.llm == "google/gemini-2.5-flash"  # fastest first token in our benchmark
    assert cfg.models.tts == "cartesia/sonic-3"


def test_missing_owner_or_credentials_raises(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[livekit]\nurl="wss://x"\n')
    with pytest.raises(ConfigError):
        load_config(p, env={})


def test_missing_file_raises_config_error_with_init_hint(tmp_path):
    with pytest.raises(ConfigError, match="voy init"):
        load_config(tmp_path / "nope.toml", env={})


def test_no_disclosure_toggle_exists():
    assert "disclos" not in CONFIG_TEMPLATE.lower()
    assert not any("disclos" in f for f in Config.__dataclass_fields__)


def test_broken_toml_is_a_config_error(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('owner = "Roberto\n')
    with pytest.raises(ConfigError, match="c.toml"):
        load_config(p, env={})


def test_rendered_config_survives_quotes_and_backslashes(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(render_config(owner='Ro"b\\o', url="wss://x.livekit.cloud", api_key="k", api_secret='s"\\'))
    cfg = load_config(p, env={})
    assert cfg.owner == 'Ro"b\\o' and cfg.livekit.api_secret == 's"\\'


def test_template_does_not_pin_models_so_defaults_can_improve(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(render_config(owner="Yama", url="wss://x", api_key="k", api_secret="s"))
    assert load_config(p, env={}).models == type(load_config(p, env={}).models)()
    assert "\nllm =" not in CONFIG_TEMPLATE  # commented out, not set


def test_voices_per_language(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('owner = "Yama"\n[livekit]\nurl="wss://x"\napi_key="k"\napi_secret="s"\n[voices]\nes = "deepgram/aura-2:estrella"\n')
    assert load_config(p, env={}).voices == {"es": "deepgram/aura-2:estrella"}
